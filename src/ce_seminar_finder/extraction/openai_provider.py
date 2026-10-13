"""Bounded Responses API extraction. Credentials and raw errors never escape."""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from threading import Lock

import certifi

from .models import ExtractionRequest
from .prompt import build_extraction_messages
from .validator import KNOWN_FIELDS

DEFAULT_MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/responses"


class OpenAIExtractionError(RuntimeError):
    def __init__(self, code: str, status: int | None = None):
        self.code, self.status = code, status
        super().__init__(f"OpenAI extraction: {code}" + (f" (HTTP {status})" if status else ""))


def load_api_key(env_file: Path | None = None) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    if env_file is not None and env_file.is_file() and not env_file.is_symlink():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                if key:
                    return key
    raise OpenAIExtractionError("API_KEY_MISSING")


def event_response_schema() -> dict:
    properties = {}
    for name in sorted(KNOWN_FIELDS):
        value = {"type": ["string", "null"]}
        if name == "genres":
            value = {"type": ["array", "null"], "items": {"type": "string"}}
        properties[name] = {"type": "object", "properties": {
            "value": value, "confidence": {"type": "number"},
            "evidence": {"type": ["string", "null"]}},
            "required": ["value", "confidence", "evidence"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "is_event": {"type": "boolean"}, "event_confidence": {"type": "number"},
        "fields": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
        "review_reasons": {"type": "array", "items": {"type": "string"}}},
        "required": ["is_event", "event_confidence", "fields", "review_reasons"], "additionalProperties": False}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise OpenAIExtractionError("REDIRECT_BLOCKED")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL,
                 max_requests: int | None = None, max_input_chars: int = 40_000,
                 transport: Callable | None = None):
        if not api_key.strip():
            raise OpenAIExtractionError("API_KEY_MISSING")
        if (max_requests is not None and max_requests < 1) or max_input_chars < 100:
            raise ValueError("Extraction limits must be positive")
        self._api_key = api_key
        self.model = model
        self.max_requests, self.max_input_chars = max_requests, max_input_chars
        self.requests = 0
        self.input_tokens = self.output_tokens = 0
        self._transport = transport or self._post
        self._counter_lock = Lock()

    def extract_event(self, request: ExtractionRequest) -> dict:
        messages = build_extraction_messages(request)
        if sum(len(item["content"]) for item in messages) > self.max_input_chars:
            raise OpenAIExtractionError("INPUT_LIMIT_REACHED")
        body = {"model": self.model, "input": list(messages), "store": False,
                "reasoning": {"effort": "low"}, "max_output_tokens": 6000,
                "text": {"format": {"type": "json_schema", "name": "ce_event",
                    "strict": True, "schema": event_response_schema()}}}
        with self._counter_lock:
            if self.max_requests is not None and self.requests >= self.max_requests:
                raise OpenAIExtractionError("REQUEST_LIMIT_REACHED")
            self.requests += 1
        try:
            response = self._transport(body)
        except OpenAIExtractionError:
            raise
        except Exception:
            raise OpenAIExtractionError("TRANSPORT_ERROR") from None
        usage = response.get("usage") or {}
        with self._counter_lock:
            self.input_tokens += int(usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("output_tokens") or 0)
        if response.get("status") != "completed":
            raise OpenAIExtractionError("RESPONSE_INCOMPLETE")
        texts = []
        for output in response.get("output", []):
            if output.get("type") != "message":
                continue
            for part in output.get("content", []):
                if part.get("type") == "refusal":
                    raise OpenAIExtractionError("RESPONSE_REFUSED")
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
        try:
            result = json.loads("".join(texts))
        except (ValueError, TypeError):
            raise OpenAIExtractionError("INVALID_JSON") from None
        if not isinstance(result, dict):
            raise OpenAIExtractionError("INVALID_JSON_OBJECT")
        return result

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where())))
        try:
            with opener.open(request, timeout=50) as response:
                data = response.read(2_000_001)
        except urllib.error.HTTPError as error:
            code = "HTTP_ERROR"
            try:
                detail = json.loads(error.read(16_384)).get("error", {})
                if detail.get("code") in {"invalid_api_key", "insufficient_quota", "rate_limit_exceeded",
                                           "model_not_found", "context_length_exceeded", "unsupported_parameter"}:
                    code = detail["code"]
            except (ValueError, TypeError, AttributeError):
                pass
            raise OpenAIExtractionError(code, error.code) from None
        except OpenAIExtractionError:
            raise
        except Exception:
            raise OpenAIExtractionError("NETWORK_ERROR") from None
        if len(data) > 2_000_000:
            raise OpenAIExtractionError("RESPONSE_TOO_LARGE")
        try:
            result = json.loads(data)
        except (ValueError, TypeError):
            raise OpenAIExtractionError("INVALID_RESPONSE") from None
        if not isinstance(result, dict):
            raise OpenAIExtractionError("INVALID_RESPONSE")
        return result
