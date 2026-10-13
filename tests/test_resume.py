from __future__ import annotations

import ssl
import unittest
from dataclasses import replace
from unittest.mock import patch

from test_restart import FakeSheets, candidate
from test_ai_refinement import extractor
from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.collection.snapshots import read_candidate_snapshots
from ce_seminar_finder.extraction.refinement import refine_candidates, extraction_request
from ce_seminar_finder.extraction.models import ExtractionResult
from ce_seminar_finder.sheets.requests import execute_idempotent


class ResumeTest(unittest.TestCase):
    def test_tls_eof_retries_idempotent_request_without_changing_credentials(self):
        class Request:
            def __init__(self): self.calls = 0
            def execute(self):
                self.calls += 1
                if self.calls == 1: raise ssl.SSLEOFError("temporary EOF")
                return {"ok": True}
        request = Request()
        with patch("time.sleep"):
            self.assertEqual({"ok": True}, execute_idempotent(request))
        self.assertEqual(2, request.calls)

    def test_invalid_certificate_is_not_retried_or_bypassed(self):
        class Request:
            def __init__(self): self.calls = 0
            def execute(self):
                self.calls += 1
                raise ssl.SSLCertVerificationError("invalid certificate")
        request = Request()
        with self.assertRaises(ssl.SSLCertVerificationError): execute_idempotent(request)
        self.assertEqual(1, request.calls)

    def test_private_snapshot_roundtrip_keeps_original_input_and_is_not_searchable(self):
        sheets = FakeSheets()
        original = replace(candidate(), block_text="呼吸セミナー\n" + "公式の原文" * 1200)
        ingestor = CandidateIngestor(sheets, "test")
        ingestor.ingest([original])
        resumed = read_candidate_snapshots(sheets, "test")
        self.assertEqual(extraction_request(original), extraction_request(resumed[0]))
        self.assertTrue(all(row["is_searchable"] is False for row in sheets.objects("DocumentTextChunks")))
        ingestor.ingest([candidate()])
        self.assertEqual(candidate().block_text, read_candidate_snapshots(sheets, "test")[0].block_text)

    def test_checkpoint_failure_stops_new_calls_and_returns_sanitized_resumable_summary(self):
        items = [replace(candidate(), detail_url=f"https://www.narace.jp/{i}", title_hint=f"呼吸セミナー{i}") for i in range(8)]
        def fail(rows): raise ssl.SSLEOFError("must not appear in summary")
        refined, summary = refine_candidates(items, extractor({"is_event": True, "event_confidence": .9, "fields": {}}),
            checkpoint=fail, checkpoint_size=2, workers=1)
        self.assertTrue(summary["halted"])
        self.assertEqual(2, len(refined))
        self.assertEqual(0, summary["saved"])
        self.assertEqual(2, summary["unsaved"])
        self.assertEqual("CHECKPOINT_FAILED", summary["errors"][0]["code"])
        self.assertNotIn("must not appear", str(summary))

    def test_processed_marker_is_written_only_after_other_rows(self):
        sheets = FakeSheets()
        groups = []
        original = sheets.batchUpdate
        def record(*args, **kwargs):
            groups.append(kwargs["body"]["data"])
            return original(*args, **kwargs)
        sheets.batchUpdate = record
        item = replace(candidate(), ai_result=ExtractionResult(True, .9, {}, (), "openai", "test", "v3"), ai_cache_key="key")
        CandidateIngestor(sheets, "test").ingest([item])
        self.assertEqual("is_event", groups[-1][0]["values"][0][2])
        self.assertTrue(all(not ("AutoFieldValues" in entry["range"] and entry["values"][0][2] == "is_event")
                            for group in groups[:-1] for entry in group))


if __name__ == "__main__": unittest.main()
