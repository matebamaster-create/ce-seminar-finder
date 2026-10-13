# 中四国・関西の県別スクレイパー

調査・実装基準日: 2026年7月14日

## 結論

中四国9県と関西6府県を、1県1アダプターで追加しました。共通の安全取得、
重複排除、PDF処理は再利用し、イベントの発見方法だけを各公式サイトに
最適化しています。追加した15団体は初期状態では自動公開せず、すべて
`review_only`で管理画面の確認対象にします。

## 実装一覧

| 地域 | 都道府県 | 公式取得元 | 専用方式 |
|---|---|---|---|
| 中四国 | 鳥取 | [t-ce.org](https://t-ce.org/) | WordPressの主催記事・セミナーフィード |
| 中四国 | 島根 | [shimane-ce.jp](https://shimane-ce.jp/) | 独自CMSのセミナー一覧・お知らせ詳細 |
| 中四国 | 岡山 | [okacet.or.jp](https://www.okacet.or.jp/) | WordPress RSS・投稿ID |
| 中四国 | 広島 | [hiroshima-acet.jp](https://hiroshima-acet.jp/) | 独自CMSのセミナー一覧・お知らせ詳細 |
| 中四国 | 山口 | [yamaguchi-ces.medikiki-hp1.com](https://yamaguchi-ces.medikiki-hp1.com/) | Nuxtシェル・サイトマップ。本文なしは技術保留 |
| 中四国 | 徳島 | [tokushimace.com](https://www.tokushimace.com/) | 徳島カテゴリの独自PHP詳細・PDF |
| 中四国 | 香川 | [kagawa-rinkou.com](https://www.kagawa-rinkou.com/) | トップページ県内新着・公式PDF |
| 中四国 | 愛媛 | [ehimeces.or.jp](https://ehimeces.or.jp/) | WordPress RSS・archives記事 |
| 中四国 | 高知 | [kochi-ce.com](https://www.kochi-ce.com/news.html) | 静的news一覧・連番詳細ページ |
| 関西 | 滋賀 | [sacet.jp](https://www.sacet.jp/karipage/) | セミナー分類・WordPress記事 |
| 関西 | 京都 | [kcet.jp](https://kcet.jp/) | 現行WordPress RSS・投稿ID |
| 関西 | 大阪 | [osakace.com](https://osakace.com/archives/category/studys) | 勉強会・セミナーカテゴリ限定 |
| 関西 | 兵庫 | [hce.umin.jp](https://hce.umin.jp/seminars.html) | UMIN静的HTML・PDF、60秒間隔 |
| 関西 | 奈良 | [日本臨床工学技士会公式RSS](https://ja-ces.or.jp/category/gakkai/feed/) | 奈良県表記を必須にした公式フォールバック |
| 関西 | 和歌山 | [wce-rinkou.org](https://wce-rinkou.org/seminar.html) | 新着・セミナー静的一覧・公式PDF |

## 安全側の扱い

- 新規15団体は、管理者が明示的に有効化するまで外部取得しません。
- 有効化後も自動公開せず、最初は必ずReviewQueueへ送ります。
- 公式サイトごとに許可ホストと許可パスを限定します。
- 兵庫はUMIN配下のため、リクエスト間隔を60秒にしています。
- 山口は沖縄と同じMedikiki/Nuxt基盤です。初期HTMLに本文がない場合、
  `CLIENT_RENDER_REQUIRED`として管理画面へ表示します。
- 奈良は県独自の安定した公開一覧が確認できないため、日臨工の公式RSSで
  タイトルまたは本文に「奈良県」がある候補だけを採用します。

## スプレッドシート反映

シート初期化処理は、既存のSourcesを削除せずにカタログを同期します。
既存行は管理者が設定した`enabled`と取得履歴を保持し、URL・アダプター・
robots.txt等のカタログ列だけを更新します。新しい15団体は末尾へ追加します。

## 検証

- 全24ソースに専用アダプターが登録されていること
- 中四国・関西の代表URLからイベント候補を抽出できること
- 求人リンクをイベントとして採用しないこと
- 奈良の公式RSSから他県イベントを除外すること
- 山口の空Nuxt HTMLを技術保留にすること
- Sourcesの全24行が24列の管理スキーマに一致すること

上記を含む全88件の自動テストが成功しています。
