from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ce_seminar_finder.adapters.common import PatternHtmlAdapter
from ce_seminar_finder.collection.cache import JsonFetchStateStore
from ce_seminar_finder.collection.fetcher import RawHttpResponse, SafeHttpFetcher
from ce_seminar_finder.collection.models import SourceConfig, SourceRunStatus
from ce_seminar_finder.collection.pipeline import SourceCollector
from ce_seminar_finder.collection.repository import JsonlCollectionRepository


class FakeTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, url, headers, *, timeout, max_bytes):  # type: ignore[no-untyped-def]
        self.calls += 1
        if url.endswith("/broken"):
            return RawHttpResponse(url, 500, {}, b"")
        return RawHttpResponse(
            url,
            200,
            {"content-type": "text/html; charset=utf-8"},
            '<a href="/event/one">呼吸療法Webセミナー</a>'.encode(),
        )


class PipelineTest(unittest.TestCase):
    def source(self, enabled: bool = True) -> SourceConfig:
        return SourceConfig(
            source_id="src_test",
            organization_name="テスト技士会",
            prefecture="テスト県",
            base_url="https://example.org/",
            discovery_urls=(
                "https://example.org/broken",
                "https://example.org/events",
            ),
            allowed_path_prefixes=("/",),
            adapter_type="static_html",
            enabled=enabled,
            request_interval_seconds=0,
            max_requests_per_run=5,
            user_agent="CE-Seminar-Finder-Test/1.0",
        )

    def test_disabled_source_does_not_fetch(self) -> None:
        transport = FakeTransport()
        collector = SourceCollector(
            fetcher=SafeHttpFetcher(
                transport=transport,
                resolver=lambda _host: ["93.184.216.34"],
                max_attempts=1,
            )
        )
        result = collector.collect(
            self.source(enabled=False),
            PatternHtmlAdapter(
                detail_patterns=(r"/event/",),
                include_event_text_links=True,
            ),
        )
        self.assertEqual(SourceRunStatus.DISABLED, result.status)
        self.assertEqual(0, transport.calls)

    def test_one_failure_does_not_stop_other_discovery_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = JsonFetchStateStore(Path(directory) / "state.json")
            repository = JsonlCollectionRepository(Path(directory) / "logs")
            collector = SourceCollector(
                fetcher=SafeHttpFetcher(
                    transport=FakeTransport(),
                    resolver=lambda _host: ["93.184.216.34"],
                    state_store=state,
                    max_attempts=1,
                ),
                repository=repository,
                state_store=state,
            )
            result = collector.collect(
                self.source(),
                PatternHtmlAdapter(
                    detail_patterns=(r"/event/",),
                    include_event_text_links=True,
                ),
                max_detail_pages=0,
            )
            self.assertEqual(SourceRunStatus.PARTIAL, result.status)
            self.assertEqual(1, len(result.candidates))
            self.assertTrue((Path(directory) / "logs/fetch-logs.jsonl").exists())
            self.assertTrue((Path(directory) / "logs/candidates.jsonl").exists())
            self.assertTrue((Path(directory) / "state.json").exists())


if __name__ == "__main__":
    unittest.main()

