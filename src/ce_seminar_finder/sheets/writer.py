from __future__ import annotations

from typing import Any

from ce_seminar_finder.publisher import build_public_event

from .reader import event_records_from_rows, read_event_rows
from .schema import EVENTS_HEADERS


def upsert_event_rows(
    service: Any,
    spreadsheet_id: str,
    incoming_rows: list[dict[str, Any]],
) -> dict[str, int]:
    unknown = sorted(
        {
            key
            for row in incoming_rows
            for key in row
            if key not in EVENTS_HEADERS
        }
    )
    if unknown:
        raise ValueError(f"Unknown Events columns: {', '.join(unknown)}")

    existing_rows = read_event_rows(service, spreadsheet_id)
    by_id = {str(row["event_id"]): row for row in existing_rows}
    next_row = max(
        (int(row["__row_number"]) for row in existing_rows),
        default=1,
    ) + 1
    writes: list[dict[str, Any]] = []
    inserted = 0
    updated = 0

    for incoming in incoming_rows:
        event_id = str(incoming.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("Every imported event requires event_id")
        current = by_id.get(event_id)
        merged = {
            key: value
            for key, value in (current or {}).items()
            if key in EVENTS_HEADERS
        }
        merged.update(incoming)
        merged.setdefault("canonical_event_id", event_id)

        record = event_records_from_rows([merged])[0]
        if merged.get("publication_status") == "公開":
            build_public_event(record)

        if current:
            row_number = int(current["__row_number"])
            updated += 1
        else:
            row_number = next_row
            next_row += 1
            inserted += 1
        by_id[event_id] = {**merged, "__row_number": row_number}
        writes.append(
            {
                "range": f"Events!A{row_number}:{_column_letter(len(EVENTS_HEADERS))}{row_number}",
                "majorDimension": "ROWS",
                "values": [[_sheet_value(merged.get(name, "")) for name in EVENTS_HEADERS]],
            }
        )

    if writes:
        (
            service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": writes},
            )
            .execute()
        )
    return {"inserted": inserted, "updated": updated, "total": len(incoming_rows)}


def _sheet_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    return value


def _column_letter(one_based: int) -> str:
    result = ""
    value = one_based
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result
