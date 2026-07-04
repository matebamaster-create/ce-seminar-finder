# 13. Phase 6 日次自動化・Pages配布

実装日: 2026年7月4日

## 状態

日次収集、二重実行防止、実行サマリ、Sheetsへの候補保存、終了イベントのアーカイブ、公開JSON生成、GitHub Pages配布、GASからの手動取得依頼を実装しました。

外部リポジトリ・Googleサービスアカウント・非公開Sheetsは未接続のため、実際のPages配布と連続7日運用はまだ開始していません。ローカルでは全9ソース無効のドライランを行い、外部アクセス0件、候補0件、正常終了、ロック解放を確認しました。

## 日次ワークフロー

`.github/workflows/daily.yml`は毎日06:17 JSTに起動します。GitHub Actionsの混雑を避けるため、時刻を正時からずらしています。

処理:

1. Python、Google Sheets、PDF依存関係を準備
2. 明示的に有効化されたsource_idだけ収集
3. 候補をEventSources、ログをFetchLogsへ追記
4. サマリをGitHub Actions画面へ表示
5. 終了した公開イベントをアーカイブ
6. SheetsのEvents最終値から公開JSONを生成
7. 静的サイトを再生成
8. 非公開語の混入検査
9. GitHub Pagesへ配布

`CE_ENABLED_SOURCE_IDS`が空なら、9団体すべてを`disabled`として記録し、外部サイトへアクセスしません。

## 二重実行防止

二段構えです。

- GitHub Actions: `concurrency`を固定し、先行実行をキャンセルしない
- Python: 排他的なファイルロック

異常終了でロックだけ残った場合は6時間後に期限切れとして回復します。GASの管理操作はDocumentLockで保護します。

## 障害分離

1サイトの未処理例外は、そのsourceを`failed`として記録し、次のsourceを継続します。サマリには例外の種類だけを載せ、例外本文、APIキー、認証情報、レスポンス本文を含めません。

サマリ:

- success
- partial
- failed
- technical_hold
- disabled
- 候補件数
- source別警告件数

診断アーティファクトはサマリだけを14日保存します。候補本文、PDFチャンク、秘密情報はGitHubアーティファクトへ含めません。

## 自動アーカイブ

公開中イベントについて、次の順で終了判定日時を使います。

1. `effective_end_at`
2. `stream_end_at`
3. `event_end_at`
4. `event_start_at`

現在時刻より前なら、Eventsの`publication_status`を`アーカイブ`へ変更し、`archived_at`へ処理日時を記録します。終了日時が不明、日時形式が不正、タイムゾーンがない項目は自動変更しません。

## 公開データ

SheetsのEventsは管理者が見る最終値として読み込み、公開条件を再検査します。

- publication_statusが公開
- canonical_event_idがevent_idと一致
- 必須項目が存在
- 公式URLがHTTP/HTTPS
- 開催または配信日時が存在

配布前に`admin_note`、`auto_values`、`FieldOverrides`、`ReviewQueue`が生成物に含まれないことを検査します。

## GitHub設定

### Secrets

Repository SettingsのActions secretsへ設定:

- `CE_SPREADSHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

サービスアカウントには対象スプレッドシートだけを編集者として共有します。Google Drive全体へのアクセスは不要です。

### Variables

Repository Variables:

- `CE_ENABLED_SOURCE_IDS`

例:

```text
src_fukuoka,src_saga,src_nagasaki
```

最初は1サイトだけで開始し、FetchLogsを確認してから段階的に追加します。沖縄は`CLIENT_RENDER_REQUIRED`が解消するまで含めません。

### Pages

Repository SettingsのPagesでSourceを`GitHub Actions`にします。ワークフローはSheets接続情報があり、定期実行または`publish=true`の手動実行時だけPagesアーティファクトを作ります。

接続情報がなければ公開処理を正常にスキップし、サンプルデータを誤配布しません。

## GAS手動取得

管理スプレッドシートのSourcesで行を選び、`CE Seminar Finder` → `選択したSourceを手動取得`を実行すると、そのsource_idだけで`daily.yml`を起動します。公開更新は行わず、候補とFetchLogsの確認に使います。

GASのScript Properties:

- `GITHUB_OWNER`
- `GITHUB_REPOSITORY`
- `GITHUB_TOKEN`
- `GITHUB_REF`（省略時`main`）

`GITHUB_TOKEN`は対象リポジトリのActions workflowを実行できる最小権限のFine-grained tokenを使用します。値はシートやコードへ記載しません。

## 手動ドライラン

外部アクセスなし:

```bash
python3 -m ce_seminar_finder.cli daily-run \
  --enabled-sources "" \
  --summary var/daily/summary.json \
  --candidates var/daily/candidates.json \
  --markdown-summary var/daily/summary.md
```

1ソースだけ:

```bash
python3 -m ce_seminar_finder.cli daily-run \
  --enabled-sources src_fukuoka \
  --spreadsheet-id "$CE_SPREADSHEET_ID" \
  --summary var/daily/summary.json \
  --candidates var/daily/candidates.json
```

## 検証結果

全76件のテストが成功しています。Phase 6では次を追加確認しました。

- 二重ロックの拒否と期限切れ回復
- 有効sourceが空なら外部取得0件
- 1source失敗後も次sourceを継続
- サマリ、候補JSON、Markdown出力
- 例外本文をサマリへ出さない
- Sheetsの実行行番号保持
- Events最終値からEventRecord生成
- 改行区切りジャンルと真偽値の変換
- 終了した公開イベントだけのアーカイブ
- タイムゾーンなし基準日時の拒否
- GASとJavaScript構文
- GitHub Actions YAML構文

## 7日運用の合格条件

外部設定後、次を7日連続で記録します。

- 日次ワークフロー完了
- source別の成功・部分成功・失敗
- UMINの60秒間隔
- 無変更ページの再解析スキップ
- 候補数とReviewQueue増加量
- Pages更新時刻
- 手動取得の成功
- 秘密・管理列の非公開

7日間に重大な誤公開がなく、失敗sourceが管理画面で把握できればPhase 7の限定共有へ移ります。
