# CE Seminar Finder

九州・沖縄、中四国、近畿、東海・北陸30府県と日本臨床工学技士会が掲載する、セミナー・研修会等の横断検索サービスです。

2026年10月13日に過去の要件・会話・公開コードを再検証し、31団体の公開ページで実取得を確認しました。832件は歴史的な情報・重複を含む収集候補数で、公開可能なイベント件数ではありません。管理画面と公開サイトは既存構成を維持し、候補の増殖防止と管理者修正の保護を強化しています。

## 結論

初期版は次の構成を推奨します。

- 公開サイト: GitHub Pages上の静的サイト
- 日次収集、PDF解析、AI抽出、重複判定、静的サイト生成: GitHub Actions
- 管理画面兼データストア: 非公開のGoogleスプレッドシート
- 手動再取得と管理補助: Google Apps Script
- APIキー: GitHub Actions SecretsとGAS Script Properties
- 公開リポジトリに置くデータ: 管理者が公開許可した構造化情報のみ

この構成は、AI API以外の追加費用を原則ゼロに保ちつつ、Pythonによる文字コード処理、PDF解析、AI連携を安定して実行し、管理者はGoogleスプレッドシートで日常運用できる点を重視しています。

## 成果物

1. [要件要約と設計論点](docs/01-requirements-and-issues.md)
2. [対象サイト調査表](docs/02-site-research.md)
3. [技術構成比較](docs/03-architecture-comparison.md)
4. [Googleスプレッドシート・データ設計](docs/04-data-design.md)
5. [スクレイピング・AI抽出設計](docs/05-collection-ai-design.md)
6. [公開サイト設計](docs/06-public-site-design.md)
7. [実装フェーズ分解](docs/07-implementation-plan.md)
8. [Phase 1 セットアップ](docs/08-phase1-setup.md)
9. [Phase 2 非AI収集の実装結果](docs/09-phase2-collection.md)
10. [Phase 3 PDF・AI抽出基盤](docs/10-phase3-extraction.md)
11. [Phase 4 重複・ReviewQueue・管理者判断](docs/11-phase4-review.md)
12. [Phase 5 公開サイトMVP](docs/12-phase5-site.md)
13. [Phase 6 日次自動化・Pages配布](docs/13-phase6-operations.md)
14. [中四国・関西の県別スクレイパー](docs/14-chugoku-kansai-expansion.md)
15. [西日本再開設計・実取得結果](docs/15-restart-west-japan.md)

## 今回の採用前提

- 九州の調査基準日は2026年7月4日、中四国・関西は2026年7月14日です。
- 対象は九州・沖縄8県、中四国9県、近畿6府県、東海4県、北陸3県、日本臨床工学技士会の31団体です。
- 管理者は1名または少人数を想定し、Googleスプレッドシートを非公開で共有します。
- 公開サイトには公開承認済みの情報だけを書き出し、PDF全文、AI入力、管理者メモ、ReviewQueueは公開しません。
- 自動抽出値は参考情報とし、管理者修正値を常に優先します。
- 取得頻度は各サイト1日1回以下とし、robots.txtの個別指示を優先します。

## 実装状況

Phase 1〜6の実装が完了しています。外部アカウント設定後にPages配布と7日間の運用試験を開始できます。

- Pythonの共通データ型と管理者修正優先ロジック
- Googleスプレッドシート14シートの安全な初期化
- 31団体のSources初期値（新しいシートでは無効。本番では確認後に有効化）
- 公開許可済みデータだけを出力するJSON生成
- robots.txt、許可ホスト、許可パス、低速取得、条件付き取得
- 31団体のサイト別アダプター
- CP932、RSS、見出し＋表、イベント表への対応
- 1サイトの失敗で全体を止めない収集パイプライン
- JSONLおよびGoogle Sheetsへの候補・取得ログ保存
- PDF署名・MIME・20MB上限、ページ品質評価、40,000文字チャンク
- 低品質ページだけを対象にできる限定OCR境界
- AIプロバイダー差し替え、NoopProvider、入力ハッシュキャッシュ
- URL捏造と根拠のない日付・料金・単位を破棄する検証
- プロンプトインジェクションを引用データへ閉じ込める入力形式
- タイトル・日付・主催者・URL・PDFハッシュによる重複採点
- 決定的根拠なしでは自動統合候補にしない安全制約
- 締切・開催日・変更内容に基づくReviewQueue優先度
- 公開、要確認付き公開、修正、非公開、統合の監査付き判断
- 明示承認時だけ作るAutomationRules
- Google Sheets上の判断確定用GASメニュー
- トップ、一覧、詳細、アーカイブ、このサイトについて
- キーワード・ジャンル・形式・種別・料金・開催月・締切の検索
- PDF本文を公開しないn-gramハッシュ検索
- JavaScript無効でも読める静的HTMLと`noindex`
- 1日1回の日次収集と、空設定時の外部アクセスゼロ
- ローカルロックとGitHub Actions concurrencyによる二重実行防止
- 1サイトの失敗を隔離した実行サマリ
- Sheetsの終了イベント自動アーカイブと公開JSON出力
- GitHub Pagesへの条件付き配布
- GASから選択したSourceだけを手動取得

## 管理画面

`gas/Code.gs`と`gas/Index.html`を管理スプレッドシートに紐づく
Google Apps Scriptへ配置し、ウェブアプリとしてデプロイすると、
スプレッドシートを直接操作せずに次を行えます。

- 公開中・確認待ち・要確認件数の確認
- イベント内容と公開状態の編集
- 公開前のカード表示プレビュー
- ReviewQueueの公開・要確認付き公開・非公開判断
- 取得元サイトの状態確認と手動取得
- GitHub Pages公開更新の依頼
- 九州から全国へ拡張する地域ロードマップの確認

Script Propertiesには必要に応じて次を設定します。

- `SPREADSHEET_ID`: スタンドアロンGASの場合の管理シートID
- `ADMIN_EMAILS`: 管理画面を利用できるGoogleアカウント（カンマ区切り）
- `GITHUB_OWNER`
- `GITHUB_REPOSITORY`
- `GITHUB_TOKEN`
- `GITHUB_REF`（省略時は`main`）
- GitHub Actionsによるテストとシート初期化
- 101件の自動テスト
- 14シートを収録した検証済み管理用Excel雛形

沖縄・山口・石川は匿名のブラウザ描画に対応しました。2026年10月13日の公開セミナー枠は0件でした（会員限定情報は取得しません）。奈良は現行公式サイトの見出しと表を直接取得します。大分・京都・富山は公式HTTPの公開ページを使用し、HTTPS証明書検証は無効化しません。古い調査資料は当時の記録として保持し、現状は[再開設計](docs/15-restart-west-japan.md)を参照してください。

AIの実呼び出しはまだ開始していません。専用OpenAI APIキーの作成先は選択済みですが、保存先確認が承認されなかったため、キーは作成・保存していません。現在の抽出はルール式で、根拠の弱いものは管理画面の確認待ちに保存します。

## 日常運用

Sourcesの`enabled`を日次取得が読みます。管理画面から停止した県は次回から取得しません。候補はEvents・ReviewQueueへ安定IDで反映され、AutoFieldValuesに根拠を保存します。確認済み・公開済み・管理者編集済みの表示値は自動更新しません。管理画面の修正はFieldOverridesとReviewActionsへ記録します。

```sh
python -m pip install -e '.[google,pdf]'
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python scripts/audit_sources.py --region west
```

動的ページの検証にはNode.jsのPlaywrightを別途用意し、`NODE_PATH`から参照可能にして`--render-public-pages`を付けます。GitHub Actionsは必要なときに自動準備します。ダウンロード本文や候補全文は`var/`の非公開作業領域に置き、公開リポジトリや実行成果物へアップロードしません。
