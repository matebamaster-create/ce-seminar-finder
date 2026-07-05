from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .schema import (
    FIELD_GUIDE_ROWS,
    SETTINGS_ROWS,
    SHEET_SPECS,
    SOURCE_ROWS,
    settings_ranges,
)


HEADER_BACKGROUND = {"red": 0.03, "green": 0.50, "blue": 0.48}
HEADER_FOREGROUND = {"red": 1.0, "green": 1.0, "blue": 1.0}


def column_index(headers: tuple[str, ...], name: str) -> int:
    try:
        return headers.index(name)
    except ValueError as exc:
        raise ValueError(f"Unknown column {name!r}") from exc


@dataclass(frozen=True, slots=True)
class InitializationPlan:
    sheet_titles: tuple[str, ...]
    settings_row_count: int
    dropdown_count: int
    protected_column_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet_titles": list(self.sheet_titles),
            "sheet_count": len(self.sheet_titles),
            "settings_row_count": self.settings_row_count,
            "dropdown_count": self.dropdown_count,
            "protected_column_count": self.protected_column_count,
        }


def build_plan() -> InitializationPlan:
    return InitializationPlan(
        sheet_titles=tuple(spec.title for spec in SHEET_SPECS),
        settings_row_count=len(SETTINGS_ROWS),
        dropdown_count=sum(len(spec.dropdowns) for spec in SHEET_SPECS),
        protected_column_count=sum(
            len(spec.protected_columns) for spec in SHEET_SPECS
        ),
    )


def load_google_service(credentials_json: str | None = None) -> Any:
    try:
        from google.auth import default as default_credentials
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google dependencies are missing. Install with: pip install -e '.[google]'"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    raw = credentials_json or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        credentials = Credentials.from_service_account_info(
            json.loads(raw),
            scopes=scopes,
        )
    else:
        credentials, _ = default_credentials(scopes=scopes)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _metadata(service: Any, spreadsheet_id: str) -> dict[str, Any]:
    return (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title,index,gridProperties))",
        )
        .execute()
    )


def _is_default_sheet_empty(service: Any, spreadsheet_id: str) -> bool:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="'Sheet1'!A1")
        .execute()
    )
    return not result.get("values")


def _ensure_sheets(service: Any, spreadsheet_id: str) -> set[str]:
    metadata = _metadata(service, spreadsheet_id)
    properties = [sheet["properties"] for sheet in metadata.get("sheets", [])]
    existing = {item["title"] for item in properties}
    newly_created: set[str] = set()

    requests: list[dict[str, Any]] = []
    if (
        existing == {"Sheet1"}
        and "Events" not in existing
        and _is_default_sheet_empty(service, spreadsheet_id)
    ):
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": properties[0]["sheetId"],
                        "title": "Events",
                    },
                    "fields": "title",
                }
            }
        )
        existing = {"Events"}
        newly_created.add("Events")

    for index, spec in enumerate(SHEET_SPECS):
        if spec.title not in existing:
            requests.append(
                {
                    "addSheet": {
                        "properties": {
                            "title": spec.title,
                            "index": index,
                            "gridProperties": {
                                "rowCount": 1000,
                                "columnCount": max(len(spec.headers), 10),
                            },
                        }
                    }
                }
            )
            newly_created.add(spec.title)
        else:
            current = next(item for item in properties if item["title"] == spec.title)
            current_columns = current.get("gridProperties", {}).get("columnCount", 0)
            if current_columns < len(spec.headers):
                requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": current["sheetId"],
                                "gridProperties": {
                                    "columnCount": len(spec.headers),
                                },
                            },
                            "fields": "gridProperties.columnCount",
                        }
                    }
                )

    if requests:
        (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            )
            .execute()
        )
    return newly_created


def _range_is_empty(service: Any, spreadsheet_id: str, range_name: str) -> bool:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    return not result.get("values")


def _write_headers_and_settings(service: Any, spreadsheet_id: str) -> None:
    data = [
        {
            "range": f"'{spec.title}'!A1",
            "majorDimension": "ROWS",
            "values": [list(spec.headers)],
        }
        for spec in SHEET_SPECS
    ]
    if _range_is_empty(service, spreadsheet_id, "'Settings'!A2"):
        data.append(
            {
                "range": "'Settings'!A2",
                "majorDimension": "ROWS",
                "values": [list(row) for row in SETTINGS_ROWS],
            }
        )
    if _range_is_empty(service, spreadsheet_id, "'Sources'!A2"):
        data.append(
            {
                "range": "'Sources'!A2",
                "majorDimension": "ROWS",
                "values": [list(row) for row in SOURCE_ROWS],
            }
        )
    if _range_is_empty(service, spreadsheet_id, "'項目ガイド'!A2"):
        data.append(
            {
                "range": "'項目ガイド'!A2",
                "majorDimension": "ROWS",
                "values": [list(row) for row in FIELD_GUIDE_ROWS],
            }
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


def _format_requests(
    metadata: dict[str, Any],
    newly_created: set[str],
) -> list[dict[str, Any]]:
    by_title = {
        sheet["properties"]["title"]: sheet["properties"]
        for sheet in metadata.get("sheets", [])
    }
    setting_ranges = settings_ranges()
    requests: list[dict[str, Any]] = []

    for spec in SHEET_SPECS:
        props = by_title[spec.title]
        sheet_id = props["sheetId"]
        column_count = len(spec.headers)
        requests.extend(
            [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {
                                "frozenRowCount": 1,
                                "frozenColumnCount": spec.frozen_columns,
                            },
                        },
                        "fields": (
                            "gridProperties.frozenRowCount,"
                            "gridProperties.frozenColumnCount"
                        ),
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": column_count,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": HEADER_BACKGROUND,
                                "textFormat": {
                                    "foregroundColor": HEADER_FOREGROUND,
                                    "bold": True,
                                },
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat",
                    }
                },
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": column_count,
                        }
                    }
                },
            ]
        )

        if spec.filter_enabled:
            requests.append(
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "startColumnIndex": 0,
                                "endColumnIndex": column_count,
                            }
                        }
                    }
                }
            )

        for dropdown in spec.dropdowns:
            index = column_index(spec.headers, dropdown.column)
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": index,
                            "endColumnIndex": index + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_RANGE",
                                "values": [
                                    {
                                        "userEnteredValue": (
                                            f"={setting_ranges[dropdown.setting_type]}"
                                        )
                                    }
                                ],
                            },
                            "strict": dropdown.strict,
                            "showCustomUi": True,
                        },
                    }
                }
            )

        for column, width in spec.column_widths.items():
            index = column_index(spec.headers, column)
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": index,
                            "endIndex": index + 1,
                        },
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize",
                    }
                }
            )

        if spec.title in newly_created:
            for protected_column in spec.protected_columns:
                index = column_index(spec.headers, protected_column)
                requests.append(
                    {
                        "addProtectedRange": {
                            "protectedRange": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 1,
                                    "startColumnIndex": index,
                                    "endColumnIndex": index + 1,
                                },
                                "description": (
                                    "CE Seminar Finderの機械管理列です。"
                                    "通常は編集しないでください。"
                                ),
                                "warningOnly": True,
                            }
                        }
                    }
                )

        if spec.title in newly_created and spec.title == "Events":
            status_index = column_index(spec.headers, "publication_status")
            colors = {
                "公開": {"red": 0.89, "green": 0.96, "blue": 0.91},
                "確認待ち": {"red": 1.0, "green": 0.95, "blue": 0.78},
                "非公開": {"red": 1.0, "green": 0.89, "blue": 0.88},
                "アーカイブ": {"red": 0.92, "green": 0.93, "blue": 0.94},
            }
            for value, color in colors.items():
                requests.append(
                    {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [
                                    {
                                        "sheetId": sheet_id,
                                        "startRowIndex": 1,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": column_count,
                                    }
                                ],
                                "booleanRule": {
                                    "condition": {
                                        "type": "CUSTOM_FORMULA",
                                        "values": [
                                            {
                                                "userEnteredValue": (
                                                    f"=${_column_letter(status_index + 1)}2="
                                                    f'"{value}"'
                                                )
                                            }
                                        ],
                                    },
                                    "format": {"backgroundColor": color},
                                },
                            },
                            "index": 0,
                        }
                    }
                )

    return requests


def _column_letter(one_based_index: int) -> str:
    result = ""
    number = one_based_index
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def initialize_spreadsheet(service: Any, spreadsheet_id: str) -> InitializationPlan:
    newly_created = _ensure_sheets(service, spreadsheet_id)
    _write_headers_and_settings(service, spreadsheet_id)
    metadata = _metadata(service, spreadsheet_id)
    requests = _format_requests(metadata, newly_created)
    if requests:
        (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            )
            .execute()
        )
    return build_plan()
