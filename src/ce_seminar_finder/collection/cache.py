from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FetchState:
    url: str
    etag: str = ""
    last_modified: str = ""
    content_hash: str = ""
    fetched_at: str = ""


class JsonFetchStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._states: dict[str, FetchState] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._states = {
                url: FetchState(**value) for url, value in raw.items()
            }

    def get(self, url: str) -> FetchState | None:
        return self._states.get(url)

    def put(self, state: FetchState) -> None:
        self._states[state.url] = state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    url: asdict(state)
                    for url, state in sorted(self._states.items())
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def cache_body(self, url: str, body: bytes, *, encoding: str, final_url: str, content_type: str) -> None:
        path = self.path.parent / (self.path.stem + "-bodies")
        path.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()
        (path / (key + ".body")).write_bytes(body)
        (path / (key + ".json")).write_text(json.dumps({"encoding": encoding, "final_url": final_url, "content_type": content_type}), encoding="utf-8")

    def cached_body(self, url: str):
        path = self.path.parent / (self.path.stem + "-bodies")
        key = hashlib.sha256(url.encode()).hexdigest()
        body = path / (key + ".body")
        meta = path / (key + ".json")
        if not body.exists() or not meta.exists():
            return None
        return body.read_bytes(), json.loads(meta.read_text(encoding="utf-8"))

