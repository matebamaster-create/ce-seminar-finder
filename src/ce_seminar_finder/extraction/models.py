from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ExtractedField:
    value: Any
    confidence: float
    evidence: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.evidence is not None and len(self.evidence) > 300:
            raise ValueError("evidence must be 300 characters or fewer")

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    source_id: str
    source_url: str
    candidate_text: str
    allowed_urls: tuple[str, ...]
    rule_values: Mapping[str, ExtractedField] = field(default_factory=dict)
    pdf_chunks: tuple[str, ...] = ()
    taxonomy: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def cache_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "candidate_text": self.candidate_text,
            "allowed_urls": list(self.allowed_urls),
            "rule_values": {
                key: value.as_dict()
                for key, value in sorted(self.rule_values.items())
            },
            "pdf_chunks": list(self.pdf_chunks),
            "taxonomy": {
                key: list(value) for key, value in sorted(self.taxonomy.items())
            },
        }


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    is_event: bool
    event_confidence: float
    fields: Mapping[str, ExtractedField]
    review_reasons: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.event_confidence <= 1:
            raise ValueError("event_confidence must be between 0 and 1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_event": self.is_event,
            "event_confidence": self.event_confidence,
            "fields": {
                key: value.as_dict() for key, value in sorted(self.fields.items())
            },
            "review_reasons": list(self.review_reasons),
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "cache_hit": self.cache_hit,
        }
