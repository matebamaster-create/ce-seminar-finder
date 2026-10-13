from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ce_seminar_finder.sheets.reader import (
    archive_expired_rows,
    event_records_from_rows,
    read_event_rows,
)
from ce_seminar_finder.sheets.schema import EVENTS_HEADERS


JST = timezone(timedelta(hours=9))


class Execute:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class Values:
    def __init__(self, response):
        self.response = response
        self.request = None

    def get(self, **kwargs):
        self.request = kwargs
        return Execute(self.response)


class Spreadsheets:
    def __init__(self, values):
        self._values = values

    def values(self):
        return self._values


class Service:
    def __init__(self, response):
        self.values_api = Values(response)

    def spreadsheets(self):
        return Spreadsheets(self.values_api)


class SheetReaderTest(unittest.TestCase):
    def test_reads_rows_and_preserves_actual_sheet_row_number(self) -> None:
        headers = list(EVENTS_HEADERS)
        event_id = headers.index("event_id")
        status = headers.index("publication_status")
        title = headers.index("title")
        row = [""] * len(headers)
        row[event_id] = "evt_a"
        row[status] = "公開"
        row[title] = "テスト"
        service = Service({"values": [headers, [], row]})
        result = read_event_rows(service, "sheet-id")
        self.assertEqual(1, len(result))
        self.assertEqual(3, result[0]["__row_number"])

    def test_final_sheet_values_become_public_record_fixed_values(self) -> None:
        rows = [
            {
                "event_id": "evt_a",
                "canonical_event_id": "evt_a",
                "publication_status": "公開",
                "review_status": "確認済み",
                "review_label": "なし",
                "duplicate_status": "重複なし",
                "title": "管理者確認済みタイトル",
                "organizer_name": "主催者",
                "format": "Web",
                "event_start_at": "2026-08-01T10:00:00+09:00",
                "primary_official_url": "https://example.test/event",
                "genres": "呼吸\n医療機器管理",
                "has_on_demand": "FALSE",
            }
        ]
        record = event_records_from_rows(rows)[0]
        self.assertEqual("管理者確認済みタイトル", record.fixed_values["title"])
        self.assertEqual(
            ["呼吸", "医療機器管理"],
            record.fixed_values["genres"],
        )
        self.assertFalse(record.fixed_values["has_on_demand"])

    def test_single_genre_is_still_normalized_to_a_list(self) -> None:
        record = event_records_from_rows(
            [
                {
                    "event_id": "evt_single_genre",
                    "canonical_event_id": "evt_single_genre",
                    "publication_status": "公開",
                    "genres": "循環",
                }
            ]
        )[0]
        self.assertEqual(["循環"], record.fixed_values["genres"])

    def test_archives_only_expired_published_rows(self) -> None:
        rows = [
            {
                "__row_number": 2,
                "publication_status": "公開",
                "effective_end_at": "2026-07-01T23:59:00+09:00",
            },
            {
                "__row_number": 4,
                "publication_status": "確認待ち",
                "effective_end_at": "2026-07-01T23:59:00+09:00",
            },
            {
                "__row_number": 7,
                "publication_status": "公開",
                "effective_end_at": "2026-08-01T23:59:00+09:00",
            },
        ]
        result = archive_expired_rows(
            rows,
            as_of=datetime(2026, 7, 4, 12, 0, tzinfo=JST),
        )
        self.assertEqual([2], result)

    def test_naive_archive_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            archive_expired_rows([], as_of=datetime(2026, 7, 4))


if __name__ == "__main__":
    unittest.main()
