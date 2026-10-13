"""Candidate reconciliation: stable IDs, human decisions and evidence preserved."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from ce_seminar_finder.extraction.refinement import candidate_content_hash, candidate_payload
from ce_seminar_finder.extraction.documents import pdf_evidence_location
from ce_seminar_finder.collection.sources import source_config
from ce_seminar_finder.sheets.requests import execute_idempotent
from ce_seminar_finder.sheets.schema import (
    AUTO_FIELD_HEADERS, EVENTS_HEADERS, EVENT_SOURCES_HEADERS, REVIEW_QUEUE_HEADERS, DUPLICATE_HEADERS,
    DOCUMENTS_HEADERS, DOCUMENT_TEXT_HEADERS,
)

FIELD_MAP = {"event_start": "event_start_at", "event_end": "event_end_at",
    "stream_start": "stream_start_at", "stream_end": "stream_end_at",
    "application_deadline": "application_deadline_at", "organizer": "organizer_name",
    "official_url": "primary_official_url"}


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), unquote(p.path).rstrip("/") or "/", p.query, p.fragment))


def stable_id(prefix: str, *values: str) -> str:
    return prefix + hashlib.sha256("\0".join(values).encode()).hexdigest()[:24]


def _cell(value):
    if value is None:
        return ""
    return "\n".join(map(str, value)) if isinstance(value, (tuple, list)) else value


class CandidateIngestor:
    def __init__(self, service, spreadsheet_id, *, ensure_capacity=None):
        self.api = service.spreadsheets().values()
        self.spreadsheet_id = spreadsheet_id
        self.ensure_capacity = ensure_capacity

    def _rows(self, sheet, width):
        column = self._column(width)
        rows = execute_idempotent(self.api.get(spreadsheetId=self.spreadsheet_id, range=f"'{sheet}'!A:{column}")).get("values", [])
        if not rows:
            raise ValueError(f"Missing sheet headers: {sheet}")
        headers = rows[0]
        return [dict(zip(headers, row + [""] * (len(headers)-len(row))), __row_number=i)
                for i, row in enumerate(rows[1:], 2)]

    @staticmethod
    def _column(n):
        result = ""
        while n:
            n, rem = divmod(n-1, 26)
            result = chr(65+rem) + result
        return result

    def ingest(self, candidates):
        if not candidates:
            return
        specs = {"Events": EVENTS_HEADERS, "EventSources": EVENT_SOURCES_HEADERS,
                 "ReviewQueue": REVIEW_QUEUE_HEADERS, "AutoFieldValues": AUTO_FIELD_HEADERS, "DuplicateCandidates": DUPLICATE_HEADERS}
        specs.update({"Documents": DOCUMENTS_HEADERS, "DocumentTextChunks": DOCUMENT_TEXT_HEADERS})
        rows = {name: self._rows(name, len(headers)) for name, headers in specs.items()}
        original_events = {r["__row_number"]: dict(r) for r in rows["Events"]}
        by_url = {canonical_url(str(e.get("primary_official_url", ""))): e for e in rows["Events"] if e.get("event_id")}
        by_id = {e["event_id"]: e for e in rows["Events"] if e.get("event_id")}
        sources_by_id = {s["event_source_id"]: s for s in rows["EventSources"] if s.get("event_source_id")}
        reviews_by_id = {r["event_id"]: r for r in rows["ReviewQueue"] if r.get("event_id") and r.get("decision") in ("", "未判断")}
        autos_by_id = {r["value_id"]: r for r in rows["AutoFieldValues"] if r.get("value_id")}
        duplicate_by_id = {r["duplicate_candidate_id"]: r for r in rows["DuplicateCandidates"] if r.get("duplicate_candidate_id")}
        documents_by_id = {r["document_id"]: r for r in rows.get("Documents", []) if r.get("document_id")}
        chunks_by_id = {(r["document_id"], str(r["chunk_index"])): r for r in rows.get("DocumentTextChunks", []) if r.get("document_id")}
        next_row = {name: max((r["__row_number"] for r in values), default=1)+1 for name, values in rows.items()}
        writes = {}
        now = datetime.now(UTC).isoformat()

        def save(name, value):
            if "__row_number" not in value:
                value["__row_number"] = next_row[name]
                next_row[name] += 1
            row = value["__row_number"]
            writes[(name, row)] = {"range": f"'{name}'!A{row}:{self._column(len(specs[name]))}{row}",
                                  "values": [[_cell(value.get(h, "")) for h in specs[name]]]}

        for candidate in candidates:
            url = canonical_url(candidate.detail_url)
            if candidate.discovery_method in {"html_heading_block", "html_event_table", "nara_heading_table", "shizuoka_event_row", "fukui_public_block"}:
                url = url.split("#",1)[0] + "#event-" + stable_id("", candidate.title_hint)
            if candidate.discovery_method == "html_pdf":
                url += "#pdf-event-" + stable_id("", candidate.title_hint)
            event_source_id = stable_id("es_", candidate.source_id, url, candidate.title_hint if candidate.discovery_method == "html_pdf" else "")
            previous_source = sources_by_id.get(event_source_id)
            event = by_id.get(previous_source.get("event_id")) if previous_source else by_url.get(url)
            is_new = event is None
            fields = dict(candidate.extracted_fields)
            if is_new and not candidate.ai_result:
                end_field = next((fields[k] for k in ("stream_end", "event_end", "event_start") if k in fields and fields[k].value), None)
                if end_field:
                    try:
                        end_at = datetime.fromisoformat(str(end_field.value))
                        if end_at.tzinfo and end_at < datetime.now(UTC) - timedelta(days=45):
                            continue
                    except ValueError:
                        pass
            if is_new:
                event_id = stable_id("evt_", url, candidate.title_hint if candidate.discovery_method == "html_pdf" else "")
                event = {"event_id": event_id, "canonical_event_id": event_id,
                         "publication_status": "確認待ち", "review_status": "未確認", "review_label": "あり",
                         "duplicate_status": "重複なし", "fee_verified": False,
                         "format": "要確認", "fee_category": "要確認", "organizer_type": "要確認",
                         "title": candidate.title_hint, "source_prefecture": source_config(candidate.source_id).prefecture,
                         "timezone": "Asia/Tokyo", "primary_official_url": candidate.detail_url}
                by_id[event_id] = event
                by_url.setdefault(url, event)
            event_id = event["event_id"]
            snapshot_id = stable_id("snap_", event_source_id)
            if not candidate.ai_result and (candidate.block_text.strip() or candidate.pdf_urls
                    or snapshot_id not in documents_by_id):
                # Original public input is held only in the private management
                # sheet. AI checkpoints must not replace this with AI output.
                from .snapshots import SNAPSHOT_METHOD
                text = json.dumps(candidate_payload(candidate), ensure_ascii=False, sort_keys=True)
                row = dict(documents_by_id.get(snapshot_id, {}))
                row.update({"document_id": snapshot_id, "event_source_id": event_source_id,
                    "document_type": "other", "url": candidate.detail_url, "final_url": candidate.detail_url,
                    "mime_type": "application/json", "fetched_at": now, "extraction_method": SNAPSHOT_METHOD,
                    "extraction_status": "success", "text_length": len(text), "page_count": 1,
                    "text_quality_score": 1, "sha256": hashlib.sha256(text.encode()).hexdigest()})
                save("Documents", row)
                documents_by_id[snapshot_id] = row
                segments = [text[i:i+4000] for i in range(0, len(text), 4000)]
                for index, segment in enumerate(segments):
                    key = (snapshot_id, str(index))
                    part = dict(chunks_by_id.get(key, {}))
                    part.update({"document_id": snapshot_id, "chunk_index": index, "page_from": 1, "page_to": 1,
                        "text": segment, "text_hash": hashlib.sha256(segment.encode()).hexdigest(), "is_searchable": False})
                    save("DocumentTextChunks", part)
                    chunks_by_id[key] = part
                # A shorter replacement must not leave stale JSON suffixes.
                for key, part in list(chunks_by_id.items()):
                    if key[0] == snapshot_id and int(key[1]) >= len(segments):
                        part = {**part, "text": "", "text_hash": "", "is_searchable": False}
                        save("DocumentTextChunks", part)
                        chunks_by_id[key] = part
            pdf_ids = {}
            for document in candidate.pdf_documents:
                doc_id = stable_id("doc_", event_source_id, document["url"], document.get("sha256", ""))
                pdf_ids[document["url"]] = doc_id
                row = dict(documents_by_id.get(doc_id, {}))
                row.update({k: document.get(k, "") for k in DOCUMENTS_HEADERS if k not in {"document_id", "event_source_id"}})
                row.update({"document_id": doc_id, "event_source_id": event_source_id,
                    "error_code": document.get("error_code") or "\n".join(document.get("warnings", []))})
                save("Documents", row)
                documents_by_id[doc_id] = row
                for chunk in document.get("chunks", []):
                    key = (doc_id, str(chunk["chunk_index"]))
                    chunk_row = dict(chunks_by_id.get(key, {}))
                    chunk_row.update({**chunk, "document_id": doc_id, "is_searchable": False})
                    save("DocumentTextChunks", chunk_row)
                    chunks_by_id[key] = chunk_row
            human_owned = bool(event.get("last_admin_updated_at")) or event.get("review_status") == "確認済み" or event.get("publication_status") != "確認待ち"
            classification_id = stable_id("av_", event_id, "is_event", candidate.source_id)
            classification = autos_by_id.get(classification_id, {})
            if candidate.ai_result:
                result = candidate.ai_result
                classification = dict(classification)
                try:
                    previous_location = json.loads(classification.get("evidence_location") or "{}")
                except (ValueError, TypeError):
                    previous_location = {}
                if not isinstance(previous_location, dict):
                    previous_location = {}
                previous_keys = previous_location.get("processed_cache_keys", [])
                if not isinstance(previous_keys, list):
                    previous_keys = []
                processed_keys = {key for key in [*previous_keys, previous_location.get("cache_key"), candidate.ai_cache_key]
                                  if isinstance(key, str) and key}
                classification.update({"value_id": classification_id, "event_id": event_id,
                    "field_name": "is_event", "extracted_value_json": json.dumps(result.is_event),
                    "normalized_value_json": json.dumps(result.is_event), "confidence": result.event_confidence,
                    "extractor": "ai", "provider": result.provider, "model": result.model,
                    "prompt_version": result.prompt_version, "source_document_id": event_source_id,
                    "evidence_text": candidate.title_hint[:300], "evidence_location": json.dumps({
                        "cache_key": candidate.ai_cache_key, "content_hash": candidate_content_hash(candidate),
                        "processed_cache_keys": sorted(processed_keys),
                        "review_reasons": list(result.review_reasons)}, ensure_ascii=False),
                    "extracted_at": now, "accepted": False})
                save("AutoFieldValues", classification)
                autos_by_id[classification_id] = classification
            try:
                ai_location = json.loads(classification.get("evidence_location") or "{}")
            except (ValueError, TypeError):
                ai_location = {}
            if not isinstance(ai_location, dict):
                ai_location = {}
            ai_source_changed = bool(candidate.block_text.strip() and ai_location.get("content_hash") and
                                     ai_location["content_hash"] != candidate_content_hash(candidate))
            proposed = {}
            for name, field in fields.items():
                is_ai = bool(candidate.ai_result and candidate.ai_result.is_event and
                             candidate.ai_result.fields.get(name) == field)
                if field.value is None and not (is_ai and field.evidence):
                    continue
                target = FIELD_MAP.get(name, name)
                if target not in EVENTS_HEADERS:
                    continue
                value_id = stable_id("av_", event_id, target, candidate.source_id)
                auto = dict(autos_by_id.get(value_id, {}))
                pdf_location = pdf_evidence_location(candidate, field.evidence or "") if is_ai else {}
                # A later rule-only collection must not erase a grounded AI
                # proposal. Changed source text is sent back for review/refinement.
                if not is_ai and auto.get("extractor") == "ai":
                    continue
                auto.update({"value_id": value_id, "event_id": event_id, "field_name": target,
                    "extracted_value_json": json.dumps(field.value, ensure_ascii=False),
                    "normalized_value_json": json.dumps(field.value, ensure_ascii=False),
                    "confidence": field.confidence, "extractor": "ai" if is_ai else "rule",
                    "provider": candidate.ai_result.provider if is_ai else "",
                    "model": candidate.ai_result.model if is_ai else "",
                    "prompt_version": candidate.ai_result.prompt_version if is_ai else "",
                    "evidence_text": field.evidence or "", "evidence_location": json.dumps({
                        "cache_key": candidate.ai_cache_key, "content_hash": candidate_content_hash(candidate), **pdf_location},
                        ensure_ascii=False) if is_ai else "",
                    "source_document_id": pdf_ids.get(pdf_location.get("pdf_url"), event_source_id), "extracted_at": now,
                    "accepted": field.value is not None and field.confidence >= 0.85 and not human_owned})
                save("AutoFieldValues", auto)
                autos_by_id[value_id] = auto
                if field.value is not None and field.confidence >= 0.85:
                    proposed[target] = field.value
            # Existing approved/edited rows are display snapshots controlled by
            # administrators. Automatic values remain available for comparison.
            changed = [name for name, value in proposed.items() if event.get(name) not in ("", None, _cell(value), value)]
            if not human_owned:
                event.update(proposed)
                if re.search(r"[:：]\s*(?:[、,;；]|$)", str(event.get("fee_text") or "")):
                    event["fee_text"] = ""
                event.setdefault("event_type", "その他")
                if candidate.pdf_urls:
                    event["primary_pdf_url"] = candidate.pdf_urls[0]
                ends = [str(event[k]) for k in ("event_end_at", "stream_end_at") if event.get(k)]
                if ends:
                    event["effective_end_at"] = max(ends)
                elif event.get("event_start_at"):
                    event["effective_end_at"] = str(event["event_start_at"])[:10] + "T23:59:59+09:00"
            event["last_auto_fetched_at"] = now
            save("Events", event)

            source_row = dict(previous_source or {})
            source_row.update({"event_source_id": event_source_id, "event_id": event_id,
                "source_id": candidate.source_id, "source_url": candidate.detail_url,
                "source_role": "association_listing", "last_seen_at": now,
                "page_title": candidate.title_hint, "source_published_at": candidate.published_at or "",
                "content_hash": hashlib.sha256(candidate.block_text.encode()).hexdigest() if candidate.block_text.strip()
                    else (previous_source or {}).get("content_hash", "")})
            source_row.setdefault("discovered_at", now)
            save("EventSources", source_row)
            sources_by_id[event_source_id] = source_row

            reasons = list(candidate.extraction_warnings)
            if candidate.ai_result:
                end = next((event.get(k) for k in ("stream_end_at", "event_end_at", "event_start_at") if event.get(k)), None)
                if end:
                    try:
                        date = datetime.fromisoformat(str(end))
                        if date.tzinfo and date < datetime.now(UTC):
                            reasons.append("PAST_EVENT_CANDIDATE")
                    except ValueError:
                        pass
            if classification.get("extractor") == "ai":
                if classification.get("normalized_value_json") == "false":
                    reasons.append("NON_EVENT_CANDIDATE")
                if float(classification.get("confidence") or 0) < .85:
                    reasons.append("LOW_EVENT_CONFIDENCE")
                reasons.extend(ai_location.get("review_reasons", []))
            if ai_source_changed:
                reasons.append("AI_SOURCE_CHANGED")
            if not event.get("event_start_at") and not event.get("stream_start_at"):
                reasons.append("DATE_UNKNOWN")
            if not event.get("organizer_name"):
                reasons.append("ORGANIZER_UNKNOWN")
            if event.get("format") == "要確認":
                reasons.append("FORMAT_UNKNOWN")
            if not event.get("application_deadline_at"):
                reasons.append("DEADLINE_UNKNOWN")
            if not event.get("fee_text"):
                reasons.append("FEE_UNKNOWN")
            if candidate.pdf_urls and not candidate.extracted_fields:
                reasons.append("PDF_PRIMARY")
            if human_owned and changed:
                reasons.append("HIGH_IMPACT_FIELD_CHANGED")
            from ce_seminar_finder.review.duplicates import EventSnapshot, assess_duplicate
            def snapshot(row):
                return EventSnapshot(row["event_id"], str(row.get("title", "")),
                    event_start_at=str(row.get("event_start_at") or row.get("stream_start_at") or "") or None,
                    organizer_name=str(row.get("organizer_name", "")), event_format=str(row.get("format", "")))
            for other in list(by_id.values()):
                if other["event_id"] == event_id or not event.get("event_start_at") and not event.get("stream_start_at"):
                    continue
                assessment = assess_duplicate(snapshot(event), snapshot(other))
                if assessment.disposition == "separate":
                    continue
                a, b = sorted((event_id, other["event_id"]))
                duplicate_id = stable_id("dup_", a, b)
                duplicate = dict(duplicate_by_id.get(duplicate_id, {}))
                if duplicate.get("status") in {"統合済み", "別イベント"}:
                    continue
                duplicate.update({"duplicate_candidate_id": duplicate_id, "event_id_a": a, "event_id_b": b,
                    "total_score": assessment.total_score, "title_score": assessment.title_score,
                    "date_score": assessment.date_score, "organizer_score": assessment.organizer_score,
                    "format_score": assessment.format_score, "status": "未確認"})
                save("DuplicateCandidates", duplicate)
                duplicate_by_id[duplicate_id] = duplicate
                reasons.append("DUPLICATE_CANDIDATE")
                if not human_owned:
                    event["duplicate_status"] = "重複候補"
            if not human_owned:
                from .repository import _review_reason_display
                event["review_reason_codes"] = "\n".join(reasons)
                event["review_reason_display"] = _review_reason_display(reasons) or "自動取得情報を確認してください"
                event["review_label"] = "あり"
                save("Events", event)
            if is_new or (not human_owned) or (human_owned and event.get("publication_status") == "公開" and
                (changed or ai_source_changed or candidate.ai_result and reasons)):
                review = dict(reviews_by_id.get(event_id, {}))
                review.update({"review_id": review.get("review_id") or stable_id("rev_", event_id, now), "event_id": event_id,
                    "priority": "高" if "HIGH_IMPACT_FIELD_CHANGED" in reasons or "AI_SOURCE_CHANGED" in reasons else "通常", "reason_codes": "\n".join(dict.fromkeys(reasons or ["ADMIN_REVIEW_REQUIRED"])),
                    "suggested_action": "修正" if human_owned else "要確認付き公開",
                    "source_excerpt": candidate.block_text[:500] or review.get("source_excerpt") or candidate.title_hint, "source_urls": candidate.detail_url,
                    "uncertain_fields": "\n".join(changed), "decision": "未判断", "automation_choice": "次回も確認"})
                review.setdefault("opened_at", now)
                save("ReviewQueue", review)
                reviews_by_id[event_id] = review
        if writes:
            # Re-read immediately before saving: an administrator may have
            # edited a row while PDF/API processing was running.
            latest_events = {r["__row_number"]: r for r in self._rows("Events", len(EVENTS_HEADERS))}
            concurrent_ids = set()
            for (name, number), item in writes.items():
                if name != "Events" or number not in original_events:
                    continue
                latest = latest_events.get(number)
                if latest and latest != original_events[number]:
                    concurrent_ids.add(latest.get("event_id"))
                    latest["last_auto_fetched_at"] = now
                    item["values"] = [[_cell(latest.get(h, "")) for h in EVENTS_HEADERS]]
            for (name, _), item in writes.items():
                if name == "AutoFieldValues" and item["values"][0][AUTO_FIELD_HEADERS.index("event_id")] in concurrent_ids:
                    item["values"][0][AUTO_FIELD_HEADERS.index("accepted")] = False
            if self.ensure_capacity:
                self.ensure_capacity({name: number-1 for name, number in next_row.items()})
            # Persist the processed-key marker only after every field/document
            # write succeeded. A partial save must remain resumable.
            markers, ordinary = [], []
            for (name, _), item in writes.items():
                is_marker = name == "AutoFieldValues" and item["values"][0][AUTO_FIELD_HEADERS.index("field_name")] == "is_event"
                (markers if is_marker else ordinary).append(item)
            self._write_batches(ordinary)
            self._write_batches(markers)

    def _write_batches(self, items):
        # All these explicit range updates are idempotent: retrying cannot
        # append a duplicate event, field, or document.
        batch, size = [], 0
        for item in items:
            item_size = len(json.dumps(item, ensure_ascii=False).encode())
            if batch and (len(batch) >= 100 or size + item_size > 1_500_000):
                execute_idempotent(self.api.batchUpdate(spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": batch}))
                batch, size = [], 0
            batch.append(item)
            size += item_size
        if batch:
            execute_idempotent(self.api.batchUpdate(spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": batch}))
