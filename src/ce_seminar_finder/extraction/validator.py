from __future__ import annotations

from datetime import datetime
import re
import math
import unicodedata
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit, quote

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
    "event_date_precision",
    "event_start_text",
    "event_end_text",
    "stream_start_text",
    "stream_end_text",
    "venue_name",
    "venue_address",
    "venue_prefecture",
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
    source_text: str | None = None,
) -> ExtractionResult:
    reasons = _string_list(raw.get("review_reasons"))
    allowed = {normalized for value in allowed_urls if (normalized := _normalize_url(value))}
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

        if value is not None and source_text is not None and name not in URL_FIELDS and not evidence:
            value, confidence = None, 0.0
            reasons.append(f"{name.upper()}_EVIDENCE_MISSING")
        if value is not None and name in EVIDENCE_REQUIRED and not evidence:
            value = None
            confidence = 0.0
            reasons.append(f"{name.upper()}_EVIDENCE_MISSING")
        if value is not None and evidence and source_text is not None and name not in URL_FIELDS:
            if _ground_text(evidence) not in _ground_text(source_text):
                value, confidence = None, 0.0
                reasons.append(f"{name.upper()}_EVIDENCE_NOT_IN_SOURCE")
            elif name in DATE_FIELDS and _valid_datetime(value) and not _date_supported(value, evidence, name):
                value, confidence = None, 0.0
                reasons.append(f"{name.upper()}_EVIDENCE_MISMATCH")
            elif name in {"fee_text", "credits_text"} and not _numbers_supported(value, evidence):
                value, confidence = None, 0.0
                reasons.append(f"{name.upper()}_EVIDENCE_MISMATCH")
            elif name in {"title", "organizer", "audience_conditions", "credits_text",
                          "event_start_text", "event_end_text", "stream_start_text", "stream_end_text",
                          "venue_name", "venue_address", "venue_prefecture"} and _ground_text(str(value)) not in _ground_text(evidence):
                value, confidence = None, 0.0
                reasons.append(f"{name.upper()}_EVIDENCE_MISMATCH")
            elif name == "fee_text" and re.search(r"[:：]\s*(?:[、,;；]|$)", str(value)):
                value, confidence = None, 0.0
                reasons.append("FEE_TEXT_INCOMPLETE")
            elif name == "fee_text" and _fee_ground(str(value)) not in _fee_ground(evidence):
                value, confidence = None, 0.0
                reasons.append("FEE_TEXT_EVIDENCE_MISMATCH")
            elif name == "fee_category" and value == "無料" and not _free_supported(evidence):
                value, confidence = None, 0.0
                reasons.append("FEE_CATEGORY_EVIDENCE_MISMATCH")
        if value is not None and name in DATE_FIELDS and not _valid_datetime(value):
            value = None
            confidence = 0.0
            reasons.append(f"{name.upper()}_INVALID")
        if value is not None and name in DATE_FIELDS:
            from .rules import JST
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST).isoformat()
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
        if name == "event_date_precision" and value not in {None, "date", "datetime"}:
            value, confidence = None, 0.0
            reasons.append("DATE_PRECISION_INVALID")
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
        is_event=raw.get("is_event") is True,
        event_confidence=_confidence(raw.get("event_confidence")),
        fields=fields,
        review_reasons=tuple(dict.fromkeys(reasons)),
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        cache_hit=cache_hit,
    )


def _ground_text(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def _date_supported(value: str, evidence: str, name: str) -> bool:
    from .rules import DATE_PATTERN, JST, _normalized
    date = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST)
    normalized = _normalized(evidence)
    # A single explicit year in a same-year range also governs the short end
    # date: 2026年11月20日〜12月10日. Never use publication year or roll years.
    if name in {"event_end", "stream_end"}:
        range_end = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*\d{1,2}日[^\n]{0,30}?(?:〜|~|～|から)\s*(\d{1,2})月\s*(\d{1,2})日", normalized)
        if range_end and int(range_end[1]) == date.year and int(range_end[3]) >= int(range_end[2]) and (int(range_end[3]), int(range_end[4])) == (date.month, date.day):
            normalized = normalized[:range_end.start(3)] + str(date.year) + "年" + normalized[range_end.start(3):]
    for match in DATE_PATTERN.finditer(normalized):
        prefix = normalized[max(0, match.start()-15):match.start()]
        if name in {"event_start", "event_end", "stream_start", "stream_end"} and re.search(r"投稿日|掲載日|更新日|公開日", prefix) and not re.search(r"開催|会期|日程|配信", prefix):
            continue
        if (int(match["year"]), int(match["month"]), int(match["day"])) != (date.year, date.month, date.day):
            continue
        if match["hour"] is not None:
            if int(match["hour"]) != date.hour or int(match["minute"] or 0) != date.minute:
                # An end time may follow the first date's start time in a range.
                if name not in {"event_end", "stream_end"} or not re.search(
                    rf"(?:~|〜|～|-|−|－|–|—|から|to)\s*0?{date.hour}[:：時]0?{date.minute}", normalized):
                    continue
        elif (date.hour, date.minute, date.second) not in {(0, 0, 0), (23, 59, 0), (23, 59, 59)}:
            continue
        return True
    return False


def _free_supported(evidence: str) -> bool:
    text = _ground_text(evidence).replace(",", "")
    matches = re.findall(r"(?:[¥￥](\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)円)", text)
    amounts = [float(a or b) for a, b in matches]
    return ("無料" in text or any(value == 0 for value in amounts)) and not any(value > 0 for value in amounts)


def _fee_ground(value: str) -> str:
    # Formatting may change; fee amounts must remain tied to the original roles.
    text = re.sub(r"[￥¥](\d[\d,]*(?:\.\d+)?)", r"\1円", _ground_text(value))
    return re.sub(r"[,，:：、。・／/;；|]", "", text)


def _numbers_supported(value: Any, evidence: str) -> bool:
    numbers = lambda text: set(re.findall(r"\d+(?:\.\d+)?", _ground_text(str(text)).replace(",", "")))
    return numbers(value).issubset(numbers(evidence))


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except (ValueError, AttributeError):
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").lower()
    netloc = host
    if port and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, quote(parsed.path or "/", safe="/%:@"),
        quote(parsed.query, safe="=&%/?:@+"), ""))


def _confidence(value: Any) -> float:
    try:
        number = float(value)
        return min(1.0, max(0.0, number)) if math.isfinite(number) else 0.0
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
