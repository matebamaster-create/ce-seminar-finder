from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ce_seminar_finder.models import AutoFieldValue, FieldOverride
from ce_seminar_finder.resolver import resolve_field


class ResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 4, tzinfo=UTC)

    def test_active_admin_override_always_wins(self) -> None:
        result = resolve_field(
            "title",
            [
                AutoFieldValue(
                    field_name="title",
                    value="自動値",
                    confidence=1.0,
                    extracted_at=self.now,
                )
            ],
            [
                FieldOverride(
                    field_name="title",
                    value="管理者値",
                    updated_at=self.now - timedelta(days=1),
                )
            ],
        )
        self.assertEqual("管理者値", result.value)
        self.assertEqual("override", result.origin)

    def test_latest_active_override_wins(self) -> None:
        result = resolve_field(
            "title",
            [],
            [
                FieldOverride("title", "旧", self.now - timedelta(hours=1)),
                FieldOverride("title", "新", self.now),
                FieldOverride("title", "無効", self.now + timedelta(hours=1), False),
            ],
        )
        self.assertEqual("新", result.value)

    def test_highest_confidence_accepted_auto_value_wins(self) -> None:
        result = resolve_field(
            "format",
            [
                AutoFieldValue("format", "現地開催", 0.70, self.now),
                AutoFieldValue("format", "Web", 0.95, self.now),
                AutoFieldValue("format", "ハイブリッド", 1.0, self.now, False),
            ],
            [],
        )
        self.assertEqual("Web", result.value)
        self.assertEqual(0.95, result.confidence)

    def test_fixed_value_is_last_fallback(self) -> None:
        result = resolve_field("timezone", [], [], {"timezone": "Asia/Tokyo"})
        self.assertEqual("Asia/Tokyo", result.value)
        self.assertEqual("fixed", result.origin)


if __name__ == "__main__":
    unittest.main()

