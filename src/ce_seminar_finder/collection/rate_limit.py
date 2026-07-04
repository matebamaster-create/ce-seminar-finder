from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit


class HostRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: dict[str, float] = {}

    def wait(self, url: str, minimum_interval: float) -> float:
        host = (urlsplit(url).hostname or "").lower()
        now = self._clock()
        last = self._last_request_at.get(host)
        waited = 0.0
        if last is not None:
            remaining = minimum_interval - (now - last)
            if remaining > 0:
                self._sleeper(remaining)
                waited = remaining
                now = self._clock()
        self._last_request_at[host] = now
        return waited

