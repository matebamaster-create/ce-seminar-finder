# 2. 対象サイト調査表

調査日: 2026年7月4日  
対象: 九州8県臨床工学技士会、公益社団法人日本臨床工学技士会

## 調査方法

団体名の検索結果だけでは確定せず、次を突き合わせました。

- サイト自身の団体名、法人種別、活動内容、連絡先
- [日本臨床工学技士会の都道府県技士会役員一覧](https://ja-ces.or.jp/about-jaces/overview/prefectures/)
- 他県技士会の公式リンク集
- イベントPDF内の主催表記
- 現在のURLへの転送とページ内容

「あり」は調査時点で実際に取得できたもの、「なし」は代表的な標準パスで404等を確認したものです。サイト側の変更に備え、実装時にも再検査します。

## 一覧

| 団体 | 公式サイト | 主な収集入口 | PDF | RSS | サイトマップ | robots.txt | 実装優先度 |
|---|---|---|---|---|---|---|---|
| 福岡県 | [hp.fcet.or.jp](https://hp.fcet.or.jp/) | [セミナー情報](https://hp.fcet.or.jp/event/) | あり | あり | あり | あり | A |
| 佐賀県 | [sagacet.web.fc2.com](https://sagacet.web.fc2.com/) | [イベント](https://sagacet.web.fc2.com/event_society.html)、[外部セミナー](https://sagacet.web.fc2.com/event_seminar.html) | あり | 未検出 | 未検出 | 未検出 | A |
| 長崎県 | [plaza.umin.ac.jp/~ncet](https://plaza.umin.ac.jp/~ncet/) | [当会主催](https://plaza.umin.ac.jp/~ncet/event.html)、[関連学会](https://plaza.umin.ac.jp/~ncet/kanren.html) | あり | 未検出 | 未検出 | ルートにあり | A |
| 熊本県 | [kumamoto-acet.jp](http://kumamoto-acet.jp/) | [お知らせ](http://kumamoto-acet.jp/news.html)、[イベント一覧](http://www.kumamoto-acet.jp/system/event_list.php?ct=24) | あり | 未検出 | 未検出 | 未検出 | B |
| 大分県 | [oacet.or.jp](https://oacet.or.jp/) | [学術集会・各種セミナー](https://oacet.or.jp/event/) | あり | 未検出 | 未検出 | 未検出 | A |
| 宮崎県 | [miyazakice.com](https://www.miyazakice.com/) | [イベント](https://www.miyazakice.com/%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88)、[関連団体学会情報](https://www.miyazakice.com/%E9%96%A2%E9%80%A3%E5%AD%A6%E4%BC%9A%E6%83%85%E5%A0%B1) | 資料リンクあり | あり | あり | あり | B |
| 鹿児島県 | [karinkou.jp](https://www.karinkou.jp/) | [お知らせ全体](https://www.karinkou.jp/?post_type=news)、[勉強会・セミナー](https://www.karinkou.jp/?news_category=%E5%8B%89%E5%BC%B7%E4%BC%9A%E3%83%BB%E3%82%BB%E3%83%9F%E3%83%8A%E3%83%BC) | あり | あり | あり | 未検出 | A |
| 沖縄県 | [okinawa-ces.medikiki-hp1.com](https://okinawa-ces.medikiki-hp1.com/) | [セミナー](https://okinawa-ces.medikiki-hp1.com/seminars)、[履歴](https://okinawa-ces.medikiki-hp1.com/seminars-history) | 要動的確認 | 未検出 | あり・不整合あり | 未検出 | C |
| 日本臨床工学技士会 | [ja-ces.or.jp](https://ja-ces.or.jp/) | [学会・セミナー一覧](https://ja-ces.or.jp/seminar-info-list/)、[主催研修](https://ja-ces.or.jp/jsc/seminar/) | あり | あり | あり | あり | A |

優先度Aは通常HTTP取得でMVP実装しやすい、Bは文字コードまたは動的HTMLへの対応が必要、Cはクライアント側APIの確認やブラウザ取得の検討が必要、という意味です。

## 団体別詳細

### 福岡県臨床工学技士会

- 公式サイト: https://hp.fcet.or.jp/
- 候補ページ:
  - https://hp.fcet.or.jp/event/
  - https://hp.fcet.or.jp/event_tag/fcet/
  - https://hp.fcet.or.jp/event_tag/tadantai/
  - https://hp.fcet.or.jp/news/
- フィード:
  - https://hp.fcet.or.jp/event/feed/
  - https://hp.fcet.or.jp/sitemap.rss
- サイトマップ: https://hp.fcet.or.jp/sitemap.xml
- robots.txt: https://hp.fcet.or.jp/robots.txt
- 公式性の根拠: サイトが一般社団法人福岡県臨床工学技士会の公式サイトと明記し、事務局情報を掲載。日本臨床工学技士会の都道府県会情報と整合する。
- 注意点:
  - WordPressのイベント投稿を優先し、一般ニュースは候補抽出に限定する。
  - 主催タグが明示されるため、主催形態判定の強い根拠にできる。
  - イベント一覧と詳細の双方に日付がある場合、詳細ページを優先する。
  - PDFは詳細記事内またはアップロード領域に存在する。

### 佐賀県臨床工学技士会

- 公式サイト: https://sagacet.web.fc2.com/
- 候補ページ:
  - https://sagacet.web.fc2.com/event_society.html
  - https://sagacet.web.fc2.com/event_seminar.html
  - https://sagacet.web.fc2.com/news.html
  - https://sagacet.web.fc2.com/event-poster-manager/poster.html
- RSS、サイトマップ、robots.txt: 標準的な候補URLでは未検出
- 公式性の根拠: サイトが法人名を明記。福岡県臨床工学技士会の公式リンク集から同URLへリンクされ、日本臨床工学技士会の団体情報とも一致する。
- 注意点:
  - FC2の静的HTMLで、複数イベントが1ページに連続掲載される。
  - 詳細ページがない項目があるため、見出し単位でDOMを分割する必要がある。
  - PDFリンクが多く、相対URL解決が必要。
  - サイト更新日時とイベント開催日を混同しない。

### 長崎県臨床工学技士会

- 公式サイト: https://plaza.umin.ac.jp/~ncet/
- 旧URL: http://www.ncet.umin.jp/ は現URLへ転送
- 候補ページ:
  - https://plaza.umin.ac.jp/~ncet/event.html
  - https://plaza.umin.ac.jp/~ncet/kanren.html
- robots.txt: https://plaza.umin.ac.jp/robots.txt
- RSS、サイトマップ: サブサイト固有のものは未検出
- 公式性の根拠: サイトの法人名、定款、役員・事務局情報が日本臨床工学技士会の団体情報と整合。旧公式URLからも転送される。
- 注意点:
  - UMIN全体のrobots.txtに`Crawl-delay: 60`がある。最低60秒間隔を厳守する。
  - 同一ホスト上の他団体へ探索を広げず、`/~ncet/`配下だけを取得する。
  - HTMLは静的で解析しやすいが、古い記事と現行記事が同ページに混在する。
  - PDFと画像チラシの双方を想定する。

### 熊本県臨床工学技士会

- 公式サイト: http://kumamoto-acet.jp/
- 候補ページ:
  - http://kumamoto-acet.jp/news.html
  - http://www.kumamoto-acet.jp/system/event_list.php?ct=24
  - http://kumamoto-acet.jp/news_business.html
- RSS、サイトマップ、robots.txt: 未検出
- 公式性の根拠: サイトの団体名、会員案内、活動情報が日本臨床工学技士会の団体情報と一致する。
- 注意点:
  - HTMLがShift_JISのため、HTTPレスポンスとmeta charsetを見てCP932として明示変換する。
  - 調査時点でHTTPS接続が安定せず、HTTPが正常応答した。HTTP取得を許容しつつ、リンク先のHTTPS可否を別に検証する。
  - 複数イベントが`news.html`のアンカー単位で並ぶ。
  - 旧UMIN URLは現サイトの根拠として使わず、現在の内容を基準にする。

### 大分県臨床工学技士会

- 公式サイト: https://oacet.or.jp/
- 候補ページ:
  - https://oacet.or.jp/event/
  - https://oacet.or.jp/info/
  - 個別ページ形式: `https://oacet.or.jp/event/detail.php?...`
- RSS、サイトマップ、robots.txt: 標準的な候補URLでは未検出
- 公式性の根拠: 公益社団法人名、役員、事務局、活動目的が日本臨床工学技士会の団体情報と整合する。
- 注意点:
  - 独自CMSで、一覧ページに大量の過去イベントが含まれる。
  - 初回だけ期間を区切って過去分を取り込み、以後は先頭ページと既知ID差分を取得する。
  - 詳細ページは項目が比較的構造化され、PDFリンクも多い。
  - 一覧ページ全体を毎回AIへ渡さず、詳細単位で処理する。

### 宮崎県臨床工学技士会

- 公式サイト: https://www.miyazakice.com/
- 候補ページ:
  - https://www.miyazakice.com/%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88
  - https://www.miyazakice.com/%E9%96%A2%E9%80%A3%E5%AD%A6%E4%BC%9A%E6%83%85%E5%A0%B1
  - https://www.miyazakice.com/blog-feed.xml
- サイトマップ: https://www.miyazakice.com/sitemap.xml
- robots.txt: https://www.miyazakice.com/robots.txt
- 公式性の根拠: サイトが一般社団法人宮崎県臨床工学技士会公式ホームページと明記し、入会・事務局情報が日本臨床工学技士会の団体情報と整合する。
- 注意点:
  - Wixで生成され、HTMLが大きく動的データを含む。まずRSSとサイトマップを使う。
  - 旧ドメイン`miyazaki-ce.com`は調査時点で無関係な美容情報サイトになっているため、絶対に取得対象にしない。
  - 日本語パスは正規化し、リダイレクト後URLを保存する。
  - 添付資料はWixの配信URLになる可能性があるため、許可ホストとContent-Typeを検証する。

### 鹿児島県臨床工学技士会

- 公式サイト: https://www.karinkou.jp/
- 候補ページ:
  - https://www.karinkou.jp/?post_type=news
  - https://www.karinkou.jp/?news_category=%E5%8B%89%E5%BC%B7%E4%BC%9A%E3%83%BB%E3%82%BB%E3%83%9F%E3%83%8A%E3%83%BC
  - https://www.karinkou.jp/?news_category=%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B
- RSS: https://www.karinkou.jp/?feed=rss2&post_type=news
- サイトマップ: https://www.karinkou.jp/sitemap.xml
- robots.txt: 標準パスでは未検出
- 公式性の根拠: サイトが公益社団法人鹿児島県臨床工学技士会と明記し、所在地、役員、活動内容が日本臨床工学技士会の情報と整合する。
- 注意点:
  - イベント専用投稿ではなく`news`カスタム投稿内に事務連絡や企業向け案内も混在する。
  - カテゴリを一次フィルターにしつつ、「お知らせ」にあるイベントも候補抽出する。
  - URLがクエリ形式なので、正規化時に`news`パラメータを落とさない。
  - RSSはカスタム投稿タイプを明示したURLを利用する。

### 沖縄県臨床工学技士会

- 現行サイト候補: https://okinawa-ces.medikiki-hp1.com/
- 候補ページ:
  - https://okinawa-ces.medikiki-hp1.com/seminars
  - https://okinawa-ces.medikiki-hp1.com/seminars-history
  - https://okinawa-ces.medikiki-hp1.com/notice
- サイトマップ: https://okinawa-ces.medikiki-hp1.com/sitemap.xml
- RSS、robots.txt: 未検出
- 公式性の根拠: 2025年の沖縄県理学療法士協会理事会資料に、沖縄県臨床工学技士会主催大会の案内先として同ホストの`/seminars`が記載されている。団体の存在・現事務局は日本臨床工学技士会の一覧で確認できる。
- 注意点:
  - 旧SharePoint URLは認証エラーとなり、現行収集先に使えない。
  - Nuxtのクライアントサイドアプリで、初期HTMLはローディング画面だけ。イベント本文はJavaScript実行後またはAPIから取得される。
  - サイトマップの`loc`がサブドメインを欠く`https://medikiki-hp1.com/...`になっており、そのまま信用できない。
  - Phase 2でブラウザのネットワーク通信を確認し、公開APIがあればAPIアダプター、なければ低頻度のブラウザ取得を使う。
  - 技術的取得が安定するまで、沖縄は日本臨床工学技士会等の転載掲載から候補を補完し、`source_gap`をReviewQueueに記録する。

### 公益社団法人日本臨床工学技士会

- 公式サイト: https://ja-ces.or.jp/
- 候補ページ:
  - https://ja-ces.or.jp/seminar-info-list/
  - https://ja-ces.or.jp/category/gakkai/
  - https://ja-ces.or.jp/category/koushuukai/
  - https://ja-ces.or.jp/jsc/seminar/
  - https://ja-ces.or.jp/for-ce-medical-staff/conference-seminar-information/kanrendantai_seminar-workshop/
- RSS:
  - https://ja-ces.or.jp/category/gakkai/feed/
  - https://ja-ces.or.jp/category/koushuukai/feed/
- サイトマップ: https://ja-ces.or.jp/wp-sitemap.xml
- robots.txt: https://ja-ces.or.jp/robots.txt
- 公式性の根拠: 公益社団法人日本臨床工学技士会自身が運営する公式ドメインで、法人概要、所在地、役員等を掲載する。
- 注意点:
  - 日臨工主催研修と関連団体主催情報を分けて取得し、主催形態を誤らない。
  - e-プリバド等の外部申込先は申込URLとして保持し、クロール範囲を広げない。
  - 全国情報を掲載するため、九州各県会との重複が最も多い掲載元になる。
  - WordPress本文、表、PDFの順に抽出し、公式詳細ページを主リンクとして保持する。

## robots.txt確認結果

- 福岡: WordPress管理領域を拒否し、公開サイトマップを明示。イベント公開ページは拒否されていない。
- 長崎/UMIN: 全クローラーに60秒のCrawl-delay。最も厳しい間隔として実装する。
- 宮崎: 公開領域を許可し、lightbox等を拒否。サイトマップを明示。
- 日本臨床工学技士会: WordPress管理領域等を拒否。公開カテゴリは拒否されていない。
- 佐賀、熊本、大分、鹿児島、沖縄: 標準パスではrobots.txtを検出できなかった。これは無制限取得の許可を意味しないため、1日1回、低速、条件付き取得を維持する。

## 調査時点のリスク

1. 沖縄の現行サイトは公式性の直接表示と取得APIを追加確認する必要がある。
2. 熊本はHTTPのみ正常取得できる状態で、通信経路上の改変リスクを考慮し、AI抽出結果を自動公開しない初期設定が安全。
3. 宮崎の旧ドメインは第三者用途に変わっており、古いリンク集を無条件に追うと誤収集する。
4. UMINのCrawl-delay違反を避けるため、長崎サイトは他のUMIN取得ジョブと共有レート制限が必要。
5. サイト構成、robots.txt、規約は変更されるため、Sourcesに`last_policy_checked_at`を持たせ、月1回再確認する。

## Phase 2 実サイト確認結果

2026年7月4日に、各団体の登録済み入口へ1回ずつ低頻度で確認し、次の結果を得ました。件数はサイト更新で変わるため、合否ではなくアダプター方式の適合確認に使用しています。

| 団体 | 状態 | 確認した方式 |
|---|---|---|
| 福岡 | 成功 | WordPressイベントRSS |
| 佐賀 | 成功 | 静的HTML、イベントリンク、PDF |
| 長崎 | 成功 | `h3`見出しと後続表、空文字PDFリンク |
| 熊本 | 成功 | CP932、`h3`アンカーと後続表 |
| 大分 | 成功 | `table.event`の「名称」欄、PDF |
| 宮崎 | 成功 | WixブログRSS |
| 鹿児島 | 成功 | カスタム投稿RSS |
| 沖縄 | 技術的保留 | Nuxt初期HTMLにイベント本文なし |
| 日本臨床工学技士会 | 成功 | WordPressカテゴリRSS |

沖縄の技術的保留は全体停止にせず、`CLIENT_RENDER_REQUIRED`として記録します。その他の詳細、運用制限、再現方法は[Phase 2 非AI収集の実装結果](09-phase2-collection.md)にまとめています。
