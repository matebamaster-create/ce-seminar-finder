from __future__ import annotations

from .common import PatternHtmlAdapter
from .structured import CmsAdapter, NaraOfficialAdapter, ShizuokaAdapter, FukuiAdapter
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
    "src_shimane": CmsAdapter,
    "src_okayama": OkayamaAdapter,
    "src_hiroshima": CmsAdapter,
    "src_yamaguchi": YamaguchiAdapter,
    "src_tokushima": TokushimaAdapter,
    "src_kagawa": KagawaAdapter,
    "src_ehime": EhimeAdapter,
    "src_kochi": KochiAdapter,
    "src_shiga": ShigaAdapter,
    "src_kyoto": KyotoAdapter,
    "src_osaka": OsakaAdapter,
    "src_hyogo": HyogoAdapter,
    "src_nara": NaraOfficialAdapter,
    "src_wakayama": WakayamaAdapter,
    "src_gifu": CmsAdapter,
    "src_shizuoka": ShizuokaAdapter,
    "src_aichi": lambda: PatternHtmlAdapter(detail_patterns=(r"/new/",), include_event_text_links=True),
    "src_mie": lambda: PatternHtmlAdapter(detail_patterns=(r"/wp/",), include_event_text_links=True),
    "src_toyama": lambda: PatternHtmlAdapter(detail_patterns=(r"/deta/|\.html",), include_event_text_links=True),
    "src_ishikawa": YamaguchiAdapter,
    "src_fukui": FukuiAdapter,
}


def adapter_for_source(source_id: str) -> PatternHtmlAdapter:
    try:
        return ADAPTERS[source_id]()
    except KeyError as exc:
        raise KeyError(f"No adapter registered for {source_id}") from exc
