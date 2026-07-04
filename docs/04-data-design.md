# 4. Googleスプレッドシート・データ設計

## 設計方針

- 管理者が日常的に見るのはEventsとReviewQueue
- 自動取得値と管理者修正値を物理的に分離
- 1イベントに複数の掲載元、文書、分類根拠を紐づける
- IDと日時は機械処理向けの安定形式で保持
- 表示名はSettingsのマスタを参照
- 行削除を原則禁止し、状態変更と履歴追記で運用

## シート一覧

| シート | 用途 | 日常編集 |
|---|---|---|
| Events | イベントの表示用最終値と管理状態 | あり |
| ReviewQueue | 要確認候補の作業一覧 | あり |
| Sources | 対象サイト、取得設定、停止スイッチ | 一部 |
| EventSources | イベントと複数掲載元URLの対応 | 原則なし |
| Documents | HTML・PDF等の取得文書メタデータ | 原則なし |
| DocumentTextChunks | PDF等の抽出テキスト断片 | なし |
| AutoFieldValues | 自動抽出値、信頼度、根拠 | なし |
| FieldOverrides | 管理者修正値 | GAS経由または一部 |
| DuplicateCandidates | 重複候補とスコア | あり |
| ReviewActions | 管理者判断履歴 | 追記のみ |
| AutomationRules | 明示承認済みの次回ルール | あり |
| FetchLogs | 取得・解析・AI・公開ログ | なし |
| Settings | 選択肢、閾値、表示順 | あり |

## Events

Eventsは管理者向けの「現在値」です。自動処理は直接手入力列を上書きせず、AutoFieldValuesとFieldOverridesから表示用最終値を再計算します。

### ID・状態

| 列 | 型・選択肢 | 説明 |
|---|---|---|
| event_id | `evt_`＋ULID | 永続ID |
| canonical_event_id | event_id | 統合先。通常は自身 |
| publication_status | 公開／非公開／確認待ち／アーカイブ | 公開状態 |
| review_status | 未確認／確認済み／要修正 | 確認状態 |
| review_label | あり／なし | 公開画面の要確認表示 |
| review_reason_codes | 複数コード | 機械判定用 |
| review_reason_display | 文字列 | 公開可能な短い説明 |
| duplicate_status | 重複なし／重複候補／統合済み | 重複状態 |
| data_quality_score | 0.00–1.00 | 総合品質 |
| auto_publish_eligible | TRUE/FALSE | 自動公開条件の結果 |
| archived_at | ISO 8601 | アーカイブ日時 |

### イベント内容

| 列 | 型・選択肢 | 説明 |
|---|---|---|
| title | 文字列 | 表示用イベント名 |
| summary | 短文 | 転載にならない要約 |
| event_type | セミナー／研修会／講習会／学会・大会／研究会／オンデマンド／その他 | イベント種別 |
| genres | 複数選択相当 | 初期8分類。中間表化可能 |
| detailed_tags | 複数文字列 | VA、ECMO等の将来タグ |
| organizer_name | 文字列 | 主催団体 |
| organizer_type | 技士会主催／関連団体主催／企業主催／企業共催／要確認 | 主催形態 |
| source_prefecture | マスタ | 掲載元の都道府県 |
| venue_prefecture | マスタ | 現地会場の都道府県 |
| venue_name | 文字列 | 会場 |
| venue_address | 文字列 | 必要な場合のみ |
| format | Web／オンデマンド／ハイブリッド／現地開催／要確認 | 開催形式 |
| has_on_demand | TRUE/FALSE/不明 | 後日配信の有無 |
| audience_conditions | 文字列 | 対象者・参加条件 |
| capacity_text | 文字列 | 定員 |
| credits_text | 文字列 | 単位・ポイント |

### 日時

| 列 | 型 | 説明 |
|---|---|---|
| event_start_at | ISO 8601 | ライブ・現地開始 |
| event_end_at | ISO 8601 | ライブ・現地終了 |
| event_date_precision | date／datetime／month／unknown | 精度 |
| stream_start_at | ISO 8601 | 配信開始 |
| stream_end_at | ISO 8601 | 配信終了 |
| stream_period_text | 文字列 | 原文補助 |
| application_start_at | ISO 8601 | 申込開始 |
| application_deadline_at | ISO 8601 | 申込締切 |
| application_deadline_text | 文字列 | 原文補助 |
| timezone | IANA | 初期値Asia/Tokyo |
| effective_end_at | ISO 8601 | 通常一覧から外す判定日 |

`effective_end_at`は、オンデマンド終了 > イベント終了 > イベント開始の順で採用します。終了時刻がない日付は23:59:59 JSTとして扱います。

### 料金

| 列 | 型 | 説明 |
|---|---|---|
| fee_category | 無料／有料／要確認 | 絞り込み用 |
| fee_text | 文字列 | 会員・非会員等の原文要約 |
| fee_verified | TRUE/FALSE | 管理者または明確な公式表記 |

### URL・由来

| 列 | 型 | 説明 |
|---|---|---|
| primary_official_url | URL | 主催者ページ優先 |
| application_url | URL | 取得できた場合のみ |
| primary_pdf_url | URL | 代表PDF |
| source_url_count | 数値 | EventSources件数 |
| pdf_count | 数値 | Documents内PDF件数 |
| pdf_keyword_hit | TRUE/FALSE | 検索時に動的に算出してもよい |
| last_auto_fetched_at | ISO 8601 | 最終自動取得 |
| last_admin_updated_at | ISO 8601 | 最終管理者更新 |
| last_verified_at | ISO 8601 | 最終確認日 |
| admin_note | 文字列 | 非公開 |

## ReviewQueue

Eventsの確認待ちを単純に複製するのではなく、作業単位を持ちます。

| 列 | 説明 |
|---|---|
| review_id | `rev_`＋ULID |
| event_id | 対象イベント |
| priority | 緊急／高／通常／低 |
| reason_codes | 要確認理由コード |
| suggested_action | 公開／要確認付き公開／修正／非公開／統合 |
| source_excerpt | 短い根拠。全文は出さない |
| source_urls | 主要URL |
| uncertain_fields | 不確実なフィールド一覧 |
| opened_at | キュー追加日時 |
| due_at | 開催・締切から算出 |
| assignee | 管理者 |
| decision | 未判断／公開／要確認付き公開／修正後公開／非公開／重複統合 |
| automation_choice | 自動公開／要確認付き公開／非公開／次回も確認 |
| decided_at | 判断日時 |
| decision_note | 判断理由 |

### 優先度

1. 申込締切まで72時間未満
2. 開催まで7日未満
3. 公開中イベントの情報変更・中止
4. 新規候補
5. 過去分・低信頼候補

## Sources

| 列 | 説明 |
|---|---|
| source_id | `src_`＋ULID |
| organization_name | 掲載団体 |
| prefecture | 都道府県 |
| base_url | 公式サイト |
| discovery_urls | RSS、サイトマップ、一覧URL |
| allowed_path_prefixes | 取得範囲 |
| adapter_type | wordpress／static_html／wix／nuxt_api等 |
| text_encoding | UTF-8／CP932／auto |
| enabled | サイト単位の緊急停止 |
| auto_publish_policy | allow／review_only／disabled |
| request_interval_seconds | 最小アクセス間隔 |
| max_requests_per_run | 1実行の上限 |
| user_agent | クローラー識別子 |
| contact_url | サイト側連絡先 |
| robots_url | robots.txt |
| robots_checked_at | 確認日時 |
| terms_url | 規約・ポリシー |
| terms_checked_at | 確認日時 |
| etag | 一覧入口の最終ETag |
| last_modified | 一覧入口の最終更新 |
| last_content_hash | 内容ハッシュ |
| last_success_at | 最終成功 |
| consecutive_failures | 連続失敗 |
| notes | サイト別注意 |

## EventSources

| 列 | 説明 |
|---|---|
| event_source_id | 永続ID |
| event_id | 統合イベント |
| source_id | 掲載元 |
| source_url | 掲載ページ |
| source_role | organizer_official／jace／prefecture／registration／other |
| discovered_at | 初回発見 |
| last_seen_at | 最終確認 |
| is_primary | 主リンクか |
| page_title | 取得時タイトル |
| content_hash | 本文ハッシュ |
| source_published_at | 掲載日 |
| http_status | 最終状態 |

## Documents

| 列 | 説明 |
|---|---|
| document_id | 永続ID |
| event_source_id | 元掲載 |
| document_type | html／pdf／image／external |
| url | 文書URL |
| final_url | 転送後URL |
| mime_type | Content-Type |
| byte_size | サイズ |
| sha256 | 再取得防止 |
| etag | 条件付き取得 |
| last_modified | 条件付き取得 |
| fetched_at | 取得日時 |
| extraction_method | html／pdftotext／ocr／none |
| extraction_status | success／partial／failed |
| page_count | PDFページ数 |
| text_length | 抽出文字数 |
| text_quality_score | 0–1 |
| error_code | 失敗理由 |

## DocumentTextChunks

| 列 | 説明 |
|---|---|
| document_id | Documents参照 |
| chunk_index | 0始まり |
| page_from | 開始ページ |
| page_to | 終了ページ |
| text | 40,000文字以下 |
| text_hash | 差分確認 |
| is_searchable | 検索対象か |

全文が極端に大きい場合はGoogle Driveの非公開テキストファイルへ置き、DocumentsにDrive file IDだけを保存する移行余地を残します。

## AutoFieldValues

| 列 | 説明 |
|---|---|
| value_id | 永続ID |
| event_id | 対象 |
| field_name | title等 |
| extracted_value_json | 値 |
| normalized_value_json | 正規化値 |
| confidence | 0–1 |
| extractor | rule／ai／pdf／admin_import |
| provider | OpenAI／Gemini等 |
| model | モデル識別子 |
| prompt_version | プロンプト版 |
| source_document_id | 根拠文書 |
| evidence_text | 25–300文字程度の根拠 |
| evidence_location | CSS selector／page番号等 |
| extracted_at | 抽出日時 |
| accepted | 採用状態 |

## FieldOverrides

| 列 | 説明 |
|---|---|
| override_id | 永続ID |
| event_id | 対象 |
| field_name | 修正対象 |
| override_value_json | 管理者値 |
| active | 現在有効か |
| reason | 修正理由 |
| updated_by | 管理者 |
| updated_at | 修正日時 |

自動処理はFieldOverridesの`active=TRUE`を絶対に上書きしません。

## DuplicateCandidates

| 列 | 説明 |
|---|---|
| duplicate_candidate_id | 永続ID |
| event_id_a / event_id_b | 比較対象 |
| total_score | 0–1 |
| title_score | タイトル類似度 |
| date_score | 日付一致 |
| organizer_score | 主催者一致 |
| url_score | 申込・PDF等の一致 |
| format_score | 形式一致 |
| ai_score | AI補助判定 |
| deterministic_anchor | URL完全一致等 |
| status | 未確認／別イベント／統合済み／保留 |
| canonical_event_id | 統合先 |
| reviewed_at | 確認日時 |

## ReviewActions

全判断を追記専用で残します。

| 列 | 説明 |
|---|---|
| action_id | 永続ID |
| review_id / event_id | 対象 |
| action | publish／publish_with_warning／edit／reject／merge |
| before_json | 変更前 |
| after_json | 変更後 |
| automation_choice | 次回方針 |
| actor | 実行者 |
| acted_at | 実行日時 |
| note | 理由 |

## AutomationRules

管理者が「次回から」と明示したものだけを登録します。

| 列 | 説明 |
|---|---|
| rule_id | 永続ID |
| enabled | 有効・無効 |
| scope | source／organizer／keyword／url_pattern／field |
| condition_json | 条件 |
| action | auto_publish／publish_with_warning／exclude／map_value |
| approved_from_action_id | 根拠となる判断 |
| approved_by | 承認者 |
| approved_at | 承認日時 |
| expires_at | 任意の失効日 |
| notes | 説明 |

## FetchLogs

| 列 | 説明 |
|---|---|
| run_id | Actions実行単位 |
| log_id | ログID |
| source_id | 対象 |
| stage | discover／fetch／parse／pdf／ai／dedupe／sheet／build／deploy |
| level | info／warning／error |
| started_at / finished_at | 時刻 |
| url | 対象URL |
| http_status | HTTP状態 |
| attempt | 試行回数 |
| duration_ms | 所要時間 |
| bytes | 取得量 |
| result_code | 機械判定コード |
| message | 秘密を含まない説明 |
| github_run_url | 実行履歴 |

## Settings

カテゴリごとに`setting_type`、`code`、`display_name`、`sort_order`、`enabled`を持ちます。

初期マスタ:

- genres: 血液浄化、呼吸、循環、医療機器管理、手術室、教育・研究、DX・IT、その他
- event_types: セミナー、研修会、講習会、学会・大会、研究会、オンデマンド、その他
- formats: Web、オンデマンド、ハイブリッド、現地開催、要確認
- fee_categories: 無料、有料、要確認
- publication_statuses: 公開、非公開、確認待ち、アーカイブ
- review_statuses: 未確認、確認済み、要修正
- duplicate_statuses: 重複なし、重複候補、統合済み
- organizer_types: 技士会主催、関連団体主催、企業主催、企業共催、要確認
- review_reason_codes

## 要確認理由コード

| コード | 意味 |
|---|---|
| DATE_UNKNOWN | 開催日不明 |
| DEADLINE_UNKNOWN | 申込締切不明 |
| FEE_UNKNOWN | 参加費不明 |
| CREDITS_UNCERTAIN | 単位情報が不確実 |
| PDF_PRIMARY | PDF由来情報が中心 |
| DUPLICATE_CANDIDATE | 重複候補あり |
| LOW_EVENT_CONFIDENCE | イベント性が低信頼 |
| ORGANIZER_UNKNOWN | 主催団体不明 |
| FORMAT_UNKNOWN | 開催形式が要確認 |
| OFFICIAL_URL_UNKNOWN | 公式詳細URL不明 |
| SOURCE_UNREACHABLE | 掲載元へ到達不能 |
| TEXT_QUALITY_LOW | PDF/OCR品質が低い |
| HIGH_IMPACT_FIELD_CHANGED | 料金等の重要項目が変更 |
| SOURCE_GAP | 対象サイトから直接取得できない |

## スプレッドシートUI

### Events

- 1行目固定、フィルターを有効化
- 左側に状態、イベント名、開催日、形式、ジャンル、締切、主催を配置
- 管理列と技術列は右側へ寄せ、列グループで折りたたむ
- 条件付き書式:
  - 公開: 淡い緑
  - 確認待ち: 淡い黄
  - 要修正・取得失敗: 淡い赤
  - アーカイブ: グレー
  - 重複候補: オレンジ
- URL列はリンク表示名を短くする
- データ検証はSettingsの範囲を参照
- `event_id`等の機械列は保護

### ReviewQueue

- 優先度、締切までの日数、理由、候補値、根拠URL、判断欄を左から並べる
- 「公開」「要確認付き公開」「非公開」「重複統合」はプルダウン
- GASメニューで選択行の判断を確定し、ReviewActionsへ追記
- 判断確定時にEvents、FieldOverrides、AutomationRulesをトランザクション相当で更新

## 公開用データ生成

公開条件は次のすべてです。

- `publication_status = 公開`
- `canonical_event_id = event_id`
- `primary_official_url`が存在
- 必須フィールドの表示用最終値が存在

公開JSONから除外する列:

- admin_note
- source excerptの長文
- PDF全文
- AIプロンプト・応答
- confidenceの内部詳細
- ReviewActions
- 管理者名・メール
- 非公開URL
