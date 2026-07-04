# 8. Phase 1 セットアップ

## Phase 1で実装したもの

- `src/ce_seminar_finder`: 共通データ型、最終値解決、公開データ生成
- `src/ce_seminar_finder/sheets`: 13シートの定義と初期化
- `fixtures/sample-events.json`: 管理者修正優先を確認するサンプル
- `site/data/events.json`: 公開用JSONのサンプル
- `tests`: 自動テスト
- `.github/workflows/test.yml`: 継続テスト
- `.github/workflows/initialize-sheet.yml`: 手動のシート初期化
- `outputs/phase1-20260704/CE_Seminar_Finder_Admin_Template.xlsx`: Google Sheets変換用の検証済み雛形

外部サイトの定期取得、AI API、公開サイトUIはまだ動かしません。

管理用Excel雛形は13タブすべてをレンダリングして目視確認済みです。Google Driveコネクタが利用できる環境では、このファイルを「ネイティブGoogle Sheets」形式でインポートします。

## 初期化される13シート

1. Events
2. ReviewQueue
3. Sources
4. EventSources
5. Documents
6. DocumentTextChunks
7. AutoFieldValues
8. FieldOverrides
9. DuplicateCandidates
10. ReviewActions
11. AutomationRules
12. FetchLogs
13. Settings

初期化処理は既存行を削除しません。SettingsとSourcesの初期値はA2が空の場合だけ書き込みます。Sourcesの9団体はすべて`enabled = FALSE`で作られるため、Phase 2開始前に外部取得が走ることはありません。

## Googleスプレッドシートの準備

1. 管理者のGoogleアカウントで空のスプレッドシートを作成します。
2. Google Cloud側でSheets APIを利用できるサービスアカウントを用意します。
3. サービスアカウントの`client_email`を、空のスプレッドシートへ編集者として共有します。
4. スプレッドシートURLの`/d/`と`/edit`の間にあるIDを控えます。
5. サービスアカウントJSONをGitHubへファイルとしてコミットしないでください。

## GitHub Actionsから初期化する場合

1. GitHubリポジトリのSecret `GOOGLE_SERVICE_ACCOUNT_JSON`へ、サービスアカウントJSONの内容全体を登録します。
2. Actionsの「Initialize Google Sheet」を開きます。
3. `spreadsheet_id`へ対象IDを入力して実行します。
4. 実行完了後、13シート、ヘッダー、プルダウン、色分け、Sources初期値を確認します。

ワークフローの権限はリポジトリ内容の読み取りだけです。Google側もSheets APIのスコープだけを要求します。

## ローカルから初期化する場合

仮想環境を作成し、Google連携を含めてインストールします。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[google]'
```

認証ファイルは`.gitignore`対象の名前でワークスペース外または安全な場所に置き、環境変数で指定します。

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/安全な場所/service-account.json"
python -m ce_seminar_finder.cli init-sheet --spreadsheet-id "スプレッドシートID"
```

## 外部依存なしのローカル検証

Google接続を行わず、標準ライブラリだけでテストできます。

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m ce_seminar_finder.cli plan-sheet
```

サンプル公開JSONの再生成:

```bash
PYTHONPATH=src python3 -m ce_seminar_finder.cli build-public \
  --input fixtures/sample-events.json \
  --output site/data/events.json \
  --generated-at 2026-07-04T12:00:00+09:00
```

## 安全設計

- 管理者修正値が存在するフィールドは、自動値より必ず優先されます。
- 公開状態が「公開」以外のイベントはJSONへ出ません。
- 重複統合元はJSONへ出ません。
- イベント名、主催者、形式、公式URL、開催日または配信期間が不足する公開行は、ビルドエラーになります。
- `javascript:`等の不正な公式URLは拒否します。
- admin_note、PDF全文、AI生データ、ReviewQueueは公開JSONの許可リストに含まれません。
- Sourcesは初期状態ですべて無効です。

## 管理者修正優先の仕組み

フィールド値は次の順で決定します。

1. 最新の有効なFieldOverrides
2. 採用済みAutoFieldValuesのうち最も高信頼な値
3. 安全な固定初期値
4. 空欄

自動抽出値が信頼度1.0でも、管理者修正値を上書きしません。

## 未接続のもの

次は認証情報または次Phaseの実装が必要です。

- 実Googleスプレッドシートへの初期化実行
- 各公式サイトへの取得
- PDF解析
- AI API
- ReviewQueueのGAS操作
- GitHub Pagesの画面

## Phase 2へ進む条件

- GitHubリポジトリの公開・非公開方針を決定
- 空のGoogleスプレッドシートを初期化
- 13シートの見た目を管理者が確認
- クローラー説明URLと連絡先は、実アクセス開始までに決定

「OK」でPhase 2へ進む場合、まず外部アクセスなしの保存HTMLを使って共通HTTP・候補抽出を実装し、その後、福岡から順に低頻度の実地検証へ移ります。
