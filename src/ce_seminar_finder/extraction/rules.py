from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlsplit

from .models import ExtractedField


JST = timezone(timedelta(hours=9))
DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})[年/\-.]"
    r"(?P<month>0?[1-9]|1[0-2])[月/\-.]"
    r"(?P<day>0?[1-9]|[12]\d|3[01])日?"
    r"(?:\s*[（(]?[月火水木金土日][）)]?)?"
    r"(?:\s*(?P<hour>[01]?\d|2[0-3])[:：時]"
    r"(?P<minute>[0-5]?\d)?分?)?"
)
URL_PATTERN = re.compile(r"https?://[^\s<>'\"）)]+")
FEE_PATTERN = re.compile(
    r"(?:参加費|受講料|料金)[：:\s]*(?P<value>無料|[\d,，]+円(?:[^\n。]{0,80})?)"
)
CREDIT_PATTERN = re.compile(
    r"(?P<value>[^\n。]{0,60}(?:単位|ポイント)[^\n。]{0,80})"
)


def extract_rule_values(
    text: str,
    *,
    allowed_urls: Iterable[str] = (),
) -> dict[str, ExtractedField]:
    values: dict[str, ExtractedField] = {}
    date_match = DATE_PATTERN.search(text)
    if date_match:
        hour = int(date_match.group("hour") or 0)
        minute = int(date_match.group("minute") or 0)
        try:
            parsed = datetime(
                int(date_match.group("year")),
                int(date_match.group("month")),
                int(date_match.group("day")),
                hour,
                minute,
                tzinfo=JST,
            )
        except ValueError:
            pass
        else:
            evidence = date_match.group(0)
            values["event_start"] = ExtractedField(
                parsed.isoformat(),
                0.92 if date_match.group("hour") else 0.85,
                evidence,
            )

    fee_match = FEE_PATTERN.search(text)
    if fee_match:
        evidence = fee_match.group(0)
        fee_text = fee_match.group("value").strip()
        values["fee_text"] = ExtractedField(fee_text, 0.95, evidence)
        values["fee_category"] = ExtractedField(
            "無料" if "無料" in fee_text else "有料",
            0.95,
            evidence,
        )

    credit_match = CREDIT_PATTERN.search(text)
    if credit_match:
        evidence = " ".join(credit_match.group("value").split())
        values["credits_text"] = ExtractedField(evidence, 0.9, evidence)

    allowed = {_normalize_url(url) for url in allowed_urls}
    for found in URL_PATTERN.findall(text):
        normalized = _normalize_url(found)
        if normalized and normalized in allowed:
            values.setdefault(
                "application_url",
                ExtractedField(normalized, 1.0, found[:300]),
            )
            break
    return values


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed.geturl()
