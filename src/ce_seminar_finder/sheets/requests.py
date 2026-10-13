"""Retry only transient failures of idempotent Sheets requests."""
from __future__ import annotations

import ssl
import time


def execute_idempotent(request, *, attempts=3):
    for attempt in range(attempts):
        try:
            return request.execute()
        except Exception as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            transient = isinstance(error, (ssl.SSLError, TimeoutError, ConnectionError)) or status in {408, 429, 500, 502, 503, 504}
            if isinstance(error, ssl.SSLCertVerificationError) or not transient or attempt + 1 >= attempts:
                raise
            # Discard a stale TLS connection, never disable certificate checks
            # or change the credential's recipient, scope, or lifetime.
            http = getattr(request, "http", None)
            close = getattr(http, "close", None) or getattr(getattr(http, "http", None), "close", None)
            if close:
                close()
            time.sleep(2 ** attempt)
