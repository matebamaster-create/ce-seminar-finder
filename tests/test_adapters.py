from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from ce_seminar_finder.adapters import adapter_for_source
from ce_seminar_finder.collection.models import FetchResponse
from ce_seminar_finder.collection.sources import source_config, source_configs


FIXTURES = Path(__file__).parent / "fixtures" / "sites"


def document(
    filename: str,
    final_url: str,
    *,
    content_type: str = "text/html",
    encoding: str = "utf-8",
) -> FetchResponse:
    body = (FIXTURES / filename).read_bytes()
    return FetchResponse(
        url=final_url,
        final_url=final_url,
        status_code=200,
        headers={"content-type": content_type},
        body=body,
        fetched_at=datetime.now(UTC),
        content_hash="fixture",
        encoding=encoding,
    )


def text_document(
    text: str,
    final_url: str,
    *,
    content_type: str = "text/html",
) -> FetchResponse:
    return FetchResponse(
        url=final_url,
        final_url=final_url,
        status_code=200,
        headers={"content-type": content_type},
        body=text.encode("utf-8"),
        fetched_at=datetime.now(UTC),
        content_hash="inline-fixture",
        encoding="utf-8",
    )


class AdapterTest(unittest.TestCase):
    def test_all_thirty_one_sources_have_adapters(self) -> None:
        configs = source_configs()
        self.assertEqual(31, len(configs))
        for config in configs:
            with self.subTest(source=config.source_id):
                self.assertIsNotNone(adapter_for_source(config.source_id))

    def test_chugoku_shikoku_and_kansai_adapters_find_event_links(self) -> None:
        cases = [
            ("src_tottori", "https://t-ce.org/2026/07/respiratory-seminar/"),
            ("src_shimane", "https://shimane-ce.jp/seminardetail?sid=21"),
            ("src_okayama", "https://www.okacet.or.jp/?p=6753"),
            ("src_hiroshima", "https://hiroshima-acet.jp/seminardetail?sid=15"),
            ("src_tokushima", "https://www.tokushimace.com/topicsdetail.php?id=99"),
            ("src_kagawa", "https://www.kagawa-rinkou.com/meeting/detail.html"),
            ("src_ehime", "https://ehimeces.or.jp/archives/11614"),
            ("src_kochi", "https://www.kochi-ce.com/news_detail72.html"),
            ("src_shiga", "https://www.sacet.jp/respiratory-seminar/"),
            ("src_kyoto", "https://kcet.jp/?p=902"),
            ("src_osaka", "https://osakace.com/archives/42769"),
        ]
        for source_id, detail_url in cases:
            with self.subTest(source=source_id):
                html = (
                    '<a href="{}">第10回 呼吸療法セミナー</a>'
                    '<a href="/recruit.html">求人情報</a>'
                ).format(detail_url)
                result = adapter_for_source(source_id).parse(
                    source_config(source_id),
                    text_document(html, source_config(source_id).base_url),
                )
                self.assertEqual(1, len(result.candidates))
                candidate = result.candidates[0]
                if detail_url.endswith(".pdf"):
                    self.assertIn(detail_url, candidate.pdf_urls)
                else:
                    self.assertEqual(detail_url, candidate.detail_url)

    def test_hyogo_heading_and_pdf_do_not_mix_other_events_or_archives(self):
        html = '<h2>セミナー＆学習会への案内</h2><h6>呼吸セミナー</h6><p class="mb2">日時：2026年11月20日 19:00<a href="/pdf/a.pdf">PDF</a></p><h6>循環セミナー</h6><p class="mb2">日時：2026年12月20日 10:00<a href="/pdf/b.pdf">PDF</a></p><h2>過去のセミナー</h2><h6>古いセミナー</h6><p><a href="/pdf/old.pdf">PDF</a></p>'
        result = adapter_for_source("src_hyogo").parse(source_config("src_hyogo"), text_document(html, "https://hce.umin.jp/seminars.html"))
        self.assertEqual(2, len(result.candidates))
        self.assertEqual(("https://hce.umin.jp/pdf/a.pdf",), result.candidates[0].pdf_urls)
        self.assertTrue(result.candidates[1].extracted_fields["event_start"].value.startswith("2026-12-20"))

    def test_wakayama_dated_links_keep_one_pdf_and_original_date(self):
        html = '<li><a href="/pdf/a.pdf">2026年11月20日 呼吸セミナー開催のご案内</a></li><li><a href="/pdf/b.pdf">2026年12月20日 循環セミナー開催のご案内</a></li>'
        result = adapter_for_source("src_wakayama").parse(source_config("src_wakayama"), text_document(html, "https://wce-rinkou.org/seminar.html"))
        self.assertEqual(2, len(result.candidates))
        self.assertEqual(1, len(result.candidates[0].pdf_urls))
        self.assertTrue(result.candidates[0].extracted_fields["event_start"].value.startswith("2026-11-20"))

    def test_wakayama_external_and_image_event_links_keep_their_own_literal_text(self):
        html = '<li><a href="https://other.example/2027/">2026年06月22日：2027年05月08日-09日「第37回日本臨床工学会」開催のご案内</a><li><a href="/pdf/news/20251029.PNG">2025年11月29日開催「第18回滋賀県呼吸療法セミナー」のご案内</a></li></li>'
        from ce_seminar_finder.adapters.structured import WakayamaOfficialAdapter
        result = WakayamaOfficialAdapter(recovery_links=True).parse(source_config("src_wakayama"),text_document(html,"https://wce-rinkou.org/seminar.html"))
        self.assertEqual(2, len(result.candidates))
        self.assertTrue(result.candidates[0].extracted_fields["event_start"].value.startswith("2027-05-08"))
        self.assertNotIn("第18回", result.candidates[0].block_text)
        self.assertEqual("https://wce-rinkou.org/pdf/news/20251029.PNG",result.candidates[1].detail_url)
        self.assertEqual((), result.candidates[1].pdf_urls)

    def test_nara_filters_national_feed_by_prefecture(self) -> None:
        rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item><title>【奈良県】第23回人工呼吸器安全セミナー</title>
            <link>https://ja-ces.or.jp/gakkai/nara-respiratory/</link>
            <description>一般社団法人奈良県臨床工学技士会 主催</description></item>
          <item><title>【東京都】血液浄化セミナー</title>
            <link>https://ja-ces.or.jp/gakkai/tokyo-dialysis/</link>
            <description>東京都開催</description></item>
        </channel></rss>"""
        result = adapter_for_source("src_nara").parse(
            source_config("src_nara"),
            text_document(
                rss,
                "https://ja-ces.or.jp/category/gakkai/feed/",
                content_type="application/rss+xml",
            ),
        )
        self.assertEqual(1, len(result.candidates))
        self.assertIn("奈良県", result.candidates[0].title_hint)

    def test_yamaguchi_nuxt_shell_is_technical_hold(self) -> None:
        result = adapter_for_source("src_yamaguchi").parse(
            source_config("src_yamaguchi"),
            text_document(
                '<div id="__nuxt"><div>Loading...</div></div>',
                "https://yamaguchi-ces.medikiki-hp1.com/seminars",
            ),
        )
        self.assertEqual("CLIENT_RENDER_REQUIRED", result.technical_hold_reason)

    def test_html_adapters_find_expected_candidates(self) -> None:
        cases = [
            ("src_fukuoka", "fukuoka.html", "https://hp.fcet.or.jp/event/", 1),
            (
                "src_saga",
                "saga.html",
                "https://sagacet.web.fc2.com/event_seminar.html",
                2,
            ),
            (
                "src_nagasaki",
                "nagasaki.html",
                "https://plaza.umin.ac.jp/~ncet/event.html",
                2,
            ),
            (
                "src_kumamoto",
                "kumamoto.html",
                "http://kumamoto-acet.jp/news.html",
                2,
            ),
            ("src_oita", "oita.html", "https://oacet.or.jp/event/", 1),
            (
                "src_kagoshima",
                "kagoshima.html",
                "https://www.karinkou.jp/?post_type=news",
                1,
            ),
        ]
        for source_id, filename, url, minimum in cases:
            with self.subTest(source=source_id):
                config = source_config(source_id)
                encoding = "cp932" if source_id == "src_kumamoto" else "utf-8"
                item = document(filename, url, encoding=encoding)
                if source_id == "src_kumamoto":
                    item = FetchResponse(
                        **{
                            **{
                                field: getattr(item, field)
                                for field in item.__dataclass_fields__
                            },
                            "body": (FIXTURES / filename)
                            .read_text(encoding="utf-8")
                            .encode("cp932"),
                        }
                    )
                result = adapter_for_source(source_id).parse(config, item)
                self.assertGreaterEqual(len(result.candidates), minimum)
                self.assertTrue(
                    all(candidate.title_hint for candidate in result.candidates)
                )

    def test_rss_adapters_filter_non_events(self) -> None:
        cases = [
            (
                "src_miyazaki",
                "miyazaki.xml",
                "https://www.miyazakice.com/blog-feed.xml",
            ),
            (
                "src_jace",
                "jace.xml",
                "https://ja-ces.or.jp/category/gakkai/feed/",
            ),
        ]
        for source_id, filename, url in cases:
            with self.subTest(source=source_id):
                result = adapter_for_source(source_id).parse(
                    source_config(source_id),
                    document(
                        filename,
                        url,
                        content_type="application/rss+xml",
                    ),
                )
                self.assertEqual(1, len(result.candidates))

    def test_heading_blocks_capture_empty_pdf_links_and_skip_navigation(self) -> None:
        cases = [
            (
                "src_nagasaki",
                "nagasaki.html",
                "https://plaza.umin.ac.jp/~ncet/event.html",
                "utf-8",
                "第21回九州・沖縄臨床工学会",
            ),
            (
                "src_kumamoto",
                "kumamoto.html",
                "http://kumamoto-acet.jp/news.html",
                "cp932",
                "第3回JSPPCEセミナー 新生児編",
            ),
        ]
        for source_id, filename, url, encoding, expected_title in cases:
            with self.subTest(source=source_id):
                item = document(filename, url, encoding=encoding)
                if encoding == "cp932":
                    item = FetchResponse(
                        **{
                            **{
                                field: getattr(item, field)
                                for field in item.__dataclass_fields__
                            },
                            "body": (FIXTURES / filename)
                            .read_text(encoding="utf-8")
                            .encode("cp932"),
                        }
                    )
                result = adapter_for_source(source_id).parse(
                    source_config(source_id), item
                )
                self.assertEqual(expected_title, result.candidates[0].title_hint)
                self.assertEqual(1, len(result.candidates[0].pdf_urls))
                self.assertFalse(
                    any(
                        candidate.title_hint.startswith(("http://", "https://"))
                        for candidate in result.candidates
                    )
                )

    def test_oita_uses_name_cell_and_skips_non_event_table(self) -> None:
        result = adapter_for_source("src_oita").parse(
            source_config("src_oita"),
            document("oita.html", "https://oacet.or.jp/event/"),
        )
        self.assertEqual(1, len(result.candidates))
        self.assertEqual(
            "2026年度 大分県臨床工学技士会ECMOセミナー",
            result.candidates[0].title_hint,
        )
        self.assertEqual(1, len(result.candidates[0].pdf_urls))

    def test_okinawa_shell_is_technical_hold(self) -> None:
        result = adapter_for_source("src_okinawa").parse(
            source_config("src_okinawa"),
            document(
                "okinawa.html",
                "https://okinawa-ces.medikiki-hp1.com/seminars",
            ),
        )
        self.assertEqual("CLIENT_RENDER_REQUIRED", result.technical_hold_reason)

    def test_okinawa_sitemap_host_is_corrected(self) -> None:
        result = adapter_for_source("src_okinawa").parse(
            source_config("src_okinawa"),
            document(
                "okinawa-sitemap.xml",
                "https://okinawa-ces.medikiki-hp1.com/sitemap.xml",
                content_type="text/xml",
            ),
        )
        self.assertEqual(2, len(result.discovered_urls))
        self.assertTrue(
            all(
                "okinawa-ces.medikiki-hp1.com" in url
                for url in result.discovered_urls
            )
        )


if __name__ == "__main__":
    unittest.main()
