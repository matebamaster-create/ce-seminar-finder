from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ce_seminar_finder.automation.daily import (
    run_daily_collection,
    write_daily_outputs,
)
from ce_seminar_finder.automation.lock import FileRunLock, RunAlreadyActive
from ce_seminar_finder.collection.models import (
    EventCandidate,
    SourceRunResult,
    SourceRunStatus,
)
from ce_seminar_finder.collection.sources import source_config


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 4, 6, 17, tzinfo=JST)


class FakeCollector:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.enabled_seen: list[str] = []

    def collect(self, source, adapter, *, max_detail_pages):
        if not source.enabled:
            return SourceRunResult(source.source_id, SourceRunStatus.DISABLED)
        self.enabled_seen.append(source.source_id)
        if source.source_id in self.failing:
            raise RuntimeError("secret=must-not-leak-but-error-is-bounded")
        return SourceRunResult(
            source.source_id,
            SourceRunStatus.SUCCESS,
            candidates=[
                EventCandidate(
                    source_id=source.source_id,
                    source_url=source.base_url,
                    detail_url=source.base_url + "event/1",
                    title_hint="テストセミナー",
                )
            ],
        )


class LockTest(unittest.TestCase):
    def test_lock_prevents_overlap_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.lock"
            first = FileRunLock(path)
            first.acquire()
            with self.assertRaises(RunAlreadyActive):
                FileRunLock(path).acquire()
            first.release()
            FileRunLock(path).acquire()
            self.assertTrue(path.exists())

    def test_stale_lock_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.lock"
            path.write_text("old", encoding="utf-8")
            old = time.time() - 100
            os.utime(path, (old, old))
            lock = FileRunLock(path, stale_after_seconds=10)
            lock.acquire()
            self.assertTrue(path.exists())
            lock.release()


class DailyRunTest(unittest.TestCase):
    def test_empty_enabled_set_performs_zero_external_collection(self) -> None:
        collector = FakeCollector()
        with tempfile.TemporaryDirectory() as directory:
            summary = run_daily_collection(
                collector=collector,
                sources=(
                    source_config("src_fukuoka"),
                    source_config("src_jace"),
                ),
                enabled_source_ids=set(),
                lock_path=Path(directory) / "daily.lock",
                now=NOW,
            )
        self.assertEqual([], collector.enabled_seen)
        self.assertEqual(2, summary.status_counts["disabled"])
        self.assertEqual(0, len(summary.candidates))

    def test_source_failure_does_not_stop_next_source(self) -> None:
        collector = FakeCollector({"src_fukuoka"})
        with tempfile.TemporaryDirectory() as directory:
            summary = run_daily_collection(
                collector=collector,
                sources=(
                    source_config("src_fukuoka"),
                    source_config("src_jace"),
                ),
                enabled_source_ids={"src_fukuoka", "src_jace"},
                lock_path=Path(directory) / "daily.lock",
                now=NOW,
            )
        self.assertEqual(["src_fukuoka", "src_jace"], collector.enabled_seen)
        self.assertEqual(1, summary.status_counts["failed"])
        self.assertEqual(1, summary.status_counts["success"])
        self.assertEqual(1, len(summary.candidates))
        self.assertTrue(summary.has_failures)
        self.assertNotIn("secret=", json.dumps(summary.as_dict()))

    def test_outputs_summary_candidates_and_markdown(self) -> None:
        collector = FakeCollector()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run_daily_collection(
                collector=collector,
                sources=(source_config("src_jace"),),
                enabled_source_ids={"src_jace"},
                lock_path=root / "daily.lock",
                now=NOW,
            )
            write_daily_outputs(
                summary,
                summary_path=root / "summary.json",
                candidates_path=root / "candidates.json",
                markdown_path=root / "summary.md",
            )
            data = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            candidates = json.loads(
                (root / "candidates.json").read_text(encoding="utf-8")
            )
            markdown = (root / "summary.md").read_text(encoding="utf-8")
        self.assertEqual(1, data["candidate_count"])
        self.assertEqual("src_jace", candidates[0]["source_id"])
        self.assertIn("日次実行", markdown)
        self.assertIn("| src_jace | success |", markdown)


if __name__ == "__main__":
    unittest.main()
