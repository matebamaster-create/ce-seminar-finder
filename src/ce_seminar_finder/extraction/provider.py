from __future__ import annotations

from typing import Any, Mapping, Protocol

from .models import ExtractionRequest


class AIProvider(Protocol):
    name: str
    model: str

    def extract_event(self, request: ExtractionRequest) -> Mapping[str, Any]:
        """Return vendor-neutral structured data without persisting raw output."""
        ...


class NoopProvider:
    name = "noop"
    model = "none"

    def extract_event(self, request: ExtractionRequest) -> Mapping[str, Any]:
        return {
            "is_event": False,
            "event_confidence": 0.0,
            "fields": {},
            "review_reasons": ["AI_PENDING"],
        }
