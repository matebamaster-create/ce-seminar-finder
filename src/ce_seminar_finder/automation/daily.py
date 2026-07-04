from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from ce_seminar_finder.adapters import adapter_for_source
from ce_seminar_finder.collection.models import (
    EventCandidate,
    SourceConfig,
    SourceRunResult,
    SourceRunStatus,
)
from ce_seminar_finder.collection.pipeline import SourceCollector

from .lock import FileRunLock


@dataclass(frozen=True, slots=True)
class SourceSummary:
    source_id: str
    status: str
    candidate_count: int
    warning_count: int
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class DailyRunSummary:
    run_id: str
    started_at: str
    finished_at: str = ""
    sources: list[SourceSummary] = field(default_factory=list)
    candidates: list[EventCandidate] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in SourceRunStatus}
        for item in self.sources:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    @property
    def has_failures(self) -> bool:
        return bool(self.fatal_errors) or any(
            item.status == SourceRunStatus.FAILED.value for item in self.sources
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status_counts": self.status_counts,
            "candidate_count": len(self.candidates),
            "has_failures": self.has_failures,
            "sources": [asdict(item) for item in self.sources],
            "fatal_errors": self.fatal_errors,
        }

    def markdown(self) -> str:
        counts = self.status_counts
        lines = [
            "# CE Seminar Finder 日次実行",
            "",
            f"- 実行ID: `{self.run_id}`",
            f"- 候補件数: {len(self.candidates)}",
            f"- 成功: {counts.get('success', 0)}",
            f"- 部分成功: {counts.get('partial', 0)}",
            f"- 失敗: {counts.get('failed', 0)}",
            f"- 技術的保留: {counts.get('technical_hold', 0)}",
            f"- 無効: {counts.get('disabled', 0)}",
            "",
            "| Source | 状態 | 候補 | 警告 |",
            "|---|---:|---:|---:|",
        ]
        lines.extend(
            f"| {item.source_id} | {item.status} | "
            f"{item.candidate_count} | {item.warning_count} |"
            for item in self.sources
        )
        if self.fatal_errors:
            lines.extend(("", "## 実行エラー", ""))
            lines.extend(f"- {message}" for message in self.fatal_errors)
        return "\n".join(lines) + "\n"


def run_daily_collection(
    *,
    collector: SourceCollector,
    sources: Iterable[SourceConfig],
    enabled_source_ids: set[str],
    lock_path: Path,
    max_detail_pages: int = 1,
    now: datetime | None = None,
) -> DailyRunSummary:
    started = now or datetime.now(UTC)
    if started.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    run_id = "daily_" + started.strftime("%Y%m%dT%H%M%S")
    summary = DailyRunSummary(run_id=run_id, started_at=started.isoformat())
    with FileRunLock(lock_path):
        for original in sources:
            source = replace(
                original,
                enabled=original.source_id in enabled_source_ids,
            )
            try:
                result = collector.collect(
                    source,
                    adapter_for_source(source.source_id),
                    max_detail_pages=max_detail_pages,
                )
            except Exception as exc:
                result = SourceRunResult(
                    source.source_id,
                    SourceRunStatus.FAILED,
                    warnings=["UNHANDLED_SOURCE_ERROR"],
                )
                summary.fatal_errors.append(
                    f"{source.source_id}: {type(exc).__name__}"
                )
            summary.sources.append(
                SourceSummary(
                    source_id=result.source_id,
                    status=result.status.value,
                    candidate_count=len(result.candidates),
                    warning_count=len(result.warnings),
                    warnings=tuple(result.warnings[:20]),
                )
            )
            summary.candidates.extend(result.candidates)
    summary.finished_at = datetime.now(UTC).isoformat()
    return summary


def write_daily_outputs(
    summary: DailyRunSummary,
    *,
    summary_path: Path,
    candidates_path: Path,
    markdown_path: Path | None = None,
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps(
            [
                {
                    "source_id": item.source_id,
                    "source_url": item.source_url,
                    "detail_url": item.detail_url,
                    "title_hint": item.title_hint,
                    "pdf_urls": list(item.pdf_urls),
                    "published_at": item.published_at,
                    "discovery_method": item.discovery_method,
                    "block_text": item.block_text,
                    "confidence_hint": item.confidence_hint,
                }
                for item in summary.candidates
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(summary.markdown(), encoding="utf-8")
