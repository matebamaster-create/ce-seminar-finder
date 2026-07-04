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


class AdapterTest(unittest.TestCase):
    def test_all_nine_sources_have_adapters(self) -> None:
        configs = source_configs()
        self.assertEqual(9, len(configs))
        for config in configs:
            with self.subTest(source=config.source_id):
                self.assertIsNotNone(adapter_for_source(config.source_id))

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
