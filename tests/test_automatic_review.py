from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime

from test_restart import FakeSheets
from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.collection.models import EventCandidate
from ce_seminar_finder.extraction.models import ExtractionResult, ExtractedField
from ce_seminar_finder.extraction.rules import extract_rule_values
from ce_seminar_finder.review.automatic import AutomaticReviewer, ACTOR, RULE_ID
from ce_seminar_finder.sheets.schema import SOURCE_ROWS

NOW = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)


def candidate(url="https://www.narace.jp/#one", date="2026年11月20日", title="第10回 呼吸セミナー", fee="会員1,000円 非会員2,000円"):
    text = f"{title}\n開催日時 {date} 19:00~20:00\n開催方法 Web（Zoom）\n主催 奈良県臨床工学技士会\n参加費 {fee}"
    return EventCandidate("src_nara", "https://www.narace.jp/", url, title,
        block_text=text, extracted_fields=extract_rule_values(text, title_hint=title))


def setup(items=None, *, ai=True):
    service = FakeSheets()
    service.tables["Sources"].extend([list(row) for row in SOURCE_ROWS])
    h = service.tables["Sources"][0]
    next(r for r in service.tables["Sources"][1:] if r[0] == "src_nara")[h.index("enabled")] = True
    ingestor = CandidateIngestor(service, "test")
    for item in items or [candidate()]:
        ingestor.ingest([item])
        if ai:
            refined = replace(item, ai_cache_key="cache-key-"+item.detail_url,
                ai_result=ExtractionResult(True, .99, item.extracted_fields, (), "openai", "test", "v3"))
            ingestor.ingest([refined])
    reviewer = AutomaticReviewer(service, "test", now=NOW)
    reviewer.enable_policy()
    return service, reviewer


class AutomaticReviewTest(unittest.TestCase):
    def test_policy_disabled_by_default(self):
        s, _ = setup()
        s.tables["AutomationRules"] = [s.tables["AutomationRules"][0]]
        summary = AutomaticReviewer(s, "test", now=NOW).run()
        self.assertFalse(summary["enabled"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])

    def test_grounded_event_is_published_without_optional_deadline_or_units(self):
        s, reviewer = setup()
        summary = reviewer.run()
        row = s.objects("Events")[0]
        self.assertEqual("公開", row["publication_status"])
        self.assertEqual("なし", row["review_label"])
        self.assertTrue(row["fee_verified"])
        self.assertEqual("有料", row["fee_category"])
        self.assertEqual("公開", s.objects("ReviewQueue")[0]["decision"])
        self.assertEqual(ACTOR, s.objects("ReviewActions")[0]["actor"])
        self.assertEqual(1, summary["newly_published"])
        self.assertEqual(0, reviewer.run()["written"])
        self.assertEqual(1, len(s.objects("ReviewActions")))

    def test_dry_run_does_not_change_publication_or_audit(self):
        s, reviewer = setup()
        before = json.dumps(s.tables, sort_keys=True)
        self.assertEqual(1, reviewer.run(dry_run=True)["publish"])
        self.assertEqual(before, json.dumps(s.tables, sort_keys=True))

    def test_bad_fee_and_high_ai_confidence_cannot_authorize_publication(self):
        s, reviewer = setup()
        h, row = s.tables["Events"][:2]
        row[h.index("fee_text")] = "会員2,000円 非会員1,000円"
        summary = reviewer.run()
        self.assertEqual(1, summary["human"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])
        self.assertIn("AUTO_FEE_TEXT_UNVERIFIED", s.objects("ReviewQueue")[0]["reason_codes"])

    def test_missing_ai_is_processing_not_human_review(self):
        s, reviewer = setup(ai=False)
        self.assertEqual(1, reviewer.run()["processing"])
        self.assertEqual("AUTO_PROCESSING_PENDING", s.objects("ReviewQueue")[0]["reason_codes"])
        self.assertEqual("なし", s.objects("Events")[0]["review_label"])

    def test_end_before_start_is_not_archived_or_published(self):
        item = candidate()
        item = replace(item, block_text=item.block_text + "\n終了 2026年9月20日20:00",
            extracted_fields={**item.extracted_fields, "event_end":
                ExtractedField("2026-09-20T20:00:00+09:00", 1, "終了 2026年9月20日20:00")})
        s, reviewer = setup([item])
        self.assertEqual(1, reviewer.run()["human"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])
        self.assertIn("DATE_CONFLICT", s.objects("ReviewQueue")[0]["reason_codes"])

    def test_month_spanning_live_range_requires_schedule_review(self):
        item = candidate()
        item = replace(item, block_text=item.block_text + "\n終了 2027年2月20日20:00",
            extracted_fields={**item.extracted_fields, "event_end":
                ExtractedField("2027-02-20T20:00:00+09:00", 1, "終了 2027年2月20日20:00")})
        s, reviewer = setup([item])
        self.assertEqual(1, reviewer.run()["human"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])
        self.assertIn("DATE_CONFLICT", s.objects("ReviewQueue")[0]["reason_codes"])

    def test_past_event_is_archived_reversibly_even_before_ai(self):
        s, reviewer = setup([candidate(date="2026年9月20日")], ai=False)
        summary = reviewer.run()
        self.assertEqual(1, summary["newly_archived"])
        self.assertEqual("アーカイブ", s.objects("Events")[0]["publication_status"])
        self.assertEqual("非公開", s.objects("ReviewQueue")[0]["decision"])
        self.assertIn("確認待ち", s.objects("ReviewActions")[0]["before_json"])

    def test_human_edits_and_private_choice_are_protected(self):
        s, reviewer = setup()
        h, row = s.tables["Events"][:2]
        row[h.index("title")] = "本人が修正したイベント名"
        row[h.index("publication_status")] = "非公開"
        row[h.index("last_admin_updated_at")] = "2026-10-13T00:00:00+09:00"
        before = list(row)
        reviewer.run()
        self.assertEqual(before, s.tables["Events"][1])

    def test_changed_source_or_missing_snapshot_never_auto_publishes(self):
        s, reviewer = setup()
        s.tables["DocumentTextChunks"][1][4] += "改変"
        self.assertEqual(1, reviewer.run()["human"])
        self.assertIn("SOURCE_SNAPSHOT_INVALID", s.objects("ReviewQueue")[0]["reason_codes"])

    def test_ambiguous_duplicate_is_left_for_human(self):
        a, b = candidate(), candidate(url="https://www.narace.jp/#two")
        s, reviewer = setup([a, b])
        summary = reviewer.run()
        self.assertEqual(2, summary["human"])
        self.assertTrue(all(r["publication_status"] == "確認待ち" for r in s.objects("Events")))

    def test_disabled_source_cannot_be_published(self):
        s, reviewer = setup()
        h = s.tables["Sources"][0]
        next(r for r in s.tables["Sources"][1:] if r[0] == "src_nara")[h.index("enabled")] = False
        self.assertEqual(1, reviewer.run()["protected"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])

    def test_unpriced_text_is_not_treated_as_free(self):
        item = candidate(fee="後日案内")
        item = replace(item, extracted_fields={**item.extracted_fields, "fee_text": ExtractedField("後日案内", 1, "参加費 後日案内")})
        s, reviewer = setup([item])
        self.assertEqual(1, reviewer.run()["human"])
        self.assertFalse(s.objects("Events")[0]["fee_verified"])

    def test_deterministic_shared_application_can_merge_unedited_duplicates(self):
        url = "https://peatix.com/event/12345"
        items = []
        for suffix in ("one", "two"):
            item = candidate(url="https://www.narace.jp/#" + suffix)
            item = replace(item, block_text=item.block_text + "\n申込方法 " + url,
                extracted_fields={**item.extracted_fields, "application_url": ExtractedField(url, 1, url)})
            items.append(item)
        s, reviewer = setup(items)
        summary = reviewer.run()
        self.assertEqual(1, summary["newly_published"])
        self.assertEqual(1, summary["newly_merged"])
        self.assertEqual({"公開", "非公開"}, {r["publication_status"] for r in s.objects("Events")})
        self.assertEqual("統合済み", s.objects("DuplicateCandidates")[0]["status"])

    def test_false_ai_non_event_needs_independent_non_learning_title(self):
        item = replace(candidate(title="求人募集の案内"), block_text="求人募集の案内 看護師採用", extracted_fields={})
        s, reviewer = setup([item], ai=False)
        CandidateIngestor(s, "test").ingest([replace(item, ai_cache_key="negative", ai_result=ExtractionResult(False, .99, {}, (), "openai", "test", "v3"))])
        self.assertEqual(1, reviewer.run()["newly_rejected"])
        self.assertEqual("非公開", s.objects("Events")[0]["publication_status"])

    def test_ocr_only_facts_cannot_auto_publish(self):
        s, reviewer = setup()
        event = s.objects("Events")[0]
        autos = s.tables["AutoFieldValues"]
        h = autos[0]
        fee_row = next(r for r in autos[1:] if r[h.index("field_name")] == "fee_text")
        fee_row[h.index("evidence_text")] = "参加費 600円"
        fee_row[h.index("normalized_value_json")] = json.dumps("600円")
        fee_row[h.index("source_document_id")] = "ocr_doc"
        eh = s.tables["Events"][0]
        s.tables["Events"][1][eh.index("fee_text")] = "600円"
        self.assertEqual(1, reviewer.run()["human"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])

    def test_posted_date_quote_is_not_a_supported_event_date(self):
        self.assertFalse(AutomaticReviewer._date_context("投稿日：2026年11月20日\n第10回呼吸セミナー", "2026年11月20日"))
        self.assertTrue(AutomaticReviewer._date_context("開催日時：2026年11月20日", "2026年11月20日"))

    def test_concurrent_admin_edit_is_not_overwritten_or_review_closed(self):
        s, reviewer = setup()
        get = s.get
        reads = 0
        def concurrent_get(**kwargs):
            nonlocal reads
            if kwargs["range"].startswith("'Events'!"):
                reads += 1
                if reads == 2:
                    h = s.tables["Events"][0]
                    s.tables["Events"][1][h.index("title")] = "保存直前の手修正"
                    s.tables["Events"][1][h.index("last_admin_updated_at")] = NOW.isoformat()
            return get(**kwargs)
        s.get = concurrent_get
        summary = reviewer.run()
        self.assertEqual(1, summary["concurrent_edit_skipped"])
        self.assertEqual("保存直前の手修正", s.objects("Events")[0]["title"])
        self.assertEqual("未判断", s.objects("ReviewQueue")[0]["decision"])
        self.assertEqual([], s.objects("ReviewActions"))

    def test_policy_stop_before_write_is_respected(self):
        s, reviewer = setup()
        get = s.get
        reads = 0
        def stopped_get(**kwargs):
            nonlocal reads
            if kwargs["range"].startswith("'AutomationRules'!"):
                reads += 1
                if reads == 2:
                    h = s.tables["AutomationRules"][0]
                    s.tables["AutomationRules"][1][h.index("enabled")] = False
            return get(**kwargs)
        s.get = stopped_get
        self.assertTrue(reviewer.run()["suspended_before_write"])
        self.assertEqual("確認待ち", s.objects("Events")[0]["publication_status"])

    def test_initial_enable_retry_does_not_undo_operator_stop(self):
        s, reviewer = setup()
        h = s.tables["AutomationRules"][0]
        s.tables["AutomationRules"][1][h.index("enabled")] = False
        reviewer.enable_policy()
        self.assertFalse(reviewer.run()["enabled"])

    def test_enable_policy_does_not_overwrite_concurrent_source_stop(self):
        s = FakeSheets()
        s.tables["Sources"].extend([list(row) for row in SOURCE_ROWS])
        h = s.tables["Sources"][0]
        row = next(r for r in s.tables["Sources"][1:] if r[0] == "src_nara")
        row[h.index("enabled")] = True
        update = s.batchUpdate
        def stopped_update(**kwargs):
            if any(d["range"].startswith("'Sources'!J") for d in kwargs["body"]["data"]):
                row[h.index("enabled")] = False
            return update(**kwargs)
        s.batchUpdate = stopped_update
        AutomaticReviewer(s, "test", now=NOW).enable_policy()
        self.assertFalse(row[h.index("enabled")])
        self.assertEqual("allow", row[h.index("auto_publish_policy")])


if __name__ == "__main__":
    unittest.main()
