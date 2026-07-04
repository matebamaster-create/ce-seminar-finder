from __future__ import annotations

from .common import PatternHtmlAdapter
from .sites import (
    FukuokaAdapter,
    JaceAdapter,
    KagoshimaAdapter,
    KumamotoAdapter,
    MiyazakiAdapter,
    NagasakiAdapter,
    OitaAdapter,
    OkinawaAdapter,
    SagaAdapter,
)


ADAPTERS = {
    "src_fukuoka": FukuokaAdapter,
    "src_saga": SagaAdapter,
    "src_nagasaki": NagasakiAdapter,
    "src_kumamoto": KumamotoAdapter,
    "src_oita": OitaAdapter,
    "src_miyazaki": MiyazakiAdapter,
    "src_kagoshima": KagoshimaAdapter,
    "src_okinawa": OkinawaAdapter,
    "src_jace": JaceAdapter,
}


def adapter_for_source(source_id: str) -> PatternHtmlAdapter:
    try:
        return ADAPTERS[source_id]()
    except KeyError as exc:
        raise KeyError(f"No adapter registered for {source_id}") from exc

