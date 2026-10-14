from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

from test_automatic_review import setup, candidate, NOW
from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.collection.recovery import select_recoveries, recover_source_snapshots, dated_link_schedule
from ce_seminar_finder.collection.models import SourceRunStatus
from ce_seminar_finder.review.automatic import AutomaticReviewer


class SourceRecoveryTest(unittest.TestCase):
    def test_push_cannot_start_collection_or_ai_even_with_nonempty_inputs(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/daily.yml"
        text = workflow.read_text()
        for name in ("Install public-page renderer", "Collect explicitly enabled sources", "Install Japanese PDF OCR",
                     "Refresh existing Google connection before AI", "Refine all public candidates with AI and PDF (never auto-publish)"):
            step = text.split("- name: "+name, 1)[1].split("      - name:", 1)[0]
            self.assertIn("github.event_name != 'push'", step)
            self.assertIn("inputs.recovery_source_ids == ''", step)
        self.assertGreaterEqual(text.count('if [[ "$GITHUB_EVENT_NAME" == "push" ]]; then exit 0; fi'), 2)

    def test_input_recovery_requires_manual_dispatch_and_explicit_source_ids(self):
        text = (Path(__file__).resolve().parents[1] / ".github/workflows/daily.yml").read_text()
        step = text.split("- name: Recover only matched official inputs (no AI)", 1)[1].split("      - name:", 1)[0]
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.recovery_source_ids != ''", step)
        self.assertIn('if [[ "$GITHUB_EVENT_NAME" != "workflow_dispatch" ]]; then exit 1; fi', step)

    def legacy(self):
        item = replace(candidate(title="2025年11月20日開催「第10回 呼吸セミナー」のご案内"),
                       block_text="", extracted_fields={})
        s, reviewer = setup([item], ai=False)
        reviewer.run()
        return s, item

    def test_same_url_and_subject_recovers_existing_event_without_creating_one(self):
        s, item = self.legacy()
        restored = replace(item, block_text=item.title_hint, discovery_method="official_dated_link")
        selected, n = select_recoveries([restored], s.objects("Events"), s.objects("EventSources"))
        self.assertEqual(1, n)
        self.assertEqual([restored], selected)
        CandidateIngestor(s, "test").ingest(selected, existing_only=True)
        self.assertEqual(1, len(s.objects("Events")))

    def test_same_root_url_never_borrows_another_event(self):
        s, item = self.legacy()
        other = replace(item, title_hint="2025年11月20日開催「第11回 呼吸セミナー」のご案内", block_text="other")
        self.assertEqual([], select_recoveries([other], s.objects("Events"), s.objects("EventSources"))[0])

    def test_source_link_label_cannot_redefine_a_generic_catalogue_event(self):
        s, item = self.legacy()
        events, sources = s.objects("Events"), s.objects("EventSources")
        events[0]["title"] = "セミナー＆学習会への案内 他団体からのご案内"
        sources[0]["page_title"] = item.title_hint
        restored = replace(item, block_text=item.title_hint)
        self.assertEqual([], select_recoveries([restored], events, sources)[0])

    def test_matching_title_at_another_url_is_not_a_recovery(self):
        s, item = self.legacy()
        other = replace(item, detail_url="https://www.narace.jp/#other", block_text=item.title_hint)
        self.assertEqual([], select_recoveries([other], s.objects("Events"), s.objects("EventSources"))[0])

    def test_same_event_number_at_same_root_but_different_year_is_not_borrowed(self):
        s, item = self.legacy()
        other = replace(item,title_hint="2027年11月20日開催「第10回 呼吸セミナー」のご案内",block_text="new year")
        self.assertEqual([],select_recoveries([other],s.objects("Events"),s.objects("EventSources"))[0])

    def test_admin_override_is_protected(self):
        s, item = self.legacy()
        event_id = s.objects("Events")[0]["event_id"]
        restored = replace(item, block_text=item.title_hint)
        self.assertEqual([], select_recoveries([restored], s.objects("Events"), s.objects("EventSources"),
                                             [{"event_id":event_id,"active":True}])[0])

    def test_existing_only_ingestion_cannot_create_a_new_candidate(self):
        s, item = self.legacy()
        CandidateIngestor(s, "test").ingest([replace(item, detail_url="https://www.narace.jp/new")], existing_only=True)
        self.assertEqual(1, len(s.objects("Events")))

    def test_publication_date_is_not_the_second_explicit_event_date(self):
        value = "2026年06月22日：2027年05月08日-09日「第37回日本臨床工学会」開催のご案内"
        self.assertTrue(dated_link_schedule(value).startswith("2027年05月08日"))
        self.assertEqual("3月9日開催", dated_link_schedule("2024年2月1日：3月9日開催"))

    def test_recovery_never_ignores_an_operator_stop(self):
        s, item = self.legacy()
        h = s.tables["Sources"][0]
        next(r for r in s.tables["Sources"][1:] if r[0] == "src_nara")[h.index("enabled")] = False
        class Collector:
            def collect(self, *a, **k): raise AssertionError("disabled source must not be fetched")
        result = recover_source_snapshots(s,"test",["src_nara"],collector=Collector(),ensure_capacity=lambda r:None)
        self.assertEqual(0, result["written"])

    def test_recovery_dry_run_fetches_discovery_only_and_does_not_write(self):
        s, item = self.legacy()
        before = repr(s.tables)
        class Collector:
            def collect(self, config, adapter, **kwargs):
                assert kwargs == {"max_detail_pages":0}
                return SimpleNamespace(status=SourceRunStatus.SUCCESS,candidates=[replace(item,block_text=item.title_hint)])
        result = recover_source_snapshots(s,"test",["src_nara"],dry_run=True,collector=Collector(),ensure_capacity=lambda r:None)
        self.assertEqual(1, result["matched"])
        self.assertEqual(0, result["written"])
        self.assertEqual(before, repr(s.tables))

    def test_targeted_recovery_writes_input_but_never_calls_ai_or_creates_events(self):
        s, item = self.legacy()
        class Collector:
            def collect(self, config, adapter, **kwargs):
                return SimpleNamespace(status=SourceRunStatus.SUCCESS,candidates=[replace(item,block_text=item.title_hint,discovery_method="official_dated_link")])
        result = recover_source_snapshots(s,"test",["src_nara"],collector=Collector(),ensure_capacity=lambda r:None)
        self.assertEqual(1, result["written"])
        self.assertEqual(0, result["api_requests"])
        self.assertEqual(0, result["new_events"])
        self.assertEqual(1, len(s.objects("Events")))
        self.assertEqual(1, AutomaticReviewer(s,"test",now=NOW).run()["newly_archived"])

    def test_stop_during_fetch_is_rechecked_before_recovery_write(self):
        s, item = self.legacy()
        before = s.objects("Documents")[0]["sha256"]
        class Collector:
            def collect(self, config, adapter, **kwargs):
                h=s.tables["Sources"][0]
                next(r for r in s.tables["Sources"][1:] if r[0]=="src_nara")[h.index("enabled")]=False
                return SimpleNamespace(status=SourceRunStatus.SUCCESS,candidates=[replace(item,block_text=item.title_hint)])
        result = recover_source_snapshots(s,"test",["src_nara"],collector=Collector(),ensure_capacity=lambda r:None)
        self.assertEqual(0,result["written"])
        self.assertEqual(before,s.objects("Documents")[0]["sha256"])

    def test_relative_month_after_publication_year_does_not_become_event_year(self):
        s, item = self.legacy()
        new_item=replace(item,title_hint="2024年2月1日：3月9日開催「第10回 呼吸セミナー」のご案内",
                         block_text="2024年2月1日：3月9日開催「第10回 呼吸セミナー」のご案内",
                         discovery_method="official_dated_link")
        CandidateIngestor(s,"test").ingest([new_item],existing_only=True)
        self.assertEqual(1,AutomaticReviewer(s,"test",now=NOW).run()["processing"])
