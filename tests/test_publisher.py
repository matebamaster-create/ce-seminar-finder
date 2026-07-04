from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ce_seminar_finder.models import EventRecord
from ce_seminar_finder.publisher import (
    PublicationError,
    build_pdf_search_hashes,
    build_public_event,
    build_public_payload,
    load_event_records,
    write_public_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class PublisherTest(unittest.TestCase):
    def test_sample_only_publishes_canonical_approved_event(self) -> None:
        records = load_event_records(ROOT / "fixtures/sample-events.json")
        payload = build_public_payload(
            records,
            datetime.fromisoformat("2026-07-04T12:00:00+09:00"),
        )
        self.assertEqual(1, payload["event_count"])
        event = payload["events"][0]
        self.assertEqual(
            "管理者が確認した呼吸療法Webセミナー",
            event["title"],
        )
        self.assertNotIn("admin_note", event)
        self.assertNotIn("auto_values", event)
        self.assertNotIn("overrides", event)

    def test_missing_required_field_is_rejected(self) -> None:
        record = EventRecord.from_dict(
            {
                "event_id": "evt_missing",
                "publication_status": "公開",
                "fixed_values": {
                    "title": "不足イベント",
                    "event_start_at": "2026-08-01T10:00:00+09:00",
                },
            }
        )
        with self.assertRaises(PublicationError):
            build_public_event(record)

    def test_invalid_url_is_rejected(self) -> None:
        record = EventRecord.from_dict(
            {
                "event_id": "evt_invalid_url",
                "publication_status": "公開",
                "fixed_values": {
                    "title": "URL検査",
                    "organizer_name": "主催者",
                    "format": "Web",
                    "event_start_at": "2026-08-01T10:00:00+09:00",
                    "primary_official_url": "javascript:alert(1)",
                },
            }
        )
        with self.assertRaises(PublicationError):
            build_public_event(record)

    def test_writer_outputs_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "events.json"
            payload = write_public_payload(
                ROOT / "fixtures/sample-events.json",
                output,
                datetime.fromisoformat("2026-07-04T12:00:00+09:00"),
            )
            loaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, loaded)
            self.assertIn("管理者", output.read_text(encoding="utf-8"))

    def test_pdf_search_publishes_hashes_not_approved_terms(self) -> None:
        record = EventRecord.from_dict(
            {
                "event_id": "evt_pdf_search",
                "publication_status": "公開",
                "fixed_values": {
                    "title": "PDF検索イベント",
                    "organizer_name": "主催者",
                    "format": "Web",
                    "event_start_at": "2026-08-01T10:00:00+09:00",
                    "primary_official_url": "https://example.test/event",
                    "pdf_search_terms": ["人工呼吸器", "ECMO"],
                },
            }
        )
        public = build_public_event(record)
        assert public is not None
        self.assertNotIn("pdf_search_terms", public)
        self.assertTrue(public["pdf_search_hashes"])
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("人工呼吸器", serialized)
        self.assertEqual(
            build_pdf_search_hashes(["ＥＣＭＯ"]),
            build_pdf_search_hashes(["ecmo"]),
        )


if __name__ == "__main__":
    unittest.main()
