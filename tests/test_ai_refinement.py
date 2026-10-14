from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from test_restart import FakeSheets, candidate
from test_openai_provider import response
from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.extraction.cache import JsonExtractionCache
from ce_seminar_finder.extraction.models import ExtractedField
from ce_seminar_finder.extraction.openai_provider import OpenAIProvider
from ce_seminar_finder.extraction.prompt import PROMPT_VERSION
from ce_seminar_finder.extraction.refinement import (
    candidate_payload, read_saved_candidates, read_processed_keys, refine_candidates,
)
from ce_seminar_finder.extraction.service import ExtractionService


def extractor(raw, max_requests=5, cache=None):
    return ExtractionService(OpenAIProvider("test-secret", max_requests=max_requests,
        transport=lambda body: response(raw)), prompt_version=PROMPT_VERSION, cache=cache)


def ai_payload():
    return {"is_event": True, "event_confidence": .98, "review_reasons": [], "fields": {
        "fee_text": {"value": "会員1,000円 非会員2,000円", "confidence": .95,
                     "evidence": "参加費 会員1,000円 非会員2,000円"},
        "title": {"value": "呼吸セミナー", "confidence": .99, "evidence": "呼吸セミナー"}}}


class RefinementTest(unittest.TestCase):
    def test_old_post_date_does_not_skip_future_date_in_announcement_title(self):
        item = replace(candidate(), title_hint="2020年1月1日：2099年11月1日 呼吸セミナー",
            extracted_fields={"event_start":
                ExtractedField("2020-01-01T00:00:00+09:00", .9, "2020年1月1日")})
        _, stats = refine_candidates([item], extractor(ai_payload()))
        self.assertEqual(1, stats["requests"])

    def test_explicit_selected_past_input_still_respects_completed_keys(self):
        item = replace(candidate(), extracted_fields={"event_start":
            ExtractedField("2020-01-01T00:00:00+09:00", .9, "2020年1月1日")})
        _, skipped = refine_candidates([item], extractor(ai_payload()))
        self.assertEqual(0, skipped["requests"])
        refined, stats = refine_candidates([item], extractor(ai_payload()), include_past=True)
        self.assertEqual(1, stats["requests"])
        replay, stats = refine_candidates([item], extractor(ai_payload()), include_past=True,
            processed_keys={refined[0].ai_cache_key})
        self.assertEqual([], replay)
        self.assertEqual(0, stats["requests"])
    def test_ai_metadata_persists_and_unchanged_input_does_not_call_api_again(self):
        sheets = FakeSheets()
        service = extractor(ai_payload())
        refined, stats = refine_candidates([candidate()], service)
        CandidateIngestor(sheets, "test").ingest(refined)
        self.assertEqual(1, stats["requests"])
        self.assertEqual("確認待ち", sheets.objects("Events")[0]["publication_status"])
        self.assertFalse(sheets.objects("Events")[0]["fee_verified"])
        autos = sheets.objects("AutoFieldValues")
        classification = next(a for a in autos if a["field_name"] == "is_event")
        self.assertEqual("openai", classification["provider"])
        self.assertFalse(classification["accepted"])
        self.assertEqual(PROMPT_VERSION, classification["prompt_version"])
        processed = read_processed_keys(sheets, "test")
        next_service = extractor(ai_payload())
        rerun, stats = refine_candidates([candidate()], next_service, processed_keys=processed)
        self.assertEqual([], rerun)
        self.assertEqual(0, stats["requests"])

    def test_rule_collection_does_not_erase_ai_and_source_changes_require_review(self):
        sheets = FakeSheets()
        refined, _ = refine_candidates([candidate()], extractor(ai_payload()))
        ingestor = CandidateIngestor(sheets, "test")
        ingestor.ingest(refined)
        fields = dict(candidate().extracted_fields, fee_text=ExtractedField("会員500円", .99, "参加費 会員500円"))
        changed = replace(candidate(), block_text=candidate().block_text.replace("1,000円", "500円"), extracted_fields=fields)
        ingestor.ingest([changed])
        self.assertEqual("会員1,000円 非会員2,000円", sheets.objects("Events")[0]["fee_text"])
        auto = next(a for a in sheets.objects("AutoFieldValues") if a["field_name"] == "fee_text")
        self.assertEqual("ai", auto["extractor"])
        self.assertIn("AI_SOURCE_CHANGED", sheets.objects("ReviewQueue")[0]["reason_codes"])

    def test_changed_input_keeps_previously_completed_key(self):
        sheets = FakeSheets()
        ingestor = CandidateIngestor(sheets, "test")
        first, _ = refine_candidates([candidate()], extractor(ai_payload()))
        ingestor.ingest(first)
        changed = replace(candidate(), block_text=candidate().block_text + "\n追加のお知らせ")
        second, _ = refine_candidates([changed], extractor(ai_payload()))
        ingestor.ingest(second)
        keys = read_processed_keys(sheets, "test")
        self.assertEqual(2, len(keys))
        replay, stats = refine_candidates([candidate()], extractor(ai_payload()), processed_keys=keys)
        self.assertEqual([], replay)
        self.assertEqual(0, stats["requests"])

    def test_same_event_inputs_in_one_checkpoint_keep_both_keys(self):
        sheets = FakeSheets()
        changed = replace(candidate(), block_text=candidate().block_text + "\n別の公開本文")
        refined, stats = refine_candidates([candidate(), changed], extractor(ai_payload()))
        self.assertEqual(2, stats["requests"])
        CandidateIngestor(sheets, "test").ingest(refined)
        markers = [row for row in sheets.objects("AutoFieldValues") if row["field_name"] == "is_event"]
        self.assertEqual(1, len(markers))
        self.assertEqual(2, len(read_processed_keys(sheets, "test")))

    def test_ai_never_overwrites_admin_values_or_publication_decision(self):
        sheets = FakeSheets()
        ingestor = CandidateIngestor(sheets, "test")
        ingestor.ingest([candidate()])
        headers, row = sheets.tables["Events"][:2]
        for name, value in {"title": "手修正済み", "fee_text": "本人確認した料金", "fee_verified": True,
                            "publication_status": "公開", "last_admin_updated_at": "2026-10-13"}.items():
            row[headers.index(name)] = value
        refined, _ = refine_candidates([candidate()], extractor(ai_payload()))
        ingestor.ingest(refined)
        event = sheets.objects("Events")[0]
        self.assertEqual("手修正済み", event["title"])
        self.assertEqual("本人確認した料金", event["fee_text"])
        self.assertEqual("公開", event["publication_status"])
        self.assertTrue(event["fee_verified"])
        self.assertFalse(next(a for a in sheets.objects("AutoFieldValues") if a["field_name"] == "fee_text")["accepted"])

    def test_non_event_is_retained_for_human_judgment_and_not_repeated(self):
        sheets = FakeSheets()
        refined, _ = refine_candidates([candidate()], extractor({
            "is_event": False, "event_confidence": .99, "fields": {}, "review_reasons": []}))
        ingestor = CandidateIngestor(sheets, "test")
        ingestor.ingest(refined)
        ingestor.ingest([candidate()])
        self.assertIn("NON_EVENT_CANDIDATE", sheets.objects("ReviewQueue")[0]["reason_codes"])
        self.assertEqual("確認待ち", sheets.objects("Events")[0]["publication_status"])
        self.assertEqual(1, len(read_processed_keys(sheets, "test")))

    def test_grounded_cache_avoids_second_charge_and_budget_is_total(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = JsonExtractionCache(Path(directory) / "cache.json")
            service = extractor(ai_payload(), max_requests=1, cache=cache)
            first, stats = refine_candidates([candidate(), replace(candidate(), title_hint="別イベント")], service)
            self.assertEqual(1, stats["requests"])
            self.assertEqual(1, len(first))
            replay, stats = refine_candidates([candidate()], extractor(ai_payload(), cache=cache))
            self.assertEqual(0, stats["requests"])
            self.assertTrue(replay[0].ai_result.cache_hit)

    def test_input_deduplication_and_no_trust_in_saved_ai_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.json"
            row = candidate_payload(candidate())
            row["ai_result"] = {"is_event": True}
            path.write_text(json.dumps([row, row]))
            rows = read_saved_candidates([path])
            self.assertEqual(1, len(rows))
            self.assertIsNone(rows[0].ai_result)

    def test_incomplete_rule_fee_does_not_survive_rejected_ai_fee(self):
        incomplete = "一般5,000円、患者会:、学生500円"
        item = replace(candidate(), block_text="参加費 " + incomplete, extracted_fields={
            "fee_text": ExtractedField(incomplete, .95, incomplete)})
        raw = {"is_event": True, "event_confidence": .99, "fields": {"fee_text": {
            "value": incomplete, "confidence": .99, "evidence": incomplete}}}
        refined, _ = refine_candidates([item], extractor(raw))
        self.assertIsNone(refined[0].extracted_fields["fee_text"].value)
        sheets = FakeSheets()
        CandidateIngestor(sheets, "test").ingest(refined)
        self.assertEqual("", sheets.objects("Events")[0]["fee_text"])


if __name__ == "__main__":
    unittest.main()
