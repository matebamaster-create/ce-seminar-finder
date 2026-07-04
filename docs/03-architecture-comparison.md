# 3. 技術構成比較

## 評価軸

5点が最良です。費用は「追加費用が少ないほど高得点」、制限は「MVPの範囲で余裕があるほど高得点」としています。

| 案 | 追加費用 | 保守 | 管理者操作 | 収集安定性 | PDF・AI | 将来拡張 | 秘密管理 | 総評 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1. ムームーサーバー中心 | 2 | 2 | 3 | 3 | 3 | 3 | 3 | WordPress公開には向くが、クローラーと管理画面を同居させると保守負担が大きい |
| 2. GAS＋Sheets中心 | 5 | 4 | 5 | 2 | 2 | 2 | 4 | 小規模収集は容易だが、6分制限、PDF、文字コード、依存ライブラリが弱点 |
| 3. Pages＋Actions中心 | 5 | 4 | 2 | 5 | 5 | 4 | 5 | 技術処理は強いが、非技術者向けの管理・修正画面が不足 |
| 4. Pages公開＋GAS/Actions収集 | 5 | 4 | 4 | 4 | 4 | 4 | 5 | 良いが、データ管理先を明確にしないと二重管理になる |
| 5. ムームー公開＋GitHub処理 | 3 | 3 | 3 | 5 | 5 | 4 | 4 | 既存サーバーを活用できるが、デプロイと障害点が増える |
| 6. Pages＋Sheets＋GAS/Actions | 5 | 4 | 5 | 5 | 5 | 4 | 5 | **推奨。公開、処理、管理の責務が明確** |

## 6案の詳細

### 案1: ムームーレンタルサーバー中心

構成例はWordPress/PHP＋MySQL＋cronです。

長所:

- 独自ドメイン、WordPress、メールを一体管理しやすい
- 将来、ログインや問い合わせフォームをPHP側へ追加しやすい
- 既存契約が十分な機能を持つ場合は追加費用を抑えられる

短所:

- Python、PDF/OCR、ブラウザ自動化、AI SDKを安定運用できるかは契約仕様に依存
- WordPressプラグイン、PHP、DB、バックアップ、セキュリティ更新の保守が増える
- スクレイピング障害が公開サイトへ波及しやすい

ムームーサーバーの現行案内は月額1,430円、WordPress、自動バックアップ、600GB等を掲げています。ただし、ユーザーの既存「ムームーレンタルサーバー」が同一商品・仕様とは限らないため、採用判断には契約画面でPHP、SSH、cron、実行時間、外部通信の確認が必要です。

公式情報: [ムームーサーバー](https://muumuu-domain.com/hosting/muumuu-servers)

### 案2: GAS＋Googleスプレッドシート中心

長所:

- Sheetsを直接操作でき、管理者UIを最短で作れる
- 時間主導トリガーとカスタムメニューを実装しやすい
- Script Propertiesで秘密を管理できる

短所:

- 1実行6分、個人アカウントではトリガー合計90分/日等の制限がある
- PDF解析、OCR、Shift_JIS、HTMLパーサー、AI SDKの選択肢がPythonより少ない
- 長崎の60秒間隔を守りながら複数ページを取ると実行時間を消費する
- 全国展開時に分割実行・再開制御が複雑になる

GASは手動再取得、シートUI、軽い整形に限定し、重い処理はActionsへ寄せるのが安全です。

公式情報: [Apps Script quotas](https://developers.google.com/apps-script/guides/services/quotas)

### 案3: GitHub Pages＋GitHub Actions中心

長所:

- PythonでHTML、PDF、文字コード、AI処理を実装しやすい
- コードレビュー、テスト、実行履歴、再実行が標準で揃う
- 静的公開の攻撃面が小さい

短所:

- GitHub上のJSON/YAMLを管理者が直接編集する運用は難しい
- ReviewQueueの見やすい管理画面を別途作る必要がある
- 公開Pagesを無料利用するなら公開リポジトリが基本となる

GitHub Pagesには公開サイト1GB、月100GBのソフト帯域上限等がありますが、MVPの構造化イベントサイトには十分です。標準GitHub-hosted runnerは公開リポジトリで無料、非公開リポジトリのGitHub Freeは月2,000分です。

公式情報: [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)、[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

### 案4: Pages公開＋GASまたはActions収集

公開と収集を分離する考え方は適切です。ただし、管理データの正本をどこに置くかを決めないと、JSON、Sheets、GAS内データの三重管理になります。正本をSheetsと定めれば案6になります。

### 案5: ムームー公開＋GitHub処理

長所:

- 公開側でPHP、WordPress、将来の認証機能を使える
- Actions側で重い収集処理を実行できる

短所:

- Actionsからサーバーへの安全な配布設定が必要
- WordPressと静的生成物の責務が曖昧になりやすい
- MVP段階ではPagesより障害点と保守対象が多い

ユーザー登録や通知を実装する段階で、Pagesから既存サーバーへ公開面だけ移す候補として残します。

### 案6: GitHub Pages＋Googleスプレッドシート＋GAS/Actions

推奨構成です。

```text
対象公式サイト
    ↓ 1日1回、低頻度
GitHub Actions
  取得 → PDF解析 → ルール抽出 → AI抽出 → 重複判定
    ↓ Google Sheets API
非公開Googleスプレッドシート
  Events / ReviewQueue / Sources / Logs / Overrides
    ↓ 公開可データだけを読出し
GitHub Actions
  静的JSON・HTML生成 → GitHub Pages配布

管理者
  Sheetsで確認・修正
  GASメニューから手動再取得
```

## 推奨構成の具体方針

### リポジトリ

MVPでは1つの公開リポジトリを使用できます。

- 公開する: アプリコード、クローラーコード、テスト、公開承認済みJSON
- 公開しない: サービスアカウント鍵、AIキー、PDF全文、未公開候補、管理メモ、生HTML、ReviewQueue
- Secrets: `GOOGLE_SERVICE_ACCOUNT_JSON`、`AI_API_KEY`等

非公開リポジトリを希望する場合、Pages利用条件とActions無料枠を契約プランで再確認します。完全無料を優先するなら、コード公開に問題がない前提で公開リポジトリが単純です。

### データの正本

Googleスプレッドシートを運用上の正本とします。ただし履歴監査のため、各実行の入力ハッシュ、AIモデル、プロンプト版、変更差分を補助シートに追記します。

Google Sheetsは最大1,000万セル、1セル50,000文字という制約があるため、PDFテキストはチャンク化し、全国展開前にDB移行判定を行います。

公式情報: [Google Driveで保存できるファイル](https://support.google.com/drive/answer/37603)

### 公開方式

公開サイトはビルド時に次を生成します。

- `/index.html`
- `/events/index.html`
- `/events/{event_id}/index.html`
- `/archive/index.html`
- `/data/events.min.json`
- `/data/search-index.json`

ブラウザはGoogle Sheetsへ直接アクセスしません。これによりシートID、非公開列、APIキーの露出を避けます。

### 手動再取得

SheetsのGASカスタムメニューからGitHub Actionsの`workflow_dispatch`または`repository_dispatch`を呼びます。

- トークンはScript Propertiesに保存
- fine-grained tokenで対象リポジトリのActions実行権限だけを付与
- 二重実行防止のロックと最終実行時刻を表示
- GASが失敗した場合はGitHub Actions画面から手動実行可能

### 将来拡張

- 通知: Actionsからメール配信基盤等へ追加
- ユーザー登録: 認証とDBが必要になった時点で別バックエンドを導入
- 全国展開: Sourcesとサイトアダプターを追加し、Sheets容量・Actions実行時間を監視
- ムームー移行: 生成済み静的ファイルを配布するだけなら、公開面だけ比較的容易に移せる

## 採用しない構成

MVPでは、ブラウザから直接Google Sheetsを公開APIとして読む方式は採用しません。公開範囲の誤設定、列追加による漏えい、クォータ、表示速度、CORSへの依存が大きいためです。

また、AI APIをブラウザから直接呼ぶ方式も採用しません。キー流出と入力改ざんを防ぐため、必ずActionsまたはGASのサーバー側から呼びます。
