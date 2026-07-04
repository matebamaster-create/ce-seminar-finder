from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ce_seminar_finder.review.decisions import apply_review_decision
from ce_seminar_finder.review.duplicates import (
    EventSnapshot,
    assess_duplicate,
    normalize_organizer,
    normalize_title,
)
from ce_seminar_finder.review.repository import JsonlReviewRepository
from ce_seminar_finder.review.router import route_review


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 4, 12, 0, tzinfo=JST)


def event(
    event_id: str,
    *,
    title: str = "第10回 人工呼吸器 Webセミナー",
    date: str = "2026-08-01T13:00:00+09:00",
    organizer: str = "一般社団法人福岡県臨床工学技士会",
    event_format: str = "Web",
    official_url: str = "",
    application_url: str = "",
    pdf_hash: str = "",
) -> EventSnapshot:
    return EventSnapshot(
        event_id=event_id,
        title=title,
        event_start_at=date,
        organizer_name=organizer,
        event_format=event_format,
        official_urls=(official_url,) if official_url else (),
        application_urls=(application_url,) if application_url else (),
        pdf_hashes=(pdf_hash,) if pdf_hash else (),
    )


class DuplicateTest(unittest.TestCase):
    def test_normalization_preserves_edition_and_removes_format_noise(self) -> None:
        self.assertEqual(
            normalize_title("第10回 人工呼吸器 WEBセミナー"),
            normalize_title("第10回　人工呼吸器セミナー（オンライン）"),
        )
        self.assertNotEqual(
            normalize_title("第10回 人工呼吸器セミナー"),
            normalize_title("第11回 人工呼吸器セミナー"),
        )
        self.assertEqual(
            "福岡県臨床工学技士会",
            normalize_organizer("一般社団法人 福岡県臨床工学技士会"),
        )

    def test_high_score_without_anchor_never_auto_merges(self) -> None:
        result = assess_duplicate(event("evt_a"), event("evt_b"))
        self.assertGreaterEqual(result.total_score, 0.65)
        self.assertEqual("review", result.disposition)
        self.assertFalse(result.auto_merge_candidate)

    def test_matching_official_url_allows_auto_merge_candidate(self) -> None:
        url = "https://example.test/event/10/"
        result = assess_duplicate(
            event("evt_a", official_url=url),
            event("evt_b", official_url=url.rstrip("/")),
        )
        self.assertEqual("official_url", result.deterministic_anchor)
        self.assertTrue(result.auto_merge_candidate)

    def test_pdf_hash_is_deterministic_anchor(self) -> None:
        result = assess_duplicate(
            event("evt_a", pdf_hash="ABC123"),
            event("evt_b", pdf_hash="abc123"),
        )
        self.assertEqual("pdf_hash", result.deterministic_anchor)

    def test_different_events_stay_separate(self) -> None:
        result = assess_duplicate(
            event("evt_a"),
            event(
                "evt_b",
                title="第5回 血液浄化研究会",
                date="2026-09-20T10:00:00+09:00",
                organizer="別団体",
                event_format="現地開催",
            ),
        )
        self.assertEqual("separate", result.disposition)


class ReviewRouterTest(unittest.TestCase):
    def test_deadline_within_72_hours_is_urgent(self) -> None:
        item = route_review(
            event_id="evt_a",
            reason_codes=("FEE_UNKNOWN",),
            uncertain_fields=("fee_text",),
            source_excerpt="参加費は 詳細参照",
            source_urls=("https://example.test/a",),
            now=NOW,
            application_deadline_at=NOW + timedelta(hours=48),
        )
        self.assertEqual("緊急", item.priority)
        self.assertEqual("修正", item.suggested_action)
        self.assertLessEqual(len(item.source_excerpt), 300)

    def test_high_impact_change_is_high_priority(self) -> None:
        item = route_review(
            event_id="evt_a",
            reason_codes=("HIGH_IMPACT_FIELD_CHANGED",),
            uncertain_fields=("event_start_at",),
            source_excerpt="開催日変更",
            source_urls=(),
            now=NOW,
            event_start_at=NOW + timedelta(days=30),
        )
        self.assertEqual("高", item.priority)

    def test_duplicate_suggests_merge_and_past_item_is_low(self) -> None:
        item = route_review(
            event_id="evt_a",
            reason_codes=("DUPLICATE_CANDIDATE",),
            uncertain_fields=(),
            source_excerpt="重複候補",
            source_urls=(),
            now=NOW,
            event_start_at=NOW - timedelta(days=1),
        )
        self.assertEqual("低", item.priority)
        self.assertEqual("統合", item.suggested_action)

    def test_requires_timezone_aware_now(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            route_review(
                event_id="evt_a",
                reason_codes=(),
                uncertain_fields=(),
                source_excerpt="",
                source_urls=(),
                now=datetime(2026, 7, 4),
            )


class DecisionTest(unittest.TestCase):
    def base_event(self) -> dict[str, object]:
        return {
            "event_id": "evt_a",
            "canonical_event_id": "evt_a",
            "publication_status": "確認待ち",
            "review_status": "未確認",
            "review_label": "なし",
            "duplicate_status": "重複なし",
            "title": "人工呼吸器セミナー",
        }

    def test_publish_with_warning_updates_event_and_audits_before_after(self) -> None:
        outcome = apply_review_decision(
            review_id="rev_a",
            event=self.base_event(),
            decision="要確認付き公開",
            automation_choice="次回も確認",
            actor="admin@example.test",
            acted_at=NOW,
        )
        self.assertEqual("公開", outcome.event["publication_status"])
        self.assertEqual("あり", outcome.event["review_label"])
        self.assertIsNone(outcome.automation_rule)
        self.assertEqual("publish_with_warning", outcome.action.action)
        self.assertEqual(
            "確認待ち",
            json.loads(outcome.action.before_json)["publication_status"],
        )

    def test_next_time_review_never_creates_rule_even_if_flag_is_true(self) -> None:
        outcome = apply_review_decision(
            review_id="rev_a",
            event=self.base_event(),
            decision="公開",
            automation_choice="次回も確認",
            actor="admin",
            acted_at=NOW,
            approve_automation=True,
            automation_condition={"source_id": "src_fukuoka"},
        )
        self.assertIsNone(outcome.automation_rule)

    def test_explicit_approval_and_condition_create_traceable_rule(self) -> None:
        outcome = apply_review_decision(
            review_id="rev_a",
            event=self.base_event(),
            decision="公開",
            automation_choice="自動公開",
            actor="admin",
            acted_at=NOW,
            approve_automation=True,
            automation_condition={
                "source_id": "src_fukuoka",
                "event_type": "セミナー",
            },
        )
        rule = outcome.automation_rule
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertEqual(outcome.action.action_id, rule.approved_from_action_id)
        self.assertEqual("publish", rule.action)

    def test_automation_without_condition_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a condition"):
            apply_review_decision(
                review_id="rev_a",
                event=self.base_event(),
                decision="公開",
                automation_choice="自動公開",
                actor="admin",
                acted_at=NOW,
                approve_automation=True,
            )

    def test_edit_requires_overrides_and_merge_requires_canonical(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires overrides"):
            apply_review_decision(
                review_id="rev_a",
                event=self.base_event(),
                decision="修正後公開",
                automation_choice="次回も確認",
                actor="admin",
                acted_at=NOW,
            )
        with self.assertRaisesRegex(ValueError, "canonical_event_id"):
            apply_review_decision(
                review_id="rev_a",
                event=self.base_event(),
                decision="重複統合",
                automation_choice="次回も確認",
                actor="admin",
                acted_at=NOW,
            )

    def test_merge_keeps_source_event_as_merged_record(self) -> None:
        outcome = apply_review_decision(
            review_id="rev_a",
            event=self.base_event(),
            decision="重複統合",
            automation_choice="次回も確認",
            actor="admin",
            acted_at=NOW,
            canonical_event_id="evt_canonical",
        )
        self.assertEqual("統合済み", outcome.event["duplicate_status"])
        self.assertEqual("evt_canonical", outcome.event["canonical_event_id"])
        self.assertEqual("非公開", outcome.event["publication_status"])

    def test_repository_is_append_only(self) -> None:
        outcome = apply_review_decision(
            review_id="rev_a",
            event=self.base_event(),
            decision="公開",
            automation_choice="次回も確認",
            actor="admin",
            acted_at=NOW,
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlReviewRepository(Path(directory))
            repository.append_decision(outcome)
            repository.append_decision(outcome)
            lines = (
                Path(directory) / "review-actions.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(2, len(lines))


if __name__ == "__main__":
    unittest.main()
