# CE Seminar Finder

九州8県の臨床工学技士会と公益社団法人日本臨床工学技士会が掲載する、セミナー・研修会等の横断検索サービスに向けた初期調査・設計資料です。

初期調査と設計に加え、管理用スプレッドシート基盤と、公式9団体を対象にした安全な非AI収集基盤まで実装しています。

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

## 今回の採用前提

- 調査基準日は2026年7月4日です。
- 初期対象は九州8県と日本臨床工学技士会の9団体です。
- 管理者は1名または少人数を想定し、Googleスプレッドシートを非公開で共有します。
- 公開サイトには公開承認済みの情報だけを書き出し、PDF全文、AI入力、管理者メモ、ReviewQueueは公開しません。
- 自動抽出値は参考情報とし、管理者修正値を常に優先します。
- 取得頻度は各サイト1日1回以下とし、robots.txtの個別指示を優先します。

## 実装状況

Phase 1〜6の実装が完了しています。外部アカウント設定後にPages配布と7日間の運用試験を開始できます。

- Pythonの共通データ型と管理者修正優先ロジック
- Googleスプレッドシート13シートの安全な初期化
- 9団体のSources初期値（すべて無効状態）
- 公開許可済みデータだけを出力するJSON生成
- robots.txt、許可ホスト、許可パス、低速取得、条件付き取得
- 9団体のサイト別アダプター
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
- GitHub Actionsによるテストとシート初期化
- 76件の自動テスト
- 13シートを収録した検証済み管理用Excel雛形

沖縄はクライアント側描画が必要なため技術保留とし、他8団体は2026年7月4日の低頻度実サイト確認で候補抽出を確認しました。詳細は[Phase 2 非AI収集の実装結果](docs/09-phase2-collection.md)を参照してください。

AIの実呼び出しは、APIの選択・キー・月次予算が未設定のため開始していません。現在はNoopProviderで安全に`AI_PENDING`へ送り、設定後にプロバイダーだけを追加できる状態です。
