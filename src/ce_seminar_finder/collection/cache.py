from __future__ import annotations

import json
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

