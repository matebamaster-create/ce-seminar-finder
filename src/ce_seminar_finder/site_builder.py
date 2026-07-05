from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


WEB_FORMATS = {"Web", "オンデマンド", "ハイブリッド"}
GENRES = (
    "血液浄化",
    "呼吸",
    "循環",
    "医療機器管理",
    "手術室",
    "教育・研究",
    "DX・IT",
    "その他",
)
FORMATS = ("Web", "オンデマンド", "ハイブリッド", "現地開催", "要確認")


def build_static_site(data_path: Path, output_dir: Path) -> dict[str, int]:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    events = payload.get("events", [])
    generated_at = _parse_datetime(payload["generated_at"])
    active, archived = _partition_events(events, generated_at)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write(output_dir / "index.html", _home_page(active, generated_at))
    _write(
        output_dir / "events" / "index.html",
        _listing_page("イベント一覧", active, generated_at, archive=False),
    )
    _write(
        output_dir / "archive" / "index.html",
        _listing_page("過去のイベント", archived, generated_at, archive=True),
    )
    _write(output_dir / "about" / "index.html", _about_page(generated_at))
    for event in events:
        path = output_dir / "events" / str(event["event_id"]) / "index.html"
        _write(path, _detail_page(event, generated_at))
    return {
        "active_count": len(active),
        "archive_count": len(archived),
        "detail_count": len(events),
    }


def _partition_events(
    events: list[dict[str, Any]],
    generated_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    for event in events:
        end_value = (
            event.get("effective_end_at")
            or event.get("stream_end_at")
            or event.get("event_end_at")
            or event.get("event_start_at")
        )
        end = _parse_datetime(end_value) if end_value else None
        (archived if end and end < generated_at else active).append(event)
    active.sort(key=_event_sort_key)
    archived.sort(key=_event_sort_key, reverse=True)
    return active, archived


def _home_page(events: list[dict[str, Any]], generated_at: datetime) -> str:
    web_events = [event for event in events if event.get("format") in WEB_FORMATS][:6]
    cards = "".join(
        _event_card(event, generated_at, route_prefix="") for event in web_events
    )
    genre_links = "".join(
        f'<a class="explore-chip" href="events/?genre={_e(value)}">{_e(value)}</a>'
        for value in GENRES
    )
    format_links = "".join(
        f'<a class="explore-chip" href="events/?format={_e(value)}">{_e(value)}</a>'
        for value in FORMATS
    )
    body = f"""
<section class="hero">
  <p class="eyebrow">九州・沖縄から探す</p>
  <h1>臨床工学技士の学びを、<br><span>ひとつの場所で。</span></h1>
  <p class="hero-copy">九州8県と日本臨床工学技士会に掲載された学びの機会を、Web開催を中心に探せます。</p>
  <form class="hero-search" action="events/" method="get">
    <label class="sr-only" for="home-keyword">イベントを検索</label>
    <input id="home-keyword" name="q" type="search" placeholder="例：ECMO、呼吸、オンデマンド">
    <button type="submit">検索する</button>
  </form>
</section>
<section class="section">
  <div class="section-heading"><div><p class="eyebrow">ONLINE LEARNING</p><h2>新着Webセミナー</h2></div><a href="events/">すべて見る</a></div>
  <div class="card-grid">{cards or '<p class="empty">現在、公開中のWebセミナーはありません。</p>'}</div>
</section>
<section class="section explore">
  <div><p class="eyebrow">BY SPECIALTY</p><h2>ジャンルから探す</h2><div class="chip-grid">{genre_links}</div></div>
  <div><p class="eyebrow">BY FORMAT</p><h2>開催形式から探す</h2><div class="chip-grid">{format_links}</div></div>
</section>
"""
    return _page(
        "CE Seminar Finder",
        body,
        generated_at,
        script=False,
        asset_prefix="",
    )


def _listing_page(
    title: str,
    events: list[dict[str, Any]],
    generated_at: datetime,
    *,
    archive: bool,
) -> str:
    cards = "".join(
        _event_card(
            event,
            generated_at,
            archive=archive,
            route_prefix="../",
        )
        for event in events
    )
    body = f"""
<section class="page-intro">
  <p class="eyebrow">{'ARCHIVE' if archive else 'EVENT DIRECTORY'}</p>
  <h1>{_e(title)}</h1>
  <p>{'終了したイベントを確認できます。' if archive else 'キーワードや開催形式から、参加したいイベントを絞り込めます。'}</p>
</section>
<main class="listing-layout">
  <details class="filters" open>
    <summary>絞り込み条件</summary>
    <div class="filter-body">
      <label>キーワード<input id="keyword" type="search" placeholder="2文字以上"></label>
      <label>ジャンル<select id="genre"><option value="">すべて</option>{_options(GENRES)}</select></label>
      <label>開催形式<select id="format"><option value="">すべて</option>{_options(FORMATS)}</select></label>
      <label>イベント種別<select id="event-type"><option value="">すべて</option>{_options(('セミナー','研修会','講習会','学会・大会','研究会','オンデマンド','その他'))}</select></label>
      <label>参加費<select id="fee"><option value="">すべて</option>{_options(('無料','有料','要確認'))}</select></label>
      <label>開催月<input id="month" type="month"></label>
      <label class="check"><input id="deadline-open" type="checkbox">申込受付中のみ</label>
      <button id="clear-filters" type="button" class="secondary-button">条件をすべて解除</button>
    </div>
  </details>
  <section class="results" aria-labelledby="result-heading">
    <div class="result-toolbar">
      <h2 id="result-heading"><span id="result-count">{len(events)}</span>件</h2>
      <label>並び順<select id="sort"><option value="date">開催日が近い順</option><option value="deadline">申込締切が近い順</option><option value="title">イベント名順</option></select></label>
    </div>
    <p id="active-filters" class="active-filters" aria-live="polite"></p>
    <div id="event-list" class="card-grid">{cards or '<p class="empty">該当するイベントはありません。</p>'}</div>
    <p id="no-results" class="empty" hidden>条件に合うイベントはありません。</p>
  </section>
</main>
"""
    return _page(title, body, generated_at, script=True, asset_prefix="../")


def _event_card(
    event: dict[str, Any],
    generated_at: datetime,
    *,
    archive: bool = False,
    route_prefix: str,
) -> str:
    genres = event.get("genres") or []
    search_values = [
        event.get("title", ""),
        event.get("organizer_name", ""),
        event.get("summary", ""),
        event.get("event_type", ""),
        event.get("format", ""),
        event.get("source_prefecture", ""),
        event.get("venue_prefecture", ""),
        event.get("audience_conditions", ""),
        event.get("credits_text", ""),
        *genres,
        *(event.get("detailed_tags") or []),
    ]
    tags = "".join(f'<span class="tag">{_e(value)}</span>' for value in genres[:3])
    review = (
        f'<p class="review-note">要確認：{_e(event.get("review_reason_display", "公式情報をご確認ください"))}</p>'
        if event.get("review_label") == "あり"
        else ""
    )
    start = event.get("event_start_at") or event.get("stream_start_at")
    deadline = event.get("application_deadline_at")
    pdf_hashes = ",".join(event.get("pdf_search_hashes") or [])
    archive_label = '<span class="status-ended">開催終了</span>' if archive else ""
    detail_url = route_prefix + str(event.get("detail_path", "#")).lstrip("/")
    return f"""
<article class="event-card"
 data-search="{_e(' '.join(str(value) for value in search_values))}"
 data-genre="{_e('|'.join(genres))}"
 data-format="{_e(event.get('format', '要確認'))}"
 data-event-type="{_e(event.get('event_type', 'その他'))}"
 data-fee="{_e(event.get('fee_category', '要確認'))}"
 data-date="{_e(start or '')}"
 data-deadline="{_e(deadline or '')}"
 data-pdf-hashes="{_e(pdf_hashes)}">
  <div class="tag-row"><span class="format-tag">{_e(event.get('format', '要確認'))}</span>{tags}{archive_label}</div>
  <h3><a href="{_e(detail_url)}">{_e(event.get('title', '名称要確認'))}</a></h3>
  <dl class="card-facts">
    <div><dt>開催</dt><dd>{_time(start)}</dd></div>
    <div><dt>締切</dt><dd>{_time(deadline)}</dd></div>
    <div><dt>参加費</dt><dd>{_e(event.get('fee_text') or event.get('fee_category', '要確認'))}</dd></div>
  </dl>
  <p class="organizer">主催：{_e(event.get('organizer_name', '要確認'))}</p>
  {review}
  <p class="pdf-hit" hidden>PDF内に関連語あり</p>
  <div class="card-actions">
    <a class="primary-button" href="{_e(event.get('primary_official_url', '#'))}" target="_blank" rel="noopener" aria-label="公式詳細を見る（新しいタブ）">公式詳細を見る</a>
    <a class="text-link" href="{_e(detail_url)}">このサイトで詳細を見る</a>
  </div>
</article>
"""


def _detail_page(event: dict[str, Any], generated_at: datetime) -> str:
    genres = "".join(
        f'<span class="tag">{_e(value)}</span>' for value in event.get("genres", [])
    )
    application = (
        f'<a class="secondary-button" href="{_e(event["application_url"])}" target="_blank" rel="noopener" aria-label="申込ページへ（新しいタブ）">申込ページへ</a>'
        if event.get("application_url")
        else ""
    )
    pdf = (
        f'<a class="text-link" href="{_e(event["primary_pdf_url"])}" target="_blank" rel="noopener" aria-label="公式PDFを見る（新しいタブ）">公式PDFを見る</a>'
        if event.get("primary_pdf_url")
        else ""
    )
    review = (
        f'<aside class="review-panel"><strong>要確認</strong><p>{_e(event.get("review_reason_display", "申込前に公式情報をご確認ください。"))}</p></aside>'
        if event.get("review_label") == "あり"
        else ""
    )
    body = f"""
<article class="detail">
  <a class="back-link" href="../">← イベント一覧へ</a>
  <div class="tag-row"><span class="format-tag">{_e(event.get('format', '要確認'))}</span>{genres}<span class="tag">{_e(event.get('event_type', 'その他'))}</span></div>
  <h1>{_e(event.get('title', '名称要確認'))}</h1>
  <p class="detail-organizer">主催：{_e(event.get('organizer_name', '要確認'))}</p>
  {review}
  <div class="detail-actions">
    <a class="primary-button" href="{_e(event.get('primary_official_url', '#'))}" target="_blank" rel="noopener" aria-label="公式詳細を見る（新しいタブ）">公式詳細を見る</a>
    {application}{pdf}
  </div>
  <section class="detail-grid" aria-label="イベント情報">
    {_fact('開催日時', _time_text(event.get('event_start_at')))}
    {_fact('配信期間', _period(event.get('stream_start_at'), event.get('stream_end_at'), event.get('stream_period_text')))}
    {_fact('申込締切', _time(event.get('application_deadline_at')))}
    {_fact('参加費', event.get('fee_text') or event.get('fee_category', '要確認'))}
    {_fact('会場', event.get('venue_name') or event.get('venue_prefecture') or '要確認')}
    {_fact('対象・参加条件', event.get('audience_conditions', '要確認'))}
    {_fact('定員', event.get('capacity_text', '要確認'))}
    {_fact('単位・ポイント', event.get('credits_text', '要確認'))}
  </section>
  <aside class="notice"><strong>公式情報をご確認ください</strong><p>本ページは公式サイト・公式PDFから取得した参考情報です。参加費、参加条件、単位・ポイント、申込締切、開催形式は、申込前に必ず主催者の公式ページでご確認ください。</p></aside>
</article>
"""
    return _page(
        str(event.get("title", "イベント詳細")),
        body,
        generated_at,
        script=False,
        asset_prefix="../../",
    )


def _about_page(generated_at: datetime) -> str:
    body = """
<article class="detail prose">
  <p class="eyebrow">ABOUT</p>
  <h1>CE Seminar Finderについて</h1>
  <p>九州8県の臨床工学技士会と日本臨床工学技士会に掲載された、セミナー・研修会等を横断して探すための限定共有版です。</p>
  <h2>掲載情報について</h2>
  <p>情報は公式サイト・公式PDFをもとに整理しています。正確な参加条件、料金、単位、締切は必ず公式ページで確認してください。</p>
  <h2>限定共有について</h2>
  <p>検索エンジンへの登録を抑制していますが、URLを知る人へのアクセス制限ではありません。</p>
</article>
"""
    return _page(
        "このサイトについて",
        body,
        generated_at,
        script=False,
        asset_prefix="../",
    )


def _page(
    title: str,
    body: str,
    generated_at: datetime,
    *,
    script: bool,
    asset_prefix: str,
) -> str:
    script_tag = (
        f'<script src="{asset_prefix}assets/app.js" defer></script>'
        if script
        else ""
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta name="description" content="臨床工学技士向けセミナー・研修会の横断検索">
  <title>{_e(title)} | CE Seminar Finder</title>
  <link rel="stylesheet" href="{asset_prefix}assets/styles.css">
  {script_tag}
</head>
<body>
  <a class="skip-link" href="#main">本文へ移動</a>
  <header class="site-header">
    <a class="brand" href="{asset_prefix}"><span class="brand-mark">CE</span><span>Seminar Finder<small>学びを、見つけやすく。</small></span></a>
    <nav aria-label="主要メニュー"><a href="{asset_prefix}events/">イベント</a><a href="{asset_prefix}archive/">過去のイベント</a><a href="{asset_prefix}about/">このサイトについて</a></nav>
  </header>
  <main id="main">{body}</main>
  <footer><p><strong>CE Seminar Finder</strong></p><p>掲載内容は参考情報です。必ず主催者の公式情報をご確認ください。</p><p>データ更新: <time datetime="{generated_at.isoformat()}">{_e(generated_at.strftime('%Y年%m月%d日'))}</time></p></footer>
</body>
</html>
"""


def _fact(label: str, value: Any) -> str:
    return f"<div><dt>{_e(label)}</dt><dd>{_e(value or '要確認')}</dd></div>"


def _period(start: Any, end: Any, text: Any) -> str:
    if text:
        return str(text)
    if start or end:
        return f"{_time_text(start)} 〜 {_time_text(end)}"
    return "要確認"


def _time(value: Any) -> str:
    if not value:
        return "要確認"
    try:
        parsed = _parse_datetime(str(value))
    except ValueError:
        return _e(value)
    display = f"{parsed.month}月{parsed.day}日"
    if parsed.hour or parsed.minute:
        display += f" {parsed.strftime('%H:%M')}"
    return f'<time datetime="{_e(str(value))}">{display}</time>'


def _time_text(value: Any) -> str:
    if not value:
        return "要確認"
    try:
        parsed = _parse_datetime(str(value))
    except ValueError:
        return str(value)
    display = f"{parsed.month}月{parsed.day}日"
    if parsed.hour or parsed.minute:
        display += f" {parsed.strftime('%H:%M')}"
    return display


def _event_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    return (
        str(
            event.get("event_start_at")
            or event.get("stream_start_at")
            or event.get("stream_end_at")
            or "9999"
        ),
        str(event.get("title", "")),
    )


def _options(values: tuple[str, ...]) -> str:
    return "".join(f'<option value="{_e(value)}">{_e(value)}</option>' for value in values)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
