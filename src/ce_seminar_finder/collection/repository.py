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
