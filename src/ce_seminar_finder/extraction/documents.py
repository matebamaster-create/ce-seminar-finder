"""Fetch only explicitly discovered public PDFs; retain private page provenance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ce_seminar_finder.collection.cache import JsonFetchStateStore
from ce_seminar_finder.collection.fetcher import SafeHttpFetcher
from ce_seminar_finder.collection.models import EventCandidate, FetchOutcome, FetchRequest
from ce_seminar_finder.collection.robots import RobotsPolicy
from ce_seminar_finder.collection.sources import source_config
from .pdf import MAX_PDF_BYTES, LocalOcrProvider, extract_pdf

PDF_PROCESSOR_VERSION = "pdf-text-ocr-v1"


class PdfContextLoader:
    def __init__(self, directory: Path, *, fetcher=None, ocr_provider=None, extractor=None):
        self.directory = directory
        self.store = JsonFetchStateStore(directory / "fetch-state.json")
        self.fetcher = fetcher or SafeHttpFetcher(state_store=self.store, timeout=15, max_attempts=1)
        self.ocr_provider = ocr_provider
        self.extractor = extractor or extract_pdf
        self._documents, self._robots = {}, {}
        self.stats = {"pdf_unique": 0, "pdf_success": 0, "pdf_partial": 0, "pdf_failed": 0,
                      "pdf_pages": 0, "ocr_pages": 0}

    def enrich(self, candidate: EventCandidate) -> EventCandidate:
        urls = list(candidate.pdf_urls)
        if urlsplit(candidate.detail_url).path.lower().endswith(".pdf"):
            urls.append(candidate.detail_url)
        documents = [self._load(url, candidate.source_id) for url in dict.fromkeys(urls)]
        warnings = list(candidate.extraction_warnings)
        for document in documents:
            warnings.extend(document.get("warnings", []))
        return replace(candidate, pdf_documents=tuple(documents), extraction_warnings=tuple(dict.fromkeys(warnings)))

    def _fetch(self, url, source, *, robots=None, max_bytes=MAX_PDF_BYTES):
        parsed = urlsplit(url)
        # The PDF URL was found by an official-source adapter, not authored by AI.
        # Cross-host attachments are exact-link fetches; DNS/IP and redirects are
        # still checked by SafeHttpFetcher. No cookies or account tokens are used.
        host = parsed.hostname or ""
        hosts = frozenset({host, host[4:] if host.startswith("www.") else "www." + host})
        request = FetchRequest(url, source.source_id, source.user_agent, hosts, max_bytes=max_bytes)
        return self.fetcher.fetch(request, robots_policy=robots,
            minimum_interval=source.request_interval_seconds)

    def _policy(self, url, source):
        parsed = urlsplit(url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        if origin not in self._robots:
            robot_url = origin + "/robots.txt"
            response = self._fetch(robot_url, source, max_bytes=250_000)
            text = response.text() if response.outcome == FetchOutcome.FETCHED else ""
            self._robots[origin] = RobotsPolicy(robot_url, text) if text else RobotsPolicy.unavailable(robot_url)
        return self._robots[origin]

    def _load(self, url, source_id):
        if url in self._documents:
            return self._documents[url]
        source = source_config(source_id)
        document = {"url": url, "final_url": url, "document_type": "pdf",
            "fetched_at": datetime.now(UTC).isoformat(), "extraction_status": "failed",
            "chunks": [], "pages": [], "warnings": []}
        try:
            response = self._fetch(url, source, robots=self._policy(url, source))
            data = response.body
            if response.outcome == FetchOutcome.NOT_MODIFIED and not data:
                cached = self.store.cached_body(url)
                if cached:
                    data, _ = cached
            if response.outcome not in {FetchOutcome.FETCHED, FetchOutcome.NOT_MODIFIED} or not data:
                raise ValueError("PDF_FETCH_FAILED")
            sha = hashlib.sha256(data).hexdigest()
            path = self.directory / (sha + ".json")
            if path.is_file():
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("processor_version") == PDF_PROCESSOR_VERSION and saved.get("extraction_status") == "success":
                    document = {**saved, "url": url, "final_url": response.final_url}
                    return self._remember(url, document)
            # A fresh page budget for each document avoids one brochure using all OCR.
            ocr = self.ocr_provider if self.ocr_provider is not None else LocalOcrProvider()
            result = self.extractor(data, mime_type=response.content_type or "application/pdf",
                ocr_provider=ocr, important_candidate=True, chunk_size=4000)
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / (sha + ".pdf")).write_bytes(data)
            document.update({"final_url": response.final_url, "mime_type": response.content_type,
                "byte_size": result.byte_size, "sha256": result.sha256,
                "etag": response.headers.get("etag", ""), "last_modified": response.headers.get("last-modified", ""),
                "processor_version": PDF_PROCESSOR_VERSION, "extraction_status": result.extraction_status,
                "page_count": len(result.pages), "text_quality_score": result.quality_score,
                "text_length": sum(len(p.text) for p in result.pages),
                "extraction_method": "ocr" if any(p.extraction_method == "ocr" for p in result.pages) else "text_layer",
                "pages": [{"page_number": p.page_number, "quality_score": p.quality_score,
                    "needs_ocr": p.needs_ocr, "extraction_method": p.extraction_method} for p in result.pages],
                "chunks": [{"chunk_index": c.chunk_index, "page_from": c.page_from, "page_to": c.page_to,
                    "text": c.text, "text_hash": c.text_hash} for c in result.chunks],
                "warnings": list(result.warnings)})
            if result.extraction_status != "success":
                document["warnings"].append("PDF_TEXT_REVIEW_REQUIRED")
            if any(p.extraction_method == "ocr" for p in result.pages):
                document["warnings"].append("OCR_TEXT_REVIEW_REQUIRED")
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        except Exception as error:
            known = {"PDF_FETCH_FAILED", "PDF_TOO_LARGE", "PDF_PAGE_LIMIT", "ENCRYPTED_PDF",
                     "INVALID_PDF_SIGNATURE", "INVALID_PDF_MIME"}
            code = str(error) if isinstance(error, ValueError) and str(error) in known else "PDF_PROCESSING_FAILED"
            document["warnings"] = [code]
            document["error_code"] = code
        self.store.save()
        return self._remember(url, document)

    def _remember(self, url, document):
        self._documents[url] = document
        self.stats["pdf_unique"] += 1
        self.stats["pdf_" + {"success": "success", "partial": "partial"}.get(document["extraction_status"], "failed")] += 1
        self.stats["pdf_pages"] += document.get("page_count", 0)
        self.stats["ocr_pages"] += sum(p.get("extraction_method") == "ocr" for p in document.get("pages", []))
        return document


def pdf_evidence_location(candidate, evidence: str) -> dict:
    from .validator import _ground_text
    if not evidence:
        return {}
    for document in candidate.pdf_documents:
        for chunk in document.get("chunks", []):
            if _ground_text(evidence) in _ground_text(chunk["text"]):
                return {"pdf_url": document["url"], "pdf_sha256": document.get("sha256", ""),
                        "page_from": chunk["page_from"], "page_to": chunk["page_to"]}
    return {}
