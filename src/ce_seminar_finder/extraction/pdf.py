from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Protocol


MAX_PDF_BYTES = 20 * 1024 * 1024


class PdfTextBackend(Protocol):
    def extract_pages(self, data: bytes) -> list[str]:
        ...


class OcrProvider(Protocol):
    def extract_page(self, pdf_data: bytes, page_number: int) -> str:
        ...


class PypdfBackend:
    def extract_pages(self, data: bytes) -> list[str]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "PDF extraction requires the optional 'pdf' dependencies"
            ) from exc
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("ENCRYPTED_PDF")
        return [(page.extract_text() or "") for page in reader.pages]


@dataclass(frozen=True, slots=True)
class PdfPage:
    page_number: int
    text: str
    quality_score: float
    needs_ocr: bool
    extraction_method: str = "text_layer"


@dataclass(frozen=True, slots=True)
class PdfChunk:
    chunk_index: int
    page_from: int
    page_to: int
    text: str
    text_hash: str


@dataclass(frozen=True, slots=True)
class PdfExtractionResult:
    sha256: str
    byte_size: int
    pages: tuple[PdfPage, ...]
    chunks: tuple[PdfChunk, ...]
    quality_score: float
    extraction_status: str
    warnings: tuple[str, ...] = ()


def extract_pdf(
    data: bytes,
    *,
    mime_type: str = "application/pdf",
    backend: PdfTextBackend | None = None,
    ocr_provider: OcrProvider | None = None,
    important_candidate: bool = False,
    max_bytes: int = MAX_PDF_BYTES,
    chunk_size: int = 40_000,
) -> PdfExtractionResult:
    if len(data) > max_bytes:
        raise ValueError("PDF_TOO_LARGE")
    if not data.startswith(b"%PDF-"):
        raise ValueError("INVALID_PDF_SIGNATURE")
    if mime_type.split(";", 1)[0].strip().lower() not in {
        "application/pdf",
        "application/octet-stream",
    }:
        raise ValueError("INVALID_PDF_MIME")
    if chunk_size < 500:
        raise ValueError("chunk_size must be at least 500")

    texts = (backend or PypdfBackend()).extract_pages(data)
    pages: list[PdfPage] = []
    warnings: list[str] = []
    for page_number, text in enumerate(texts, start=1):
        normalized = _normalize_text(text)
        quality = text_quality_score(normalized)
        needs_ocr = len(normalized) < 30 or quality < 0.35
        method = "text_layer"
        if needs_ocr and important_candidate and ocr_provider is not None:
            ocr_text = _normalize_text(
                ocr_provider.extract_page(data, page_number)
            )
            if text_quality_score(ocr_text) > quality:
                normalized = ocr_text
                quality = text_quality_score(ocr_text)
                needs_ocr = False
                method = "ocr"
        if needs_ocr:
            warnings.append(f"OCR_CANDIDATE_PAGE_{page_number}")
        pages.append(PdfPage(page_number, normalized, quality, needs_ocr, method))

    chunks = _chunk_pages(pages, chunk_size)
    overall = (
        sum(page.quality_score for page in pages) / len(pages) if pages else 0.0
    )
    status = "success"
    if not pages or all(not page.text for page in pages):
        status = "failed"
    elif any(page.needs_ocr for page in pages):
        status = "partial"
    return PdfExtractionResult(
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        pages=tuple(pages),
        chunks=tuple(chunks),
        quality_score=round(overall, 4),
        extraction_status=status,
        warnings=tuple(warnings),
    )


def text_quality_score(text: str) -> float:
    if not text:
        return 0.0
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    replacement_ratio = text.count("\ufffd") / len(visible)
    control_ratio = sum(
        1 for char in visible if ord(char) < 32 and char not in "\n\t"
    ) / len(visible)
    length_factor = min(1.0, len(visible) / 80)
    score = length_factor * (1 - replacement_ratio) * (1 - control_ratio)
    return round(min(1.0, max(0.0, score)), 4)


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _chunk_pages(pages: list[PdfPage], chunk_size: int) -> list[PdfChunk]:
    chunks: list[PdfChunk] = []
    buffer = ""
    page_from = 0
    page_to = 0
    for page in pages:
        marker = f"[page {page.page_number}]\n"
        segments = [
            page.text[index : index + chunk_size - len(marker)]
            for index in range(0, max(1, len(page.text)), chunk_size - len(marker))
        ]
        for segment in segments:
            addition = marker + segment
            if buffer and len(buffer) + 1 + len(addition) > chunk_size:
                chunks.append(_make_chunk(len(chunks), page_from, page_to, buffer))
                buffer = ""
                page_from = 0
            if not buffer:
                page_from = page.page_number
            buffer = f"{buffer}\n{addition}".strip()
            page_to = page.page_number
    if buffer:
        chunks.append(_make_chunk(len(chunks), page_from, page_to, buffer))
    return chunks


def _make_chunk(index: int, page_from: int, page_to: int, text: str) -> PdfChunk:
    return PdfChunk(
        chunk_index=index,
        page_from=page_from,
        page_to=page_to,
        text=text,
        text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
