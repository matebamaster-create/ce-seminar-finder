"""User-approved, source-grounded decisions; no AI calls and no hard deletes."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from ce_seminar_finder.adapters.common import is_title_hint
from ce_seminar_finder.collection.ingestion import CandidateIngestor, FIELD_MAP, stable_id, _cell
from ce_seminar_finder.collection.sources import source_configs, allowed_hosts
from ce_seminar_finder.collection.models import EventCandidate
from ce_seminar_finder.collection.snapshots import SNAPSHOT_METHOD
from ce_seminar_finder.extraction.refinement import candidate_from_payload, candidate_content_hash
from ce_seminar_finder.extraction.validator import validate_extraction, _ground_text, _normalize_url, _fee_ground
from ce_seminar_finder.extraction.rules import DATE_PATTERN, LABELS, _normalized, extract_rule_values
from ce_seminar_finder.sheets.schema import (
    EVENTS_HEADERS, EVENT_SOURCES_HEADERS, REVIEW_QUEUE_HEADERS, AUTO_FIELD_HEADERS,
    DOCUMENTS_HEADERS, DOCUMENT_TEXT_HEADERS, FIELD_OVERRIDE_HEADERS, SOURCES_HEADERS,
    DUPLICATE_HEADERS, REVIEW_ACTION_HEADERS, AUTOMATION_RULE_HEADERS,
)
from .duplicates import normalize_title, normalize_organizer

POLICY = "grounded_v1"
POLICY_REVISION = "grounded_facts_r2"
RULE_ID = "rule_grounded_v1_west20261013"
ACTOR = "automation:grounded_v1"
REVERSE_FIELDS = {v: k for k, v in FIELD_MAP.items()}
REVERSE_FIELDS["application_deadline_at"] = "application_deadline"
OPTIONAL_FIELDS = ("application_deadline_at", "application_url", "credits_text", "capacity_text")
NON_EVENT_TITLE = re.compile(r"求人|採用|会費(?:納入|案内)|役員選挙|議事録|アンケート|実態調査|業務実態報告")
LEARNING_TITLE = re.compile(r"セミナー|研修|講習|勉強会|カンファレンス|学術集会|学術大会|研究会|ハンズオン")
CATALOGUE_TITLE = re.compile(r"学会[/／]研究会[/／]セミナー")


def literal_fee_quote(value):
    text = str(value or "").strip()
    # Retain every qualifier and participant category in a concise fee quote.
    # A number alone, dues, discounts or a cropped table cannot repair fees.
    return bool(len(text) <= 180 and re.search(r"参加\s*費|受\s*講\s*料|聴\s*講\s*料|登録\s*料", text)
                and re.search(r"無料|[\d,]+\s*円|[￥¥]\s*[\d,]+", text)
                and not re.search(r"年会費|月会費|割引|要確認|未定|別途|[：:]\s*$", text))


def fee_section(text):
    match = re.search(r"参加費|受講料|聴講料|登録料|料金", _normalized(text))
    if not match:
        return ""
    tail = _normalized(text)[match.end():match.end()+500]
    return re.split(r"開催日時|開催方法|締切|締め切り|定員|対象|主催|共催|取得単位|申込方法|お問い合わせ", tail, maxsplit=1)[0]


def comparable_fee(value):
    return _fee_ground(re.sub(r"^(?:参加費|受講料|聴講料|登録料|料金)\s*[:：]?\s*", "", _normalized(str(value))))


def source_url(value):
    # Percent-escape letter case is not a different resource. Do not decode
    # reserved path separators or treat arbitrary hosts as equivalent.
    return re.sub(r"%[0-9a-fA-F]{2}", lambda match: match[0].upper(), _normalize_url(str(value)))


def truth(value):
    return value is True or str(value).lower() in {"true", "1"}


def parsed(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def json_value(value, default=None):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def clean(row):
    return {k: v for k, v in row.items() if not k.startswith("__")}


@dataclass
class InputProof:
    event_source_id: str
    source_id: str
    candidate: object
    html: str
    pdfs: dict

    @property
    def text(self):
        return self.html + "\n" + "\n".join(p["text"] for p in self.pdfs.values())


class AutomaticReviewer:
    def __init__(self, service, spreadsheet_id, *, now=None, ensure_capacity=None):
        self.writer = CandidateIngestor(service, spreadsheet_id, ensure_capacity=ensure_capacity)
        self.now = now or datetime.now(UTC)
        if self.now.tzinfo is None:
            raise ValueError("now must include a timezone")
        self.tables = {}

    def read(self):
        specs = {"Events": EVENTS_HEADERS, "EventSources": EVENT_SOURCES_HEADERS,
            "ReviewQueue": REVIEW_QUEUE_HEADERS, "AutoFieldValues": AUTO_FIELD_HEADERS,
            "Documents": DOCUMENTS_HEADERS, "DocumentTextChunks": DOCUMENT_TEXT_HEADERS,
            "FieldOverrides": FIELD_OVERRIDE_HEADERS, "Sources": SOURCES_HEADERS,
            "DuplicateCandidates": DUPLICATE_HEADERS, "ReviewActions": REVIEW_ACTION_HEADERS,
            "AutomationRules": AUTOMATION_RULE_HEADERS}
        self.tables = {name: self.writer._rows(name, len(headers)) for name, headers in specs.items()}
        return specs

    def enable_policy(self):
        """Only the explicit CLI enable flag records the owner's authorization."""
        self.read()
        ids = {s.source_id for s in source_configs()}
        now = self.now.isoformat()
        source_rows = []
        for source in self.tables["Sources"]:
            if source.get("source_id") in ids and source.get("auto_publish_policy") != "allow":
                source_rows.append({**source, "auto_publish_policy": "allow"})
        existing = next((r for r in self.tables["AutomationRules"] if r.get("rule_id") == RULE_ID), {})
        if existing:
            # This switch is initial authorization, not a way to undo a later
            # operator stop or per-source opt-out on an automated retry.
            return
        rule = {**existing, "rule_id": RULE_ID, "enabled": True, "scope": "western_31_official",
            "condition_json": json.dumps({"policy_version": POLICY, "source_ids": sorted(ids)}, ensure_ascii=False),
            "action": "publish", "approved_from_action_id": "act_user_grounded_west20261013",
            "approved_by": "owner:explicit-user-approval-2026-10-13", "approved_at": existing.get("approved_at") or now,
            "notes": "公式原文の日時・料金・主催・形式を検証。曖昧な重複と読み取り不良だけ人の確認へ。"}
        policy_column = self.writer._column(SOURCES_HEADERS.index("auto_publish_policy") + 1)
        self.writer._write_batches([{"range": f"'Sources'!{policy_column}{row['__row_number']}",
            "values": [["allow"]]} for row in source_rows])
        # The authorization marker is last; a partial setup cannot publish.
        self._write_rows("AutomationRules", [rule], AUTOMATION_RULE_HEADERS)

    def _proofs(self):
        chunks = defaultdict(list)
        for row in self.tables["DocumentTextChunks"]:
            if row.get("document_id") and row.get("text"):
                chunks[row["document_id"]].append(row)
        docs = defaultdict(list)
        for row in self.tables["Documents"]:
            docs[row.get("event_source_id")].append(row)
        proofs = {}
        broken = set()
        for sid, documents in docs.items():
            snapshot = next((d for d in documents if d.get("extraction_method") == SNAPSHOT_METHOD), None)
            if not snapshot:
                continue
            parts = sorted(chunks[snapshot["document_id"]], key=lambda c: int(c["chunk_index"]))
            text = "".join(str(c["text"]) for c in parts)
            if hashlib.sha256(text.encode()).hexdigest() != snapshot.get("sha256"):
                broken.add(sid)
                continue
            try:
                candidate = candidate_from_payload(json.loads(text))
            except (ValueError, KeyError, TypeError):
                broken.add(sid)
                continue
            pdfs, latest_pdf = {}, {}
            allowed_pdf_urls = {source_url(u) for u in candidate.pdf_urls}
            if urlsplit(candidate.detail_url).path.lower().endswith(".pdf"):
                allowed_pdf_urls.add(source_url(candidate.detail_url))
            for document in documents:
                if document.get("document_type") != "pdf":
                    continue
                url = source_url(document.get("url") or "")
                if url not in allowed_pdf_urls:
                    continue
                if url not in latest_pdf or str(document.get("fetched_at")) > str(latest_pdf[url].get("fetched_at")):
                    latest_pdf[url] = document
            for document in latest_pdf.values():
                parts = sorted(chunks[document["document_id"]], key=lambda c: int(c["chunk_index"]))
                complete = bool(parts) and all(hashlib.sha256(str(c["text"]).encode()).hexdigest() == c.get("text_hash") for c in parts)
                pdfs[document["document_id"]] = {"text": "\n".join(str(c["text"]) for c in parts) if complete else "",
                    "safe": complete and document.get("extraction_status") == "success"
                        and document.get("extraction_method") == "text_layer"
                        and not document.get("error_code"),
                    "hash": document.get("sha256"), "url": document.get("url")}
            proofs[sid] = InputProof(sid, candidate.source_id, candidate,
                candidate.title_hint + "\n" + candidate.block_text, pdfs)
        return proofs, broken

    def _support(self, event, name, proofs, autos, *, allow_ocr=False):
        value = event.get(name)
        if value in (None, ""):
            return False
        if name == "fee_text" and not re.search(r"無料|[\d,]+\s*円|[￥¥]\s*[\d,]+", str(value)):
            return False
        mapped = REVERSE_FIELDS.get(name, name)
        for auto in autos:
            if auto.get("field_name") != name:
                continue
            evidence = str(auto.get("evidence_text") or "")
            same = self._equal(value, json_value(auto.get("normalized_value_json")), name)
            if not same and not (name == "fee_text" and literal_fee_quote(evidence) and self._equal(value, evidence, name)):
                continue
            if not evidence:
                continue
            for proof in proofs:
                # Even OCR evidence is acceptable when the official HTML
                # independently contains and supports the identical fact.
                contexts = [proof.html]
                contexts.extend(p["text"] for id_, p in proof.pdfs.items()
                    if (p["safe"] or allow_ocr) and id_ == auto.get("source_document_id"))
                for text in contexts:
                    quote = evidence
                    if name == "organizer_name" and (len(str(value)) > 100
                            or not re.search(r"技士会|学会|研究会|協議会|委員会|大学|病院|会社|法人", str(value))
                            or re.search(r"電話|FAX|TEL|https?://|@|〒", str(value), re.I)):
                        continue
                    if name == "fee_text":
                        section = fee_section(text)
                        if re.search(r"非会員|会員|一般|学生", section) and re.search(r"未定|後日|別途|要相談|要確認", section):
                            continue
                    if auto.get("extractor") == "rule" and mapped in {"event_start", "event_end", "stream_start", "stream_end"}:
                        # Rule quotes are normalized Gregorian dates; apply
                        # the identical deterministic era conversion to source.
                        text, quote = _normalized(text), _normalized(evidence)
                    result = validate_extraction({"is_event": True, "event_confidence": 1,
                        "fields": {mapped: {"value": value, "confidence": 1, "evidence": quote}}},
                        allowed_urls=(), provider="grounded-policy", model="", prompt_version=POLICY, source_text=text)
                    field = result.fields.get(mapped)
                    if not field or field.value is None or result.review_reasons:
                        continue
                    if name == "format" and not self._format_supported(str(value), evidence):
                        continue
                    if mapped in {"event_start", "event_end", "stream_start", "stream_end"} and not self._date_context(text, quote):
                        continue
                    if name == "fee_text" and _fee_ground(str(value)) not in _fee_ground(evidence):
                        continue
                    return True
        if name == "title":
            return any(_ground_text(str(value)) in _ground_text(p.html) for p in proofs)
        return False

    @staticmethod
    def _date_context(text, evidence):
        source, quote = _ground_text(text), _ground_text(evidence)
        start = 0
        while quote and (at := source.find(quote, start)) >= 0:
            prefix = source[max(0, at - 35):at]
            if not re.search(r"投稿日|掲載日|更新日|公開日", prefix) or re.search(r"開催|日時|日程|会期|配信", prefix):
                return True
            start = at + len(quote)
        return False

    @staticmethod
    def _equal(a, b, field):
        if isinstance(a, str) and isinstance(b, (list, tuple)):
            return a.splitlines() == list(b)
        if field == "fee_text":
            return comparable_fee(a) == comparable_fee(b)
        if field.endswith("_at") and parsed(a) and parsed(b):
            return parsed(a) == parsed(b)
        return _ground_text(str(a)) == _ground_text(str(b))

    @staticmethod
    def _format_supported(value, evidence):
        if value == "Web":
            return bool(re.search(r"Web|オンライン|Zoom|ライブ|LIVE", evidence, re.I)) and not re.search(r"オンデマンド|録画|e-?learning", evidence, re.I)
        if value == "オンデマンド":
            return bool(re.search(r"オンデマンド|録画|e-?learning|eラーニング", evidence, re.I))
        if value == "ハイブリッド":
            return bool(re.search(r"ハイブリッド|現地.*(?:Web|配信)|会場.*(?:Web|オンライン)", evidence, re.I))
        if value == "現地開催":
            return bool(re.search(r"現地|対面|会場|ホール|会議室|講堂|学校", evidence)) and not re.search(r"Web|Zoom|オンライン", evidence, re.I)
        return False

    def _classification(self, event, proofs, autos):
        for row in autos:
            if row.get("field_name") != "is_event" or row.get("extractor") != "ai":
                continue
            location = json_value(row.get("evidence_location"), {})
            if not isinstance(location, dict) or not location.get("cache_key"):
                continue
            if any(location.get("content_hash") == candidate_content_hash(p.candidate) for p in proofs
                   if row.get("source_document_id") == p.event_source_id):
                return json_value(row.get("normalized_value_json")), location
        return None, {}

    def _base_decision(self, event, proofs, autos, broken):
        if broken and not proofs:
            return "technical", ["AUTO_SOURCE_INTEGRITY_PENDING"]
        if not proofs:
            return "technical", ["AUTO_SOURCE_RECOVERY_PENDING"]
        if all(not p.candidate.block_text.strip() and not p.candidate.pdf_urls for p in proofs):
            return "technical", ["AUTO_SOURCE_RECOVERY_PENDING"]
        classification, location = self._classification(event, proofs, autos)
        title = str(event.get("title") or "")
        if all(CATALOGUE_TITLE.search(p.candidate.title_hint) for p in proofs):
            return "technical", ["AUTO_SOURCE_SPLIT_PENDING"]
        if event.get("publication_status") == "確認待ち" and any(
            re.search(r"御礼|お礼|開催報告", p.candidate.title_hint)
            and _ground_text(title) in _ground_text(p.html)
            and re.search(r"無事終了|盛会のうちに.{0,12}(?:終了|閉幕)|終了いたしました", p.candidate.block_text)
            for p in proofs):
            return "archive", ["PAST_EVENT_CANDIDATE"]
        if classification is False:
            if NON_EVENT_TITLE.search(title) and not LEARNING_TITLE.search(title):
                return "reject", ["NON_EVENT_CANDIDATE"]
            return "human", ["EVENT_CLASSIFICATION_CONFLICT"]
        streaming = event.get("format") == "オンデマンド" or bool(not event.get("event_start_at") and event.get("stream_start_at"))
        start_field = "stream_start_at" if streaming and event.get("stream_start_at") else "event_start_at"
        start = parsed(event.get(start_field))
        end_field = "stream_end_at" if streaming else "event_end_at"
        end = parsed(event.get(end_field))
        # A reversed range or a month-spanning live event needs schedule-level
        # review, even when both dates occur somewhere in a long source page.
        if start and end and (end < start or not streaming
                              and end - start > timedelta(days=31)):
            return "human", ["DATE_CONFLICT"]
        if start and self._support(event, start_field, proofs, autos):
            for auto in autos:
                alternate = json_value(auto.get("normalized_value_json"))
                if auto.get("field_name") == start_field and parsed(alternate) and parsed(alternate) != start and self._support({**event, start_field: alternate}, start_field, proofs, [auto]):
                    if (parsed(alternate).date() >= self.now.astimezone(start.tzinfo).date()) != (start.date() >= self.now.astimezone(start.tzinfo).date()):
                        return "human", ["SOURCE_FIELD_CONFLICT"]
            if end and self._support(event, end_field, proofs, autos) and end < self.now:
                return "archive", ["PAST_EVENT_CANDIDATE"]
            if not streaming and not end and start.date() < self.now.astimezone(start.tzinfo).date():
                future_dates = []
                for proof in proofs:
                    for match in DATE_PATTERN.finditer(_normalized(proof.text)):
                        try:
                            future_dates.append(datetime(int(match["year"]), int(match["month"]), int(match["day"]), tzinfo=start.tzinfo).date())
                        except ValueError:
                            pass
                if not any(d >= self.now.astimezone(start.tzinfo).date() for d in future_dates):
                    return "archive", ["PAST_EVENT_CANDIDATE"]
        if classification is None:
            # A lost/stale AI-to-input association is not a reason to pay for
            # the same input again. A single, explicitly dated old notice can
            # be closed using its verified HTML without adopting stale AI facts.
            if self._grounded_old_notice(event, proofs):
                return "archive", ["PAST_EVENT_CANDIDATE"]
            if self._changed_listing_target(event, proofs, autos):
                return "technical", ["AUTO_SOURCE_SPLIT_PENDING"]
            return "processing", ["AUTO_PROCESSING_PENDING"]
        reasons = []
        required = ("title", "organizer_name", "format", "fee_text", start_field)
        for field in required:
            if not self._support(event, field, proofs, autos):
                reasons.append("AUTO_" + field.upper() + "_UNVERIFIED")
        if not is_title_hint(title):
            reasons.append("EVENT_CLASSIFICATION_CONFLICT")
        if re.fullmatch(r"(?:学会・)?(?:セミナー|研修会|講習会|研究会|イベント|学会)(?:情報|案内|一覧|のお知らせ|開催案内)?", title.strip()):
            reasons.append("EVENT_CLASSIFICATION_CONFLICT")
        if not start:
            reasons.append("DATE_UNKNOWN")
        if event.get("format") == "オンデマンド" and not self._support(event, "stream_end_at", proofs, autos):
            reasons.append("AUTO_STREAM_END_AT_UNVERIFIED")
        if any(event.get(f) and not self._support(event, f, proofs, autos)
               for f in ("event_end_at", "stream_end_at")):
            reasons.append("DATE_CONFLICT")
        official = source_url(event.get("primary_official_url") or "")
        if not official or not any(official == source_url(p.candidate.detail_url) for p in proofs):
            reasons.append("OFFICIAL_URL_UNVERIFIED")
        if start and start > self.now + timedelta(days=730):
            reasons.append("DATE_OUTSIDE_NORMAL_RANGE")
        for field in required + ("event_end_at", "stream_end_at"):
            for auto in autos:
                other = json_value(auto.get("normalized_value_json"))
                if auto.get("field_name") == field and other not in (None, "") and not self._equal(event.get(field), other, field):
                    if self._conflicting_value(event.get(field), other, field) and self._support({**event, field: other}, field, proofs, [auto]):
                        reasons.append("SOURCE_FIELD_CONFLICT")
        return ("human", sorted(set(reasons))) if reasons else ("publish", [])

    def _grounded_old_notice(self, event, proofs):
        """Close a specific old grounded notice; never infer a year or read OCR."""
        title = _ground_text(str(event.get("title") or ""))
        if (event.get("publication_status") != "確認待ち" or len(title) < 8 or not LEARNING_TITLE.search(title)
                or event.get("format") == "オンデマンド" or truth(event.get("has_on_demand"))
                or event.get("stream_start_at") or event.get("stream_end_at")):
            return False
        starts = []
        for proof in proofs:
            text = _normalized(proof.candidate.block_text)
            dated_link = proof.candidate.discovery_method == "official_dated_link"
            if dated_link:
                from ce_seminar_finder.collection.recovery import dated_link_schedule, dated_link_subject
                same_link = _ground_text(proof.candidate.title_hint) == _ground_text(proof.candidate.block_text)
                same_title = dated_link_subject(event.get("title")) == dated_link_subject(proof.candidate.title_hint)
                schedule = dated_link_schedule(proof.candidate.title_hint)
            else:
                same_link = same_title = False
                schedule = ""
            for label in sorted(LABELS, key=len, reverse=True):
                text = re.sub(r"\s*".join(re.escape(c) for c in label), label, text)
            stream_hint_text = re.sub(r"録画\s*[,、]\s*録音\s*および\s*撮影\s*は\s*(?:ご遠慮|禁止)", "", text)
            schedule_labels = []
            for label in re.finditer(r"開催日時|開催日|日時|日程|会期", text):
                if not re.search(r"申込|応募|受付|締切|投稿|掲載|更新|公開", text[max(0, label.start()-8):label.start()]):
                    if DATE_PATTERN.match(text[label.end():].lstrip(" \t\r\n:：")):
                        schedule_labels.append(label)
            # A long catalogue, a second schedule or any streaming clue needs
            # targeted recovery. A past initial date cannot close a stream.
            if (not text or len(text) > 2500 or not (title in _ground_text(text) or same_link and same_title)
                    or re.search(r"オンデマンド|配信|録画|e[- ]?learning|e[-ー]?ラーニング", stream_hint_text, re.I)
                    or not (len(schedule_labels) == 1 or dated_link and same_link and same_title
                            and "開催" in text and DATE_PATTERN.match(schedule))):
                return False
            field = extract_rule_values(schedule or text, title_hint=schedule).get("event_start")
            start = parsed(field.value) if field else None
            if not start or start.date() >= self.now.astimezone(start.tzinfo).date():
                return False
            saved_start = parsed(event.get("event_start_at"))
            if saved_start and saved_start.date() != start.date():
                return False
            dates = list(DATE_PATTERN.finditer(_normalized(proof.text)))
            try:
                future = any(datetime(int(m["year"]), int(m["month"]), int(m["day"]),
                                      tzinfo=start.tzinfo).date() >= self.now.astimezone(start.tzinfo).date()
                             for m in dates)
            except ValueError:
                return False
            if not dates or future:
                return False
            rule = {"field_name": "event_start_at", "normalized_value_json": json.dumps(field.value),
                    "evidence_text": field.evidence, "extractor": "rule", "source_document_id": proof.event_source_id}
            if not self._support({**event, "event_start_at": field.value}, "event_start_at", [proof], [rule]):
                return False
            starts.append(start.date())
        return bool(starts) and len(set(starts)) == 1

    def _grounded_saved_pdf_end(self, event, sources):
        """Legacy raw HTML can be absent while its exact official PDF survives.

        This closure-only path does not invent a candidate snapshot or authorize
        publication/AI. Require the event's specific PDF URL, its source record,
        official host, successful text layer and verified stored text chunks.
        """
        url = source_url(event.get("primary_pdf_url") or "")
        if not url or not urlsplit(url).path.lower().endswith(".pdf"):
            return False
        configs = {c.source_id: c for c in source_configs()}
        found = []
        for source in sources:
            config = configs.get(source.get("source_id"))
            if not config or urlsplit(url).hostname not in allowed_hosts(config):
                continue
            matches = [d for d in self.tables["Documents"]
                       if d.get("event_source_id") == source.get("event_source_id")
                       and d.get("document_type") == "pdf" and source_url(d.get("url") or "") == url]
            if not matches:
                continue
            document = max(matches, key=lambda d: str(d.get("fetched_at") or ""))
            if (document.get("extraction_method") != "text_layer" or document.get("extraction_status") != "success"
                    or document.get("error_code") or not re.fullmatch(r"[0-9a-f]{64}", str(document.get("sha256") or ""))
                    or urlsplit(document.get("final_url") or url).hostname not in allowed_hosts(config)):
                return False
            chunks = sorted((c for c in self.tables["DocumentTextChunks"] if c.get("document_id") == document.get("document_id")),
                            key=lambda c: int(c["chunk_index"]))
            if not chunks or any(hashlib.sha256(str(c.get("text") or "").encode()).hexdigest() != c.get("text_hash") for c in chunks):
                return False
            text = "\n".join(str(c["text"]) for c in chunks)
            candidate = EventCandidate(config.source_id, source.get("source_url") or config.base_url,
                                       url, str(event.get("title") or ""), block_text=text)
            found.append(InputProof(source["event_source_id"], config.source_id, candidate,
                                    candidate.title_hint+"\n"+text, {}))
        return self._grounded_old_notice(event, found)

    @staticmethod
    def _changed_listing_target(event, proofs, autos):
        """A previously processed event now points to an unrelated catalogue."""
        title = _ground_text(str(event.get("title") or ""))
        prior_sources = {a.get("source_document_id") for a in autos
                         if a.get("field_name") == "is_event" and a.get("extractor") == "ai"
                         and isinstance(location := json_value(a.get("evidence_location"), {}), dict)
                         and location.get("cache_key")}
        if len(title) < 8 or not proofs:
            return False
        for proof in proofs:
            text = _normalized(proof.candidate.block_text)
            if (proof.event_source_id not in prior_sources or title in _ground_text(text)
                    or len(list(DATE_PATTERN.finditer(text))) < 2
                    or len(LEARNING_TITLE.findall(text)) < 2):
                return False
        return True

    @staticmethod
    def _conflicting_value(current, other, field):
        if field == "organizer_name":
            canonical = lambda value: re.sub(r"\((?:公社|一社|公財|一財)\)", "", normalize_organizer(str(value)))
            a, b = canonical(current), canonical(other)
            # A legal-form abbreviation, committee office suffix or a shorter
            # parent name is not a second organizer. Never use this to replace
            # or ground an unsupported name; this only compares supported ones.
            if a == b or min(len(a), len(b)) >= 8 and (a in b or b in a):
                return False
            if not re.search(r"技士会|学会|研究会|協議会|委員会|大学|病院|会社|法人", str(other)):
                return False
        if field == "fee_text":
            def prices(value):
                text = comparable_fee(value)
                return set(re.findall(r"\d+(?:\.\d+)?円|無料", text))
            if prices(current) != prices(other):
                return True
            for role in (r"非会員", r"(?<!非)会員", r"一般", r"学生"):
                pattern = role + r"[^\d円]{0,50}(\d+(?:\.\d+)?円|無料)"
                a = set(re.findall(pattern, comparable_fee(current)))
                b = set(re.findall(pattern, comparable_fee(other)))
                if a and b and a.isdisjoint(b):
                    return True
            return False
        return True

    def _repair_fields(self, event, proofs, autos):
        """Reconcile saved source facts locally, without another AI request.

        Only an unedited pending record calls this method. A field changes only
        when every independently grounded proposal agrees; conflicting source
        facts and unsafe/OCR-only PDF values remain unresolved.
        """
        repaired, supporting = dict(event), list(autos)
        if self._classification(event, proofs, autos)[0] is not True or any(CATALOGUE_TITLE.search(p.candidate.title_hint) for p in proofs):
            return repaired, supporting
        rules = []
        for proof in proofs:
            contexts = [(proof.event_source_id, proof.candidate.block_text)]
            # Do not interpret an unrelated linked PDF or OCR as this event's
            # schedule. Require the event title within its safe text layer.
            event_title = _ground_text(str(event.get("title") or ""))
            contexts.extend((doc, pdf["text"]) for doc, pdf in proof.pdfs.items()
                if pdf["safe"] and len(event_title) >= 8 and event_title in _ground_text(pdf["text"]))
            for doc, text in contexts:
                # Posters commonly letter-space labels: 主 催 / 開 催 方 法.
                # Normalize locally for review, not the saved AI request/cache.
                for label in sorted(LABELS, key=len, reverse=True):
                    text = re.sub(r"\s*".join(re.escape(c) for c in label), label, text)
                for name, field in extract_rule_values(text).items():
                    target = FIELD_MAP.get(name, name)
                    if target:
                        rules.append({"field_name": target, "normalized_value_json": json.dumps(field.value, ensure_ascii=False),
                            "evidence_text": field.evidence, "extractor": "rule", "source_document_id": doc})
        supporting.extend(rules)
        for name in ("organizer_name", "format", "fee_text", "event_start_at", "event_end_at", "stream_start_at", "stream_end_at"):
            if self._support(repaired, name, proofs, supporting):
                continue
            values = []
            for auto in supporting:
                if auto.get("field_name") != name:
                    continue
                choices = [json_value(auto.get("normalized_value_json"))]
                if name == "fee_text" and literal_fee_quote(auto.get("evidence_text")) and not (choices[0] not in (None, "") and self._support({**repaired, name: choices[0]}, name, proofs, [auto])):
                    choices.append(auto["evidence_text"])
                for value in choices:
                    if value not in (None, "") and self._support({**repaired, name: value}, name, proofs, [auto]):
                        if not any(self._equal(value, old, name) for old in values):
                            values.append(value)
            if len(values) == 1:
                repaired[name] = values[0]
        return repaired, supporting

    def run(self, *, dry_run=False):
        specs = self.read()
        rule = next((r for r in self.tables["AutomationRules"] if r.get("rule_id") == RULE_ID and truth(r.get("enabled"))), None)
        condition = json_value(rule.get("condition_json"), {}) if rule else {}
        if not isinstance(condition, dict) or condition.get("policy_version") != POLICY:
            return {"enabled": False, "policy": POLICY, "written": 0}
        allowed = set(condition.get("source_ids", []))
        enabled = {r["source_id"] for r in self.tables["Sources"] if r.get("source_id") in allowed
                   and truth(r.get("enabled")) and r.get("auto_publish_policy") == "allow"}
        proofs, broken = self._proofs()
        source_by_event, auto_by_event, reviews = defaultdict(list), defaultdict(list), defaultdict(list)
        for row in self.tables["EventSources"]:
            if row.get("source_id") in enabled:
                source_by_event[row.get("event_id")].append(row)
        for row in self.tables["AutoFieldValues"]:
            auto_by_event[row.get("event_id")].append(row)
        for row in self.tables["ReviewQueue"]:
            if row.get("review_id") and row.get("decision") in (None, "", "未判断"):
                reviews[row.get("event_id")].append(row)
        overridden = {r.get("event_id") for r in self.tables["FieldOverrides"] if truth(r.get("active"))}
        events = {r["event_id"]: r for r in self.tables["Events"] if r.get("event_id")}
        decisions = {}
        link_repairs = {}
        field_repairs = {}
        for id_, event in events.items():
            sources = source_by_event[id_]
            if not sources:
                decisions[id_] = ("protected", [])
                continue
            items = [proofs[s["event_source_id"]] for s in sources if s.get("event_source_id") in proofs]
            repaired, auto_by_event[id_] = self._repair_fields(event, items, auto_by_event[id_])
            probe = event
            if event.get("publication_status") == "確認待ち" and not event.get("last_admin_updated_at") and id_ not in overridden:
                probe = repaired
                field_repairs[id_] = {k: v for k, v in probe.items() if v != event.get(k)}
                urls = {source_url(p.candidate.detail_url) for p in items}
                if len(urls) == 1 and source_url(probe.get("primary_official_url") or "") not in urls and self._support(probe, "title", items, auto_by_event[id_]):
                    link_repairs[id_] = min(p.candidate.detail_url for p in items)
                    probe = {**probe, "primary_official_url": link_repairs[id_]}
            decision = self._base_decision(probe, items, auto_by_event[id_], any(s.get("event_source_id") in broken for s in sources))
            if (decision == ("technical", ["AUTO_SOURCE_RECOVERY_PENDING"])
                    and event.get("publication_status") == "確認待ち" and not event.get("last_admin_updated_at")
                    and id_ not in overridden and self._grounded_saved_pdf_end(event, sources)):
                decision = ("archive", ["PAST_EVENT_CANDIDATE"])
            # Human choices and overrides never become implicit publication.
            if event.get("last_admin_updated_at") or id_ in overridden or event.get("publication_status") in {"非公開", "アーカイブ"}:
                if event.get("publication_status") != "公開":
                    decision = ("protected", []) if not reviews[id_] else ("human", ["ADMIN_REVIEW_REQUIRED"])
                elif decision[0] == "reject":
                    decision = ("human", ["EVENT_CLASSIFICATION_CONFLICT"])
            decisions[id_] = decision
        self.duplicate_updates = []
        effective_events = {id_: {**event, **field_repairs.get(id_, {})} for id_, event in events.items()}
        self._duplicates(effective_events, decisions, source_by_event, proofs)
        summary = {"enabled": True, "policy": POLICY, "input": len(events), "written": 0,
                   **dict(Counter(action for action, _ in decisions.values()))}
        summary["reason_counts"] = dict(Counter(reason for _, reasons in decisions.values() for reason in reasons))
        if dry_run:
            return summary
        now = self.now.isoformat()
        event_writes, review_writes, audit_writes = [], [], []
        latest = {r.get("event_id"): r for r in self.writer._rows("Events", len(EVENTS_HEADERS))}
        latest_overrides = {r.get("event_id") for r in self.writer._rows("FieldOverrides", len(FIELD_OVERRIDE_HEADERS)) if truth(r.get("active"))}
        latest_reviews = {r.get("review_id"): r for r in self.writer._rows("ReviewQueue", len(REVIEW_QUEUE_HEADERS))}
        live_rules = self.writer._rows("AutomationRules", len(AUTOMATION_RULE_HEADERS))
        if not any(r.get("rule_id") == RULE_ID and truth(r.get("enabled")) and
                   r.get("condition_json") == rule.get("condition_json") for r in live_rules):
            return {**summary, "suspended_before_write": True}
        live_sources = self.writer._rows("Sources", len(SOURCES_HEADERS))
        live_enabled = {r.get("source_id") for r in live_sources if truth(r.get("enabled")) and r.get("auto_publish_policy") == "allow"}
        concurrent = {id_ for id_, event in events.items() if latest.get(id_) != event
            or id_ in latest_overrides and id_ not in overridden
            or bool(source_by_event[id_]) and not any(s.get("source_id") in live_enabled for s in source_by_event[id_])}
        for id_, (action, reasons) in decisions.items():
            if action == "merge" and reasons[0].split(":", 1)[1] in concurrent:
                concurrent.add(id_)
        for id_, (action, reasons) in decisions.items():
            event = events[id_]
            if id_ in concurrent:
                summary["concurrent_edit_skipped"] = summary.get("concurrent_edit_skipped", 0) + 1
                continue
            if action == "protected":
                continue
            human_owned = bool(event.get("last_admin_updated_at")) or id_ in overridden or event.get("publication_status") != "確認待ち"
            after = dict(event)
            if human_owned and event.get("publication_status") == "公開" and action == "archive":
                after.update({"publication_status": "アーカイブ", "archived_at": now})
            if not human_owned:
                after.update(field_repairs.get(id_, {}))
                if id_ in link_repairs:
                    after["primary_official_url"] = link_repairs[id_]
                after.update({"auto_publish_eligible": action == "publish", "review_reason_codes": "\n".join(reasons),
                    "review_reason_display": "自動処理待ち" if action == "processing" else "・".join(reason_label(r) for r in reasons),
                    "review_label": "あり" if action == "human" else "なし"})
                if action in {"publish", "archive", "reject", "merge"}:
                    after.update({"publication_status": {"publish": "公開", "archive": "アーカイブ", "reject": "非公開", "merge": "非公開"}[action],
                        "review_status": "確認済み", "last_verified_at": now})
                    if action == "archive":
                        after["archived_at"] = now
                    if action == "merge":
                        after.update({"canonical_event_id": reasons[0].split(":", 1)[1], "duplicate_status": "統合済み"})
                    if action == "publish":
                        after["fee_verified"] = True
                        fee = _fee_ground(str(after.get("fee_text") or ""))
                        after["fee_category"] = "有料" if any(float(n) > 0 for n in re.findall(r"(\d+(?:\.\d+)?)円", fee)) else "無料"
                        after["event_date_precision"] = self._date_precision(after, auto_by_event[id_])
                        items = [proofs[s["event_source_id"]] for s in source_by_event[id_] if s.get("event_source_id") in proofs]
                        for field in OPTIONAL_FIELDS:
                            if after.get(field) and not self._optional_support(after, field, items, auto_by_event[id_]):
                                after[field] = ""
                                if field == "application_deadline_at": after["application_deadline_text"] = "公式ページで要確認"
            if clean(after) != clean(event):
                event_writes.append(after)
            changed_reviews = []
            for review in reviews[id_]:
                if latest_reviews.get(review["review_id"]) != review:
                    continue
                updated = dict(review)
                if action == "human":
                    updated.update({"reason_codes": "\n".join(reasons), "decision_note": "公式原文の自動照合で解消できない項目だけを残しています。"})
                elif action == "processing":
                    updated.update({"reason_codes": "AUTO_PROCESSING_PENDING", "priority": "低", "decision_note": "人の確認ではなくAI/PDF処理待ちです。"})
                elif action == "technical":
                    updated.update({"reason_codes": "\n".join(reasons), "priority": "低", "decision_note": "人の判断ではなく、収集側の原文復旧・処理方法の修正が必要です。未確認のまま公開はしません。"})
                else:
                    updated.update({"decision": {"publish": "公開", "archive": "非公開", "reject": "非公開", "merge": "重複統合"}[action],
                        "decided_at": now, "decision_note": "公式原文に基づく自動" + {"publish": "公開", "archive": "終了整理", "reject": "対象外整理", "merge": "重複整理"}[action],
                        "automation_choice": "自動公開" if action == "publish" else "非公開"})
                if clean(updated) != clean(review):
                    changed_reviews.append(updated)
            if action in {"human", "technical", "processing"} and not reviews[id_]:
                changed_reviews.append({"review_id": stable_id("rev_auto_", id_), "event_id": id_,
                    "priority": "通常", "reason_codes": "\n".join(reasons), "suggested_action": "修正",
                    "source_urls": event.get("primary_official_url", ""), "opened_at": now,
                    "decision": "未判断", "automation_choice": "次回も確認",
                    "decision_note": "公式原文の判断が必要です。" if action == "human" else "収集・自動処理側の対応待ちです。"})
            review_writes.extend(changed_reviews)
            if clean(after) != clean(event) or changed_reviews:
                digest = hashlib.sha256(json.dumps({"before": clean(event), "action": action, "reasons": reasons,
                    "reviews": [clean(r) for r in reviews[id_]]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                audit_writes.append({"action_id": "act_auto_" + digest[:24], "event_id": id_,
                    "review_id": reviews[id_][0]["review_id"] if reviews[id_] else "", "action": "auto_" + action,
                    "before_json": json.dumps({"event": clean(event), "reviews": [clean(r) for r in reviews[id_]]}, ensure_ascii=False),
                    "after_json": json.dumps({"event": clean(after), "reviews": [clean(r) for r in changed_reviews]}, ensure_ascii=False),
                    "actor": ACTOR, "acted_at": now, "automation_choice": POLICY,
                    "note": "利用者が承認した公式原文照合ルール。削除はせず変更前の内容を保存。"})
        self._write_rows("ReviewActions", audit_writes, REVIEW_ACTION_HEADERS)
        self._write_rows("Events", event_writes, EVENTS_HEADERS)
        self._write_rows("DuplicateCandidates", [r for r in self.duplicate_updates
            if r.get("event_id_a") not in concurrent and r.get("event_id_b") not in concurrent], DUPLICATE_HEADERS)
        self._write_rows("ReviewQueue", review_writes, REVIEW_QUEUE_HEADERS)
        summary["written"] = len(event_writes)
        summary["review_rows_updated"] = len(review_writes)
        for name, status in (("published", "公開"), ("archived", "アーカイブ"), ("rejected", "非公開")):
            summary["newly_" + name] = sum(r.get("publication_status") == status
                and events[r["event_id"]].get("publication_status") != status for r in event_writes)
        summary["newly_merged"] = sum(r.get("duplicate_status") == "統合済み"
            and events[r["event_id"]].get("duplicate_status") != "統合済み" for r in event_writes)
        summary["fields_repaired"] = sum(len(field_repairs.get(r["event_id"], {})) for r in event_writes)
        # Last marker confirms all decision writes, not merely AI collection.
        # Append one private, bounded record; no raw text or input keys.
        summary_json = json.dumps({**summary, "policy_revision": POLICY_REVISION}, ensure_ascii=False)
        self._write_rows("ReviewActions", [{"action_id": stable_id("act_auto_summary_", POLICY_REVISION, now, summary_json),
            "action": "auto_review_summary", "after_json": summary_json,
            "actor": ACTOR, "acted_at": now, "automation_choice": POLICY, "note": "原文照合と保存完了の集計。公開サイトへの反映とは別。"}], REVIEW_ACTION_HEADERS)
        return summary

    def _optional_support(self, event, field, proofs, autos):
        if field == "application_url":
            value = _normalize_url(str(event.get(field) or ""))
            return bool(value) and any(value in {_normalize_url(u) for u in
                (*p.candidate.pdf_urls, *re.findall(r"https?://[^\s<>'\"）)]+", p.text),
                 *(f.value for n, f in p.candidate.extracted_fields.items() if n == "application_url" and isinstance(f.value, str)))} for p in proofs)
        return self._support(event, field, proofs, autos)

    @staticmethod
    def _date_precision(event, autos):
        field = "stream_start_at" if event.get("format") == "オンデマンド" else "event_start_at"
        date = parsed(event.get(field))
        for auto in autos:
            if auto.get("field_name") != field or parsed(json_value(auto.get("normalized_value_json"))) != date:
                continue
            for match in DATE_PATTERN.finditer(_normalized(str(auto.get("evidence_text") or ""))):
                if date and (int(match["year"]), int(match["month"]), int(match["day"])) == (date.year, date.month, date.day) and match["hour"] is not None:
                    return "datetime"
        return "date"

    def _duplicates(self, events, decisions, sources, proofs):
        # Similarity alone cannot authorize merging; require a unique common
        # application link/PDF, identical time and organizer, and compatible fees.
        for pair in self.tables["DuplicateCandidates"]:
            if pair.get("status") in {"統合済み", "別イベント"}:
                continue
            a, b = pair.get("event_id_a"), pair.get("event_id_b")
            if a not in events or b not in events or any(decisions[x][0] in {"archive", "reject", "merge", "processing", "technical"}
                    or decisions[x][0] == "protected" and events[x].get("publication_status") != "公開" for x in (a, b)):
                continue
            ea, eb = events[a], events[b]
            da, db = parsed(ea.get("event_start_at") or ea.get("stream_start_at")), parsed(eb.get("event_start_at") or eb.get("stream_start_at"))
            hashes = lambda id_: {p["hash"] for s in sources[id_] if (proof := proofs.get(s.get("event_source_id")))
                for p in proof.pdfs.values() if p.get("safe") and p.get("hash")}
            app_a, app_b = str(ea.get("application_url") or ""), str(eb.get("application_url") or "")
            item_proofs = lambda id_: [proofs[s["event_source_id"]] for s in sources[id_] if s.get("event_source_id") in proofs]
            autos = lambda id_: [v for v in self.tables["AutoFieldValues"] if v.get("event_id") == id_]
            unique_app = app_a == app_b and bool(re.search(r"/(?:event|events|seminar)/\d+", app_a))
            unique_app = unique_app and all(self._optional_support(events[id_], "application_url", item_proofs(id_), autos(id_)) for id_ in (a, b))
            anchor = bool(hashes(a) & hashes(b)) or unique_app
            exact = da and da == db and normalize_title(str(ea.get("title"))) == normalize_title(str(eb.get("title")))
            exact = exact and normalize_organizer(str(ea.get("organizer_name"))) == normalize_organizer(str(eb.get("organizer_name")))
            exact = exact and ea.get("format") == eb.get("format") and _fee_ground(str(ea.get("fee_text"))) == _fee_ground(str(eb.get("fee_text")))
            exact = exact and all(not ea.get(field) or not eb.get(field) or parsed(ea[field]) == parsed(eb[field])
                for field in ("event_end_at", "stream_start_at", "stream_end_at"))
            exact = exact and all(self._date_precision(events[id_], autos(id_)) == "datetime" for id_ in (a, b))
            from .duplicates import EventSnapshot, assess_duplicate
            score = assess_duplicate(EventSnapshot(a, str(ea.get("title")), str(ea.get("event_start_at") or ea.get("stream_start_at")), str(ea.get("organizer_name")), ea.get("format")),
                EventSnapshot(b, str(eb.get("title")), str(eb.get("event_start_at") or eb.get("stream_start_at")), str(eb.get("organizer_name")), eb.get("format")))
            if score.disposition == "separate":
                continue
            if anchor and exact and all(decisions[id_][0] == "publish" or events[id_].get("publication_status") == "公開" for id_ in (a, b)):
                canonical, alias = sorted((a, b), key=lambda id_: (events[id_].get("publication_status") != "公開", id_))
                if events[alias].get("publication_status") == "確認待ち" and not events[alias].get("last_admin_updated_at"):
                    decisions[alias] = ("merge", ["CANONICAL:" + canonical])
                    self.duplicate_updates.append({**pair, "status": "統合済み", "canonical_event_id": canonical, "reviewed_at": self.now.isoformat()})
                    continue
            for id_ in (a, b):
                decisions[id_] = ("human", sorted(set((*decisions[id_][1], "DUPLICATE_CANDIDATE"))))

    def _write_rows(self, name, rows, headers):
        if not rows:
            return
        existing = self.tables.get(name, [])
        by_key = {r.get(headers[0]): r for r in existing if r.get(headers[0])}
        if name == "ReviewActions":
            fresh = [r for r in rows if r.get(headers[0]) not in by_key]
            if fresh:
                if self.writer.ensure_capacity:
                    self.writer.ensure_capacity({name: max((r.get("__row_number", 1) for r in existing), default=1) + len(fresh) + 1})
                # Server-side append preserves audit rows added concurrently by
                # the admin UI. On ambiguous transport failure, stop; a resumed
                # run reads action IDs before retrying, rather than re-appending.
                self.writer.api.append(spreadsheetId=self.writer.spreadsheet_id, range="'ReviewActions'!A:J",
                    valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                    body={"values": [[_cell(row.get(h, "")) for h in headers] for row in fresh]}).execute()
                self.tables[name].extend(fresh)
            return
        next_row = max((r["__row_number"] for r in existing), default=1) + 1
        data = []
        for row in rows:
            number = row.get("__row_number") or by_key.get(row.get(headers[0]), {}).get("__row_number")
            if not number:
                number, next_row = next_row, next_row + 1
            data.append({"range": f"'{name}'!A{number}:{self.writer._column(len(headers))}{number}",
                         "values": [[_cell(row.get(h, "")) for h in headers]]})
        if self.writer.ensure_capacity:
            self.writer.ensure_capacity({name: max(int(re.search(r"\d+", d["range"].split("!")[1])[0]) for d in data)})
        self.writer._write_batches(data)


def reason_label(code):
    labels = {"AUTO_SOURCE_RECOVERY_PENDING": "収集側対応待ち：公式原文の再取得・復旧", "AUTO_SOURCE_INTEGRITY_PENDING": "収集側対応待ち：保存原文の整合性復旧",
        "AUTO_SOURCE_SPLIT_PENDING": "収集側対応待ち：一覧を個別イベントへ分割", "DATE_UNKNOWN": "開催日が確認できません", "DATE_CONFLICT": "開催日時・終了日時の根拠が一致しません",
        "SOURCE_FIELD_CONFLICT": "掲載元どうしで日時・料金などが食い違っています", "SOURCE_TEXT_UNAVAILABLE": "公式本文を取得できていません",
        "OFFICIAL_URL_UNVERIFIED": "公式URLの根拠を確認できません", "EVENT_CLASSIFICATION_CONFLICT": "イベント告知か判断が分かれます",
        "DUPLICATE_CANDIDATE": "同じイベントの可能性があります", "SOURCE_SNAPSHOT_INVALID": "保存原文の整合性を確認できません",
        "DATE_OUTSIDE_NORMAL_RANGE": "開催年の確認が必要です", "ADMIN_REVIEW_REQUIRED": "管理者が変更した内容の確認が必要です"}
    names = {"title": "イベント名", "organizer_name": "主催者", "format": "開催形式", "fee_text": "参加費",
        "event_start_at": "開催日時", "stream_start_at": "配信開始", "stream_end_at": "配信終了"}
    if code.startswith("AUTO_") and code.endswith("_UNVERIFIED"):
        field = code[5:-11].lower()
        return names.get(field, field) + "の公式原文・PDFの確認が必要です"
    return labels.get(code, code)
