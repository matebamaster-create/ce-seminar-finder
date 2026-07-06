from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import EventCandidate, FetchLogEntry


def candidate_sheet_row(candidate: EventCandidate) -> list[object]:
    digest = hashlib.sha256(
        f"{candidate.source_id}\0{candidate.detail_url}".encode()
    ).hexdigest()[:24]
    return [
        f"es_{digest}",
        "",
        candidate.source_id,
        candidate.detail_url,
        "discovered_candidate",
        "",
        "",
        False,
        candidate.title_hint,
        "",
        candidate.published_at or "",
        "",
    ]


class SheetCollectionRepository:
    def __init__(self, service: Any, spreadsheet_id: str) -> None:
        self.service = service
        self.spreadsheet_id = spreadsheet_id

    def append_candidates(self, candidates: list[EventCandidate]) -> None:
        if not candidates:
            return
        self._append(
            "EventSources!A:L",
            [candidate_sheet_row(candidate) for candidate in candidates],
        )
        self._apply_extracted_fields(candidates)

    def append_logs(self, logs: list[FetchLogEntry]) -> None:
        if not logs:
            return
        self._append("FetchLogs!A:O", [log.as_sheet_row() for log in logs])

    def _append(self, range_name: str, values: list[list[object]]) -> None:
        (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )

    def _apply_extracted_fields(
        self,
        candidates: list[EventCandidate],
    ) -> None:
        response = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range="Events!A:AY",
            )
            .execute()
        )
        rows = response.get("values", [])
        if len(rows) < 2:
            return
        headers = [str(value) for value in rows[0]]
        columns = {header: index for index, header in enumerate(headers)}
        url_column = columns.get("primary_official_url")
        if url_column is None:
            return
        by_url: dict[str, tuple[int, list[object]]] = {}
        for row_number, row in enumerate(rows[1:], start=2):
            if url_column < len(row):
                normalized = _normalize_url(str(row[url_column]))
                if normalized:
                    by_url[normalized] = (row_number, row)

        updates: list[dict[str, object]] = []
        for candidate in candidates:
            matched = by_url.get(_normalize_url(candidate.detail_url))
            if not matched or not candidate.extracted_fields:
                continue
            row_number, row = matched
            extracted = candidate.extracted_fields
            field_values: dict[str, object] = {}
            for source_name, event_name in (
                ("event_start", "event_start_at"),
                ("application_deadline_at", "application_deadline_at"),
                ("application_deadline_text", "application_deadline_text"),
                ("capacity_text", "capacity_text"),
                ("fee_category", "fee_category"),
                ("fee_text", "fee_text"),
                ("application_url", "application_url"),
            ):
                field = extracted.get(source_name)
                if field is not None and field.confidence >= 0.85:
                    field_values[event_name] = field.value
            if "fee_text" in field_values:
                field_values["fee_verified"] = True

            resolved_codes = {
                "event_start": "DATE_UNKNOWN",
                "application_deadline_at": "DEADLINE_UNKNOWN",
                "fee_text": "FEE_UNKNOWN",
                "capacity_text": "CAPACITY_UNKNOWN",
            }
            reason_column = columns.get("review_reason_codes")
            reasons = (
                str(row[reason_column]).splitlines()
                if reason_column is not None and reason_column < len(row)
                else []
            )
            for extracted_name, reason in resolved_codes.items():
                if extracted_name in extracted:
                    reasons = [item for item in reasons if item != reason]
            field_values["review_reason_codes"] = "\n".join(reasons)
            field_values["review_reason_display"] = _review_reason_display(reasons)
            field_values["review_label"] = "あり" if reasons else "なし"
            field_values["last_auto_fetch_at"] = datetime.now(UTC).isoformat()

            for field_name, value in field_values.items():
                column = columns.get(field_name)
                if column is None:
                    continue
                updates.append(
                    {
                        "range": f"Events!{_column_name(column)}{row_number}",
                        "values": [[value]],
                    }
                )
        if updates:
            (
                self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "valueInputOption": "RAW",
                        "data": updates,
                    },
                )
                .execute()
            )


class JsonlCollectionRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def append_candidates(self, candidates: list[EventCandidate]) -> None:
        rows = [
            {
                "source_id": item.source_id,
                "source_url": item.source_url,
                "detail_url": item.detail_url,
                "title_hint": item.title_hint,
                "pdf_urls": list(item.pdf_urls),
                "published_at": item.published_at,
                "discovery_method": item.discovery_method,
                "block_text": item.block_text,
                "extracted_fields": {
                    key: value.as_dict()
                    for key, value in item.extracted_fields.items()
                },
                "confidence_hint": item.confidence_hint,
            }
            for item in candidates
        ]
        self._append("candidates.jsonl", rows)

    def append_logs(self, logs: list[FetchLogEntry]) -> None:
        self._append(
            "fetch-logs.jsonl",
            [
                dict(zip(
                    (
                        "run_id",
                        "log_id",
                        "source_id",
                        "stage",
                        "level",
                        "started_at",
                        "finished_at",
                        "url",
                        "http_status",
                        "attempt",
                        "duration_ms",
                        "bytes",
                        "result_code",
                        "message",
                        "github_run_url",
                    ),
                    item.as_sheet_row(),
                ))
                for item in logs
            ],
        )

    def _append(self, filename: str, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / filename).open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


def _column_name(index: int) -> str:
    name = ""
    current = index + 1
    while current:
        current, remainder = divmod(current - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _review_reason_display(reasons: list[str]) -> str:
    labels = {
        "DATE_UNKNOWN": "開催日時を確認してください",
        "DEADLINE_UNKNOWN": "申込締切を確認してください",
        "FEE_UNKNOWN": "参加費を確認してください",
        "CAPACITY_UNKNOWN": "定員を確認してください",
        "CREDITS_UNCERTAIN": "取得単位を確認してください",
        "PDF_PRIMARY": "PDF原本を確認してください",
        "DUPLICATE_CANDIDATE": "重複候補を確認してください",
        "LOW_EVENT_CONFIDENCE": "イベント情報を確認してください",
        "ORGANIZER_UNKNOWN": "主催者を確認してください",
        "FORMAT_UNKNOWN": "開催形式を確認してください",
        "OFFICIAL_URL_UNKNOWN": "公式URLを確認してください",
        "SOURCE_UNREACHABLE": "公式ページの取得状況を確認してください",
        "TEXT_QUALITY_LOW": "原文の読み取り結果を確認してください",
        "HIGH_IMPACT_FIELD_CHANGED": "重要項目の変更を確認してください",
        "SOURCE_GAP": "情報源の不足を確認してください",
    }
    return "\n".join(labels.get(reason, reason) for reason in reasons)


class CompositeCollectionRepository:
    def __init__(self, *repositories: object) -> None:
        self.repositories = repositories

    def append_candidates(self, candidates: list[EventCandidate]) -> None:
        for repository in self.repositories:
            repository.append_candidates(candidates)

    def append_logs(self, logs: list[FetchLogEntry]) -> None:
        for repository in self.repositories:
            repository.append_logs(logs)
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import EventCandidate, FetchLogEntry


def candidate_sheet_row(candidate: EventCandidate) -> list[object]:
    digest = hashlib.sha256(
        f"{candidate.source_id}\0{candidate.detail_url}".encode()
    ).hexdigest()[:24]
    return [
        f"es_{digest}",
        "",
        candidate.source_id,
        candidate.detail_url,
        "discovered_candidate",
        "",
        "",
        False,
        candidate.title_hint,
        "",
        candidate.published_at or "",
        "",
    ]


class SheetCollectionRepository:
    def __init__(self, service: Any, spreadsheet_id: str) -> None:
        self.service = service
        self.spreadsheet_id = spreadsheet_id

    def append_candidates(self, candidates: list[EventCandidate]) -> None:
        if not candidates:
            return
        self._append(
            "EventSources!A:L",
            [candidate_sheet_row(candidate) for candidate in candidates],
        )

    def append_logs(self, logs: list[FetchLogEntry]) -> None:
        if not logs:
            return
        self._append("FetchLogs!A:O", [log.as_sheet_row() for log in logs])

    def _append(self, range_name: str, values: list[list[object]]) -> None:
        (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )


class JsonlCollectionRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def append_candidates(self, candidates: list[EventCandidate]) -> None:
        rows = [
            {
                "source_id": item.source_id,
                "source_url": item.source_url,
                "detail_url": item.detail_url,
                "title_hint": item.title_hint,
                "pdf_urls": list(item.pdf_urls),
                "published_at": item.published_at,
                "discovery_method": item.discovery_method,
                "confidence_hint": item.confidence_hint,
            }
            for item in candidates
        ]
        self._append("candidates.jsonl", rows)

    def append_logs(self, logs: list[FetchLogEntry]) -> None:
        self._append(
            "fetch-logs.jsonl",
            [
                dict(zip(
                    (
                        "run_id",
                        "log_id",
                        "source_id",
                        "stage",
                        "level",
                        "started_at",
                        "finished_at",
                        "url",
                        "http_status",
                        "attempt",
                        "duration_ms",
                        "bytes",
                        "result_code",
                        "message",
                        "github_run_url",
                    ),
                    item.as_sheet_row(),
                ))
                for item in logs
            ],
        )

    def _append(self, filename: str, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / filename).open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class CompositeCollectionRepository:
    def __init__(self, *repositories: object) -> None:
        self.repositories = repositories

    def append_candidates(self, candidates: list[EventCandidate]) -> None:
        for repository in self.repositories:
            repository.append_candidates(candidates)

    def append_logs(self, logs: list[FetchLogEntry]) -> None:
        for repository in self.repositories:
            repository.append_logs(logs)
