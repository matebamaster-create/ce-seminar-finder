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
from ce_seminar_finder.collection.sources import source_configs
from ce_seminar_finder.collection.snapshots import SNAPSHOT_METHOD
from ce_seminar_finder.extraction.refinement import candidate_from_payload, candidate_content_hash
from ce_seminar_finder.extraction.validator import validate_extraction, _ground_text, _normalize_url, _fee_ground
from ce_seminar_finder.extraction.rules import DATE_PATTERN, _normalized
from ce_seminar_finder.sheets.schema import (
    EVENTS_HEADERS, EVENT_SOURCES_HEADERS, REVIEW_QUEUE_HEADERS, AUTO_FIELD_HEADERS,
    DOCUMENTS_HEADERS, DOCUMENT_TEXT_HEADERS, FIELD_OVERRIDE_HEADERS, SOURCES_HEADERS,
    DUPLICATE_HEADERS, REVIEW_ACTION_HEADERS, AUTOMATION_RULE_HEADERS,
)
from .duplicates import normalize_title, normalize_organizer

POLICY = "grounded_v1"
RULE_ID = "rule_grounded_v1_west20261013"
ACTOR = "automation:grounded_v1"
REVERSE_FIELDS = {v: k for k, v in FIELD_MAP.items()}
REVERSE_FIELDS["application_deadline_at"] = "application_deadline"
OPTIONAL_FIELDS = ("application_deadline_at", "application_url", "credits_text", "capacity_text")
NON_EVENT_TITLE = re.compile(r"求人|採用|会費(?:納入|案内)|役員選挙|議事録|アンケート|実態調査|業務実態報告")
LEARNING_TITLE = re.compile(r"セミナー|研修|講習|勉強会|カンファレンス|学術集会|学術大会|研究会|ハンズオン")


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
            allowed_pdf_urls = {_normalize_url(u) for u in candidate.pdf_urls}
            if urlsplit(candidate.detail_url).path.lower().endswith(".pdf"):
                allowed_pdf_urls.add(_normalize_url(candidate.detail_url))
            for document in documents:
                if document.get("document_type") != "pdf":
                    continue
                url = _normalize_url(str(document.get("url") or ""))
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
            if auto.get("field_name") != name or not self._equal(value, json_value(auto.get("normalized_value_json")), name):
                continue
            evidence = str(auto.get("evidence_text") or "")
            if not evidence:
                continue
            for proof in proofs:
                # Even OCR evidence is acceptable when the official HTML
                # independently contains and supports the identical fact.
                contexts = [proof.html]
                contexts.extend(p["text"] for id_, p in proof.pdfs.items()
                    if (p["safe"] or allow_ocr) and id_ == auto.get("source_document_id"))
                for text in contexts:
                    result = validate_extraction({"is_event": True, "event_confidence": 1,
                        "fields": {mapped: {"value": value, "confidence": 1, "evidence": evidence}}},
                        allowed_urls=(), provider="grounded-policy", model="", prompt_version=POLICY, source_text=text)
                    field = result.fields.get(mapped)
                    if not field or field.value is None or result.review_reasons:
                        continue
                    if name == "format" and not self._format_supported(str(value), evidence):
                        continue
                    if mapped in {"event_start", "event_end", "stream_start", "stream_end"} and not self._date_context(text, evidence):
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
            return _fee_ground(str(a)) == _fee_ground(str(b))
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
            return "human", ["SOURCE_SNAPSHOT_INVALID"]
        if not proofs:
            return "processing", ["AUTO_PROCESSING_PENDING"]
        if all(not p.candidate.block_text.strip() and not p.candidate.pdf_urls for p in proofs):
            return "human", ["SOURCE_TEXT_UNAVAILABLE"]
        classification, location = self._classification(event, proofs, autos)
        title = str(event.get("title") or "")
        if classification is False:
            if NON_EVENT_TITLE.search(title) and not LEARNING_TITLE.search(title):
                return "reject", ["NON_EVENT_CANDIDATE"]
            return "human", ["EVENT_CLASSIFICATION_CONFLICT"]
        start_field = "stream_start_at" if event.get("format") == "オンデマンド" and event.get("stream_start_at") else "event_start_at"
        start = parsed(event.get(start_field))
        end_field = "stream_end_at" if event.get("format") == "オンデマンド" else "event_end_at"
        end = parsed(event.get(end_field))
        # A reversed range or a month-spanning live event needs schedule-level
        # review, even when both dates occur somewhere in a long source page.
        if start and end and (end < start or event.get("format") != "オンデマンド"
                              and end - start > timedelta(days=31)):
            return "human", ["DATE_CONFLICT"]
        if start and self._support(event, start_field, proofs, autos):
            if end and self._support(event, end_field, proofs, autos) and end < self.now:
                return "archive", ["PAST_EVENT_CANDIDATE"]
            if event.get("format") != "オンデマンド" and not end and start.date() < self.now.astimezone(start.tzinfo).date():
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
        official = _normalize_url(str(event.get("primary_official_url") or ""))
        if not official or not any(official == _normalize_url(p.candidate.detail_url) for p in proofs):
            reasons.append("OFFICIAL_URL_UNVERIFIED")
        if start and start > self.now + timedelta(days=730):
            reasons.append("DATE_OUTSIDE_NORMAL_RANGE")
        for field in required + ("event_end_at", "stream_end_at"):
            for auto in autos:
                other = json_value(auto.get("normalized_value_json"))
                if auto.get("field_name") == field and other not in (None, "") and not self._equal(event.get(field), other, field):
                    if self._support({**event, field: other}, field, proofs, autos):
                        reasons.append("SOURCE_FIELD_CONFLICT")
        return ("human", sorted(set(reasons))) if reasons else ("publish", [])

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
        for id_, event in events.items():
            sources = source_by_event[id_]
            if not sources:
                decisions[id_] = ("protected", [])
                continue
            items = [proofs[s["event_source_id"]] for s in sources if s.get("event_source_id") in proofs]
            decision = self._base_decision(event, items, auto_by_event[id_], any(s.get("event_source_id") in broken for s in sources))
            # Human choices and overrides never become implicit publication.
            if event.get("last_admin_updated_at") or id_ in overridden or event.get("publication_status") in {"非公開", "アーカイブ"}:
                if event.get("publication_status") != "公開":
                    decision = ("protected", []) if not reviews[id_] else ("human", ["ADMIN_REVIEW_REQUIRED"])
                elif decision[0] == "reject":
                    decision = ("human", ["EVENT_CLASSIFICATION_CONFLICT"])
            decisions[id_] = decision
        self.duplicate_updates = []
        self._duplicates(events, decisions, source_by_event, proofs)
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
                else:
                    updated.update({"decision": {"publish": "公開", "archive": "非公開", "reject": "非公開", "merge": "重複統合"}[action],
                        "decided_at": now, "decision_note": "公式原文に基づく自動" + {"publish": "公開", "archive": "終了整理", "reject": "対象外整理", "merge": "重複整理"}[action],
                        "automation_choice": "自動公開" if action == "publish" else "非公開"})
                if clean(updated) != clean(review):
                    changed_reviews.append(updated)
            if action == "human" and not reviews[id_]:
                changed_reviews.append({"review_id": stable_id("rev_auto_", id_), "event_id": id_,
                    "priority": "通常", "reason_codes": "\n".join(reasons), "suggested_action": "修正",
                    "source_urls": event.get("primary_official_url", ""), "opened_at": now,
                    "decision": "未判断", "automation_choice": "次回も確認",
                    "decision_note": "公式原文の自動照合で解消できない項目だけを残しています。"})
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
            if a not in events or b not in events or any(decisions[x][0] in {"archive", "reject", "merge", "processing"}
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
    labels = {"DATE_UNKNOWN": "開催日が確認できません", "DATE_CONFLICT": "開催日時・終了日時の根拠が一致しません",
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
