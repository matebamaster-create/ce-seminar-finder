from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping


class FetchOutcome(StrEnum):
    FETCHED = "fetched"
    NOT_MODIFIED = "not_modified"
    BLOCKED = "blocked"
    FAILED = "failed"


class SourceRunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TECHNICAL_HOLD = "technical_hold"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class SourceConfig:
    source_id: str
    organization_name: str
    prefecture: str
    base_url: str
    discovery_urls: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    adapter_type: str
    text_encoding: str = "auto"
    enabled: bool = False
    auto_publish_policy: str = "review_only"
    request_interval_seconds: float = 10
    max_requests_per_run: int = 30
    user_agent: str = ""
    robots_url: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class FetchRequest:
    url: str
    source_id: str
    user_agent: str
    allowed_hosts: frozenset[str]
    allowed_path_prefixes: tuple[str, ...] = ("/",)
    encoding: str = "auto"
    etag: str | None = None
    last_modified: str | None = None
    max_bytes: int = 5_000_000


@dataclass(frozen=True, slots=True)
class FetchResponse:
    url: str
    final_url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    fetched_at: datetime
    content_hash: str
    outcome: FetchOutcome = FetchOutcome.FETCHED
    encoding: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    def text(self) -> str:
        if not self.body:
            return ""
        encoding = self.encoding or "utf-8"
        return self.body.decode(encoding, errors="replace")


@dataclass(frozen=True, slots=True)
class EventCandidate:
    source_id: str
    source_url: str
    detail_url: str
    title_hint: str
    pdf_urls: tuple[str, ...] = ()
    published_at: str | None = None
    discovery_method: str = "html"
    block_text: str = ""
    confidence_hint: float = 0.5


@dataclass(frozen=True, slots=True)
class AdapterResult:
    candidates: tuple[EventCandidate, ...] = ()
    discovered_urls: tuple[str, ...] = ()
    pdf_urls: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    technical_hold_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FetchLogEntry:
    run_id: str
    log_id: str
    source_id: str
    stage: str
    level: str
    started_at: str
    finished_at: str
    url: str
    http_status: int | None
    attempt: int
    duration_ms: int
    bytes: int
    result_code: str
    message: str
    github_run_url: str = ""

    def as_sheet_row(self) -> list[object]:
        return [
            self.run_id,
            self.log_id,
            self.source_id,
            self.stage,
            self.level,
            self.started_at,
            self.finished_at,
            self.url,
            self.http_status or "",
            self.attempt,
            self.duration_ms,
            self.bytes,
            self.result_code,
            self.message,
            self.github_run_url,
        ]


@dataclass(slots=True)
class SourceRunResult:
    source_id: str
    status: SourceRunStatus
    candidates: list[EventCandidate] = field(default_factory=list)
    logs: list[FetchLogEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched_urls: list[str] = field(default_factory=list)

