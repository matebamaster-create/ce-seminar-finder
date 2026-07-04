from __future__ import annotations

from datetime import datetime
from typing import Any

from ce_seminar_finder.enums import PublicationStatus
from ce_seminar_finder.models import EventRecord
from ce_seminar_finder.publisher import PUBLIC_FIELDS

from .schema import EVENTS_HEADERS


def read_event_rows(service: Any, spreadsheet_id: str) -> list[dict[str, Any]]:
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"Events!A:{_column_letter(len(EVENTS_HEADERS))}",
        )
        .execute()
    )
    values = response.get("values", [])
    if not values:
        return []
    headers = [str(value) for value in values[0]]
    missing = {"event_id", "publication_status"} - set(headers)
    if missing:
        raise ValueError(f"Events is missing columns: {', '.join(sorted(missing))}")
    rows: list[dict[str, Any]] = []
    for row_number, raw in enumerate(values[1:], start=2):
        padded = list(raw) + [""] * (len(headers) - len(raw))
        row = dict(zip(headers, padded))
        if row.get("event_id"):
            row["__row_number"] = row_number
            rows.append(row)
    return rows


def event_records_from_rows(rows: list[dict[str, Any]]) -> list[EventRecord]:
    records: list[EventRecord] = []
    for row in rows:
        fixed = {
            field: _normalize_cell(row.get(field))
            for field in PUBLIC_FIELDS
            if row.get(field) not in (None, "")
        }
        records.append(
            EventRecord.from_dict(
                {
                    "event_id": str(row["event_id"]),
                    "canonical_event_id": str(
                        row.get("canonical_event_id") or row["event_id"]
                    ),
                    "publication_status": str(
                        row.get("publication_status") or PublicationStatus.PRIVATE
                    ),
                    "review_status": str(row.get("review_status") or "未確認"),
                    "review_label": str(row.get("review_label") or "なし"),
                    "duplicate_status": str(
                        row.get("duplicate_status") or "重複なし"
                    ),
                    "fixed_values": fixed,
                }
            )
        )
    return records


def archive_expired_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: datetime,
) -> list[int]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    row_numbers: list[int] = []
    for fallback_row_number, row in enumerate(rows, start=2):
        row_number = int(row.get("__row_number", fallback_row_number))
        if row.get("publication_status") != PublicationStatus.PUBLISHED.value:
            continue
        end_value = (
            row.get("effective_end_at")
            or row.get("stream_end_at")
            or row.get("event_end_at")
            or row.get("event_start_at")
        )
        if not end_value:
            continue
        try:
            end = datetime.fromisoformat(str(end_value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if end.tzinfo is not None and end < as_of:
            row_numbers.append(row_number)
    return row_numbers


def archive_expired_sheet_events(
    service: Any,
    spreadsheet_id: str,
    *,
    as_of: datetime,
) -> int:
    rows = read_event_rows(service, spreadsheet_id)
    expired = archive_expired_rows(rows, as_of=as_of)
    if not expired:
        return 0
    publication_column = _column_letter(
        EVENTS_HEADERS.index("publication_status") + 1
    )
    archived_column = _column_letter(EVENTS_HEADERS.index("archived_at") + 1)
    data = []
    for row_number in expired:
        data.extend(
            [
                {
                    "range": f"Events!{publication_column}{row_number}",
                    "values": [[PublicationStatus.ARCHIVED.value]],
                },
                {
                    "range": f"Events!{archived_column}{row_number}",
                    "values": [[as_of.isoformat()]],
                },
            ]
        )
    (
        service.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        )
        .execute()
    )
    return len(expired)


def _normalize_cell(value: Any) -> Any:
    if isinstance(value, str):
        if value.upper() == "TRUE":
            return True
        if value.upper() == "FALSE":
            return False
        if "\n" in value:
            return [item for item in value.splitlines() if item]
    return value


def _column_letter(one_based: int) -> str:
    value = one_based
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result
