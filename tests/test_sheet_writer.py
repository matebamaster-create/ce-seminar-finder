from __future__ import annotations

import unittest

from ce_seminar_finder.sheets.schema import EVENTS_HEADERS
from ce_seminar_finder.sheets.writer import upsert_event_rows


class Execute:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class Values:
    def __init__(self, response):
        self.response = response
        self.batch_body = None

    def get(self, **kwargs):
        return Execute(self.response)

    def batchUpdate(self, **kwargs):
        self.batch_body = kwargs
        return Execute({})


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


def event(event_id: str, title: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "canonical_event_id": event_id,
        "publication_status": "公開",
        "review_status": "確認済み",
        "review_label": "なし",
        "duplicate_status": "重複なし",
        "title": title,
        "organizer_name": "主催者",
        "format": "Web",
        "event_start_at": "2026-08-01T10:00:00+09:00",
        "primary_official_url": "https://example.test/event",
    }


class SheetWriterTest(unittest.TestCase):
    def test_inserts_new_event_after_existing_rows(self) -> None:
        service = Service({"values": [list(EVENTS_HEADERS)]})
        result = upsert_event_rows(service, "sheet-id", [event("evt_new", "新規")])
        self.assertEqual({"inserted": 1, "updated": 0, "total": 1}, result)
        write = service.values_api.batch_body["body"]["data"][0]
        self.assertTrue(write["range"].startswith("Events!A2:"))

    def test_updates_existing_event_in_place(self) -> None:
        row = [""] * len(EVENTS_HEADERS)
        row[EVENTS_HEADERS.index("event_id")] = "evt_existing"
        row[EVENTS_HEADERS.index("canonical_event_id")] = "evt_existing"
        row[EVENTS_HEADERS.index("publication_status")] = "非公開"
        service = Service({"values": [list(EVENTS_HEADERS), row]})
        result = upsert_event_rows(
            service,
            "sheet-id",
            [event("evt_existing", "更新")],
        )
        self.assertEqual({"inserted": 0, "updated": 1, "total": 1}, result)
        write = service.values_api.batch_body["body"]["data"][0]
        self.assertTrue(write["range"].startswith("Events!A2:"))

    def test_rejects_unknown_columns(self) -> None:
        service = Service({"values": [list(EVENTS_HEADERS)]})
        with self.assertRaisesRegex(ValueError, "Unknown Events columns"):
            upsert_event_rows(service, "sheet-id", [{"event_id": "evt_x", "wat": 1}])


if __name__ == "__main__":
    unittest.main()
