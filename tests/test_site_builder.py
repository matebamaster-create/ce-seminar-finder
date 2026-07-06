from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ce_seminar_finder.site_builder import build_static_site


class SiteBuilderTest(unittest.TestCase):
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": "2026-07-04T12:00:00+09:00",
            "event_count": 2,
            "events": [
                {
                    "event_id": "evt_active",
                    "detail_path": "/events/evt_active/",
                    "review_label": "あり",
                    "title": "<呼吸> Webセミナー",
                    "event_type": "セミナー",
                    "genres": ["呼吸"],
                    "organizer_name": "県臨床工学技士会",
                    "format": "Web",
                    "event_start_at": "2026-08-10T13:00:00+09:00",
                    "application_deadline_at": "2026-08-07T23:59:00+09:00",
                    "fee_category": "有料",
                    "primary_official_url": "https://example.test/active",
                    "review_reason_display": "単位を確認",
                    "pdf_search_hashes": ["abc"],
                },
                {
                    "event_id": "evt_past",
                    "detail_path": "/events/evt_past/",
                    "review_label": "なし",
                    "title": "過去の研究会",
                    "event_type": "研究会",
                    "genres": ["教育・研究"],
                    "organizer_name": "主催者",
                    "format": "現地開催",
                    "event_start_at": "2026-06-01T10:00:00+09:00",
                    "fee_category": "無料",
                    "primary_official_url": "https://example.test/past",
                },
            ],
        }

    def test_builds_all_routes_and_partitions_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "events.json"
            data.write_text(
                json.dumps(self.payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = build_static_site(data, root / "site")
            self.assertEqual(
                {"active_count": 1, "archive_count": 1, "detail_count": 2},
                result,
            )
            expected = [
                "index.html",
                "events/index.html",
                "archive/index.html",
                "about/index.html",
                "events/evt_active/index.html",
                "events/evt_past/index.html",
            ]
            for filename in expected:
                self.assertTrue((root / "site" / filename).exists(), filename)

            listing = (root / "site/events/index.html").read_text(encoding="utf-8")
            archive = (root / "site/archive/index.html").read_text(encoding="utf-8")
            self.assertIn("&lt;呼吸&gt; Webセミナー", listing)
            self.assertNotIn("<呼吸> Webセミナー", listing)
            self.assertNotIn("過去の研究会", listing)
            self.assertIn("過去の研究会", archive)

    def test_pages_are_noindex_accessible_and_do_not_embed_private_fields(self) -> None:
        payload = self.payload()
        payload["events"][0]["admin_note"] = "絶対に公開しない"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "events.json"
            data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            build_static_site(data, root / "site")
            combined = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "site").rglob("*.html")
            )
        self.assertIn('name="robots" content="noindex,nofollow"', combined)
        self.assertIn('class="skip-link"', combined)
        self.assertIn('aria-live="polite"', combined)
        self.assertIn('rel="noopener"', combined)
        self.assertNotIn("絶対に公開しない", combined)

    def test_legacy_string_genre_is_rendered_as_one_tag(self) -> None:
        payload = self.payload()
        payload["events"][0]["genres"] = "血液浄化"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "events.json"
            data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            build_static_site(data, root / "site")
            listing = (root / "site/events/index.html").read_text(encoding="utf-8")
        self.assertIn('<span class="tag">血液浄化</span>', listing)
        self.assertNotIn('<span class="tag">血</span>', listing)


if __name__ == "__main__":
    unittest.main()
