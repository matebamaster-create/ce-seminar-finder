from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ce_seminar_finder.collection.cache import JsonFetchStateStore
from ce_seminar_finder.collection.fetcher import (
    RawHttpResponse,
    SafeHttpFetcher,
    detect_encoding,
)
from ce_seminar_finder.collection.models import (
    FetchOutcome,
    FetchRequest,
    SourceConfig,
)
from ce_seminar_finder.collection.rate_limit import HostRateLimiter
from ce_seminar_finder.collection.robots import RobotsPolicy
from ce_seminar_finder.collection.safety import UnsafeUrlError, validate_url


PUBLIC_IP = lambda _host: ["93.184.216.34"]


class FakeTransport:
    def __init__(self, responses: list[RawHttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def request(self, url, headers, *, timeout, max_bytes):  # type: ignore[no-untyped-def]
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError("Unexpected transport request")
        return self.responses.pop(0)


def request(url: str, **kwargs) -> FetchRequest:
    return FetchRequest(
        url=url,
        source_id="src_test",
        user_agent="CE-Seminar-Finder-Test/1.0",
        allowed_hosts=frozenset({"example.org"}),
        allowed_path_prefixes=("/",),
        **kwargs,
    )


class SafetyTest(unittest.TestCase):
    def test_accepts_allowlisted_public_url_and_removes_fragment(self) -> None:
        value = validate_url(
            "https://EXAMPLE.org/events/1#section",
            allowed_hosts=frozenset({"example.org"}),
            resolver=PUBLIC_IP,
        )
        self.assertEqual("https://example.org/events/1", value)

    def test_rejects_wrong_host_path_and_credentials(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_url(
                "https://evil.example/events",
                allowed_hosts=frozenset({"example.org"}),
                resolver=PUBLIC_IP,
            )
        with self.assertRaises(UnsafeUrlError):
            validate_url(
                "https://example.org/admin",
                allowed_hosts=frozenset({"example.org"}),
                allowed_path_prefixes=("/event/",),
                resolver=PUBLIC_IP,
            )
        with self.assertRaises(UnsafeUrlError):
            validate_url(
                "https://user:pass@example.org/event/1",
                allowed_hosts=frozenset({"example.org"}),
                resolver=PUBLIC_IP,
            )

    def test_rejects_private_dns_result(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_url(
                "https://example.org/",
                allowed_hosts=frozenset({"example.org"}),
                resolver=lambda _host: ["127.0.0.1"],
            )


class RobotsTest(unittest.TestCase):
    def test_crawl_delay_and_disallow(self) -> None:
        policy = RobotsPolicy(
            "https://example.org/robots.txt",
            "User-agent: *\nDisallow: /private\nCrawl-delay: 60\n",
        )
        self.assertEqual(60, policy.crawl_delay("CE-Seminar-Finder-Test/1.0"))
        self.assertFalse(
            policy.can_fetch(
                "CE-Seminar-Finder-Test/1.0",
                "https://example.org/private/a",
            )
        )
        self.assertTrue(
            policy.can_fetch(
                "CE-Seminar-Finder-Test/1.0",
                "https://example.org/event/a",
            )
        )


class RateLimiterTest(unittest.TestCase):
    def test_waits_for_remaining_host_interval(self) -> None:
        now = [100.0]
        sleeps: list[float] = []

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        limiter = HostRateLimiter(clock=lambda: now[0], sleeper=sleeper)
        limiter.wait("https://example.org/a", 60)
        now[0] += 10
        waited = limiter.wait("https://example.org/b", 60)
        self.assertEqual(50, waited)
        self.assertEqual([50], sleeps)


class FetcherTest(unittest.TestCase):
    def test_detects_cp932_from_meta(self) -> None:
        body = (
            '<meta http-equiv="Content-Type" '
            'content="text/html; charset=shift_jis">熊本'
        ).encode("cp932")
        self.assertEqual("cp932", detect_encoding(body, {}, "auto"))

    def test_hash_cache_skips_unchanged_body_and_sends_etag(self) -> None:
        raw = RawHttpResponse(
            "https://example.org/event",
            200,
            {"content-type": "text/html; charset=utf-8", "etag": '"abc"'},
            "セミナー".encode(),
        )
        with tempfile.TemporaryDirectory() as directory:
            store = JsonFetchStateStore(Path(directory) / "state.json")
            transport = FakeTransport([raw, raw])
            fetcher = SafeHttpFetcher(
                transport=transport,
                state_store=store,
                resolver=PUBLIC_IP,
                sleeper=lambda _seconds: None,
            )
            first = fetcher.fetch(request("https://example.org/event"), minimum_interval=0)
            second = fetcher.fetch(request("https://example.org/event"), minimum_interval=0)
        self.assertEqual(FetchOutcome.FETCHED, first.outcome)
        self.assertEqual(FetchOutcome.NOT_MODIFIED, second.outcome)
        self.assertEqual(b"", second.body)
        self.assertEqual('"abc"', transport.calls[1][1]["If-None-Match"])

    def test_robots_block_prevents_transport_request(self) -> None:
        transport = FakeTransport([])
        fetcher = SafeHttpFetcher(transport=transport, resolver=PUBLIC_IP)
        policy = RobotsPolicy(
            "https://example.org/robots.txt",
            "User-agent: *\nDisallow: /blocked\n",
        )
        response = fetcher.fetch(
            request("https://example.org/blocked"),
            robots_policy=policy,
            minimum_interval=0,
        )
        self.assertEqual(FetchOutcome.BLOCKED, response.outcome)
        self.assertEqual([], transport.calls)

    def test_retries_retryable_status_then_succeeds(self) -> None:
        transport = FakeTransport(
            [
                RawHttpResponse("https://example.org/a", 503, {}, b""),
                RawHttpResponse(
                    "https://example.org/a",
                    200,
                    {"content-type": "text/html"},
                    b"ok",
                ),
            ]
        )
        sleeps: list[float] = []
        fetcher = SafeHttpFetcher(
            transport=transport,
            resolver=PUBLIC_IP,
            sleeper=sleeps.append,
        )
        response = fetcher.fetch(request("https://example.org/a"), minimum_interval=0)
        self.assertEqual(FetchOutcome.FETCHED, response.outcome)
        self.assertEqual(2, len(transport.calls))
        self.assertEqual([1.0], sleeps)

    def test_redirect_outside_allowlist_is_rejected(self) -> None:
        transport = FakeTransport(
            [
                RawHttpResponse(
                    "https://example.org/a",
                    302,
                    {"location": "https://evil.example/a"},
                    b"",
                )
            ]
        )
        fetcher = SafeHttpFetcher(transport=transport, resolver=PUBLIC_IP)
        response = fetcher.fetch(request("https://example.org/a"), minimum_interval=0)
        self.assertEqual(FetchOutcome.FAILED, response.outcome)
        self.assertEqual("UNSAFEURLERROR", response.error_code)


if __name__ == "__main__":
    unittest.main()

