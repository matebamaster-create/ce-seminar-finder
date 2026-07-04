from __future__ import annotations

import json
import os
import time
from pathlib import Path


class RunAlreadyActive(RuntimeError):
    pass


class FileRunLock:
    def __init__(self, path: Path, *, stale_after_seconds: int = 21_600) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self._owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_lock()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise RunAlreadyActive(f"run lock already exists: {self.path}") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"pid": os.getpid(), "created_at_epoch": time.time()},
                handle,
            )
        self._owned = True

    def release(self) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False

    def __enter__(self) -> "FileRunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()

    def _remove_stale_lock(self) -> None:
        if not self.path.exists():
            return
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age > self.stale_after_seconds:
            self.path.unlink(missing_ok=True)
