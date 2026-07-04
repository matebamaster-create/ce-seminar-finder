from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from ce_seminar_finder.adapters.common import PatternHtmlAdapter

from .cache import JsonFetchStateStore
from .fetcher import SafeHttpFetcher
from .models import (
    EventCandidate,
    FetchLogEntry,
    FetchOutcome,
    FetchRequest,
    FetchResponse,
    SourceConfig,
    SourceRunResult,
    SourceRunStatus,
)
from .robots import RobotsPolicy
from .sources import allowed_hosts


class CollectionRepository(Protocol):
    def append_candidates(self, candidates: list[EventCandidate]) -> None: ...

    def append_logs(self, logs: list[FetchLogEntry]) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SourceCollector:
    def __init__(
        self,
        *,
        fetcher: SafeHttpFetcher,
        repository: CollectionRepository | None = None,
        state_store: JsonFetchStateStore | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.repository = repository
        self.state_store = state_store

    def collect(
        self,
        source: SourceConfig,
        adapter: PatternHtmlAdapter,
        *,
        force: bool = False,
        max_detail_pages: int = 3,
        resolve_dns: bool = True,
    ) -> SourceRunResult:
        if not source.enabled and not force:
            return SourceRunResult(source.source_id, SourceRunStatus.DISABLED)

        run_id = f"run_{uuid.uuid4().hex}"
        result = SourceRunResult(source.source_id, SourceRunStatus.SUCCESS)
        robots_policy = self._load_robots(
            source,
            run_id,
            result,
            resolve_dns=resolve_dns,
        )
        request_count = 1 if source.robots_url else 0

        candidates: list[EventCandidate] = []
        fetched_documents: dict[str, FetchResponse] = {}
        technical_holds: list[str] = []
        failures = 0

        for url in source.discovery_urls:
            if request_count >= source.max_requests_per_run:
                result.warnings.append("MAX_REQUESTS_REACHED")
                break
            response = self._fetch_and_log(
                source,
                url,
                run_id,
                result,
                robots_policy=robots_policy,
                resolve_dns=resolve_dns,
            )
            request_count += 1
            if response.outcome == FetchOutcome.FAILED:
                failures += 1
                continue
            if response.outcome in {
                FetchOutcome.NOT_MODIFIED,
                FetchOutcome.BLOCKED,
            }:
                continue
            fetched_documents[response.final_url.split("#", 1)[0]] = response
            parsed = adapter.parse(source, response)
            candidates.extend(parsed.candidates)
            result.warnings.extend(parsed.warnings)
            if parsed.technical_hold_reason:
                technical_holds.append(parsed.technical_hold_reason)

        candidates = self._deduplicate(candidates)
        enriched: list[EventCandidate] = []
        detail_fetches = 0
        hosts = allowed_hosts(source)
        for candidate in candidates:
            if detail_fetches >= max_detail_pages:
                enriched.append(candidate)
                continue
            parsed = urlsplit(candidate.detail_url)
            base_url = candidate.detail_url.split("#", 1)[0]
            if parsed.hostname not in hosts:
                enriched.append(candidate)
                continue
            if base_url in fetched_documents:
                enriched.append(
                    adapter.enrich_candidate(
                        candidate,
                        fetched_documents[base_url],
                    )
                )
                continue
            if request_count >= source.max_requests_per_run:
                enriched.append(candidate)
                continue
            response = self._fetch_and_log(
                source,
                candidate.detail_url,
                run_id,
                result,
                robots_policy=robots_policy,
                resolve_dns=resolve_dns,
            )
            request_count += 1
            detail_fetches += 1
            if response.outcome == FetchOutcome.FETCHED:
                enriched.append(adapter.enrich_candidate(candidate, response))
            else:
                enriched.append(candidate)
                if response.outcome == FetchOutcome.FAILED:
                    failures += 1

        result.candidates = self._deduplicate(enriched)
        if technical_holds and not result.candidates:
            result.status = SourceRunStatus.TECHNICAL_HOLD
            result.warnings.extend(technical_holds)
        elif failures and result.candidates:
            result.status = SourceRunStatus.PARTIAL
        elif failures:
            result.status = SourceRunStatus.FAILED

        if self.state_store:
            self.state_store.save()
        if self.repository:
            self.repository.append_candidates(result.candidates)
            self.repository.append_logs(result.logs)
        return result

    def _load_robots(
        self,
        source: SourceConfig,
        run_id: str,
        result: SourceRunResult,
        *,
        resolve_dns: bool,
    ) -> RobotsPolicy:
        if not source.robots_url:
            result.warnings.append("ROBOTS_NOT_PUBLISHED")
            return RobotsPolicy.unavailable("")
        request = FetchRequest(
            url=source.robots_url,
            source_id=source.source_id,
            user_agent=source.user_agent,
            allowed_hosts=allowed_hosts(source),
            allowed_path_prefixes=("/robots.txt",),
            encoding="utf-8",
            max_bytes=250_000,
        )
        started = _utcnow()
        start_clock = time.monotonic()
        response = self.fetcher.fetch(
            request,
            minimum_interval=0,
            resolve_dns=resolve_dns,
            use_cache=False,
        )
        finished = _utcnow()
        result.logs.append(
            self._log(
                run_id,
                source.source_id,
                "robots",
                source.robots_url,
                response.status_code,
                response.outcome.value,
                response.error_message or "robots.txt check",
                started,
                finished,
                start_clock,
                len(response.body),
                "warning" if response.outcome == FetchOutcome.FAILED else "info",
            )
        )
        if response.outcome != FetchOutcome.FETCHED:
            result.warnings.append("ROBOTS_UNAVAILABLE")
            return RobotsPolicy.unavailable(source.robots_url)
        return RobotsPolicy(source.robots_url, response.text())

    def _fetch_and_log(
        self,
        source: SourceConfig,
        url: str,
        run_id: str,
        result: SourceRunResult,
        *,
        robots_policy: RobotsPolicy,
        resolve_dns: bool,
    ):
        started = _utcnow()
        start_clock = time.monotonic()
        request = FetchRequest(
            url=url,
            source_id=source.source_id,
            user_agent=source.user_agent,
            allowed_hosts=allowed_hosts(source),
            allowed_path_prefixes=source.allowed_path_prefixes,
            encoding=source.text_encoding,
        )
        response = self.fetcher.fetch(
            request,
            robots_policy=robots_policy,
            minimum_interval=source.request_interval_seconds,
            resolve_dns=resolve_dns,
        )
        finished = _utcnow()
        result.fetched_urls.append(url)
        level = "info"
        if response.outcome in {FetchOutcome.FAILED, FetchOutcome.BLOCKED}:
            level = "error" if response.outcome == FetchOutcome.FAILED else "warning"
        result.logs.append(
            self._log(
                run_id,
                source.source_id,
                "fetch",
                url,
                response.status_code,
                response.outcome.value,
                response.error_message or "fetch completed",
                started,
                finished,
                start_clock,
                len(response.body),
                level,
            )
        )
        return response

    @staticmethod
    def _deduplicate(
        candidates: list[EventCandidate],
    ) -> list[EventCandidate]:
        unique: dict[tuple[str, str], EventCandidate] = {}
        for candidate in candidates:
            key = (candidate.detail_url, candidate.title_hint)
            previous = unique.get(key)
            if previous is None or len(candidate.pdf_urls) > len(previous.pdf_urls):
                unique[key] = candidate
        return list(unique.values())

    @staticmethod
    def _log(
        run_id: str,
        source_id: str,
        stage: str,
        url: str,
        http_status: int,
        result_code: str,
        message: str,
        started: datetime,
        finished: datetime,
        start_clock: float,
        size: int,
        level: str,
    ) -> FetchLogEntry:
        duration_ms = max(0, int((time.monotonic() - start_clock) * 1000))
        digest = hashlib.sha256(
            f"{run_id}\0{stage}\0{url}\0{started.isoformat()}".encode()
        ).hexdigest()[:24]
        return FetchLogEntry(
            run_id=run_id,
            log_id=f"log_{digest}",
            source_id=source_id,
            stage=stage,
            level=level,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            url=url,
            http_status=http_status or None,
            attempt=1,
            duration_ms=duration_ms,
            bytes=size,
            result_code=result_code,
            message=message[:500],
        )
