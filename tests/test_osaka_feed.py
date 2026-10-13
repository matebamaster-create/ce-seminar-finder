from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

from ce_seminar_finder.adapters import adapter_for_source
from ce_seminar_finder.collection.fetcher import RawHttpResponse, SafeHttpFetcher
from ce_seminar_finder.collection.models import FetchResponse, SourceRunStatus
from ce_seminar_finder.collection.pipeline import SourceCollector
from ce_seminar_finder.collection.sources import source_config


FEED = '''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>第14回 医療機器安全管理セミナー</title><link>https://osakace.com/archives/43299</link>
<pubDate>2026-09-17</pubDate><description>抜粋</description><content:encoded><![CDATA[
<p>開催日時：2026年11月3日 10:00～16:00</p><p>参加費：会員・学生 1000円、非会員 2000円</p>
<a href="/wp-content/uploads/one.pdf">案内PDF</a><a href="https://peatix.com/event/123">申込</a>
]]></content:encoded></item><item><title>求人情報</title><link>https://osakace.com/archives/1</link></item>
</channel></rss>'''


def document(body=FEED):
    url = "https://osakace.com/archives/category/studys/feed"
    return FetchResponse(url, url, 200, {"content-type": "application/rss+xml"},
        body.encode(), datetime.now(UTC), "fixture")


class OsakaFeedTest(unittest.TestCase):
    def test_full_feed_body_pdf_and_actual_event_date(self):
        result = adapter_for_source("src_osaka").parse(source_config("src_osaka"), document())
        self.assertEqual(1, len(result.candidates))
        candidate = result.candidates[0]
        self.assertEqual("wordpress_public_post", candidate.discovery_method)
        self.assertIn("2026-11-03", candidate.extracted_fields["event_start"].value)
        self.assertNotIn("2026-09-17", candidate.block_text)
        self.assertIn("非会員 2000円", candidate.block_text)
        self.assertEqual(("https://osakace.com/wp-content/uploads/one.pdf",), candidate.pdf_urls)

    def test_full_feed_does_not_refetch_unavailable_article_pages(self):
        class Transport:
            def request(self, url, headers, **kwargs):
                if "/feed" not in url:
                    raise AssertionError("Full public RSS needs no article refetch")
                return RawHttpResponse(url, 200, {"content-type": "application/rss+xml"}, FEED.encode())
        source = replace(source_config("src_osaka"), enabled=True, robots_url="", request_interval_seconds=0)
        result = SourceCollector(fetcher=SafeHttpFetcher(transport=Transport(),
            resolver=lambda host: ["93.184.216.34"], max_attempts=1)).collect(source, adapter_for_source("src_osaka"))
        self.assertEqual(SourceRunStatus.SUCCESS, result.status)
        self.assertEqual(2, len(result.fetched_urls))

    def test_excerpt_still_requires_detail_and_external_link_is_rejected(self):
        feed = FEED.replace("content:encoded", "notfull")
        candidate = adapter_for_source("src_osaka").parse(source_config("src_osaka"), document(feed)).candidates[0]
        self.assertEqual("rss", candidate.discovery_method)
        self.assertEqual(0, len(adapter_for_source("src_osaka").parse(source_config("src_osaka"),
            document(FEED.replace("https://osakace.com/archives/43299", "https://example.net/archives/43299"))).candidates))


if __name__ == "__main__":
    unittest.main()
