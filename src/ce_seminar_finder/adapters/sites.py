from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit

from ce_seminar_finder.collection.models import (
    AdapterResult,
    EventCandidate,
    FetchResponse,
    SourceConfig,
)

from .common import (
    EventTableParser,
    HeadingBlockParser,
    PatternHtmlAdapter,
    _deduplicate_candidates,
    is_event_like,
    is_pdf_url,
    is_title_hint,
    rss_candidates,
    sitemap_urls,
)


class FukuokaAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(detail_patterns=(r"/event/(?!$|tag/)[^/?#]+/?",))


class SagaAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(
            detail_patterns=(r"/(?:\d+(?:st|th)_saga/)?index\.html", r"#\d+$"),
            include_event_text_links=True,
        )


class NagasakiAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(
            detail_patterns=(r"/~ncet/(?:event|kanren)\.html#",),
            include_event_text_links=True,
        )

    def parse(
        self,
        source: SourceConfig,
        document: FetchResponse,
    ) -> AdapterResult:
        structural = _heading_candidates(source, document)
        if structural.candidates:
            return structural
        return super().parse(source, document)


class KumamotoAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(
            detail_patterns=(r"/news\.html#\d+", r"/system/event_[^?]+\.php"),
            include_event_text_links=True,
        )

    def parse(
        self,
        source: SourceConfig,
        document: FetchResponse,
    ) -> AdapterResult:
        structural = _heading_candidates(source, document)
        if structural.candidates:
            return structural
        return super().parse(source, document)


class OitaAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(detail_patterns=(r"/event/detail\.php\?",))

    def parse(
        self,
        source: SourceConfig,
        document: FetchResponse,
    ) -> AdapterResult:
        parser = EventTableParser()
        parser.feed(document.text())
        parser.close()
        candidates: list[EventCandidate] = []
        discovered: list[str] = []
        all_pdfs: list[str] = []
        for index, table in enumerate(parser.tables, start=1):
            title = table.value_after("名称")
            urls = [
                urljoin(document.final_url, href)
                for href in table.links
                if not href.startswith("#")
            ]
            pdfs = [url for url in urls if is_pdf_url(url)]
            discovered.extend(url for url in urls if not is_pdf_url(url))
            all_pdfs.extend(pdfs)
            if not is_title_hint(title):
                continue
            candidates.append(
                EventCandidate(
                    source_id=source.source_id,
                    source_url=document.final_url,
                    detail_url=f"{document.final_url}#event-{index}",
                    title_hint=title,
                    pdf_urls=tuple(dict.fromkeys(pdfs)),
                    discovery_method="html_event_table",
                    block_text=table.text[:4000],
                    confidence_hint=0.85,
                )
            )
        if candidates:
            return AdapterResult(
                candidates=_deduplicate_candidates(candidates),
                discovered_urls=tuple(dict.fromkeys(discovered)),
                pdf_urls=tuple(dict.fromkeys(all_pdfs)),
            )
        return super().parse(source, document)


class MiyazakiAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(detail_patterns=(r"/post/", r"/イベント", r"/関連学会情報"))

    def parse(
        self,
        source: SourceConfig,
        document: FetchResponse,
    ) -> AdapterResult:
        try:
            if "xml" in document.content_type or document.body.lstrip().startswith(
                b"<?xml"
            ):
                return rss_candidates(source, document)
        except ET.ParseError:
            pass
        return super().parse(source, document)


class KagoshimaAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(detail_patterns=(r"\?news=",))


class JaceAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(
            detail_patterns=(
                r"/gakkai/",
                r"/info-ce/",
                r"/jsc/seminar/",
            )
        )


class OkinawaAdapter(PatternHtmlAdapter):
    def __init__(self) -> None:
        super().__init__(
            detail_patterns=(r"/seminars(?:/|$)", r"/seminars-history", r"/notice")
        )

    def parse(
        self,
        source: SourceConfig,
        document: FetchResponse,
    ) -> AdapterResult:
        text = document.text()
        if 'id="__nuxt"' in text and "Loading..." in text:
            return AdapterResult(
                technical_hold_reason="CLIENT_RENDER_REQUIRED",
                warnings=(
                    "Nuxtの初期HTMLにイベント本文がなく、公開APIまたはブラウザ取得が必要",
                ),
            )
        if "xml" in document.content_type:
            try:
                urls = []
                expected_host = urlsplit(source.base_url).hostname or ""
                for value in sitemap_urls(document):
                    parsed = urlsplit(value)
                    if parsed.hostname != expected_host:
                        value = urlunsplit(
                            (
                                parsed.scheme or "https",
                                expected_host,
                                parsed.path,
                                parsed.query,
                                "",
                            )
                        )
                    urls.append(value)
                return AdapterResult(
                    discovered_urls=tuple(dict.fromkeys(urls)),
                    warnings=(
                        "サイトマップのホスト名を公式サブドメインへ補正",
                    ),
                )
            except ET.ParseError:
                pass
        return super().parse(source, document)


def _heading_candidates(
    source: SourceConfig,
    document: FetchResponse,
) -> AdapterResult:
    parser = HeadingBlockParser()
    parser.feed(document.text())
    parser.close()
    candidates: list[EventCandidate] = []
    discovered: list[str] = []
    all_pdfs: list[str] = []
    for index, block in enumerate(parser.blocks, start=1):
        urls = [
            urljoin(document.final_url, href)
            for href in block.links
            if not href.startswith("#")
        ]
        pdfs = [url for url in urls if is_pdf_url(url)]
        discovered.extend(url for url in urls if not is_pdf_url(url))
        all_pdfs.extend(pdfs)
        if not is_title_hint(block.title) and not is_event_like(block.text):
            continue
        title = block.title
        if not is_title_hint(title):
            continue
        anchor = block.heading_id or f"event-{index}"
        candidates.append(
            EventCandidate(
                source_id=source.source_id,
                source_url=document.final_url,
                detail_url=f"{document.final_url.split('#', 1)[0]}#{anchor}",
                title_hint=title,
                pdf_urls=tuple(dict.fromkeys(pdfs)),
                discovery_method="html_heading_block",
                block_text=block.text[:4000],
                confidence_hint=0.85,
            )
        )
    return AdapterResult(
        candidates=_deduplicate_candidates(candidates),
        discovered_urls=tuple(dict.fromkeys(discovered)),
        pdf_urls=tuple(dict.fromkeys(all_pdfs)),
    )
