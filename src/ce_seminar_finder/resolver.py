from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from .models import AutoFieldValue, EventRecord, FieldOverride


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    value: Any
    origin: Literal["override", "auto", "fixed", "missing"]
    confidence: float | None = None


def resolve_field(
    field_name: str,
    auto_values: list[AutoFieldValue],
    overrides: list[FieldOverride],
    fixed_values: dict[str, Any] | None = None,
) -> ResolvedValue:
    active_overrides = [
        item for item in overrides if item.active and item.field_name == field_name
    ]
    if active_overrides:
        selected = max(active_overrides, key=lambda item: item.updated_at)
        return ResolvedValue(value=selected.value, origin="override")

    accepted = [
        item
        for item in auto_values
        if item.accepted and item.field_name == field_name and item.value is not None
    ]
    if accepted:
        selected = max(
            accepted,
            key=lambda item: (item.confidence, item.extracted_at),
        )
        return ResolvedValue(
            value=selected.value,
            origin="auto",
            confidence=selected.confidence,
        )

    if fixed_values and field_name in fixed_values:
        return ResolvedValue(value=fixed_values[field_name], origin="fixed")

    return ResolvedValue(value=None, origin="missing")


def resolve_event(
    event: EventRecord,
    fields: Iterable[str],
) -> dict[str, ResolvedValue]:
    return {
        field_name: resolve_field(
            field_name,
            event.auto_values,
            event.overrides,
            event.fixed_values,
        )
        for field_name in fields
    }
