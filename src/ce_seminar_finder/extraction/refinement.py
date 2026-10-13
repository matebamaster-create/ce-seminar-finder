"""Reproducible refinement of public candidates, without automatic publication."""
from __future__ import annotations

import hashlib
import json
import re
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


def candidate_content_hash(candidate: EventCandidate) -> str:
    return hashlib.sha256((candidate.title_hint + "\n" + candidate.block_text).encode()).hexdigest()


def extraction_request(candidate: EventCandidate, pdf_chunks: tuple[str, ...] = ()) -> ExtractionRequest:
    urls = [candidate.detail_url, candidate.source_url, *candidate.pdf_urls,
            *URL_PATTERN.findall(candidate.block_text)]
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
        "ai_cache_key": candidate.ai_cache_key}


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
            candidate = EventCandidate(source_id=row["source_id"], source_url=row["source_url"],
                detail_url=row["detail_url"], title_hint=row["title_hint"],
                pdf_urls=tuple(row.get("pdf_urls", [])), published_at=row.get("published_at"),
                discovery_method=row.get("discovery_method", "html"), block_text=row.get("block_text", ""),
                extracted_fields={k: ExtractedField(v.get("value"), float(v.get("confidence", 0)), v.get("evidence"))
                    for k, v in row.get("extracted_fields", {}).items()},
                confidence_hint=float(row.get("confidence_hint", .5)))
            candidates[(candidate.source_id, candidate.detail_url, candidate.title_hint)] = candidate
    return list(candidates.values())


def read_processed_keys(service, spreadsheet_id: str) -> set[str]:
    rows = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="AutoFieldValues!A:O").execute().get("values", [])
    if not rows:
        return set()
    headers, *values = rows
    keys = set()
    for value in values:
        row = dict(zip(headers, value))
        if row.get("field_name") != "is_event" or row.get("extractor") != "ai":
            continue
        try:
            key = json.loads(row.get("evidence_location") or "{}").get("cache_key")
            if key: keys.add(key)
        except (ValueError, AttributeError):
            pass
    return keys


def refine_candidates(candidates: list[EventCandidate], service: ExtractionService,
                      *, processed_keys: set[str] | None = None) -> tuple[list[EventCandidate], dict]:
    processed = processed_keys or set()
    refined, skipped, errors = [], 0, []
    provider = service.provider
    for candidate in candidates:
        if not candidate.block_text.strip():
            skipped += 1
            continue
        end = next((candidate.extracted_fields[k].value for k in ("stream_end", "event_end", "event_start")
            if k in candidate.extracted_fields and candidate.extracted_fields[k].value), None)
        if end:
            try:
                date = datetime.fromisoformat(str(end))
                if date.tzinfo and date < datetime.now(UTC) - timedelta(days=45):
                    skipped += 1
                    continue
            except ValueError:
                pass
        request = extraction_request(candidate)
        key = extraction_cache_key(request, provider=provider.name, model=provider.model, prompt_version=service.prompt_version)
        if key in processed:
            skipped += 1
            continue
        try:
            result = service.extract(request)
        except OpenAIExtractionError as error:
            if error.code == "REQUEST_LIMIT_REACHED":
                break
            errors.append({"source_id": candidate.source_id, "code": error.code, "http_status": error.status})
            if error.code != "INPUT_LIMIT_REACHED":
                break  # Authentication/quota/network problems must not cause repeated requests.
            continue
        merged = dict(candidate.extracted_fields)
        fee = merged.get("fee_text")
        if fee and re.search(r"[:：]\s*(?:[、,;；]|$)", str(fee.value or "")):
            merged.pop("fee_text")  # Do not fall back to the same invalid rule value.
        if result.is_event:
            merged.update({k: v for k, v in result.fields.items() if v.value is not None})
        refined.append(replace(candidate, extracted_fields=merged, ai_result=result, ai_cache_key=key))
        processed.add(key)
    return refined, {"input_candidates": len(candidates), "refined": len(refined), "skipped": skipped,
        "requests": getattr(provider, "requests", 0), "input_tokens": getattr(provider, "input_tokens", 0),
        "output_tokens": getattr(provider, "output_tokens", 0), "errors": errors}
