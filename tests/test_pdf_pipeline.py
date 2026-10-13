from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from test_restart import FakeSheets, Execute, candidate
from test_openai_provider import response
from test_ai_refinement import extractor
from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.collection.models import FetchOutcome, FetchResponse
from ce_seminar_finder.extraction.cache import JsonExtractionCache
from ce_seminar_finder.extraction.documents import PdfContextLoader
from ce_seminar_finder.extraction.pdf import LocalOcrProvider, extract_pdf
from ce_seminar_finder.extraction.refinement import refine_candidates, fit_request, extraction_request
from ce_seminar_finder.extraction.prompt import build_extraction_messages
from ce_seminar_finder.extraction.openai_provider import OpenAIProvider
from ce_seminar_finder.sheets.capacity import ensure_row_capacity


PDF_TEXT = "呼吸セミナー\n主催 奈良県臨床工学技士会\n開催日時 2026年11月20日 19:00～20:00\n参加費 会員500円 非会員1000円\n開催方法 Web\n申込 https://example.test/apply"


class Backend:
    def extract_pages(self, data): return [PDF_TEXT]


class Fetcher:
    def __init__(self): self.pdf_calls = 0
    def fetch(self, request, **kwargs):
        robot = request.url.endswith("robots.txt")
        self.pdf_calls += not robot
        return FetchResponse(request.url, request.url, 200,
            {"content-type": "text/plain" if robot else "application/pdf"},
            b"User-agent: *\nAllow: /" if robot else b"%PDF-test", datetime.now(UTC), "hash")


class PdfPipelineTest(unittest.TestCase):
    def loader(self, path, fetcher=None):
        return PdfContextLoader(path, fetcher=fetcher or Fetcher(),
            extractor=lambda data, **kwargs: extract_pdf(data, backend=Backend(), **kwargs))

    def test_pdf_only_candidate_is_extracted_and_persisted_with_pages_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            item = replace(candidate(), block_text="", extracted_fields={}, pdf_urls=("https://www.narace.jp/one.pdf",))
            raw = {"is_event": True, "event_confidence": .99, "fields": {"fee_text": {
                "value": "会員500円 非会員1000円", "confidence": .99, "evidence": "参加費 会員500円 非会員1000円"}}}
            refined, stats = refine_candidates([item], extractor(raw), pdf_loader=self.loader(Path(directory)))
            self.assertEqual(1, stats["pdf_success"])
            self.assertEqual("会員500円 非会員1000円", refined[0].extracted_fields["fee_text"].value)
            sheets = FakeSheets()
            CandidateIngestor(sheets, "test").ingest(refined)
            self.assertEqual(1, len(sheets.objects("Documents")))
            self.assertEqual(1, len(sheets.objects("DocumentTextChunks")))
            auto = next(a for a in sheets.objects("AutoFieldValues") if a["field_name"] == "fee_text")
            self.assertTrue(auto["source_document_id"].startswith("doc_"))
            location = json.loads(auto["evidence_location"])
            self.assertEqual(1, location["page_from"])
            self.assertEqual(item.pdf_urls[0], location["pdf_url"])
            CandidateIngestor(sheets, "test").ingest(refined)
            self.assertEqual(1, len(sheets.objects("Documents")))

    def test_same_pdf_is_downloaded_once_for_multiple_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = Fetcher()
            loader = self.loader(Path(directory), fetcher)
            item = replace(candidate(), pdf_urls=("https://www.narace.jp/one.pdf",))
            loader.enrich(item); loader.enrich(replace(item, title_hint="別の研修会"))
            self.assertEqual(1, fetcher.pdf_calls)
            self.assertEqual(1, loader.stats["pdf_unique"])

    def test_corrupt_pdf_is_a_review_warning_not_an_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            loader = PdfContextLoader(Path(directory), fetcher=Fetcher(),
                extractor=lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("INVALID_PDF_SIGNATURE")))
            updated = loader.enrich(replace(candidate(), pdf_urls=("https://www.narace.jp/bad.pdf",)))
            self.assertIn("INVALID_PDF_SIGNATURE", updated.extraction_warnings)
            self.assertEqual(1, loader.stats["pdf_failed"])

    def test_missing_ocr_retains_partial_text_and_warning(self):
        class Empty:
            def extract_pages(self, data): return [""]
        with patch("shutil.which", return_value=None):
            result = extract_pdf(b"%PDF-test", backend=Empty(), ocr_provider=LocalOcrProvider(), important_candidate=True)
        self.assertIn("OCR_UNAVAILABLE", result.warnings)
        self.assertEqual("failed", result.extraction_status)

    def test_context_truncation_is_explicit_and_bounded(self):
        item = replace(candidate(), pdf_documents=({"url": "https://www.narace.jp/one.pdf", "sha256": "abc",
            "chunks": [{"text": PDF_TEXT * 100, "page_from": 1, "page_to": 10}]},))
        request, truncated = fit_request(extraction_request(item), 8000)
        self.assertTrue(truncated)
        self.assertLessEqual(sum(len(m["content"]) for m in build_extraction_messages(request)), 8000)

    def test_unlimited_provider_can_process_more_than_five_and_parallel_cache_is_consistent(self):
        provider = OpenAIProvider("test-secret", transport=lambda body: response({"is_event": False, "fields": {}}))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda n: provider.extract_event(extraction_request(candidate())), range(8)))
        self.assertEqual(8, provider.requests)
        with tempfile.TemporaryDirectory() as directory:
            cache = JsonExtractionCache(Path(directory) / "cache.json")
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda n: cache.put(str(n), {"n": n}), range(20)))
            self.assertEqual(20, len(json.loads(cache.path.read_text())))

    def test_checkpoint_saves_all_candidates_without_auto_publication(self):
        items = [replace(candidate(), detail_url=f"https://www.narace.jp/{n}") for n in range(8)]
        batches = []
        refined, stats = refine_candidates(items, extractor({"is_event": True, "fields": {}, "event_confidence": .9}, max_requests=None),
            checkpoint=lambda rows: batches.append(list(rows)), checkpoint_size=3, workers=2)
        self.assertEqual(8, len(refined))
        self.assertEqual([3, 3, 2], list(map(len, batches)))

    def test_only_needed_sheet_rows_grow(self):
        class Sheets:
            def __init__(self): self.requests = []
            def spreadsheets(self): return self
            def get(self, **kwargs): return Execute({"sheets": [{"properties": {
                "title": "AutoFieldValues", "sheetId": 123, "gridProperties": {"rowCount": 1000}}}]})
            def batchUpdate(self, **kwargs): self.requests = kwargs["body"]["requests"]; return Execute({})
        sheets = Sheets()
        ensure_row_capacity(sheets, "test", {"AutoFieldValues": 1350})
        self.assertEqual({"appendDimension": {"sheetId": 123, "dimension": "ROWS", "length": 500}}, sheets.requests[0])

    def test_admin_edit_during_ingestion_is_not_overwritten(self):
        class Race(FakeSheets):
            def __init__(self): super().__init__(); self.reads = 0; self.race = False
            def get(self, **kwargs):
                if "Events" in kwargs["range"]:
                    self.reads += 1
                    if self.race and self.reads == 2:
                        h, row = self.tables["Events"][:2]
                        row[h.index("title")] = "処理中の手修正"
                        row[h.index("last_admin_updated_at")] = "2026-10-13T14:00:00Z"
                return super().get(**kwargs)
        sheets = Race()
        CandidateIngestor(sheets, "test").ingest([candidate()])
        sheets.reads = 0; sheets.race = True
        CandidateIngestor(sheets, "test").ingest([candidate()])
        self.assertEqual("処理中の手修正", sheets.objects("Events")[0]["title"])


if __name__ == "__main__": unittest.main()
