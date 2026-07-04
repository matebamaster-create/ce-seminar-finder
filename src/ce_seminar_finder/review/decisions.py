from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


DECISIONS = {
    "公開",
    "要確認付き公開",
    "修正後公開",
    "非公開",
    "重複統合",
}
AUTOMATABLE_CHOICES = {"自動公開", "要確認付き公開", "非公開"}


@dataclass(frozen=True, slots=True)
class ReviewAction:
    action_id: str
    review_id: str
    event_id: str
    action: str
    before_json: str
    after_json: str
    automation_choice: str
    actor: str
    acted_at: str
    note: str


@dataclass(frozen=True, slots=True)
class AutomationRule:
    rule_id: str
    enabled: bool
    scope: str
    condition_json: str
    action: str
    approved_from_action_id: str
    approved_by: str
    approved_at: str
    expires_at: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    event: Mapping[str, Any]
    action: ReviewAction
    automation_rule: AutomationRule | None


def apply_review_decision(
    *,
    review_id: str,
    event: Mapping[str, Any],
    decision: str,
    automation_choice: str,
    actor: str,
    acted_at: datetime,
    note: str = "",
    overrides: Mapping[str, Any] | None = None,
    canonical_event_id: str | None = None,
    approve_automation: bool = False,
    automation_scope: str = "source",
    automation_condition: Mapping[str, Any] | None = None,
) -> DecisionOutcome:
    if decision not in DECISIONS:
        raise ValueError(f"unsupported decision: {decision}")
    if acted_at.tzinfo is None:
        raise ValueError("acted_at must be timezone-aware")
    if not actor.strip():
        raise ValueError("actor is required")
    if decision == "修正後公開" and not overrides:
        raise ValueError("修正後公開 requires overrides")
    if decision == "重複統合" and not canonical_event_id:
        raise ValueError("重複統合 requires canonical_event_id")

    before = dict(event)
    after = dict(event)
    if overrides:
        after.update(overrides)
    after["review_status"] = "確認済み"
    after["last_admin_updated_at"] = acted_at.isoformat()
    if decision in {"公開", "修正後公開"}:
        after["publication_status"] = "公開"
        after["review_label"] = "なし"
    elif decision == "要確認付き公開":
        after["publication_status"] = "公開"
        after["review_label"] = "あり"
    elif decision == "非公開":
        after["publication_status"] = "非公開"
        after["review_label"] = "なし"
    elif decision == "重複統合":
        after["publication_status"] = "非公開"
        after["duplicate_status"] = "統合済み"
        after["canonical_event_id"] = canonical_event_id

    action_id = _id(
        "act",
        review_id,
        str(event.get("event_id", "")),
        acted_at.isoformat(),
    )
    action = ReviewAction(
        action_id=action_id,
        review_id=review_id,
        event_id=str(event.get("event_id", "")),
        action=_action_code(decision),
        before_json=_canonical_json(before),
        after_json=_canonical_json(after),
        automation_choice=automation_choice,
        actor=actor.strip(),
        acted_at=acted_at.isoformat(),
        note=note.strip()[:500],
    )

    rule = None
    if approve_automation and automation_choice in AUTOMATABLE_CHOICES:
        if not automation_condition:
            raise ValueError("approved automation requires a condition")
        rule = AutomationRule(
            rule_id=_id("rule", action_id, automation_choice),
            enabled=True,
            scope=automation_scope,
            condition_json=_canonical_json(dict(automation_condition)),
            action=_automation_action(automation_choice),
            approved_from_action_id=action_id,
            approved_by=actor.strip(),
            approved_at=acted_at.isoformat(),
            notes=f"ReviewAction {action_id} から明示承認",
        )
    return DecisionOutcome(event=after, action=action, automation_rule=rule)


def _action_code(decision: str) -> str:
    return {
        "公開": "publish",
        "要確認付き公開": "publish_with_warning",
        "修正後公開": "edit",
        "非公開": "reject",
        "重複統合": "merge",
    }[decision]


def _automation_action(choice: str) -> str:
    return {
        "自動公開": "publish",
        "要確認付き公開": "publish_with_warning",
        "非公開": "reject",
    }[choice]


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"
