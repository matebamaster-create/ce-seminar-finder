from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit


CORPORATE_FORMS = (
    "公益社団法人",
    "一般社団法人",
    "公益財団法人",
    "一般財団法人",
    "特定非営利活動法人",
    "NPO法人",
)
FORMAT_WORDS = (
    "オンライン",
    "web",
    "ウェブ",
    "オンデマンド",
    "ハイブリッド",
    "現地開催",
)


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    event_id: str
    title: str
    event_start_at: str | None = None
    organizer_name: str | None = None
    event_format: str | None = None
    official_urls: tuple[str, ...] = ()
    application_urls: tuple[str, ...] = ()
    pdf_hashes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DuplicateAssessment:
    event_id_a: str
    event_id_b: str
    total_score: float
    title_score: float
    date_score: float
    organizer_score: float
    url_score: float
    format_score: float
    deterministic_anchor: str
    disposition: str

    @property
    def auto_merge_candidate(self) -> bool:
        return self.disposition == "auto_merge_candidate"


def assess_duplicate(
    event_a: EventSnapshot,
    event_b: EventSnapshot,
) -> DuplicateAssessment:
    title_score = _similarity(
        normalize_title(event_a.title),
        normalize_title(event_b.title),
    )
    date_score = _date_score(event_a.event_start_at, event_b.event_start_at)
    organizer_score = _similarity(
        normalize_organizer(event_a.organizer_name or ""),
        normalize_organizer(event_b.organizer_name or ""),
    )
    format_score = _format_score(event_a.event_format, event_b.event_format)
    anchor = _deterministic_anchor(event_a, event_b)
    url_score = 1.0 if anchor else 0.0
    total = round(
        title_score * 0.40
        + date_score * 0.25
        + organizer_score * 0.15
        + url_score * 0.15
        + format_score * 0.05,
        4,
    )
    if total >= 0.85 and anchor:
        disposition = "auto_merge_candidate"
    elif total >= 0.65:
        disposition = "review"
    else:
        disposition = "separate"
    return DuplicateAssessment(
        event_id_a=event_a.event_id,
        event_id_b=event_b.event_id,
        total_score=total,
        title_score=round(title_score, 4),
        date_score=round(date_score, 4),
        organizer_score=round(organizer_score, 4),
        url_score=url_score,
        format_score=round(format_score, 4),
        deterministic_anchor=anchor,
        disposition=disposition,
    )


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    for word in FORMAT_WORDS:
        normalized = normalized.replace(word, " ")
    normalized = re.sub(r"[「」『』【】()\[\]（）:：・,，。~〜～／/]", " ", normalized)
    return re.sub(r"\s+", "", normalized)


def normalize_organizer(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    for form in CORPORATE_FORMS:
        normalized = normalized.replace(form.lower(), "")
    return re.sub(r"[\s・,，。]", "", normalized)


def _similarity(value_a: str, value_b: str) -> float:
    if not value_a or not value_b:
        return 0.0
    return SequenceMatcher(None, value_a, value_b).ratio()


def _date_score(value_a: str | None, value_b: str | None) -> float:
    date_a = _parse_datetime(value_a)
    date_b = _parse_datetime(value_b)
    if date_a is None or date_b is None:
        return 0.0
    if date_a.date() == date_b.date():
        return 1.0
    if abs((date_a.date() - date_b.date()).days) == 1:
        return 0.4
    return 0.0


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_score(value_a: str | None, value_b: str | None) -> float:
    if not value_a or not value_b:
        return 0.0
    return 1.0 if value_a == value_b else 0.0


def _deterministic_anchor(a: EventSnapshot, b: EventSnapshot) -> str:
    official = _normalized_urls(a.official_urls) & _normalized_urls(b.official_urls)
    if official:
        return "official_url"
    application = _normalized_urls(a.application_urls) & _normalized_urls(
        b.application_urls
    )
    if application:
        return "application_url"
    hashes_a = {value.lower() for value in a.pdf_hashes if value}
    hashes_b = {value.lower() for value in b.pdf_hashes if value}
    if hashes_a & hashes_b:
        return "pdf_hash"
    return ""


def _normalized_urls(values: tuple[str, ...]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        host = parsed.hostname.lower()
        path = parsed.path.rstrip("/") or "/"
        normalized.add(
            urlunsplit(
                (parsed.scheme.lower(), host, path, parsed.query, "")
            )
        )
    return normalized
