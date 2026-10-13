from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

from ce_seminar_finder.collection.models import AdapterResult, EventCandidate
from ce_seminar_finder.extraction.rules import extract_rule_values, DATE_PATTERN, _normalized
from .common import PatternHtmlAdapter, _deduplicate_candidates, is_event_like, is_pdf_url, is_title_hint


class TottoriPublicPostsAdapter(PatternHtmlAdapter):
    """Official unauthenticated WordPress posts, never drafts or protected text."""
    def __init__(self):
        super().__init__(detail_patterns=(r"/news/",), include_event_text_links=True)

    def parse(self, source, document):
        if "json" not in document.content_type:
            return super().parse(source, document)
        try:
            posts = json.loads(document.body)
        except (ValueError, TypeError):
            return AdapterResult(warnings=("PUBLIC_JSON_INVALID",))
        if not isinstance(posts, list):
            return AdapterResult(warnings=("PUBLIC_JSON_INVALID",))
        candidates = []
        for post in posts:
            if not isinstance(post, dict) or post.get("status") != "publish":
                continue
            content = post.get("content") or {}
            if not isinstance(content, dict) or content.get("protected"):
                continue
            title_value = post.get("title") or {}
            if not isinstance(title_value, dict):
                continue
            title = BeautifulSoup(str(title_value.get("rendered", "")), "html.parser").get_text(" ", strip=True)
            link = str(post.get("link") or "")
            if not is_title_hint(title) or urlsplit(link).hostname != urlsplit(source.base_url).hostname:
                continue
            block = BeautifulSoup(str(content.get("rendered", "")), "html.parser")
            for node in block.select("script,style,noscript,iframe"):
                node.decompose()
            links = tuple(dict.fromkeys(urljoin(link, a["href"]) for a in block.select("a[href]")))
            text = title + "\n" + block.get_text("\n", strip=True)
            candidates.append(EventCandidate(source.source_id, document.final_url, link, title,
                block_text=text[:16000], pdf_urls=tuple(u for u in links if is_pdf_url(u)),
                discovery_method="wordpress_public_post", confidence_hint=.9,
                extracted_fields=extract_rule_values(text, allowed_urls=links, title_hint=title)))
        pagination = ()
        try:
            parts = urlsplit(document.final_url)
            query = dict(parse_qsl(parts.query))
            page = int(query.get("page", "1"))
            total_pages = int(document.headers.get("x-wp-totalpages", "1"))
            if page >= 1 and page < total_pages and parts.path.rstrip("/") == "/wp-json/wp/v2/posts":
                query["page"] = str(page + 1)
                pagination = (urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")),)
        except (TypeError, ValueError):
            pass
        return AdapterResult(candidates=tuple(candidates), pagination_urls=pagination)


def candidate_from_block(source, document, title, block, *, anchor="", method="structured_html"):
    links = tuple(dict.fromkeys(urljoin(document.final_url, a["href"])
                              for a in block.select("a[href]")))
    pdfs = tuple(url for url in links if is_pdf_url(url))
    text = block.get_text("\n", strip=True)
    anchor = anchor or "event-" + hashlib.sha256(title.encode()).hexdigest()[:12]
    return EventCandidate(
        source.source_id, document.final_url, document.final_url.split("#")[0] + "#" + anchor,
        title, pdf_urls=pdfs, block_text=text[:16000], discovery_method=method,
        extracted_fields=extract_rule_values(text, allowed_urls=links, title_hint=title), confidence_hint=0.85,
    )


class CmsAdapter(PatternHtmlAdapter):
    """CMS cards whose link says only 'details'; title is a sibling heading."""
    def __init__(self):
        super().__init__(detail_patterns=(r"/(?:seminar|info)(?:app|detail|mation)",), include_event_text_links=True)

    def parse(self, source, document):
        result = super().parse(source, document)
        soup = BeautifulSoup(document.text(), "html.parser")
        candidates = list(result.candidates)
        for heading in soup.select("h2,h3,h4,h5,h6"):
            title = heading.get_text(" ", strip=True)
            if not is_title_hint(title):
                continue
            container = heading.parent
            for _ in range(4):
                links = container.select("a[href]")
                detail = next((a for a in links if re.search(r"(?:info|seminar)detail", a["href"])), None)
                if detail:
                    candidates.append(EventCandidate(source.source_id, document.final_url,
                        urljoin(document.final_url, detail["href"]), title,
                        block_text=container.get_text("\n", strip=True)[:4000],
                        discovery_method="cms_card", confidence_hint=0.8))
                    break
                if container.parent is None:
                    break
                container = container.parent
        return replace(result, candidates=_deduplicate_candidates(candidates))


class NaraOfficialAdapter(PatternHtmlAdapter):
    def __init__(self):
        super().__init__(detail_patterns=(r"/gakkai/",))

    def parse(self, source, document):
        # Keep the historical feed parser usable for saved fixtures only.
        if "xml" in document.content_type:
            result = super().parse(source, document)
            return replace(result, candidates=tuple(c for c in result.candidates
                if source.prefecture in c.title_hint + c.block_text))
        soup = BeautifulSoup(document.text(), "html.parser")
        candidates = []
        for heading in soup.select("h4"):
            title = heading.get_text(" ", strip=True)
            if not is_title_hint(title):
                continue
            block = BeautifulSoup("<section></section>", "html.parser").section
            block.append(BeautifulSoup(str(heading), "html.parser"))
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) in {"h3", "h4", "hr"}:
                    break
                block.append(BeautifulSoup(str(sibling), "html.parser"))
            candidates.append(candidate_from_block(source, document, title, block,
                anchor=heading.get("id", ""), method="nara_heading_table"))
        return AdapterResult(candidates=_deduplicate_candidates(candidates))

    def enrich_candidate(self, candidate, document):
        # Each candidate already contains its own table; never mix all events.
        return candidate


class ShizuokaAdapter(PatternHtmlAdapter):
    def __init__(self):
        super().__init__(detail_patterns=(r"/seminar/",))

    def parse(self, source, document):
        soup = BeautifulSoup(document.text(), "html.parser")
        candidates = []
        for row in soup.select("table tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 2:
                continue
            title = cells[0].get_text(" ", strip=True)
            if not is_title_hint(title) or "終了しました" in row.get_text():
                continue
            block = BeautifulSoup("<section></section>", "html.parser").section
            block.append(BeautifulSoup(str(row), "html.parser"))
            block.insert(0, "開催日時 " + cells[1].get_text(" ", strip=True))
            candidates.append(candidate_from_block(source, document, title, block, method="shizuoka_event_row"))
        return AdapterResult(candidates=_deduplicate_candidates(candidates))

    def enrich_candidate(self, candidate, document):
        return candidate


class FukuiAdapter(PatternHtmlAdapter):
    def __init__(self):
        super().__init__(detail_patterns=(r"/face",))

    def parse(self, source, document):
        soup = BeautifulSoup(document.text(), "html.parser")
        candidates = []
        for paragraph in soup.select("div.tyJCtd"):
            text = _normalized(paragraph.get_text(" ", strip=True))
            if not re.search(r"学会・セミナー\s*開催日", text):
                continue
            block = paragraph
            text = re.sub(r"学会・セミナー\s+開催日", "学会・セミナー開催日", text)
            title = re.split(r"学会・セミナー\s*開催日[：:\s]*", text, maxsplit=1)[-1]
            title = DATE_PATTERN.sub("", title, count=1).strip()
            title = re.sub(r"^\s*\([月火水木金土日]\s*\)\s*", "", title)
            title_node = next((n for n in paragraph.select("small,h1,h2,h3,h4") if is_event_like(n.get_text(" ",strip=True)) and "学会・セミナー" not in n.get_text()), None)
            if title_node:
                title = title_node.get_text(" ", strip=True)
            title = re.split(r"会場|会 場|開催方法|開催形式|申込方法", title)[0].strip()
            if is_event_like(title):
                candidates.append(candidate_from_block(source, document, title, block, method="fukui_public_block"))
        return AdapterResult(candidates=_deduplicate_candidates(candidates))

    def enrich_candidate(self, candidate, document):
        return candidate


class HyogoOfficialAdapter(PatternHtmlAdapter):
    """Each h6 is one event; 'past seminars' is a separate archive section."""
    def __init__(self):
        super().__init__(detail_patterns=(r"/seminars\.html",))

    def parse(self, source, document):
        if not document.final_url.split("#")[0].endswith("/seminars.html"):
            return AdapterResult()
        soup = BeautifulSoup(document.text(), "html.parser")
        candidates, past = [], False
        for node in soup.select("h2,h6"):
            title = node.get_text(" ", strip=True)
            if node.name == "h2":
                if "過去" in title:
                    past = True
                continue
            if past or not is_title_hint(title):
                continue
            block = BeautifulSoup("<section></section>", "html.parser").section
            block.append(BeautifulSoup(str(node), "html.parser"))
            for sibling in node.next_siblings:
                if getattr(sibling, "name", None) in {"h2", "h6"}:
                    break
                block.append(BeautifulSoup(str(sibling), "html.parser"))
            candidate = candidate_from_block(source, document, title, block, method="hyogo_pdf_block")
            if candidate.pdf_urls:
                candidate = replace(candidate, detail_url=candidate.pdf_urls[0])
            candidates.append(candidate)
        return AdapterResult(candidates=_deduplicate_candidates(candidates))

    def enrich_candidate(self, candidate, document): return candidate


class WakayamaOfficialAdapter(PatternHtmlAdapter):
    """A dated PDF link is an event, not all PDFs on the listing page."""
    def __init__(self):
        super().__init__(detail_patterns=(r"/seminar\.html",))

    def parse(self, source, document):
        soup = BeautifulSoup(document.text(), "html.parser")
        candidates = []
        for link in soup.select("li a[href]"):
            title = link.get_text(" ", strip=True)
            url = urljoin(document.final_url, link["href"])
            if not is_pdf_url(url) or not is_title_hint(title):
                continue
            text = link.parent.get_text("\n", strip=True)
            candidates.append(EventCandidate(source.source_id, document.final_url, document.final_url,
                title, pdf_urls=(url,), block_text=text, discovery_method="html_pdf",
                extracted_fields=extract_rule_values(text, title_hint=title), confidence_hint=.85))
        return AdapterResult(candidates=_deduplicate_candidates(candidates))

    def enrich_candidate(self, candidate, document): return candidate
