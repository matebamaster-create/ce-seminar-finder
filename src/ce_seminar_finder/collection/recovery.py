"""Targeted official-input recovery, with no AI calls or new event creation."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .ingestion import CandidateIngestor, candidate_source_identity
from .pipeline import SourceCollector
from .fetcher import SafeHttpFetcher
from .sources import source_configs_from_sheet
from ce_seminar_finder.adapters.registry import adapter_for_source
from ce_seminar_finder.extraction.rules import DATE_PATTERN, _normalized


def dated_link_schedule(value):
    """Separate an explicit publication date from a second explicit event date."""
    text = _normalized(str(value)).strip()
    first = DATE_PATTERN.match(text)
    if first:
        tail = text[first.end():].lstrip()
        if tail.startswith((":", "：")):
            # A month/day after a publication-date separator has no explicit
            # event year. Do not turn the publication day into an event date.
            return tail[1:].lstrip()
    return text


def dated_link_subject(value):
    """Only typography/date wrappers, never event-number or fuzzy matching."""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    opening = next((i for i, c in enumerate(text) if c in "「『"), -1)
    closing = max(text.rfind("」"), text.rfind("』"))
    if opening >= 0 and closing > opening and DATE_PATTERN.search(_normalized(text[:opening])):
        text = text[opening+1:closing]
    text = re.sub(r"(?:開催)?(?:の)?(?:ご案内|お知らせ)$", "", text.strip())
    return re.sub(r"[\s「」『』\"'：:]", "", text).casefold()


def _link_day(value):
    date = DATE_PATTERN.match(dated_link_schedule(value or ""))
    return f"{int(date['year']):04d}-{int(date['month']):02d}-{int(date['day']):02d}" if date else None


def select_recoveries(candidates, events, sources, overrides=()):
    protected = {r.get("event_id") for r in overrides if r.get("active") is True or str(r.get("active")).lower() in {"true", "1"}}
    targets = {e["event_id"]: e for e in events if e.get("publication_status") == "確認待ち"
               and not e.get("last_admin_updated_at") and e.get("event_id") not in protected
               and any(str(e.get("review_reason_codes") or "").startswith(code) for code in
                       ("AUTO_SOURCE_RECOVERY_PENDING", "AUTO_SOURCE_INTEGRITY_PENDING", "AUTO_SOURCE_SPLIT_PENDING"))}
    records = {s["event_source_id"]: s for s in sources if s.get("event_id") in targets}
    matches = defaultdict(list)
    for candidate in candidates:
        _, sid = candidate_source_identity(candidate)
        source = records.get(sid)
        if not source or not candidate.block_text.strip():
            continue
        event = targets[source["event_id"]]
        subject = dated_link_subject(candidate.title_hint)
        incoming_day = _link_day(candidate.title_hint)
        previous_day = _link_day(event.get("title"))
        if not previous_day and event.get("event_start_at"):
            previous_day = str(event["event_start_at"])[:10]
        if previous_day and incoming_day != previous_day:
            continue
        # A source link label cannot redefine a generic catalogue event. The
        # existing event itself must identify this exact learning opportunity.
        if len(subject) >= 8 and subject == dated_link_subject(event.get("title") or ""):
            exact = candidate.title_hint == event.get("title") or candidate.title_hint == source.get("page_title")
            matches[sid].append((exact, candidate))
    selected = []
    for sid, choices in matches.items():
        best = [c for exact, c in choices if exact] or [c for _, c in choices]
        dates = {str(c.extracted_fields.get("event_start").value) if c.extracted_fields.get("event_start") else "" for c in best}
        if len(dates) != 1:
            continue  # Conflicting matched schedules cannot repair an input.
        selected.append(sorted(best, key=lambda c: (c.source_url, c.title_hint))[0])
    return selected, len(records)


def recover_source_snapshots(service, spreadsheet_id, source_ids, *, dry_run=False, collector=None, ensure_capacity=None):
    if ensure_capacity is None:
        from ce_seminar_finder.sheets.capacity import ensure_row_capacity
        ensure_capacity = lambda required: ensure_row_capacity(service, spreadsheet_id, required)
    writer = CandidateIngestor(service, spreadsheet_id, ensure_capacity=ensure_capacity)
    from ce_seminar_finder.sheets.schema import EVENTS_HEADERS, EVENT_SOURCES_HEADERS, FIELD_OVERRIDE_HEADERS
    events = writer._rows("Events", len(EVENTS_HEADERS))
    sources = writer._rows("EventSources", len(EVENT_SOURCES_HEADERS))
    overrides = writer._rows("FieldOverrides", len(FIELD_OVERRIDE_HEADERS))
    configs = {c.source_id: c for c in source_configs_from_sheet(service, spreadsheet_id)}
    unknown = set(source_ids) - set(configs)
    if unknown:
        raise ValueError("Unknown recovery source")
    collector = collector or SourceCollector(fetcher=SafeHttpFetcher())
    summary = {"source_records": 0, "matched": 0, "written": 0, "new_events": 0, "api_requests": 0, "sources": {}, "errors": []}
    for id_ in source_ids:
        config = configs[id_]
        if not config.enabled:
            summary["sources"][id_] = {"status": "disabled", "matched": 0}
            continue
        own_sources = [s for s in sources if s.get("source_id") == id_]
        # Check for targets before fetching an official page.
        _, target_count = select_recoveries([], events, own_sources, overrides)
        summary["source_records"] += target_count
        if not target_count:
            summary["sources"][id_] = {"status": "no_targets", "matched": 0}
            continue
        adapter = adapter_for_source(id_)
        if id_ == "src_wakayama":
            from ce_seminar_finder.adapters.structured import WakayamaOfficialAdapter
            adapter = WakayamaOfficialAdapter(recovery_links=True)
        result = collector.collect(config, adapter, max_detail_pages=0)
        candidates, _ = select_recoveries(result.candidates, events, own_sources, overrides)
        summary["sources"][id_] = {"status": str(result.status), "matched": len(candidates)}
        if str(result.status) not in {"success", "partial"}:
            summary["errors"].append({"source_id": id_, "code": "SOURCE_RECOVERY_FETCH_FAILED"})
            continue
        summary["matched"] += len(candidates)
        if candidates and not dry_run:
            # Recheck current status/overrides immediately before writing.
            if not any(c.source_id == id_ and c.enabled for c in source_configs_from_sheet(service, spreadsheet_id)):
                summary["sources"][id_] = {"status": "stopped_before_write", "matched": len(candidates)}
                continue
            current_events = writer._rows("Events", len(EVENTS_HEADERS))
            current_overrides = writer._rows("FieldOverrides", len(FIELD_OVERRIDE_HEADERS))
            current_sources = [s for s in writer._rows("EventSources", len(EVENT_SOURCES_HEADERS)) if s.get("source_id") == id_]
            candidates, _ = select_recoveries(candidates, current_events, current_sources, current_overrides)
            if candidates:
                writer.ingest(candidates, existing_only=True)
                summary["written"] += len(candidates)
    return summary
