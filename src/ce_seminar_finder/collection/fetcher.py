from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from typing import Protocol
from urllib.parse import urljoin

from .cache import FetchState, JsonFetchStateStore
from .models import FetchOutcome, FetchRequest, FetchResponse
from .rate_limit import HostRateLimiter
from .robots import RobotsPolicy
from .safety import Resolver, UnsafeUrlError, default_resolver, validate_url


RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
REDIRECT_STATUS = {301, 302, 303, 307, 308}


class FetchError(RuntimeError):
    pass


class ResponseTooLarge(FetchError):
    pass


@dataclass(frozen=True, slots=True)
class RawHttpResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_bytes: int,
    ) -> RawHttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class StandardHttpTransport:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect())

    def request(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_bytes: int,
    ) -> RawHttpResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        normalized_headers = {
            key.lower(): value for key, value in response.headers.items()
        }
        content_length = normalized_headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise ResponseTooLarge(
                f"Response Content-Length exceeds {max_bytes} bytes"
            )
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ResponseTooLarge(f"Response exceeds {max_bytes} bytes")
        return RawHttpResponse(
            url=response.geturl(),
            status_code=response.getcode(),
            headers=normalized_headers,
            body=body,
        )


def detect_encoding(
    body: bytes,
    headers: Mapping[str, str],
    configured: str,
) -> str:
    if configured.lower() in {"cp932", "shift_jis", "shift-jis"}:
        return "cp932"
    if configured.lower() not in {"", "auto"}:
        return configured
    content_type = headers.get("content-type", "")
    message = Message()
    message["content-type"] = content_type
    charset = message.get_content_charset()
    if charset:
        aliases = {
            "shift_jis": "cp932",
            "shift-jis": "cp932",
            "sjis": "cp932",
        }
        return aliases.get(charset.lower(), charset)
    if body.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    head = body[:8192].decode("ascii", errors="ignore")
    match = re.search(
        r"""charset\s*=\s*["']?\s*([A-Za-z0-9._-]+)""",
        head,
        flags=re.IGNORECASE,
    )
    if match:
        value = match.group(1).lower()
        return "cp932" if value in {"shift_jis", "shift-jis", "sjis"} else value
    return "utf-8"


class SafeHttpFetcher:
    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        rate_limiter: HostRateLimiter | None = None,
        state_store: JsonFetchStateStore | None = None,
        resolver: Resolver = default_resolver,
        sleeper: Callable[[float], None] = time.sleep,
        timeout: float = 20,
        max_attempts: int = 3,
        max_redirects: int = 5,
    ) -> None:
        self.transport = transport or StandardHttpTransport()
        self.rate_limiter = rate_limiter or HostRateLimiter()
        self.state_store = state_store
        self.resolver = resolver
        self.sleeper = sleeper
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_redirects = max_redirects

    def fetch(
        self,
        request: FetchRequest,
        *,
        robots_policy: RobotsPolicy | None = None,
        minimum_interval: float = 10,
        resolve_dns: bool = True,
        use_cache: bool = True,
    ) -> FetchResponse:
        if not request.user_agent.strip():
            raise FetchError("A descriptive User-Agent is required")
        url = validate_url(
            request.url,
            allowed_hosts=request.allowed_hosts,
            allowed_path_prefixes=request.allowed_path_prefixes,
            resolver=self.resolver,
            resolve_dns=resolve_dns,
        )
        if robots_policy and not robots_policy.can_fetch(request.user_agent, url):
            return self._response(
                url=url,
                final_url=url,
                status_code=0,
                headers={},
                body=b"",
                outcome=FetchOutcome.BLOCKED,
                error_code="ROBOTS_BLOCKED",
                error_message="robots.txt disallows this URL",
            )

        interval = minimum_interval
        if robots_policy:
            crawl_delay = robots_policy.crawl_delay(request.user_agent)
            if crawl_delay is not None:
                interval = max(interval, crawl_delay)

        state = (
            self.state_store.get(url)
            if self.state_store is not None and use_cache
            else None
        )
        headers = {
            "User-Agent": request.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml,"
                "application/rss+xml,application/pdf;q=0.9,*/*;q=0.1"
            ),
            "Accept-Encoding": "identity",
        }
        etag = request.etag or (state.etag if state else "")
        last_modified = request.last_modified or (
            state.last_modified if state else ""
        )
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        current_url = url
        redirects = 0
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.rate_limiter.wait(current_url, interval)
                raw = self.transport.request(
                    current_url,
                    headers,
                    timeout=self.timeout,
                    max_bytes=request.max_bytes,
                )
                while raw.status_code in REDIRECT_STATUS:
                    location = raw.headers.get("location")
                    if not location:
                        raise FetchError("Redirect response has no Location header")
                    redirects += 1
                    if redirects > self.max_redirects:
                        raise FetchError("Too many redirects")
                    current_url = validate_url(
                        urljoin(current_url, location),
                        allowed_hosts=request.allowed_hosts,
                        allowed_path_prefixes=request.allowed_path_prefixes,
                        resolver=self.resolver,
                        resolve_dns=resolve_dns,
                    )
                    self.rate_limiter.wait(current_url, interval)
                    raw = self.transport.request(
                        current_url,
                        headers,
                        timeout=self.timeout,
                        max_bytes=request.max_bytes,
                    )

                if raw.status_code == 304:
                    return self._response(
                        url=url,
                        final_url=current_url,
                        status_code=304,
                        headers=raw.headers,
                        body=b"",
                        outcome=FetchOutcome.NOT_MODIFIED,
                    )
                if raw.status_code in RETRYABLE_STATUS:
                    if attempt < self.max_attempts:
                        self.sleeper(self._retry_delay(raw.headers, attempt))
                        continue
                    return self._response(
                        url=url,
                        final_url=current_url,
                        status_code=raw.status_code,
                        headers=raw.headers,
                        body=raw.body,
                        outcome=FetchOutcome.FAILED,
                        error_code=f"HTTP_{raw.status_code}",
                        error_message="Retry limit reached",
                    )
                if raw.status_code < 200 or raw.status_code >= 300:
                    return self._response(
                        url=url,
                        final_url=current_url,
                        status_code=raw.status_code,
                        headers=raw.headers,
                        body=raw.body,
                        outcome=FetchOutcome.FAILED,
                        error_code=f"HTTP_{raw.status_code}",
                        error_message="Non-success HTTP status",
                    )

                content_hash = hashlib.sha256(raw.body).hexdigest()
                unchanged = bool(state and state.content_hash == content_hash)
                outcome = (
                    FetchOutcome.NOT_MODIFIED if unchanged else FetchOutcome.FETCHED
                )
                encoding = detect_encoding(
                    raw.body,
                    raw.headers,
                    request.encoding,
                )
                response = self._response(
                    url=url,
                    final_url=current_url,
                    status_code=raw.status_code,
                    headers=raw.headers,
                    body=b"" if unchanged else raw.body,
                    outcome=outcome,
                    encoding=encoding,
                    content_hash=content_hash,
                )
                if self.state_store and use_cache:
                    self.state_store.put(
                        FetchState(
                            url=url,
                            etag=raw.headers.get("etag", ""),
                            last_modified=raw.headers.get("last-modified", ""),
                            content_hash=content_hash,
                            fetched_at=response.fetched_at.isoformat(),
                        )
                    )
                return response
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    self.sleeper(float(2 ** (attempt - 1)))
                    continue
            except (FetchError, UnsafeUrlError, ResponseTooLarge) as exc:
                return self._response(
                    url=url,
                    final_url=current_url,
                    status_code=0,
                    headers={},
                    body=b"",
                    outcome=FetchOutcome.FAILED,
                    error_code=exc.__class__.__name__.upper(),
                    error_message=str(exc),
                )
        return self._response(
            url=url,
            final_url=current_url,
            status_code=0,
            headers={},
            body=b"",
            outcome=FetchOutcome.FAILED,
            error_code="NETWORK_ERROR",
            error_message=str(last_error or "Unknown network error"),
        )

    @staticmethod
    def _retry_delay(headers: Mapping[str, str], attempt: int) -> float:
        retry_after = headers.get("retry-after", "")
        if retry_after.isdigit():
            return min(float(retry_after), 300)
        return float(2 ** (attempt - 1))

    @staticmethod
    def _response(
        *,
        url: str,
        final_url: str,
        status_code: int,
        headers: Mapping[str, str],
        body: bytes,
        outcome: FetchOutcome,
        encoding: str | None = None,
        content_hash: str = "",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> FetchResponse:
        if not content_hash and body:
            content_hash = hashlib.sha256(body).hexdigest()
        return FetchResponse(
            url=url,
            final_url=final_url,
            status_code=status_code,
            headers={key.lower(): value for key, value in headers.items()},
            body=body,
            fetched_at=datetime.now(UTC),
            content_hash=content_hash,
            outcome=outcome,
            encoding=encoding,
            error_code=error_code,
            error_message=error_message,
        )
