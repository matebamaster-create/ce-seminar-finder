"""Grow only the rows needed by private ingestion; retain all existing cells."""
from __future__ import annotations
from .requests import execute_idempotent


def ensure_row_capacity(service, spreadsheet_id: str, required: dict[str, int]) -> None:
    api = service.spreadsheets()
    metadata = execute_idempotent(api.get(spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,gridProperties))"))
    requests = []
    for sheet in metadata.get("sheets", []):
        prop = sheet["properties"]
        current = prop["gridProperties"]["rowCount"]
        needed = required.get(prop["title"], 0)
        if needed > current:
            requests.append({"appendDimension": {"sheetId": prop["sheetId"], "dimension": "ROWS",
                "length": max(500, needed - current)}})
    if requests:
        api.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
