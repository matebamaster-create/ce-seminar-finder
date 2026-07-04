from __future__ import annotations

import unittest

from ce_seminar_finder.sheets.initializer import (
    _format_requests,
    build_plan,
    column_index,
)
from ce_seminar_finder.sheets.schema import (
    SETTINGS_ROWS,
    SHEET_SPECS,
    SOURCE_ROWS,
    settings_ranges,
    workbook_template_payload,
)


EXPECTED_SHEETS = (
    "Events",
    "ReviewQueue",
    "Sources",
    "EventSources",
    "Documents",
    "DocumentTextChunks",
    "AutoFieldValues",
    "FieldOverrides",
    "DuplicateCandidates",
    "ReviewActions",
    "AutomationRules",
    "FetchLogs",
    "Settings",
)


class SheetSchemaTest(unittest.TestCase):
    def test_has_exactly_thirteen_required_sheets(self) -> None:
        self.assertEqual(EXPECTED_SHEETS, tuple(spec.title for spec in SHEET_SPECS))
        self.assertEqual(13, len(SHEET_SPECS))

    def test_headers_are_unique(self) -> None:
        for spec in SHEET_SPECS:
            with self.subTest(sheet=spec.title):
                self.assertEqual(len(spec.headers), len(set(spec.headers)))

    def test_initial_sources_match_source_schema(self) -> None:
        source_spec = next(spec for spec in SHEET_SPECS if spec.title == "Sources")
        self.assertEqual(9, len(SOURCE_ROWS))
        for row in SOURCE_ROWS:
            self.assertEqual(len(source_spec.headers), len(row))
            self.assertFalse(row[source_spec.headers.index("enabled")])

    def test_every_dropdown_points_to_settings_rows(self) -> None:
        available = {row[0] for row in SETTINGS_ROWS}
        for spec in SHEET_SPECS:
            for dropdown in spec.dropdowns:
                with self.subTest(sheet=spec.title, column=dropdown.column):
                    self.assertIn(dropdown.column, spec.headers)
                    self.assertIn(dropdown.setting_type, available)

    def test_settings_ranges_cover_each_group(self) -> None:
        ranges = settings_ranges()
        self.assertIn("genres", ranges)
        self.assertTrue(ranges["genres"].startswith("Settings!$C$"))

    def test_plan_counts_schema(self) -> None:
        plan = build_plan()
        self.assertEqual(13, len(plan.sheet_titles))
        self.assertGreater(plan.settings_row_count, 40)
        self.assertGreater(plan.dropdown_count, 10)

    def test_column_index_rejects_unknown_column(self) -> None:
        with self.assertRaises(ValueError):
            column_index(("a", "b"), "missing")

    def test_format_plan_contains_validations_filters_and_protection(self) -> None:
        metadata = {
            "sheets": [
                {
                    "properties": {
                        "title": spec.title,
                        "sheetId": index + 1,
                    }
                }
                for index, spec in enumerate(SHEET_SPECS)
            ]
        }
        requests = _format_requests(metadata, {"Events", "ReviewQueue"})
        request_types = {next(iter(request)) for request in requests}
        self.assertIn("setDataValidation", request_types)
        self.assertIn("setBasicFilter", request_types)
        self.assertIn("addProtectedRange", request_types)
        self.assertIn("addConditionalFormatRule", request_types)

    def test_workbook_template_payload_is_complete(self) -> None:
        payload = workbook_template_payload()
        self.assertEqual(13, len(payload["sheets"]))
        self.assertEqual(84, len(payload["settings_rows"]))
        self.assertEqual(9, len(payload["source_rows"]))


if __name__ == "__main__":
    unittest.main()
