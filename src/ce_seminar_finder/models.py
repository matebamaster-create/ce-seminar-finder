from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .enums import DuplicateStatus, PublicationStatus, ReviewLabel, ReviewStatus


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timezone is required: {value}")
    return parsed


@dataclass(frozen=True, slots=True)
class AutoFieldValue:
    field_name: str
    value: Any
    confidence: float
    extracted_at: datetime
    accepted: bool = True
    extractor: str = "rule"
    source_document_id: str | None = None
    evidence_text: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.extracted_at.tzinfo is None:
            raise ValueError("extracted_at must be timezone-aware")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutoFieldValue":
        return cls(
            field_name=data["field_name"],
            value=data.get("value"),
            confidence=float(data.get("confidence", 0)),
            extracted_at=parse_datetime(data["extracted_at"]) or datetime.now(UTC),
            accepted=bool(data.get("accepted", True)),
            extractor=data.get("extractor", "rule"),
            source_document_id=data.get("source_document_id"),
            evidence_text=data.get("evidence_text"),
        )


@dataclass(frozen=True, slots=True)
class FieldOverride:
    field_name: str
    value: Any
    updated_at: datetime
    active: bool = True
    updated_by: str = "admin"
    reason: str = ""

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FieldOverride":
        return cls(
            field_name=data["field_name"],
            value=data.get("value"),
            updated_at=parse_datetime(data["updated_at"]) or datetime.now(UTC),
            active=bool(data.get("active", True)),
            updated_by=data.get("updated_by", "admin"),
            reason=data.get("reason", ""),
        )


@dataclass(slots=True)
class EventRecord:
    event_id: str
    canonical_event_id: str
    publication_status: PublicationStatus
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    review_label: ReviewLabel = ReviewLabel.NO
    duplicate_status: DuplicateStatus = DuplicateStatus.NONE
    auto_values: list[AutoFieldValue] = field(default_factory=list)
    overrides: list[FieldOverride] = field(default_factory=list)
    fixed_values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.startswith("evt_"):
            raise ValueError("event_id must start with 'evt_'")
        if not self.canonical_event_id:
            self.canonical_event_id = self.event_id

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventRecord":
        event_id = data["event_id"]
        return cls(
            event_id=event_id,
            canonical_event_id=data.get("canonical_event_id") or event_id,
            publication_status=PublicationStatus(data["publication_status"]),
            review_status=ReviewStatus(data.get("review_status", ReviewStatus.UNREVIEWED)),
            review_label=ReviewLabel(data.get("review_label", ReviewLabel.NO)),
            duplicate_status=DuplicateStatus(
                data.get("duplicate_status", DuplicateStatus.NONE)
            ),
            auto_values=[
                AutoFieldValue.from_dict(item) for item in data.get("auto_values", [])
            ],
            overrides=[
                FieldOverride.from_dict(item) for item in data.get("overrides", [])
            ],
            fixed_values=dict(data.get("fixed_values", {})),
        )

