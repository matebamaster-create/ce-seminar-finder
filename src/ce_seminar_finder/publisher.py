from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .enums import PublicationStatus
from .models import EventRecord
from .resolver import resolve_event


PUBLIC_FIELDS = (
    "title",
    "summary",
    "event_type",
    "genres",
    "detailed_tags",
    "organizer_name",
    "organizer_type",
    "source_prefecture",
    "venue_prefecture",
    "venue_name",
    "format",
    "has_on_demand",
    "audience_conditions",
    "capacity_text",
    "credits_text",
    "event_start_at",
    "event_end_at",
    "stream_start_at",
    "stream_end_at",
    "stream_period_text",
    "application_deadline_at",
    "application_deadline_text",
    "timezone",
    "effective_end_at",
    "fee_category",
    "fee_text",
    "primary_official_url",
    "application_url",
    "primary_pdf_url",
    "pdf_keyword_hit",
    "last_verified_at",
    "review_reason_display",
)

PRIVATE_BUILD_FIELDS = ("pdf_search_terms",)

REQUIRED_FIELDS = {
    "title",
    "organizer_name",
    "format",
    "primary_official_url",
}

URL_FIELDS = {
    "primary_official_url",
    "application_url",
    "primary_pdf_url",
}


class PublicationError(ValueError):
    pass


def _valid_public_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def build_public_event(event: EventRecord) -> dict[str, Any] | None:
    if event.publication_status != PublicationStatus.PUBLISHED:
        return None
    if event.canonical_event_id != event.event_id:
        return None

    resolved = resolve_event(event, (*PUBLIC_FIELDS, *PRIVATE_BUILD_FIELDS))
    values = {key: item.value for key, item in resolved.items()}

    missing = sorted(key for key in REQUIRED_FIELDS if not values.get(key))
    if missing:
        raise PublicationError(
            f"{event.event_id}: missing required public fields: {', '.join(missing)}"
        )
    if not any(
        values.get(key)
        for key in ("event_start_at", "stream_start_at", "stream_end_at")
    ):
        raise PublicationError(f"{event.event_id}: event or stream date is required")
    for field_name in URL_FIELDS:
        value = values.get(field_name)
        if value is not None and value != "" and not _valid_public_url(value):
            raise PublicationError(
                f"{event.event_id}: invalid URL in {field_name}: {value!r}"
            )

    public = {
        "event_id": event.event_id,
        "detail_path": f"/events/{event.event_id}/",
        "review_label": event.review_label.value,
    }
    public.update(
        {
            key: _serialize(value)
            for key, value in values.items()
            if key in PUBLIC_FIELDS and value is not None and value != ""
        }
    )
    pdf_terms = values.get("pdf_search_terms")
    if isinstance(pdf_terms, list):
        hashes = build_pdf_search_hashes(
            [str(item) for item in pdf_terms if str(item).strip()]
        )
        if hashes:
            public["pdf_search_hashes"] = hashes
    return public


def build_pdf_search_hashes(approved_terms: list[str]) -> list[str]:
    """Hash 2- and 3-character n-grams from pre-approved non-sensitive terms."""
    hashes: set[str] = set()
    for term in approved_terms:
        normalized = unicodedata.normalize("NFKC", term).lower()
        normalized = re.sub(r"[\s\-_ー]+", "", normalized)
        for size in (2, 3):
            for index in range(0, len(normalized) - size + 1):
                gram = normalized[index : index + size]
                hashes.add(hashlib.sha256(gram.encode("utf-8")).hexdigest())
    return sorted(hashes)


def _sort_key(event: dict[str, Any]) -> tuple[int, str, str]:
    format_priority = {
        "Web": 0,
        "オンデマンド": 1,
        "ハイブリッド": 2,
        "現地開催": 3,
        "要確認": 4,
    }
    date = (
        event.get("event_start_at")
        or event.get("stream_start_at")
        or event.get("stream_end_at")
        or "9999-12-31"
    )
    return (format_priority.get(event.get("format", "要確認"), 4), date, event["title"])


def build_public_payload(
    records: list[EventRecord],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    events = [
        public
        for record in records
        if (public := build_public_event(record)) is not None
    ]
    events.sort(key=_sort_key)
    return {
        "schema_version": 1,
        "generated_at": timestamp.isoformat(),
        "event_count": len(events),
        "events": events,
    }


def load_event_records(path: Path) -> list[EventRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["events"] if isinstance(raw, dict) else raw
    return [EventRecord.from_dict(item) for item in items]


def write_public_payload(
    input_path: Path,
    output_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    payload = build_public_payload(load_event_records(input_path), generated_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload
