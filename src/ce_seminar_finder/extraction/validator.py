from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from ce_seminar_finder.enums import (
    EventFormat,
    EventType,
    FeeCategory,
    Genre,
    OrganizerType,
)

from .models import ExtractedField, ExtractionResult


KNOWN_FIELDS = {
    "title",
    "event_start",
    "event_end",
    "stream_start",
    "stream_end",
    "application_deadline",
    "format",
    "event_type",
    "genres",
    "organizer",
    "organizer_type",
    "fee_category",
    "fee_text",
    "audience_conditions",
    "credits_text",
    "official_url",
    "application_url",
}
DATE_FIELDS = {
    "event_start",
    "event_end",
    "stream_start",
    "stream_end",
    "application_deadline",
}
EVIDENCE_REQUIRED = DATE_FIELDS | {"fee_category", "fee_text", "credits_text"}
ENUM_VALUES = {
    "format": {item.value for item in EventFormat},
    "event_type": {item.value for item in EventType},
    "organizer_type": {item.value for item in OrganizerType},
    "fee_category": {item.value for item in FeeCategory},
}
GENRES = {item.value for item in Genre}
URL_FIELDS = {"official_url", "application_url"}


def validate_extraction(
    raw: Mapping[str, Any],
    *,
    allowed_urls: tuple[str, ...],
    provider: str,
    model: str,
    prompt_version: str,
    cache_hit: bool = False,
) -> ExtractionResult:
    reasons = _string_list(raw.get("review_reasons"))
    allowed = {_normalize_url(value) for value in allowed_urls}
    raw_fields = raw.get("fields", {})
    if not isinstance(raw_fields, Mapping):
        raw_fields = {}
        reasons.append("INVALID_FIELDS_OBJECT")

    fields: dict[str, ExtractedField] = {}
    for name, item in raw_fields.items():
        if name not in KNOWN_FIELDS or not isinstance(item, Mapping):
            continue
        value = item.get("value")
        confidence = _confidence(item.get("confidence"))
        evidence = _evidence(item.get("evidence"))

        if value is not None and name in EVIDENCE_REQUIRED and not evidence:
            value = None
            confidence = 0.0
            reasons.append(f"{name.upper()}_EVIDENCE_MISSING")
        if value is not None and name in DATE_FIELDS and not _valid_datetime(value):
            value = None
            confidence = 0.0
            reasons.append(f"{name.upper()}_INVALID")
        if value is not None and name in ENUM_VALUES and value not in ENUM_VALUES[name]:
            value = None
            confidence = 0.0
            reasons.append(f"{name.upper()}_INVALID")
        if name == "genres" and value is not None:
            if not isinstance(value, list):
                value = None
                confidence = 0.0
                reasons.append("GENRES_INVALID")
            else:
                value = [entry for entry in value if entry in GENRES]
        if value is not None and name in URL_FIELDS:
            normalized = _normalize_url(str(value))
            if normalized not in allowed:
                value = None
                confidence = 0.0
                reasons.append("URL_NOT_IN_SOURCE")
            else:
                value = normalized

        fields[name] = ExtractedField(
            value=value,
            confidence=confidence,
            evidence=evidence,
        )

    return ExtractionResult(
        is_event=bool(raw.get("is_event", False)),
        event_confidence=_confidence(raw.get("event_confidence")),
        fields=fields,
        review_reasons=tuple(dict.fromkeys(reasons)),
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        cache_hit=cache_hit,
    )


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host
    if port and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _evidence(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    return normalized[:300] or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
