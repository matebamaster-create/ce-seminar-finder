from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from ce_seminar_finder.adapters.structured import TottoriPublicPostsAdapter
from ce_seminar_finder.collection.fetcher import RawHttpResponse, SafeHttpFetcher
from ce_seminar_finder.collection.models import FetchResponse, SourceRunStatus
from ce_seminar_finder.collection.pipeline import SourceCollector
from ce_seminar_finder.collection.sources import source_config


def post(index=1, **changes):
    return {"id": index, "status": "publish", "date": "2026-10-12T12:00:00",
        "link": f"https://t-ce.org/news/event-{index}/", "title": {"rendered": f"第{index}回 呼吸療法セミナー"},
        "content": {"protected": False, "rendered": '<p>開催日時 2026年11月1日 10:00〜11:00</p><p>参加費 500円</p><a href="/one.pdf">案内</a>'}, **changes}


def document(rows, page=1, pages=2):
    url = f"https://t-ce.org/wp-json/wp/v2/posts?per_page=100&page={page}"
    return FetchResponse(url, url, 200, {"content-type": "application/json", "x-wp-totalpages": str(pages)},
        json.dumps(rows, ensure_ascii=False).encode(), datetime.now(UTC), "fixture")


class PublicPostsTest(unittest.TestCase):
    def test_exact_post_body_and_pdf_not_publication_date(self):
        result = TottoriPublicPostsAdapter().parse(source_config("src_tottori"), document([post()]))
        item = result.candidates[0]
        self.assertEqual("wordpress_public_post", item.discovery_method)
        self.assertEqual(("https://t-ce.org/one.pdf",), item.pdf_urls)
        self.assertIn("2026-11-01", item.extracted_fields["event_start"].value)
        self.assertNotIn("2026-10-12", item.block_text)
        self.assertEqual(["2"], parse_qs(urlsplit(result.pagination_urls[0]).query)["page"])

    def test_private_password_protected_and_external_posts_are_not_collected(self):
        result = TottoriPublicPostsAdapter().parse(source_config("src_tottori"), document([
            post(status="private"), post(status="draft"),
            post(content={"protected": True, "rendered": "会員限定セミナー"}),
            post(link="https://example.net/seminar"), post(5)]))
        self.assertEqual(1, len(result.candidates))
        self.assertIn("event-5", result.candidates[0].detail_url)

    def test_all_advertised_pages_are_read_without_refetching_blocked_html(self):
        class Transport:
            def __init__(self): self.urls = []
            def request(self, url, headers, **kwargs):
                self.urls.append(url)
                if "/wp-json/wp/v2/posts" not in url:
                    raise AssertionError("No HTML detail request is needed")
                page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
                return RawHttpResponse(url, 200,
                    {"content-type": "application/json", "x-wp-totalpages": "2"},
                    json.dumps([post(page)]).encode())
        transport = Transport()
        source = replace(source_config("src_tottori"), enabled=True, robots_url="", request_interval_seconds=0)
        collector = SourceCollector(fetcher=SafeHttpFetcher(transport=transport,
            resolver=lambda host: ["93.184.216.34"], max_attempts=1))
        result = collector.collect(source, TottoriPublicPostsAdapter(), max_detail_pages=None)
        self.assertEqual(SourceRunStatus.SUCCESS, result.status)
        self.assertEqual(2, len(result.candidates))
        self.assertEqual(2, len(transport.urls))

    def test_pagination_honors_source_request_budget(self):
        class Transport:
            def request(self, url, headers, **kwargs):
                return RawHttpResponse(url, 200, {"content-type": "application/json", "x-wp-totalpages": "9999"},
                    json.dumps([post()]).encode())
        source = replace(source_config("src_tottori"), enabled=True, robots_url="",
            request_interval_seconds=0, max_requests_per_run=2)
        result = SourceCollector(fetcher=SafeHttpFetcher(transport=Transport(),
            resolver=lambda host: ["93.184.216.34"], max_attempts=1)).collect(source, TottoriPublicPostsAdapter())
        self.assertIn("MAX_REQUESTS_REACHED", result.warnings)
        self.assertEqual(2, len(result.fetched_urls))


if __name__ == "__main__":
    unittest.main()
