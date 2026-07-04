from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .decisions import DecisionOutcome
from .duplicates import DuplicateAssessment
from .router import ReviewItem


class JsonlReviewRepository:
    """Append-only local audit sink; production Sheets uses the same row shapes."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def append_duplicate(self, item: DuplicateAssessment) -> None:
        self._append("duplicate-candidates.jsonl", asdict(item))

    def append_review(self, item: ReviewItem) -> None:
        self._append("review-queue.jsonl", asdict(item))

    def append_decision(self, outcome: DecisionOutcome) -> None:
        self._append("review-actions.jsonl", asdict(outcome.action))
        if outcome.automation_rule:
            self._append("automation-rules.jsonl", asdict(outcome.automation_rule))

    def _append(self, filename: str, value: object) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
