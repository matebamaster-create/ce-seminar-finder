from __future__ import annotations

from .common import PatternHtmlAdapter
from .sites import (
    EhimeAdapter,
    FukuokaAdapter,
    HiroshimaAdapter,
    HyogoAdapter,
    JaceAdapter,
    KagoshimaAdapter,
    KagawaAdapter,
    KochiAdapter,
    KumamotoAdapter,
    KyotoAdapter,
    MiyazakiAdapter,
    NagasakiAdapter,
    NaraAdapter,
    OitaAdapter,
    OkayamaAdapter,
    OkinawaAdapter,
    OsakaAdapter,
    SagaAdapter,
    ShigaAdapter,
    ShimaneAdapter,
    TokushimaAdapter,
    TottoriAdapter,
    WakayamaAdapter,
    YamaguchiAdapter,
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
    "src_tottori": TottoriAdapter,
    "src_shimane": ShimaneAdapter,
    "src_okayama": OkayamaAdapter,
    "src_hiroshima": HiroshimaAdapter,
    "src_yamaguchi": YamaguchiAdapter,
    "src_tokushima": TokushimaAdapter,
    "src_kagawa": KagawaAdapter,
    "src_ehime": EhimeAdapter,
    "src_kochi": KochiAdapter,
    "src_shiga": ShigaAdapter,
    "src_kyoto": KyotoAdapter,
    "src_osaka": OsakaAdapter,
    "src_hyogo": HyogoAdapter,
    "src_nara": NaraAdapter,
    "src_wakayama": WakayamaAdapter,
}


def adapter_for_source(source_id: str) -> PatternHtmlAdapter:
    try:
        return ADAPTERS[source_id]()
    except KeyError as exc:
        raise KeyError(f"No adapter registered for {source_id}") from exc
