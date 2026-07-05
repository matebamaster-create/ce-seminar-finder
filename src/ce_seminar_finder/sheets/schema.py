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
    "archived_at",
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

FIELD_GUIDE_HEADERS = (
    "対象シート",
    "英語項目名",
    "日本語名",
    "説明",
    "入力例",
    "入力方法",
    "公開サイトへの影響",
)

SHEET_GUIDE_ROWS = (
    ("Events", "（シート概要）", "公開イベント管理", "HPに載せるイベントの最終データを管理します。", "", "主にここを確認", "「公開」の行だけHPへ反映"),
    ("ReviewQueue", "（シート概要）", "要確認リスト", "自動取得で判断できなかった項目を確認します。", "", "必要時のみ確認", "承認後にEventsへ反映"),
    ("Sources", "（シート概要）", "取得元サイト設定", "巡回する公式サイトと取得ルールを管理します。", "", "通常は編集不要", "直接は非公開"),
    ("EventSources", "（シート概要）", "発見したイベント候補", "公式サイトから見つけた候補URLを記録します。", "", "候補確認用", "直接は非公開"),
    ("Documents", "（シート概要）", "取得文書", "PDFなど取得した資料の情報を記録します。", "", "自動入力", "直接は非公開"),
    ("DocumentTextChunks", "（シート概要）", "資料テキスト", "PDFから抽出した検索用テキストを保存します。", "", "自動入力", "直接は非公開"),
    ("AutoFieldValues", "（シート概要）", "自動抽出値", "資料から自動抽出した項目と確信度を保存します。", "", "自動入力", "承認された値だけ利用"),
    ("FieldOverrides", "（シート概要）", "手動修正値", "自動抽出値より優先する管理者修正を保存します。", "", "必要時のみ入力", "Eventsの最終値に反映"),
    ("DuplicateCandidates", "（シート概要）", "重複候補", "同じイベントと思われる候補を比較します。", "", "必要時のみ確認", "重複公開を防止"),
    ("ReviewActions", "（シート概要）", "確認履歴", "承認・修正・非公開などの操作履歴です。", "", "自動記録", "直接は非公開"),
    ("AutomationRules", "（シート概要）", "自動化ルール", "承認済みの自動公開ルールを管理します。", "", "通常は編集不要", "公開判定に影響"),
    ("FetchLogs", "（シート概要）", "取得ログ", "サイト巡回の成功・失敗を記録します。", "", "自動記録", "直接は非公開"),
    ("Settings", "（シート概要）", "選択肢設定", "プルダウンに表示する選択肢を管理します。", "", "通常は編集不要", "入力候補に影響"),
)

EVENT_FIELD_GUIDE = (
    ("event_id", "イベントID", "イベントを一意に識別する内部IDです。", "evt_20260716_fukuoka_icu", "自動入力・変更しない", "URLと重複判定に使用"),
    ("canonical_event_id", "代表イベントID", "重複統合時の代表IDです。", "evt_20260716_fukuoka_icu", "自動入力・変更しない", "代表行だけ公開"),
    ("publication_status", "公開状態", "HPへの掲載状態です。", "公開", "プルダウン", "「公開」の行だけ掲載"),
    ("review_status", "確認状態", "管理者確認の進み具合です。", "確認済み", "プルダウン", "運用確認用"),
    ("review_label", "要確認表示", "HPに注意書きを表示するかを指定します。", "あり", "プルダウン", "ありの場合は注意書きを表示"),
    ("review_reason_codes", "要確認コード", "要確認になった機械判定用コードです。", "DEADLINE_UNKNOWN", "自動入力", "直接表示しない"),
    ("review_reason_display", "要確認の日本語説明", "利用者に見せる不足・注意事項です。", "申込締切は公式ページで要確認", "必要に応じて修正", "イベント詳細に表示"),
    ("duplicate_status", "重複状態", "他イベントとの重複判定です。", "重複なし", "プルダウン", "重複公開を防止"),
    ("data_quality_score", "データ品質点", "情報の揃い具合を0〜1で表します。", "0.85", "自動入力", "直接表示しない"),
    ("auto_publish_eligible", "自動公開可否", "自動公開条件を満たすかです。", "FALSE", "自動入力", "自動公開判定に使用"),
    ("title", "イベント名", "公式表記のイベント名称です。", "第22回 関西血液浄化研究会", "必須", "一覧・詳細に表示"),
    ("summary", "概要", "イベント内容の短い説明です。", "血液浄化に関するオンライン研究会。", "任意", "一覧・詳細に表示"),
    ("event_type", "イベント種別", "セミナー・研究会などの種類です。", "研究会", "プルダウン", "絞り込みに使用"),
    ("genres", "分野", "臨床工学の分野です。複数は改行で入力します。", "血液浄化", "プルダウン・複数可", "タグ・絞り込みに使用"),
    ("detailed_tags", "詳細タグ", "より細かなテーマです。複数は改行で入力します。", "透析\nバスキュラーアクセス", "任意", "タグとして表示"),
    ("organizer_name", "主催者名", "公式に記載された主催団体です。", "関西血液浄化研究会", "必須", "一覧・詳細に表示"),
    ("organizer_type", "主催者区分", "技士会・関連団体・企業などの区分です。", "関連団体主催", "プルダウン", "詳細に表示"),
    ("source_prefecture", "情報取得元の都道府県", "情報を掲載していた技士会等の地域です。", "福岡県", "自動入力", "運用確認用"),
    ("venue_prefecture", "開催地の都道府県", "現地会場がある場合の都道府県です。", "東京都", "任意", "絞り込み・詳細に表示"),
    ("venue_name", "会場名", "現地会場の名称です。", "大手町プレイス ホール&カンファレンス", "任意", "詳細に表示"),
    ("venue_address", "会場住所", "現地会場の住所です。", "東京都千代田区大手町", "任意", "現在は管理用"),
    ("format", "開催形式", "Web・現地・ハイブリッド等です。", "Web", "必須・プルダウン", "一覧・絞り込みに使用"),
    ("has_on_demand", "オンデマンド有無", "後日視聴期間があるかです。", "TRUE", "TRUE/FALSE", "詳細に表示"),
    ("audience_conditions", "対象者・参加条件", "受講対象や会員条件などです。", "医療従事者", "任意", "詳細に表示"),
    ("capacity_text", "定員", "定員の公式表記です。", "定員200名", "任意", "詳細に表示"),
    ("credits_text", "単位・点数", "取得できる単位や点数の公式表記です。", "認定制度 5点", "要確認", "詳細に表示"),
    ("event_start_at", "開催開始日時", "ライブ・現地開催の開始日時です。", "2026-07-25T15:00:00+09:00", "ISO形式", "日付表示・並び順に使用"),
    ("event_end_at", "開催終了日時", "ライブ・現地開催の終了日時です。", "2026-07-25T17:20:00+09:00", "ISO形式", "日付表示に使用"),
    ("event_date_precision", "日時の精度", "日付のみか時刻まで確定かを表します。", "datetime", "自動入力", "要確認判定に使用"),
    ("stream_start_at", "配信開始日時", "オンデマンド配信の開始日時です。", "2026-09-16T00:00:00+09:00", "ISO形式", "配信期間に表示"),
    ("stream_end_at", "配信終了日時", "オンデマンド配信の終了日時です。", "2026-11-16T23:59:00+09:00", "ISO形式", "配信期間・終了判定に使用"),
    ("stream_period_text", "配信期間の原文", "公式サイト記載の配信期間をそのまま残します。", "9月16日〜11月16日", "任意", "詳細に表示"),
    ("application_start_at", "申込開始日時", "受付開始日時です。", "2026-07-01T00:00:00+09:00", "ISO形式", "現在は管理用"),
    ("application_deadline_at", "申込締切日時", "受付終了日時です。", "2026-09-01T23:59:00+09:00", "ISO形式", "締切表示・並び替えに使用"),
    ("application_deadline_text", "申込締切の原文", "公式サイト記載の締切表現です。", "9月1日まで", "任意", "詳細に表示"),
    ("timezone", "タイムゾーン", "日時の基準地域です。通常はAsia/Tokyoです。", "Asia/Tokyo", "原則固定", "日時表示に使用"),
    ("effective_end_at", "実質終了日時", "アーカイブへ移す判定に使う最終日時です。", "2026-11-16T23:59:00+09:00", "自動入力", "終了後の自動移動に使用"),
    ("fee_category", "料金区分", "無料・有料・要確認の区分です。", "有料", "プルダウン", "一覧・詳細に表示"),
    ("fee_text", "参加費の原文", "会員区分などを含む公式の料金表記です。", "会員1,000円、非会員2,000円", "要確認", "詳細に表示"),
    ("fee_verified", "料金確認済み", "公式情報で料金を確認できたかです。", "TRUE", "TRUE/FALSE", "運用確認用"),
    ("primary_official_url", "公式詳細URL", "イベント詳細の一次情報URLです。", "https://example.jp/event/123", "必須", "公式サイトボタンに使用"),
    ("application_url", "申込URL", "参加申込ページのURLです。", "https://example.jp/apply", "任意", "申込ボタンに使用"),
    ("primary_pdf_url", "公式PDF URL", "案内チラシ等の公式PDFです。", "https://example.jp/event.pdf", "任意", "資料リンクに使用"),
    ("source_url_count", "参照URL数", "確認した情報源URLの数です。", "2", "自動入力", "直接表示しない"),
    ("pdf_count", "参照PDF数", "確認したPDFの数です。", "1", "自動入力", "直接表示しない"),
    ("pdf_keyword_hit", "PDF検索対象", "承認済みキーワード検索の対象かです。", "FALSE", "自動入力", "検索補助に使用"),
    ("last_auto_fetched_at", "最終自動取得日時", "自動巡回で最後に確認した日時です。", "2026-07-06T10:00:00+09:00", "自動入力", "直接表示しない"),
    ("last_admin_updated_at", "最終手動更新日時", "管理者が最後に修正した日時です。", "2026-07-06T10:00:00+09:00", "自動入力", "直接表示しない"),
    ("last_verified_at", "公式情報の最終確認日時", "公式ページを最後に確認した日時です。", "2026-07-06T10:00:00+09:00", "確認時に更新", "詳細に確認日を表示"),
    ("admin_note", "管理メモ", "公開しない内部メモです。", "公式ページとPDFを確認済み", "任意", "非公開"),
    ("archived_at", "アーカイブ日時", "公開終了として移動した日時です。", "2026-11-17T00:00:00+09:00", "自動入力", "非公開・履歴用"),
)

FIELD_GUIDE_ROWS = SHEET_GUIDE_ROWS + tuple(
    ("Events", field, japanese, description, example, input_method, impact)
    for field, japanese, description, example, input_method, impact in EVENT_FIELD_GUIDE
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
    SheetSpec(
        "項目ガイド",
        FIELD_GUIDE_HEADERS,
        filter_enabled=True,
        frozen_columns=3,
        column_widths={
            "対象シート": 130,
            "英語項目名": 190,
            "日本語名": 180,
            "説明": 340,
            "入力例": 280,
            "入力方法": 170,
            "公開サイトへの影響": 240,
        },
    ),
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
        "field_guide_rows": [list(row) for row in FIELD_GUIDE_ROWS],
    }
