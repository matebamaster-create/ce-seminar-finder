from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ce_seminar_finder.enums import (
    DuplicateStatus,
    EventFormat,
    EventType,
    FeeCategory,
    Genre,
    OrganizerType,
    PublicationStatus,
    ReviewLabel,
    ReviewReason,
    ReviewStatus,
)


@dataclass(frozen=True, slots=True)
class DropdownSpec:
    column: str
    setting_type: str
    strict: bool = True


@dataclass(frozen=True, slots=True)
class SheetSpec:
    title: str
    headers: tuple[str, ...]
    dropdowns: tuple[DropdownSpec, ...] = ()
    filter_enabled: bool = False
    frozen_columns: int = 0
    protected_columns: tuple[str, ...] = ()
    column_widths: dict[str, int] = field(default_factory=dict)


EVENTS_HEADERS = (
    "event_id",
    "canonical_event_id",
    "publication_status",
    "review_status",
    "review_label",
    "review_reason_codes",
    "review_reason_display",
    "duplicate_status",
    "data_quality_score",
    "auto_publish_eligible",
    "title",
    "summary",
    "event_type",
    "genres",
    "detailed_tags",
    "organizer_name",
    "organizer_type",
    "source_prefecture",
    "venue_prefecture",
    "venue_name",
    "venue_address",
    "format",
    "has_on_demand",
    "audience_conditions",
    "capacity_text",
    "credits_text",
    "event_start_at",
    "event_end_at",
    "event_date_precision",
    "stream_start_at",
    "stream_end_at",
    "stream_period_text",
    "application_start_at",
    "application_deadline_at",
    "application_deadline_text",
    "timezone",
    "effective_end_at",
    "fee_category",
    "fee_text",
    "fee_verified",
    "primary_official_url",
    "application_url",
    "primary_pdf_url",
    "source_url_count",
    "pdf_count",
    "pdf_keyword_hit",
    "last_auto_fetched_at",
    "last_admin_updated_at",
    "last_verified_at",
    "admin_note",
)

REVIEW_QUEUE_HEADERS = (
    "review_id",
    "event_id",
    "priority",
    "reason_codes",
    "suggested_action",
    "source_excerpt",
    "source_urls",
    "uncertain_fields",
    "opened_at",
    "due_at",
    "assignee",
    "decision",
    "automation_choice",
    "decided_at",
    "decision_note",
)

SOURCES_HEADERS = (
    "source_id",
    "organization_name",
    "prefecture",
    "base_url",
    "discovery_urls",
    "allowed_path_prefixes",
    "adapter_type",
    "text_encoding",
    "enabled",
    "auto_publish_policy",
    "request_interval_seconds",
    "max_requests_per_run",
    "user_agent",
    "contact_url",
    "robots_url",
    "robots_checked_at",
    "terms_url",
    "terms_checked_at",
    "etag",
    "last_modified",
    "last_content_hash",
    "last_success_at",
    "consecutive_failures",
    "notes",
)

EVENT_SOURCES_HEADERS = (
    "event_source_id",
    "event_id",
    "source_id",
    "source_url",
    "source_role",
    "discovered_at",
    "last_seen_at",
    "is_primary",
    "page_title",
    "content_hash",
    "source_published_at",
    "http_status",
)

DOCUMENTS_HEADERS = (
    "document_id",
    "event_source_id",
    "document_type",
    "url",
    "final_url",
    "mime_type",
    "byte_size",
    "sha256",
    "etag",
    "last_modified",
    "fetched_at",
    "extraction_method",
    "extraction_status",
    "page_count",
    "text_length",
    "text_quality_score",
    "error_code",
)

DOCUMENT_TEXT_HEADERS = (
    "document_id",
    "chunk_index",
    "page_from",
    "page_to",
    "text",
    "text_hash",
    "is_searchable",
)

AUTO_FIELD_HEADERS = (
    "value_id",
    "event_id",
    "field_name",
    "extracted_value_json",
    "normalized_value_json",
    "confidence",
    "extractor",
    "provider",
    "model",
    "prompt_version",
    "source_document_id",
    "evidence_text",
    "evidence_location",
    "extracted_at",
    "accepted",
)

FIELD_OVERRIDE_HEADERS = (
    "override_id",
    "event_id",
    "field_name",
    "override_value_json",
    "active",
    "reason",
    "updated_by",
    "updated_at",
)

DUPLICATE_HEADERS = (
    "duplicate_candidate_id",
    "event_id_a",
    "event_id_b",
    "total_score",
    "title_score",
    "date_score",
    "organizer_score",
    "url_score",
    "format_score",
    "ai_score",
    "deterministic_anchor",
    "status",
    "canonical_event_id",
    "reviewed_at",
)

REVIEW_ACTION_HEADERS = (
    "action_id",
    "review_id",
    "event_id",
    "action",
    "before_json",
    "after_json",
    "automation_choice",
    "actor",
    "acted_at",
    "note",
)

AUTOMATION_RULE_HEADERS = (
    "rule_id",
    "enabled",
    "scope",
    "condition_json",
    "action",
    "approved_from_action_id",
    "approved_by",
    "approved_at",
    "expires_at",
    "notes",
)

FETCH_LOG_HEADERS = (
    "run_id",
    "log_id",
    "source_id",
    "stage",
    "level",
    "started_at",
    "finished_at",
    "url",
    "http_status",
    "attempt",
    "duration_ms",
    "bytes",
    "result_code",
    "message",
    "github_run_url",
)

SETTINGS_HEADERS = (
    "setting_type",
    "code",
    "display_name",
    "sort_order",
    "enabled",
)

SOURCE_ROWS = (
    (
        "src_fukuoka",
        "一般社団法人福岡県臨床工学技士会",
        "福岡県",
        "https://hp.fcet.or.jp/",
        "https://hp.fcet.or.jp/event/feed/\nhttps://hp.fcet.or.jp/event/",
        "/event/\n/news/",
        "wordpress",
        "auto",
        False,
        "review_only",
        10,
        30,
        "",
        "",
        "https://hp.fcet.or.jp/robots.txt",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "Phase 2検証完了まで無効",
    ),
    (
        "src_saga",
        "一般社団法人佐賀県臨床工学技士会",
        "佐賀県",
        "https://sagacet.web.fc2.com/",
        "https://sagacet.web.fc2.com/event_society.html\nhttps://sagacet.web.fc2.com/event_seminar.html",
        "/",
        "static_html",
        "auto",
        False,
        "review_only",
        10,
        30,
        "",
        "",
        "",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "FC2静的HTML。Phase 2検証完了まで無効",
    ),
    (
        "src_nagasaki",
        "一般社団法人長崎県臨床工学技士会",
        "長崎県",
        "https://plaza.umin.ac.jp/~ncet/",
        "https://plaza.umin.ac.jp/~ncet/event.html\nhttps://plaza.umin.ac.jp/~ncet/kanren.html",
        "/~ncet/",
        "static_html",
        "auto",
        False,
        "review_only",
        60,
        20,
        "",
        "",
        "https://plaza.umin.ac.jp/robots.txt",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "UMINのCrawl-delay 60秒を厳守。Phase 2検証完了まで無効",
    ),
    (
        "src_kumamoto",
        "一般社団法人熊本県臨床工学技士会",
        "熊本県",
        "http://kumamoto-acet.jp/",
        "http://kumamoto-acet.jp/news.html\nhttp://www.kumamoto-acet.jp/system/event_list.php?ct=24",
        "/news.html\n/system/",
        "static_html",
        "CP932",
        False,
        "review_only",
        10,
        30,
        "",
        "",
        "",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "HTTP・Shift_JIS。初期は必ずReviewQueue",
    ),
    (
        "src_oita",
        "公益社団法人大分県臨床工学技士会",
        "大分県",
        "https://oacet.or.jp/",
        "https://oacet.or.jp/event/",
        "/event/\n/info/",
        "static_html",
        "auto",
        False,
        "review_only",
        10,
        30,
        "",
        "",
        "",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "独自CMS。Phase 2検証完了まで無効",
    ),
    (
        "src_miyazaki",
        "一般社団法人宮崎県臨床工学技士会",
        "宮崎県",
        "https://www.miyazakice.com/",
        "https://www.miyazakice.com/blog-feed.xml\nhttps://www.miyazakice.com/sitemap.xml",
        "/",
        "wix",
        "auto",
        False,
        "review_only",
        10,
        30,
        "",
        "",
        "https://www.miyazakice.com/robots.txt",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "旧miyazaki-ce.comは取得禁止。Phase 2検証完了まで無効",
    ),
    (
        "src_kagoshima",
        "公益社団法人鹿児島県臨床工学技士会",
        "鹿児島県",
        "https://www.karinkou.jp/",
        "https://www.karinkou.jp/?feed=rss2&post_type=news\nhttps://www.karinkou.jp/?post_type=news",
        "/",
        "wordpress",
        "auto",
        False,
        "review_only",
        10,
        30,
        "",
        "",
        "",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "カスタム投稿news。Phase 2検証完了まで無効",
    ),
    (
        "src_okinawa",
        "一般社団法人沖縄県臨床工学技士会",
        "沖縄県",
        "https://okinawa-ces.medikiki-hp1.com/",
        "https://okinawa-ces.medikiki-hp1.com/seminars\nhttps://okinawa-ces.medikiki-hp1.com/seminars-history",
        "/seminars\n/seminars-history\n/notice",
        "nuxt_api",
        "auto",
        False,
        "review_only",
        10,
        20,
        "",
        "",
        "",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "動的APIとサイトマップ不整合をPhase 2で確認",
    ),
    (
        "src_jace",
        "公益社団法人日本臨床工学技士会",
        "全国",
        "https://ja-ces.or.jp/",
        "https://ja-ces.or.jp/category/gakkai/feed/\nhttps://ja-ces.or.jp/category/koushuukai/feed/\nhttps://ja-ces.or.jp/seminar-info-list/",
        "/gakkai/\n/category/gakkai/\n/category/koushuukai/\n/jsc/seminar/",
        "wordpress",
        "auto",
        False,
        "review_only",
        10,
        40,
        "",
        "",
        "https://ja-ces.or.jp/robots.txt",
        "2026-07-04T00:00:00+09:00",
        "",
        "",
        "",
        "",
        "",
        "",
        0,
        "全国情報のため重複確認を必須化。Phase 2検証完了まで無効",
    ),
)


SHEET_SPECS = (
    SheetSpec(
        "Events",
        EVENTS_HEADERS,
        dropdowns=(
            DropdownSpec("publication_status", "publication_statuses"),
            DropdownSpec("review_status", "review_statuses"),
            DropdownSpec("review_label", "review_labels"),
            DropdownSpec("duplicate_status", "duplicate_statuses"),
            DropdownSpec("event_type", "event_types"),
            DropdownSpec("genres", "genres", strict=False),
            DropdownSpec("organizer_type", "organizer_types"),
            DropdownSpec("format", "formats"),
            DropdownSpec("fee_category", "fee_categories"),
        ),
        filter_enabled=True,
        frozen_columns=3,
        protected_columns=("event_id", "canonical_event_id"),
        column_widths={"title": 320, "summary": 320, "admin_note": 280},
    ),
    SheetSpec(
        "ReviewQueue",
        REVIEW_QUEUE_HEADERS,
        dropdowns=(
            DropdownSpec("priority", "review_priorities"),
            DropdownSpec("decision", "review_decisions"),
            DropdownSpec("automation_choice", "automation_choices"),
        ),
        filter_enabled=True,
        frozen_columns=3,
        protected_columns=("review_id", "event_id"),
        column_widths={
            "source_excerpt": 360,
            "source_urls": 320,
            "decision_note": 300,
        },
    ),
    SheetSpec(
        "Sources",
        SOURCES_HEADERS,
        dropdowns=(
            DropdownSpec("adapter_type", "adapter_types"),
            DropdownSpec("text_encoding", "text_encodings"),
            DropdownSpec("auto_publish_policy", "auto_publish_policies"),
        ),
        filter_enabled=True,
        frozen_columns=2,
        protected_columns=("source_id",),
        column_widths={"base_url": 260, "discovery_urls": 360, "notes": 320},
    ),
    SheetSpec("EventSources", EVENT_SOURCES_HEADERS, filter_enabled=True),
    SheetSpec("Documents", DOCUMENTS_HEADERS, filter_enabled=True),
    SheetSpec(
        "DocumentTextChunks",
        DOCUMENT_TEXT_HEADERS,
        column_widths={"text": 500},
    ),
    SheetSpec("AutoFieldValues", AUTO_FIELD_HEADERS, filter_enabled=True),
    SheetSpec("FieldOverrides", FIELD_OVERRIDE_HEADERS, filter_enabled=True),
    SheetSpec(
        "DuplicateCandidates",
        DUPLICATE_HEADERS,
        dropdowns=(DropdownSpec("status", "duplicate_review_statuses"),),
        filter_enabled=True,
    ),
    SheetSpec("ReviewActions", REVIEW_ACTION_HEADERS, filter_enabled=True),
    SheetSpec("AutomationRules", AUTOMATION_RULE_HEADERS, filter_enabled=True),
    SheetSpec("FetchLogs", FETCH_LOG_HEADERS, filter_enabled=True),
    SheetSpec("Settings", SETTINGS_HEADERS, filter_enabled=True, frozen_columns=1),
)


def _rows(
    setting_type: str,
    values: Iterable[str],
) -> list[tuple[str, str, str, int, bool]]:
    return [
        (setting_type, value, value, index, True)
        for index, value in enumerate(values, start=1)
    ]


SETTINGS_ROWS = tuple(
    _rows("publication_statuses", PublicationStatus)
    + _rows("review_statuses", ReviewStatus)
    + _rows("review_labels", ReviewLabel)
    + _rows("duplicate_statuses", DuplicateStatus)
    + _rows("event_types", EventType)
    + _rows("genres", Genre)
    + _rows("organizer_types", OrganizerType)
    + _rows("formats", EventFormat)
    + _rows("fee_categories", FeeCategory)
    + _rows("review_reason_codes", ReviewReason)
    + _rows("review_priorities", ("緊急", "高", "通常", "低"))
    + _rows(
        "review_decisions",
        ("未判断", "公開", "要確認付き公開", "修正後公開", "非公開", "重複統合"),
    )
    + _rows(
        "automation_choices",
        ("自動公開", "要確認付き公開", "非公開", "次回も確認"),
    )
    + _rows(
        "adapter_types",
        ("wordpress", "static_html", "wix", "nuxt_api", "browser", "disabled"),
    )
    + _rows("text_encodings", ("auto", "UTF-8", "CP932"))
    + _rows("auto_publish_policies", ("allow", "review_only", "disabled"))
    + _rows(
        "duplicate_review_statuses",
        ("未確認", "別イベント", "統合済み", "保留"),
    )
)


def settings_ranges() -> dict[str, str]:
    ranges: dict[str, tuple[int, int]] = {}
    for row_number, row in enumerate(SETTINGS_ROWS, start=2):
        setting_type = row[0]
        if setting_type not in ranges:
            ranges[setting_type] = (row_number, row_number)
        else:
            ranges[setting_type] = (ranges[setting_type][0], row_number)
    return {
        key: f"Settings!$C${start}:$C${end}"
        for key, (start, end) in ranges.items()
    }


def sheet_spec(title: str) -> SheetSpec:
    for spec in SHEET_SPECS:
        if spec.title == title:
            return spec
    raise KeyError(title)


def workbook_template_payload() -> dict[str, object]:
    ranges = settings_ranges()
    return {
        "sheets": [
            {
                "title": spec.title,
                "headers": list(spec.headers),
                "dropdowns": [
                    {
                        "column": item.column,
                        "settings_range": ranges[item.setting_type],
                        "strict": item.strict,
                    }
                    for item in spec.dropdowns
                ],
                "filter_enabled": spec.filter_enabled,
                "frozen_columns": spec.frozen_columns,
                "protected_columns": list(spec.protected_columns),
                "column_widths": spec.column_widths,
            }
            for spec in SHEET_SPECS
        ],
        "settings_rows": [list(row) for row in SETTINGS_ROWS],
        "source_rows": [list(row) for row in SOURCE_ROWS],
    }
