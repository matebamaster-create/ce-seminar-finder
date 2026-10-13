"""Reproducible refinement of public candidates, without automatic publication."""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ce_seminar_finder.collection.models import EventCandidate
from ce_seminar_finder.enums import EventFormat, EventType, FeeCategory, Genre, OrganizerType
from .cache import extraction_cache_key
from .models import ExtractedField, ExtractionRequest
from .openai_provider import OpenAIExtractionError
from .rules import URL_PATTERN
from .service import ExtractionService
from .prompt import build_extraction_messages


def candidate_content_hash(candidate: EventCandidate) -> str:
    return hashlib.sha256((candidate.title_hint + "\n" + candidate.block_text).encode()).hexdigest()


def extraction_request(candidate: EventCandidate, pdf_chunks: tuple[str, ...] = ()) -> ExtractionRequest:
    if not pdf_chunks:
        pdf_chunks = tuple(f"[PDF {d['url']} sha256={d.get('sha256', '')}]\n{c['text']}"
            for d in candidate.pdf_documents for c in d.get("chunks", []))
    urls = [candidate.detail_url, candidate.source_url, *candidate.pdf_urls,
            *URL_PATTERN.findall(candidate.block_text),
            *(url for text in pdf_chunks for url in URL_PATTERN.findall(text))]
    for name in ("official_url", "application_url"):
        field = candidate.extracted_fields.get(name)
        if field and isinstance(field.value, str):
            urls.append(field.value)
    return ExtractionRequest(source_id=candidate.source_id, source_url=candidate.detail_url,
        title_hint=candidate.title_hint, candidate_text=candidate.block_text,
        allowed_urls=tuple(dict.fromkeys(urls)), rule_values=candidate.extracted_fields,
        pdf_chunks=pdf_chunks, taxonomy={
            "format": tuple(x.value for x in EventFormat), "event_type": tuple(x.value for x in EventType),
            "genres": tuple(x.value for x in Genre), "fee_category": tuple(x.value for x in FeeCategory),
            "organizer_type": tuple(x.value for x in OrganizerType)})


def candidate_payload(candidate: EventCandidate) -> dict:
    return {"source_id": candidate.source_id, "source_url": candidate.source_url,
        "detail_url": candidate.detail_url, "title_hint": candidate.title_hint,
        "pdf_urls": list(candidate.pdf_urls), "published_at": candidate.published_at,
        "discovery_method": candidate.discovery_method, "block_text": candidate.block_text,
        "extracted_fields": {k: v.as_dict() for k, v in candidate.extracted_fields.items()},
        "confidence_hint": candidate.confidence_hint,
        "ai_result": candidate.ai_result.as_dict() if candidate.ai_result else None,
        "ai_cache_key": candidate.ai_cache_key, "pdf_documents": list(candidate.pdf_documents),
        "extraction_warnings": list(candidate.extraction_warnings)}


def candidate_from_payload(row) -> EventCandidate:
    return EventCandidate(source_id=row["source_id"], source_url=row["source_url"],
        detail_url=row["detail_url"], title_hint=row["title_hint"],
        pdf_urls=tuple(row.get("pdf_urls", [])), published_at=row.get("published_at"),
        discovery_method=row.get("discovery_method", "html"), block_text=row.get("block_text", ""),
        extracted_fields={k: ExtractedField(v.get("value"), float(v.get("confidence", 0)), v.get("evidence"))
            for k, v in row.get("extracted_fields", {}).items()},
        confidence_hint=float(row.get("confidence_hint", .5)),
        pdf_documents=tuple(row.get("pdf_documents", [])),
        extraction_warnings=tuple(row.get("extraction_warnings", [])))


def read_saved_candidates(paths: list[Path]) -> list[EventCandidate]:
    candidates = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            rows = json.loads(text)
        except json.JSONDecodeError:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(rows, dict):
            rows = rows.get("candidates", [rows])
        if not isinstance(rows, list):
            raise ValueError("Candidate input must be a list")
        for row in rows:
            candidate = candidate_from_payload(row)
            candidates[(candidate.source_id, candidate.detail_url, candidate.title_hint)] = candidate
    return list(candidates.values())


def read_processed_keys(service, spreadsheet_id: str) -> set[str]:
    from ce_seminar_finder.sheets.requests import execute_idempotent
    rows = execute_idempotent(service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="AutoFieldValues!A:O")).get("values", [])
    if not rows:
        return set()
    headers, *values = rows
    keys = set()
    for value in values:
        row = dict(zip(headers, value))
        if row.get("field_name") != "is_event" or row.get("extractor") != "ai":
            continue
        try:
            location = json.loads(row.get("evidence_location") or "{}")
            key = location.get("cache_key")
            if isinstance(key, str) and key: keys.add(key)
            history = location.get("processed_cache_keys", [])
            if isinstance(history, list):
                keys.update(key for key in history if isinstance(key, str) and key)
        except (ValueError, AttributeError):
            pass
    return keys


def fit_request(request, max_chars):
    truncated = False
    while sum(len(m["content"]) for m in build_extraction_messages(request)) > max_chars:
        truncated = True
        if request.pdf_chunks:
            request = replace(request, pdf_chunks=request.pdf_chunks[:-1])
        elif len(request.candidate_text) > 1000:
            request = replace(request, candidate_text=request.candidate_text[:len(request.candidate_text)//2])
        elif request.rule_values:
            request = replace(request, rule_values={})
        else:
            break
    return request, truncated


def refine_candidates(candidates: list[EventCandidate], service: ExtractionService,
                      *, processed_keys: set[str] | None = None, pdf_loader=None,
                      checkpoint=None, checkpoint_size: int = 20, workers: int = 1) -> tuple[list[EventCandidate], dict]:
    processed = processed_keys or set()
    refined, skipped, errors, pending = [], 0, [], []
    checkpoint_failed = False
    source_stats = {}
    provider = service.provider
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")

    def flush():
        nonlocal checkpoint_failed
        if not checkpoint or not pending or checkpoint_failed:
            return not checkpoint_failed
        try:
            checkpoint(list(pending))
            pending.clear()
            return True
        except Exception as error:
            checkpoint_failed = True
            errors.append({"code": "CHECKPOINT_FAILED", "error_type": type(error).__name__})
            return False

    def accept(candidate, key, result):
        from .validator import _ground_text
        merged = dict(candidate.extracted_fields)
        fee = merged.get("fee_text")
        if fee and re.search(r"[:：]\s*(?:[、,;；]|$)", str(fee.value or "")):
            merged.pop("fee_text")
        if result.is_event:
            merged.update({k: v for k, v in result.fields.items() if v.value is not None})
            source_text = candidate.block_text + "\n" + "\n".join(c["text"]
                for d in candidate.pdf_documents for c in d.get("chunks", []))
            merged.update({k: v for k, v in result.fields.items() if v.value is None and v.evidence
                and _ground_text(v.evidence) in _ground_text(source_text)})
        if candidate.extraction_warnings:
            result = replace(result, review_reasons=tuple(dict.fromkeys((*result.review_reasons, *candidate.extraction_warnings))))
        updated = replace(candidate, extracted_fields=merged, ai_result=result, ai_cache_key=key)
        refined.append(updated)
        pending.append(updated)
        source_stats[candidate.source_id]["refined"] += 1
        processed.add(key)
        if checkpoint and len(pending) >= checkpoint_size:
            return not flush()
        return False

    def finish(job):
        candidate, key, future = job
        try:
            return accept(candidate, key, future.result())
        except OpenAIExtractionError as error:
            if error.code == "REQUEST_LIMIT_REACHED":
                return True
            errors.append({"source_id": candidate.source_id, "code": error.code, "http_status": error.status})
            return error.code != "INPUT_LIMIT_REACHED"

    # Public downloads remain sequential per host. API extraction overlaps at
    # most a small number of candidates; Sheets checkpoints remain serial.
    jobs, halted = [], False
    with ThreadPoolExecutor(max_workers=workers) as executor:
      for candidate in candidates:
        counts = source_stats.setdefault(candidate.source_id, {"input": 0, "refined": 0, "skipped": 0})
        counts["input"] += 1
        if not candidate.block_text.strip() and not candidate.pdf_urls and not candidate.pdf_documents:
            skipped += 1
            counts["skipped"] += 1
            continue
        end = next((candidate.extracted_fields[k].value for k in ("stream_end", "event_end", "event_start")
            if k in candidate.extracted_fields and candidate.extracted_fields[k].value), None)
        if end:
            try:
                date = datetime.fromisoformat(str(end))
                if date.tzinfo and date < datetime.now(UTC) - timedelta(days=45):
                    skipped += 1
                    counts["skipped"] += 1
                    continue
            except ValueError:
                pass
        if pdf_loader:
            candidate = pdf_loader.enrich(candidate)
        request, truncated = fit_request(extraction_request(candidate), getattr(provider, "max_input_chars", 40000))
        if truncated:
            candidate = replace(candidate, extraction_warnings=(*candidate.extraction_warnings, "INPUT_CONTEXT_TRUNCATED"))
        key = extraction_cache_key(request, provider=provider.name, model=provider.model, prompt_version=service.prompt_version)
        if key in processed:
            skipped += 1
            counts["skipped"] += 1
            continue
        jobs.append((candidate, key, executor.submit(service.extract, request)))
        if len(jobs) >= workers:
            halted = finish(jobs.pop(0))
            if halted:
                break
      for job in jobs:
        if not halted or not job[2].cancel():
            halted = finish(job) or halted  # Retain successful in-flight results.
    if checkpoint and pending:
        halted = not flush() or halted
    return refined, {"input_candidates": len(candidates), "refined": len(refined), "skipped": skipped,
        "requests": getattr(provider, "requests", 0), "input_tokens": getattr(provider, "input_tokens", 0),
        "output_tokens": getattr(provider, "output_tokens", 0), "errors": errors,
        "sources": source_stats, "halted": halted,
        "saved": len(refined) - len(pending) if checkpoint else 0,
        "unsaved": len(pending), **(pdf_loader.stats if pdf_loader else {})}
