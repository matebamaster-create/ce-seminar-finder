from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .models import parse_datetime
from .publisher import build_public_payload, write_public_payload
from .site_builder import build_static_site
from .adapters import adapter_for_source
from .collection.cache import JsonFetchStateStore
from .collection.fetcher import SafeHttpFetcher
from .collection.pipeline import SourceCollector
from .collection.repository import (
    CompositeCollectionRepository,
    JsonlCollectionRepository,
    SheetCollectionRepository,
)
from .collection.sources import source_config
from .collection.sources import source_configs
from .collection.sources import source_configs_from_sheet
from .regions import region_source_ids, REGIONS
from .collection.renderer import PublicPageRenderer
from .automation.daily import run_daily_collection, write_daily_outputs
from .automation.lock import RunAlreadyActive
from .extraction.pdf import extract_pdf
from .extraction.cache import JsonExtractionCache
from .extraction.openai_provider import DEFAULT_MODEL, OpenAIProvider, OpenAIExtractionError, load_api_key
from .extraction.prompt import PROMPT_VERSION
from .extraction.refinement import candidate_payload, read_saved_candidates, read_processed_keys, refine_candidates
from .extraction.service import ExtractionService
from .extraction.documents import PdfContextLoader
from .sheets.initializer import build_plan, initialize_spreadsheet, load_google_service
from .sheets.reader import (
    archive_expired_sheet_events,
    event_records_from_rows,
    read_event_rows,
)
from .sheets.schema import workbook_template_payload
from .sheets.writer import upsert_event_rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ce-seminar-finder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "plan-sheet",
        help="Googleスプレッドシート初期化計画を表示します",
    )

    init_sheet = subparsers.add_parser(
        "init-sheet",
        help="共有済みの空のGoogleスプレッドシートを初期化します",
    )
    init_sheet.add_argument("--spreadsheet-id", required=True)

    build_public = subparsers.add_parser(
        "build-public",
        help="公開許可済みイベントだけをJSONへ出力します",
    )
    build_public.add_argument("--input", type=Path, required=True)
    build_public.add_argument("--output", type=Path, required=True)
    build_public.add_argument(
        "--generated-at",
        help="再現可能なビルド用ISO 8601日時。省略時は現在時刻",
    )

    export_template = subparsers.add_parser(
        "export-sheet-template",
        help="Excel/Google Sheets雛形作成用の構造JSONを出力します",
    )
    export_template.add_argument("--output", type=Path, required=True)

    collect_source = subparsers.add_parser(
        "collect-source",
        help="指定した公式ソースを低頻度で収集します",
    )
    collect_source.add_argument("--source-id", required=True)
    collect_source.add_argument("--force", action="store_true")
    collect_source.add_argument("--render-public-pages", action="store_true")
    collect_source.add_argument("--max-detail-pages", type=int, default=1)
    collect_source.add_argument(
        "--state-file",
        type=Path,
        default=Path("var/fetch-state.json"),
    )
    collect_source.add_argument(
        "--log-directory",
        type=Path,
        default=Path("var/collection"),
    )
    collect_source.add_argument("--output", type=Path, required=True)

    extract_pdf_command = subparsers.add_parser(
        "extract-pdf",
        help="非公開PDFからページ別テキストと品質情報を抽出します",
    )
    extract_pdf_command.add_argument("--input", type=Path, required=True)
    extract_pdf_command.add_argument("--output", type=Path, required=True)

    build_site = subparsers.add_parser(
        "build-site",
        help="公開許可済みJSONから静的サイトを生成します",
    )
    build_site.add_argument("--data", type=Path, required=True)
    build_site.add_argument("--output-directory", type=Path, required=True)

    daily_run = subparsers.add_parser(
        "daily-run",
        help="明示的に有効化された公式ソースの日次収集を実行します",
    )
    daily_run.add_argument(
        "--enabled-sources",
        default="",
        help="カンマまたは空白区切りのsource_id。空なら外部取得しません",
    )
    daily_run.add_argument(
        "--state-file",
        type=Path,
        default=Path("var/fetch-state.json"),
    )
    daily_run.add_argument(
        "--work-directory",
        type=Path,
        default=Path("var/daily"),
    )
    daily_run.add_argument("--max-detail-pages", type=int, default=1)
    daily_run.add_argument("--full-detail", action="store_true", help="初回一括用。過去の終了イベント以外の発見済み詳細を低速で取得します")
    daily_run.add_argument("--spreadsheet-id")
    daily_run.add_argument("--use-sheet-sources", action="store_true")
    daily_run.add_argument("--render-public-pages", action="store_true")
    daily_run.add_argument("--region", choices=["west", *REGIONS])
    daily_run.add_argument("--summary", type=Path, required=True)
    daily_run.add_argument("--candidates", type=Path, required=True)
    daily_run.add_argument("--markdown-summary", type=Path)

    export_sheet = subparsers.add_parser(
        "export-public-from-sheet",
        help="非公開Eventsシートの最終値から公開JSONを生成します",
    )
    export_sheet.add_argument("--spreadsheet-id", required=True)
    export_sheet.add_argument("--output", type=Path, required=True)
    export_sheet.add_argument("--generated-at")

    archive_sheet = subparsers.add_parser(
        "archive-sheet",
        help="終了日時を過ぎた公開イベントをアーカイブします",
    )
    archive_sheet.add_argument("--spreadsheet-id", required=True)
    archive_sheet.add_argument("--as-of", required=True)

    import_events = subparsers.add_parser(
        "upsert-sheet-events",
        help="JSONの確認済みイベントをEventsシートへ追加または更新します",
    )
    import_events.add_argument("--spreadsheet-id", required=True)
    import_events.add_argument("--input", type=Path, required=True)

    refine = subparsers.add_parser("refine-candidates", help="公式候補をAIで補足し、確認待ちへ反映します（自動公開なし）")
    refine.add_argument("--input", type=Path, nargs="+", default=[])
    refine.add_argument("--from-sheet", action="store_true", help="非公開の保存済み候補からAI処理だけを再開します")
    refine.add_argument("--output", type=Path, required=True)
    refine.add_argument("--summary", type=Path)
    refine.add_argument("--max-calls", type=int, default=0, help="API回数上限。0は件数制限なし")
    refine.add_argument("--include-pdf", action="store_true", help="公式PDFを取得し、文字抽出・日本語OCRを行います")
    refine.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    refine.add_argument("--model", default=DEFAULT_MODEL)
    refine.add_argument("--env-file", type=Path)
    refine.add_argument("--cache", type=Path, default=Path("var/ai-cache.json"))
    refine.add_argument("--spreadsheet-id")
    automatic = subparsers.add_parser("auto-review-sheet", help="承認された公式原文照合ルールで整理・公開します（AI再送なし）")
    automatic.add_argument("--spreadsheet-id", required=True)
    automatic.add_argument("--enable-policy", action="store_true", help="所有者が明示承認した西日本31団体の条件付き自動公開を有効化")
    automatic.add_argument("--dry-run", action="store_true")
    automatic.add_argument("--summary", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "plan-sheet":
        print(json.dumps(build_plan().as_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "auto-review-sheet":
        from .review.automatic import AutomaticReviewer
        from .sheets.capacity import ensure_row_capacity
        if args.dry_run and args.enable_policy:
            raise ValueError("Dry run cannot enable a policy")
        service = load_google_service()
        reviewer = AutomaticReviewer(service, args.spreadsheet_id,
            ensure_capacity=lambda required: ensure_row_capacity(service, args.spreadsheet_id, required))
        if args.enable_policy:
            reviewer.enable_policy()
        summary = reviewer.run(dry_run=args.dry_run)
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if args.command == "init-sheet":
        service = load_google_service()
        plan = initialize_spreadsheet(service, args.spreadsheet_id)
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "refine-candidates":
        try:
            if args.max_calls < 0:
                raise ValueError("--max-calls must be nonnegative")
            provider = OpenAIProvider(load_api_key(args.env_file), model=args.model, max_requests=args.max_calls or None)
        except OpenAIExtractionError as error:
            print(json.dumps({"status": "failed", "code": error.code}))
            return 1
        google = load_google_service() if args.spreadsheet_id else None
        if args.from_sheet:
            if not google:
                raise ValueError("--from-sheet requires --spreadsheet-id")
            from ce_seminar_finder.collection.snapshots import read_candidate_snapshots
            candidates = read_candidate_snapshots(google, args.spreadsheet_id)
            if not candidates:
                raise ValueError("No private candidate snapshots; collect the enabled sources first")
            enabled = {s.source_id for s in source_configs_from_sheet(google, args.spreadsheet_id) if s.enabled}
            candidates = [c for c in candidates if c.source_id in enabled]
        else:
            if not args.input:
                raise ValueError("--input or --from-sheet is required")
            candidates = read_saved_candidates(args.input)
        processed = read_processed_keys(google, args.spreadsheet_id) if google else set()
        extractor = ExtractionService(provider, prompt_version=PROMPT_VERSION, cache=JsonExtractionCache(args.cache))
        pdf_loader = PdfContextLoader(args.cache.parent / "pdf-documents") if args.include_pdf else None
        repository = SheetCollectionRepository(google, args.spreadsheet_id) if google else None
        def checkpoint(rows):
            if repository:
                repository.append_candidates(rows)
            print(json.dumps({"status": "progress", "requests": provider.requests,
                "input_tokens": provider.input_tokens, "output_tokens": provider.output_tokens,
                "checkpoint_candidates": len(rows)}, ensure_ascii=False), flush=True)
        refined, summary = refine_candidates(candidates, extractor, processed_keys=processed,
            pdf_loader=pdf_loader, checkpoint=checkpoint, workers=args.workers)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps([candidate_payload(c) for c in refined], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary.update({"model": args.model, "prompt_version": PROMPT_VERSION,
            "sheet_updated": bool(google and summary["saved"]), "auto_published": False})
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if summary["errors"] else 0

    if args.command == "build-public":
        generated_at = parse_datetime(args.generated_at) if args.generated_at else None
        payload = write_public_payload(args.input, args.output, generated_at)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "event_count": payload["event_count"],
                    "generated_at": payload["generated_at"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "export-sheet-template":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                workbook_template_payload(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"output": str(args.output)}, ensure_ascii=False))
        return 0

    if args.command == "collect-source":
        config = source_config(args.source_id)
        store = JsonFetchStateStore(args.state_file)
        repository = JsonlCollectionRepository(args.log_directory)
        collector = SourceCollector(
            fetcher=SafeHttpFetcher(state_store=store),
            repository=repository,
            state_store=store,
            renderer=PublicPageRenderer() if args.render_public_pages else None,
        )
        result = collector.collect(
            config,
            adapter_for_source(config.source_id),
            force=args.force,
            max_detail_pages=max(0, args.max_detail_pages),
        )
        payload = {
            "source_id": result.source_id,
            "status": result.status.value,
            "candidate_count": len(result.candidates),
            "candidates": [
                {
                    "source_id": item.source_id,
                    "source_url": item.source_url,
                    "detail_url": item.detail_url,
                    "title_hint": item.title_hint,
                    "pdf_urls": list(item.pdf_urls),
                    "published_at": item.published_at,
                    "discovery_method": item.discovery_method,
                    "block_text": item.block_text,
                    "extracted_fields": {
                        key: value.as_dict()
                        for key, value in item.extracted_fields.items()
                    },
                    "confidence_hint": item.confidence_hint,
                }
                for item in result.candidates
            ],
            "warnings": result.warnings,
            "fetched_urls": result.fetched_urls,
            "log_count": len(result.logs),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(
            {
                "source_id": result.source_id,
                "status": result.status.value,
                "candidate_count": len(result.candidates),
                "output": str(args.output),
            },
            ensure_ascii=False,
        ))
        return 0

    if args.command == "extract-pdf":
        result = extract_pdf(args.input.read_bytes())
        payload = {
            "sha256": result.sha256,
            "byte_size": result.byte_size,
            "page_count": len(result.pages),
            "quality_score": result.quality_score,
            "extraction_status": result.extraction_status,
            "warnings": list(result.warnings),
            "pages": [
                {
                    "page_number": page.page_number,
                    "quality_score": page.quality_score,
                    "needs_ocr": page.needs_ocr,
                    "extraction_method": page.extraction_method,
                }
                for page in result.pages
            ],
            "chunks": [
                {
                    "chunk_index": chunk.chunk_index,
                    "page_from": chunk.page_from,
                    "page_to": chunk.page_to,
                    "text": chunk.text,
                    "text_hash": chunk.text_hash,
                }
                for chunk in result.chunks
            ],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "page_count": len(result.pages),
                    "quality_score": result.quality_score,
                    "status": result.extraction_status,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "build-site":
        result = build_static_site(args.data, args.output_directory)
        print(
            json.dumps(
                {"output": str(args.output_directory), **result},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "daily-run":
        enabled = {
            item
            for item in args.enabled_sources.replace(",", " ").split()
            if item
        }
        configs = source_configs()
        service = load_google_service() if args.spreadsheet_id else None
        if args.use_sheet_sources:
            if service is None:
                raise ValueError("--use-sheet-sources requires --spreadsheet-id")
            configs = source_configs_from_sheet(service, args.spreadsheet_id)
            if not args.enabled_sources:
                enabled = None
        if args.region:
            ids = region_source_ids(args.region)
            configs = tuple(config for config in configs if config.source_id in ids)
        if args.full_detail:
            configs = tuple(replace(config, max_requests_per_run=max(2000, config.max_requests_per_run)) for config in configs)
        known = {item.source_id for item in source_configs()}
        unknown = sorted((enabled or set()) - known)
        if unknown:
            raise ValueError(f"Unknown source_id: {', '.join(unknown)}")
        store = JsonFetchStateStore(args.state_file)
        local_repository = JsonlCollectionRepository(
            args.work_directory / "collection"
        )
        repository = local_repository
        if args.spreadsheet_id:
            repository = CompositeCollectionRepository(
                local_repository,
                SheetCollectionRepository(
                    service,
                    args.spreadsheet_id,
                ),
            )
        collector = SourceCollector(
            fetcher=SafeHttpFetcher(state_store=store),
            repository=repository,
            state_store=store,
        )
        if args.render_public_pages:
            collector.renderer = PublicPageRenderer()
        try:
            summary = run_daily_collection(
                collector=collector,
                sources=configs,
                enabled_source_ids=enabled,
                lock_path=args.work_directory / "daily.lock",
                max_detail_pages=None if args.full_detail else max(0, args.max_detail_pages),
            )
        except RunAlreadyActive as exc:
            print(json.dumps({"status": "already_running", "message": str(exc)}))
            return 75
        write_daily_outputs(
            summary,
            summary_path=args.summary,
            candidates_path=args.candidates,
            markdown_path=args.markdown_summary,
        )
        print(json.dumps(summary.as_dict(), ensure_ascii=False))
        return 0

    if args.command == "export-public-from-sheet":
        service = load_google_service()
        records = event_records_from_rows(
            read_event_rows(service, args.spreadsheet_id)
        )
        generated_at = (
            parse_datetime(args.generated_at) if args.generated_at else None
        )
        payload = build_public_payload(records, generated_at, include_archived=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {"output": str(args.output), "event_count": payload["event_count"]},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "archive-sheet":
        service = load_google_service()
        archived = archive_expired_sheet_events(
            service,
            args.spreadsheet_id,
            as_of=parse_datetime(args.as_of),
        )
        print(json.dumps({"archived_count": archived}, ensure_ascii=False))
        return 0

    if args.command == "upsert-sheet-events":
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        rows = raw.get("events", []) if isinstance(raw, dict) else raw
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Input must be an event object array or {'events': [...]}")
        service = load_google_service()
        result = upsert_event_rows(service, args.spreadsheet_id, rows)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
