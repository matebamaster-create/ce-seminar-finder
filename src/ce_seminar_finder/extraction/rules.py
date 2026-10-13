from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlsplit
from .models import ExtractedField

JST = timezone(timedelta(hours=9))
DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})(?:[（(][^）)]{1,10}[）)])?[年/\-.]\s*"
    r"(?P<month>1[0-2]|0?[1-9])[月/\-.]\s*(?P<day>[12]\d|3[01]|0?[1-9])日?"
    r"(?:\s*[（(]?[月火水木金土日](?:曜日?)?[）)]?)?"
    r"(?:\s*(?P<hour>[01]?\d|2[0-3])[:：時](?P<minute>[0-5]?\d)?分?)?"
)
URL_PATTERN = re.compile(r"https?://[^\s<>'\"）)]+")
LABELS = (
    "学会・セミナー開催日", "開催日時", "開催日", "日時", "日程", "会期", "配信期間", "開催方法", "開催形式",
    "参加費", "受講料", "聴講料", "料金", "参加定員", "募集定員", "定員", "人数",
    "申込締め切り", "申込締切", "申込み締切", "申し込み締切", "締め切り", "締切",
    "申込方法", "参加申込", "お申込み先", "お申し込み先", "申込期間", "会場", "場所",
    "対象", "主催", "共催", "取得単位", "プログラム", "お問い合わせ", "講師", "詳細", "名称",
)
LABEL_PATTERN = re.compile("|".join(re.escape(x) for x in sorted(LABELS, key=len, reverse=True)))


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"令和\s*(\d+)\s*年", lambda m: str(2018 + int(m[1])) + "年", text)
    for label in ("参加費", "締切", "定員", "受講料", "会場"):
        text = re.sub(r"\s*".join(label), label, text)
    return re.sub(r"(\d[\d\s]*)([年月日])", lambda m: re.sub(r"\s+", "", m[1]) + m[2], text)


def _value_after(text: str, labels: tuple[str, ...]) -> str:
    match = re.search("|".join(re.escape(x) for x in sorted(labels, key=len, reverse=True)), text)
    if not match:
        return ""
    tail = text[match.end():].lstrip(" \t\r\n:：")
    boundary = LABEL_PATTERN.search(tail)
    return (tail[:boundary.start()] if boundary else tail).split("。", 1)[0].strip()[:500]


def _date(match, *, end_of_day=False):
    return datetime(int(match["year"]), int(match["month"]), int(match["day"]),
        int(match["hour"] if match["hour"] is not None else (23 if end_of_day else 0)),
        int(match["minute"] if match["minute"] is not None else (59 if end_of_day else 0)), tzinfo=JST)


def extract_rule_values(text: str, *, allowed_urls: Iterable[str] = (), title_hint: str = "") -> dict[str, ExtractedField]:
    text = _normalized(text)
    values = {}

    def put(name, value, evidence, confidence=0.9):
        if value is not None and evidence:
            values[name] = ExtractedField(value, confidence, evidence[:300])

    date_text = _value_after(text, ("学会・セミナー開催日", "開催日時", "開催日", "日時", "日程", "会期"))
    if not date_text and DATE_PATTERN.match(_normalized(title_hint)):
        # A source's dated event-link label is not an article publication date.
        date_text = _normalized(title_hint)
    match = DATE_PATTERN.search(date_text)
    if match:
        try:
            start = _date(match)
            put("event_start", start.isoformat(), match[0], 0.92)
            put("event_date_precision", "datetime" if match["hour"] else "date", match[0])
            time_end = re.search(r"[~〜～－-]\s*(\d{1,2})[:時](\d{2})", date_text[match.end():])
            if time_end and match["hour"]:
                end = start.replace(hour=int(time_end[1]), minute=int(time_end[2]))
                if end >= start:
                    put("event_end", end.isoformat(), date_text)
        except ValueError:
            pass

    stream_text = _value_after(text, ("配信期間",))
    stream_dates = list(DATE_PATTERN.finditer(stream_text))
    if stream_dates:
        try:
            first = _date(stream_dates[0])
            put("stream_start", first.isoformat(), stream_text)
            if len(stream_dates) > 1:
                last = _date(stream_dates[1], end_of_day=True)
            else:
                short_end = re.search(r"[~〜～]\s*(\d{1,2})月\s*(\d{1,2})日", stream_text[stream_dates[0].end():])
                last = first.replace(month=int(short_end[1]), day=int(short_end[2]), hour=23, minute=59) if short_end else None
            if last and last >= first:
                put("stream_end", last.isoformat(), stream_text)
            put("stream_period_text", " ".join(stream_text.split()), stream_text)
        except ValueError:
            pass

    fee_text = _value_after(text, ("参加費", "受講料", "聴講料", "料金"))
    amounts = list(re.finditer(r"[\d,]+\s*円|無料", fee_text))
    if amounts:
        fee_text = fee_text[:amounts[-1].end()].strip()
        if not re.search(r"[:：]\s*(?:[、,;；]|$)", fee_text):
            put("fee_text", " ".join(fee_text.split()), fee_text, 0.92)
        paid = any(int(re.sub(r"\D", "", m[0]) or "0") > 0 for m in amounts if "円" in m[0])
        put("fee_category", "有料" if paid else "無料", fee_text, 0.92)

    deadline = _value_after(text, ("申込締め切り", "申込締切", "申込み締切", "申し込み締切", "締め切り", "締切"))
    match = DATE_PATTERN.search(deadline)
    if match:
        try:
            put("application_deadline_at", _date(match, end_of_day=True).isoformat(), match[0], 0.92)
            put("application_deadline_text", match[0], match[0], 0.92)
        except ValueError:
            pass

    capacity = _value_after(text, ("参加定員", "募集定員", "定員", "人数"))
    match = re.match(r"(?:先着\s*)?[\d,]+\s*(?:名|人)(?:程度)?", capacity)
    if match:
        put("capacity_text", match[0], match[0])

    credit = _value_after(text, ("取得単位",))
    if not credit:
        match = re.search(r"[^\n。]{0,60}\d+\s*(?:単位|ポイント|点)[^\n。]{0,60}", text)
        credit = match[0] if match else ""
    if credit:
        put("credits_text", " ".join(credit.split())[:250], credit, 0.8)

    hint = _value_after(text, ("開催方法", "開催形式")) or title_hint
    for pattern, value in ((r"ハイブリッド|現地.+(?:Web|配信)|ライブ.+オンデマンド", "ハイブリッド"),
        (r"オンデマンド|録画", "オンデマンド"), (r"Web|オンライン|Zoom|ライブ配信|Live", "Web"),
        (r"現地|会場参加|対面", "現地開催")):
        if re.search(pattern, hint, re.I):
            put("format", value, hint)
            break

    title = title_hint or text[:180]
    genres = [genre for genre, keywords in (("血液浄化", "透析|血液浄化|CHDF|アフェレシス|VA|穿刺"),
        ("呼吸", "呼吸|人工呼吸"), ("循環", "循環|心電図|心臓|PCI|ICD|不整脈|ECMO"),
        ("医療機器管理", "医療機器|医療安全|MDIC|医療ガス"), ("手術室", "手術|外科"),
        ("教育・研究", "学会|学術|教育|研究"), ("DX・IT", "(?<![A-Za-z])(?:AI|DX|IT)(?![A-Za-z])")) if re.search(keywords, title, re.I)]
    if genres:
        put("genres", genres, title)
    for event_type, keyword in (("学会・大会", "学会|大会|学術集会"), ("研究会", "研究会"),
        ("講習会", "講習"), ("研修会", "研修"), ("セミナー", "セミナー|勉強会|カンファレンス")):
        if re.search(keyword, title):
            put("event_type", event_type, title)
            break
    organizer = _value_after(text, ("主催",))
    before = re.search(r"([^\n。]{1,70}(?:臨床工学技士会|研究会|学会|協議会))\s*主催", text)
    if before:
        organizer = before[1].strip()
    elif organizer.startswith(("の", "「", "『")):
        organizer = ""
    if organizer and len(organizer) <= 140:
        put("organizer", " ".join(organizer.split()), organizer, 0.85)
    allowed = {_normalize_url(url) for url in allowed_urls}
    application = _value_after(text, ("申込方法", "参加申込", "お申込み先", "お申し込み先", "申込"))
    for found in URL_PATTERN.findall(application):
        normalized = _normalize_url(found)
        if normalized and normalized in allowed and not normalized.lower().split("?")[0].endswith(".pdf"):
            put("application_url", normalized, found, 1.0)
            break
    return values


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    return parsed.geturl() if parsed.scheme in {"http", "https"} and parsed.netloc else ""
