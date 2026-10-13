"""One bounded live run, grouped by host; output stays in ignored var/."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import argparse
import json

from ce_seminar_finder.adapters import adapter_for_source
from ce_seminar_finder.collection.fetcher import SafeHttpFetcher, StandardHttpTransport
from ce_seminar_finder.collection.pipeline import SourceCollector
from ce_seminar_finder.collection.repository import JsonlCollectionRepository
from ce_seminar_finder.collection.sources import source_configs
from ce_seminar_finder.collection.renderer import PublicPageRenderer
from ce_seminar_finder.regions import region_source_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="west")
    parser.add_argument("--source-ids", default="")
    parser.add_argument("--output", type=Path, default=Path("var/audit-west"))
    parser.add_argument("--max-detail-pages", type=int, default=2)
    parser.add_argument("--render-public-pages", action="store_true")
    args = parser.parse_args()
    ids = set(args.source_ids.split(",")) if args.source_ids else region_source_ids(args.region)
    args.output.mkdir(parents=True, exist_ok=True)

    def run(source):
        directory = args.output / source.source_id
        collector = SourceCollector(
            fetcher=SafeHttpFetcher(timeout=12, max_attempts=1),
            repository=JsonlCollectionRepository(directory),
            renderer=PublicPageRenderer() if args.render_public_pages else None,
        )
        result = collector.collect(replace(source, enabled=True, max_requests_per_run=8),
            adapter_for_source(source.source_id), max_detail_pages=args.max_detail_pages)
        row = {"source_id": source.source_id, "prefecture": source.prefecture,
               "status": result.status.value, "candidate_count": len(result.candidates),
               "warnings": result.warnings,
               "requests": [{"url": x.url, "status": x.http_status, "outcome": x.result_code}
                            for x in result.logs]}
        return row

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(run, s): s for s in source_configs() if s.source_id in ids}
        for future in as_completed(futures):
            source = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"source_id": source.source_id, "prefecture": source.prefecture,
                       "status": "failed", "candidate_count": 0, "error_type": type(exc).__name__}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    payload = {"checked_at": datetime.now(UTC).isoformat(), "sources": sorted(results, key=lambda r: r["source_id"])}
    (args.output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
