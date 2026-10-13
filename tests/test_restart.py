from __future__ import annotations
import re
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from ce_seminar_finder.adapters import adapter_for_source
from ce_seminar_finder.collection.cache import JsonFetchStateStore
from ce_seminar_finder.collection.fetcher import SafeHttpFetcher, RawHttpResponse
from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.collection.models import EventCandidate, FetchResponse
from ce_seminar_finder.collection.pipeline import SourceCollector
from ce_seminar_finder.collection.sources import source_config, source_configs_from_sheet
from ce_seminar_finder.extraction.rules import extract_rule_values
from ce_seminar_finder.regions import region_source_ids
from ce_seminar_finder.sheets.schema import SHEET_SPECS


class Execute:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class PublicationWorkflowTest(unittest.TestCase):
    def test_sample_preview_cannot_overwrite_production(self):
        workflow = Path(__file__).parents[1] / ".github/workflows/pages-preview.yml"
        text = workflow.read_text()
        self.assertNotIn("deploy-pages", text)
        self.assertNotIn("pages: write", text)
        self.assertNotIn("  push:", text)
        self.assertIn("actions/upload-artifact@", text)

    def test_frontend_changes_trigger_real_sheet_publication(self):
        workflow = Path(__file__).parents[1] / ".github/workflows/daily.yml"
        self.assertIn('"site/**"', workflow.read_text())

    def test_daily_ai_processes_all_with_pdf_and_does_not_upload_private_outputs(self):
        text = (Path(__file__).parents[1] / ".github/workflows/daily.yml").read_text()
        self.assertEqual(1, text.count("--max-calls 0 --include-pdf"))
        self.assertNotIn("--max-calls 5", text)
        self.assertIn("tesseract-ocr-jpn", text)
        self.assertIn("inputs.collect_all", text)
        self.assertIn("continue-on-error: true", text)
        uploads = text.split("name: Upload bounded run summaries")[1]
        self.assertIn("var/ai-summary.json", uploads)
        self.assertNotIn("ai-refined.json", uploads)
        self.assertNotIn("ai-cache.json", uploads)
        self.assertNotIn("candidates.json", uploads)


class FakeSheets:
    def __init__(self):
        self.tables = {spec.title: [list(spec.headers)] for spec in SHEET_SPECS}
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, **kwargs):
        sheet = kwargs["range"].split("!")[0].strip("'")
        return Execute({"values": self.tables[sheet]})
    def batchUpdate(self, **kwargs):
        for item in kwargs["body"]["data"]:
            sheet, cells = item["range"].split("!")
            sheet = sheet.strip("'")
            n = int(re.search(r"\d+", cells)[0])-1
            letters = re.match(r"[A-Z]+", cells)[0]
            offset = 0
            for letter in letters: offset = offset * 26 + ord(letter) - 64
            offset -= 1
            for index, values in enumerate(item["values"]):
                while len(self.tables[sheet]) <= n + index: self.tables[sheet].append([])
                target = self.tables[sheet][n + index]
                target.extend([""] * max(0, offset + len(values) - len(target)))
                target[offset:offset + len(values)] = values
        return Execute({})
    def objects(self, sheet):
        headers, *rows = self.tables[sheet]
        return [dict(zip(headers, row)) for row in rows]


def candidate():
    text = "開催日時 2026年11月20日 19:00~20:00\n開催方法 Zoom\n参加費 会員1,000円 非会員2,000円\n申込締切 2026年11月18日"
    return EventCandidate("src_nara", "https://www.narace.jp/", "https://www.narace.jp/#one", "呼吸セミナー",
        block_text=text, extracted_fields=extract_rule_values(text, title_hint="呼吸セミナー"))


class IngestionTest(unittest.TestCase):
    def test_new_candidate_reaches_review_and_repeated_runs_do_not_duplicate(self):
        service = FakeSheets()
        ingestor = CandidateIngestor(service, "test")
        ingestor.ingest([candidate()])
        counts = {name: len(service.tables[name]) for name in service.tables}
        ingestor.ingest([candidate()])
        self.assertEqual(counts, {name: len(service.tables[name]) for name in service.tables})
        event = service.objects("Events")[0]
        self.assertEqual("確認待ち", event["publication_status"])
        self.assertFalse(event["fee_verified"])
        self.assertEqual(event["event_id"], service.objects("ReviewQueue")[0]["event_id"])

    def test_admin_edited_title_and_fee_are_protected_and_changed_evidence_is_saved(self):
        service = FakeSheets()
        ingestor = CandidateIngestor(service, "test")
        ingestor.ingest([candidate()])
        row = service.tables["Events"][1]
        h = service.tables["Events"][0]
        row[h.index("title")] = "管理者が修正したタイトル"
        row[h.index("fee_text")] = "会員無料"
        row[h.index("publication_status")] = "公開"
        row[h.index("last_admin_updated_at")] = "2026-10-13T00:00:00+09:00"
        ingestor.ingest([candidate()])
        event = service.objects("Events")[0]
        self.assertEqual("管理者が修正したタイトル", event["title"])
        self.assertEqual("会員無料", event["fee_text"])
        self.assertEqual("公開", event["publication_status"])
        self.assertIn("HIGH_IMPACT_FIELD_CHANGED", service.objects("ReviewQueue")[0]["reason_codes"])
        self.assertTrue(any(a["field_name"] == "fee_text" for a in service.objects("AutoFieldValues")))

    def test_two_events_on_same_listing_page_stay_separate(self):
        service = FakeSheets()
        a = replace(candidate(), detail_url="https://www.narace.jp/", discovery_method="html_pdf")
        b = replace(a, title_hint="別の循環セミナー")
        CandidateIngestor(service, "test").ingest([a,b])
        self.assertEqual(2, len(service.objects("Events")))

    def test_sources_stop_setting_is_read_from_sheet(self):
        service = FakeSheets()
        headers = service.tables["Sources"][0]
        row = [""] * len(headers)
        row[headers.index("source_id")] = "src_nara"
        row[headers.index("enabled")] = True
        service.tables["Sources"].append(row)
        configs = source_configs_from_sheet(service, "test")
        self.assertEqual(["src_nara"], [s.source_id for s in configs if s.enabled])
        row[headers.index("enabled")] = False
        self.assertFalse(any(s.enabled for s in source_configs_from_sheet(service, "test")))


class RuleRegressionTest(unittest.TestCase):
    def test_oita_kaiki_and_long_credit_evidence_are_bounded(self):
        fields = extract_rule_values("会期 2026年10月20日 19:00 主催 大分県臨床工学技士会 詳細 取得単位 " + "認定8単位 " * 80)
        self.assertTrue(fields["event_start"].value.startswith("2026-10-20"))
        self.assertEqual("大分県臨床工学技士会", fields["organizer"].value)
        self.assertLessEqual(len(fields["credits_text"].evidence),300)

    def test_publication_date_is_not_event_date(self):
        fields = extract_rule_values("投稿日 2026年10月1日\n開催日時 2026年11月22日 10:00~12:30")
        self.assertTrue(fields["event_start"].value.startswith("2026-11-22"))
        self.assertNotIn("event_start", extract_rule_values("投稿日 2026年10月1日"))

    def test_empty_capacity_and_next_label_do_not_mix_into_fee(self):
        fields = extract_rule_values("参加費 会員1,000円 非会員2,000円 学生0円 参加定員 申込締切 2026年10月20日")
        self.assertNotIn("capacity_text", fields)
        self.assertNotIn("申込", fields["fee_text"].value)
        self.assertEqual("有料", fields["fee_category"].value)

    def test_zero_yen_is_free(self):
        self.assertEqual("無料", extract_rule_values("参加費 0円")["fee_category"].value)

    def test_on_demand_short_end_date_and_midnight_deadline(self):
        fields = extract_rule_values("配信期間 2026年11月20日~12月10日\n開催方法 オンデマンド\n締切 2026年11月15日 00:00")
        self.assertTrue(fields["stream_end"].value.startswith("2026-12-10"))
        self.assertEqual("2026-11-15T00:00:00+09:00", fields["application_deadline_at"].value)

    def test_plain_with_is_not_it_genre_and_organizer_precedes_label(self):
        fields = extract_rule_values("大阪府臨床工学技士会主催のセミナー", title_hint="循環with医産連携セミナー")
        self.assertNotIn("DX・IT", fields["genres"].value)
        self.assertEqual("大阪府臨床工学技士会", fields["organizer"].value)


class StructuredAdapterTest(unittest.TestCase):
    def document(self, html):
        return FetchResponse("https://www.narace.jp/", "https://www.narace.jp/", 200,
            {"content-type":"text/html"}, html.encode(), datetime.now(UTC), "test", encoding="utf-8")

    def test_nara_separate_tables_do_not_cross_contaminate(self):
        document = self.document('<h4 id="one">呼吸セミナー</h4><table><tr><td>開催日時</td><td>2026年11月1日 10:00</td></tr><tr><td>参加費</td><td>500円</td></tr></table><hr><h4 id="two">循環セミナー</h4><table><tr><td>開催日時</td><td>2026年12月1日 19:00</td></tr><tr><td>参加費</td><td>2,000円</td></tr></table>')
        items = adapter_for_source("src_nara").parse(source_config("src_nara"), document).candidates
        self.assertEqual(2, len(items))
        self.assertEqual("500円", items[0].extracted_fields["fee_text"].value)
        self.assertEqual("2,000円", items[1].extracted_fields["fee_text"].value)

    def test_cms_card_links_with_generic_text_keep_event_heading(self):
        document = self.document('<article><h5>人工呼吸器セミナー</h5><a href="/infodetail?iid=123">詳細を見る</a></article>')
        items = adapter_for_source("src_gifu").parse(source_config("src_gifu"), document).candidates
        self.assertEqual("人工呼吸器セミナー", items[0].title_hint)

    def test_west_boundary_has_thirty_prefectures_and_national(self):
        self.assertEqual(31, len(region_source_ids("west")))
        self.assertNotIn("src_nagano", region_source_ids("west"))


if __name__ == "__main__": unittest.main()
