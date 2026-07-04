from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ReviewItem:
    review_id: str
    event_id: str
    priority: str
    reason_codes: tuple[str, ...]
    suggested_action: str
    source_excerpt: str
    source_urls: tuple[str, ...]
    uncertain_fields: tuple[str, ...]
    opened_at: str
    due_at: str | None
    decision: str = "未判断"
    automation_choice: str = "次回も確認"


def route_review(
    *,
    event_id: str,
    reason_codes: Iterable[str],
    uncertain_fields: Iterable[str],
    source_excerpt: str,
    source_urls: Iterable[str],
    now: datetime,
    event_start_at: datetime | None = None,
    application_deadline_at: datetime | None = None,
) -> ReviewItem:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    reasons = tuple(dict.fromkeys(str(item) for item in reason_codes if item))
    fields = tuple(dict.fromkeys(str(item) for item in uncertain_fields if item))
    urls = tuple(dict.fromkeys(str(item) for item in source_urls if item))
    priority, due_at = _priority(
        reasons,
        now,
        event_start_at,
        application_deadline_at,
    )
    action = _suggested_action(reasons, fields)
    digest = hashlib.sha256(
        f"{event_id}|{'|'.join(reasons)}|{now.isoformat()}".encode("utf-8")
    ).hexdigest()[:20]
    return ReviewItem(
        review_id=f"rev_{digest}",
        event_id=event_id,
        priority=priority,
        reason_codes=reasons,
        suggested_action=action,
        source_excerpt=" ".join(source_excerpt.split())[:300],
        source_urls=urls,
        uncertain_fields=fields,
        opened_at=now.isoformat(),
        due_at=due_at.isoformat() if due_at else None,
    )


def _priority(
    reasons: tuple[str, ...],
    now: datetime,
    event_start_at: datetime | None,
    application_deadline_at: datetime | None,
) -> tuple[str, datetime | None]:
    if application_deadline_at and now <= application_deadline_at <= now + timedelta(
        hours=72
    ):
        return "緊急", application_deadline_at
    if "HIGH_IMPACT_FIELD_CHANGED" in reasons:
        return "高", min(
            (value for value in (event_start_at, application_deadline_at) if value),
            default=None,
        )
    if event_start_at and now <= event_start_at <= now + timedelta(days=7):
        return "高", event_start_at
    if event_start_at and event_start_at < now:
        return "低", None
    return "通常", application_deadline_at or event_start_at


def _suggested_action(
    reasons: tuple[str, ...],
    uncertain_fields: tuple[str, ...],
) -> str:
    if "DUPLICATE_CANDIDATE" in reasons:
        return "統合"
    if "LOW_EVENT_CONFIDENCE" in reasons:
        return "非公開"
    high_risk = {
        "event_start_at",
        "application_deadline_at",
        "fee_text",
        "credits_text",
    }
    if high_risk & set(uncertain_fields):
        return "修正"
    return "要確認付き公開"
