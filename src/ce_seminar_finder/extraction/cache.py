from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .models import ExtractionRequest


def extraction_cache_key(
    request: ExtractionRequest,
    *,
    provider: str,
    model: str,
    prompt_version: str,
) -> str:
    payload = {
        "request": request.cache_payload(),
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class JsonExtractionCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: dict[str, dict[str, Any]] | None = None

    def get(self, key: str) -> Mapping[str, Any] | None:
        return self._load().get(key)

    def put(self, key: str, value: Mapping[str, Any]) -> None:
        items = self._load()
        items[key] = dict(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(items, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._items is not None:
            return self._items
        if not self.path.exists():
            self._items = {}
            return self._items
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("extraction cache must contain a JSON object")
        self._items = {
            str(key): dict(value)
            for key, value in data.items()
            if isinstance(value, dict)
        }
        return self._items
