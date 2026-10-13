from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ce_seminar_finder.extraction.rules import extract_rule_values

from ce_seminar_finder.collection.models import (
    AdapterResult,
    EventCandidate,
    FetchResponse,
    SourceConfig,
)


EVENT_KEYWORDS = (
    "セミナー",
    "研修",
    "講習",
    "学会",
    "大会",
    "研究会",
    "勉強会",
    "カンファレンス",
    "フォーラム",
    "webinar",
    "seminar",
    "conference",
    "workshop",
    "e-learning",
    "eラーニング",
    "オンデマンド",
)

EXCLUSION_KEYWORDS = (
    "求人",
    "採用",
    "会費",
    "入会",
    "退会",
    "役員選挙",
    "議事録",
    "広告募集",
    "協賛募集",
    "物品販売",
)

NAVIGATION_LABELS = {
    "イベント",
    "セミナー情報",
    "お知らせ",
    "ニュース",
    "関連学会情報",
    "当会主催イベント",
    "学術セミナー",
    "学術大会",
    "詳細",
    "詳しくはこちら",
    "more",
    "一覧",
}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def is_event_like(value: str) -> bool:
    normalized = normalize_space(value).lower()
    has_event = any(keyword.lower() in normalized for keyword in EVENT_KEYWORDS)
    if not has_event:
        return False
    has_exclusion = any(keyword.lower() in normalized for keyword in EXCLUSION_KEYWORDS)
    return not has_exclusion or len(normalized) > 35


def is_pdf_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def is_title_hint(value: str) -> bool:
    normalized = normalize_space(value)
    parsed = urlsplit(normalized)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return False
    return (
        bool(normalized)
        and normalized.lower() not in NAVIGATION_LABELS
        and is_event_like(normalized)
    )


@dataclass(frozen=True, slots=True)
class Link:
    href: str
    text: str
    title: str = ""


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._href: str | None = None
        self._title = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        values = {key.lower(): value or "" for key, value in attrs}
        self._href = values.get("href", "")
        self._title = values.get("title", "")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append(
                Link(
                    href=self._href,
                    text=normalize_space(" ".join(self._text)),
                    title=normalize_space(self._title),
                )
            )
            self._href = None
            self._title = ""
            self._text = []


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self._heading_depth = 0
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if lowered == "title":
            self._title_depth += 1
        if lowered in {"h1", "h2"}:
            self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if lowered == "title" and self._title_depth:
            self._title_depth -= 1
        if lowered in {"h1", "h2"} and self._heading_depth:
            self._heading_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = normalize_space(data)
        if not value:
            return
        self.body_parts.append(value)
        if self._title_depth:
            self.title_parts.append(value)
        if self._heading_depth:
            self.heading_parts.append(value)


@dataclass(frozen=True, slots=True)
class HeadingBlock:
    heading_id: str
    title: str
    text: str
    links: tuple[str, ...]


class HeadingBlockParser(HTMLParser):
    """Capture each h3 and the content that follows it until the next h3."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[HeadingBlock] = []
        self._active = False
        self._in_heading = False
        self._heading_id = ""
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if lowered == "h3":
            self._flush()
            self._active = True
            self._in_heading = True
            self._heading_id = values.get("id", "")
        elif self._active and lowered == "a":
            href = values.get("href", "")
            if href and not href.startswith(("mailto:", "javascript:")):
                self._links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "h3":
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if not self._active:
            return
        value = normalize_space(data)
        if not value:
            return
        self._text_parts.append(value)
        if self._in_heading:
            self._title_parts.append(value)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._active:
            self.blocks.append(
                HeadingBlock(
                    heading_id=self._heading_id,
                    title=normalize_space(" ".join(self._title_parts)),
                    text=normalize_space(" ".join(self._text_parts)),
                    links=tuple(self._links),
                )
            )
        self._active = False
        self._in_heading = False
        self._heading_id = ""
        self._title_parts = []
        self._text_parts = []
        self._links = []


@dataclass(frozen=True, slots=True)
class EventTable:
    cells: tuple[tuple[str, str], ...]
    text: str
    links: tuple[str, ...]

    def value_after(self, label: str) -> str:
        for index, (kind, value) in enumerate(self.cells):
            if kind == "th" and normalize_space(value) == label:
                for next_kind, next_value in self.cells[index + 1 :]:
                    if next_kind == "td":
                        return normalize_space(next_value)
                    if next_kind == "th":
                        break
        return ""


class EventTableParser(HTMLParser):
    """Capture tables whose class contains ``event``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[EventTable] = []
        self._depth = 0
        self._cell_kind = ""
        self._cell_parts: list[str] = []
        self._cells: list[tuple[str, str]] = []
        self._text_parts: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if lowered == "table":
            if self._depth:
                self._depth += 1
            elif "event" in values.get("class", "").lower().split():
                self._depth = 1
            return
        if not self._depth:
            return
        if lowered in {"th", "td"}:
            self._finish_cell()
            self._cell_kind = lowered
        elif lowered == "a":
            href = values.get("href", "")
            if href and not href.startswith(("mailto:", "javascript:")):
                self._links.append(href)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if not self._depth:
            return
        if lowered in {"th", "td"}:
            self._finish_cell()
        elif lowered == "table":
            self._depth -= 1
            if not self._depth:
                self._finish_table()

    def handle_data(self, data: str) -> None:
        if not self._depth:
            return
        value = normalize_space(data)
        if not value:
            return
        self._text_parts.append(value)
        if self._cell_kind:
            self._cell_parts.append(value)

    def _finish_cell(self) -> None:
        if self._cell_kind:
            self._cells.append(
                (self._cell_kind, normalize_space(" ".join(self._cell_parts)))
            )
        self._cell_kind = ""
        self._cell_parts = []

    def _finish_table(self) -> None:
        self.tables.append(
            EventTable(
                cells=tuple(self._cells),
                text=normalize_space(" ".join(self._text_parts)),
                links=tuple(self._links),
            )
        )
        self._cells = []
        self._text_parts = []
        self._links = []


def html_links(document: FetchResponse) -> list[Link]:
    parser = LinkParser()
    parser.feed(document.text())
    return parser.links


def page_text(document: FetchResponse) -> tuple[str, str]:
    parser = PageTextParser()
    parser.feed(document.text())
    title = normalize_space(" ".join(parser.heading_parts[:3]))
    if not title:
        title = normalize_space(" ".join(parser.title_parts))
    body = normalize_space(" ".join(parser.body_parts))
    return title, body


def rss_candidates(
    source: SourceConfig,
    document: FetchResponse,
) -> AdapterResult:
    root = ET.fromstring(document.body)
    candidates: list[EventCandidate] = []
    urls: list[str] = []
    for item in root.findall(".//item"):
        title = normalize_space(item.findtext("title", default=""))
        link = normalize_space(item.findtext("link", default=""))
        description = normalize_space(item.findtext("description", default=""))
        published_at = normalize_space(item.findtext("pubDate", default="")) or None
        if not link:
            continue
        url = urljoin(document.final_url, link)
        urls.append(url)
        if is_event_like(f"{title} {description}"):
            candidates.append(
                EventCandidate(
                    source_id=source.source_id,
                    source_url=document.final_url,
                    detail_url=url,
                    title_hint=title,
                    published_at=published_at,
                    discovery_method="rss",
                    block_text=description[:1000],
                    confidence_hint=0.8,
                )
            )
    return AdapterResult(
        candidates=tuple(candidates),
        discovered_urls=tuple(dict.fromkeys(urls)),
    )


def sitemap_urls(document: FetchResponse) -> tuple[str, ...]:
    root = ET.fromstring(document.body)
    values = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "loc" and element.text:
            values.append(normalize_space(element.text))
    return tuple(dict.fromkeys(values))


class PatternHtmlAdapter:
    def __init__(
        self,
        *,
        detail_patterns: tuple[str, ...],
        allow_pdf_candidates: bool = True,
        include_event_text_links: bool = False,
    ) -> None:
        self.detail_patterns = tuple(re.compile(pattern) for pattern in detail_patterns)
        self.allow_pdf_candidates = allow_pdf_candidates
        self.include_event_text_links = include_event_text_links

    def parse(
        self,
        source: SourceConfig,
        document: FetchResponse,
    ) -> AdapterResult:
        content_type = document.content_type
        if "rss" in content_type or document.body.lstrip().startswith(b"<?xml"):
            try:
                return rss_candidates(source, document)
            except ET.ParseError:
                pass

        candidates: list[EventCandidate] = []
        discovered: list[str] = []
        pdfs: list[str] = []
        for link in html_links(document):
            if not link.href or link.href.startswith(("#", "mailto:", "javascript:")):
                continue
            url = urljoin(document.final_url, link.href)
            title = normalize_space(link.text or link.title)
            if is_pdf_url(url):
                pdfs.append(url)
                if (
                    self.allow_pdf_candidates
                    and title
                    and is_title_hint(title)
                ):
                    candidates.append(
                        EventCandidate(
                            source_id=source.source_id,
                            source_url=document.final_url,
                            detail_url=document.final_url,
                            title_hint=title,
                            pdf_urls=(url,),
                            discovery_method="html_pdf",
                            confidence_hint=0.65,
                        )
                    )
                continue
            matches_pattern = any(
                pattern.search(url) for pattern in self.detail_patterns
            )
            event_title = is_title_hint(title)
            if matches_pattern or (self.include_event_text_links and event_title):
                discovered.append(url)
                if event_title:
                    candidates.append(
                        EventCandidate(
                            source_id=source.source_id,
                            source_url=document.final_url,
                            detail_url=url,
                            title_hint=title,
                            discovery_method="html",
                            confidence_hint=0.7,
                        )
                    )
        return AdapterResult(
            candidates=_deduplicate_candidates(candidates),
            discovered_urls=tuple(dict.fromkeys(discovered)),
            pdf_urls=tuple(dict.fromkeys(pdfs)),
        )

    def enrich_candidate(
        self,
        candidate: EventCandidate,
        document: FetchResponse,
    ) -> EventCandidate:
        links = html_links(document)
        pdfs = [
            urljoin(document.final_url, link.href)
            for link in links
            if link.href and is_pdf_url(urljoin(document.final_url, link.href))
        ]
        allowed_urls = tuple(
            dict.fromkeys(
                urljoin(document.final_url, link.href)
                for link in links
                if link.href
            )
        )
        page_title, body = page_text(document)
        extracted_fields = extract_rule_values(
            body,
            allowed_urls=allowed_urls,
        )
        title = candidate.title_hint
        if page_title and is_event_like(page_title):
            title = page_title
        return EventCandidate(
            source_id=candidate.source_id,
            source_url=candidate.source_url,
            detail_url=candidate.detail_url,
            title_hint=title,
            pdf_urls=tuple(dict.fromkeys((*candidate.pdf_urls, *pdfs))),
            published_at=candidate.published_at,
            discovery_method=candidate.discovery_method,
            block_text=body[:4000],
            extracted_fields=extracted_fields,
            confidence_hint=max(candidate.confidence_hint, 0.8),
        )


def _deduplicate_candidates(
    candidates: list[EventCandidate],
) -> tuple[EventCandidate, ...]:
    unique: dict[tuple[str, str], EventCandidate] = {}
    for candidate in candidates:
        key = (candidate.detail_url, candidate.title_hint)
        previous = unique.get(key)
        if previous is None or len(candidate.pdf_urls) > len(previous.pdf_urls):
            unique[key] = candidate
    return tuple(unique.values())
