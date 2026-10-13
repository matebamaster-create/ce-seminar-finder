"""Make a reviewable reconciliation plan from a connector-read snapshot.

No credentials or network requests. Prints RAW-values write plans only.
"""
import argparse
import json
import re
from pathlib import Path
from dataclasses import replace
from datetime import UTC, datetime

from ce_seminar_finder.collection.ingestion import CandidateIngestor
from ce_seminar_finder.collection.models import EventCandidate
from ce_seminar_finder.extraction.models import ExtractedField
from ce_seminar_finder.extraction.rules import extract_rule_values
from ce_seminar_finder.sheets.schema import SOURCE_ROWS, SOURCES_HEADERS
from ce_seminar_finder.sheets.reader import archive_expired_rows
from ce_seminar_finder.sheets.reader import event_records_from_rows
from ce_seminar_finder.publisher import build_public_payload


class Execute:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class PlanService:
    def __init__(self, tables): self.tables, self.writes = tables, {}
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, **kwargs):
        name = kwargs["range"].split("!")[0].strip("'")
        return Execute({"values": self.tables[name]})
    def batchUpdate(self, **kwargs):
        for item in kwargs["body"]["data"]:
            name, cells = item["range"].split("!")
            name = name.strip("'")
            row = int(re.search(r"\d+", cells)[0])
            self.writes[(name, row)] = item
            while len(self.tables[name]) < row: self.tables[name].append([])
            self.tables[name][row-1] = item["values"][0]
        return Execute({})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-json", required=True)
    parser.add_argument("--audit-directory", type=Path, default=Path("var/audit-west-v2"))
    parser.add_argument("--extra-directory", type=Path, action="append", default=[])
    parser.add_argument("--verified-json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("var/restart-sheet-plan.json"))
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot_json)
    service = PlanService(snapshot)
    sources = {r[0]: (i,r) for i,r in enumerate(snapshot["Sources"][1:],2) if r}
    for row in SOURCE_ROWS:
        current = sources.get(row[0])
        number = current[0] if current else len(snapshot["Sources"])+1
        value = list(row)
        if current:
            old = current[1] + [""] * (len(row)-len(current[1]))
            for index in (8,9,10,11,12,13,15,16,17,18,19,20,21,22):
                value[index] = old[index]
        # Explicit restart rollout authorization applies to all public sources.
        value[SOURCES_HEADERS.index("enabled")] = True
        service.batchUpdate(body={"data":[{"range":f"Sources!A{number}:X{number}","values":[value]}]})
    candidates = []
    paths = {p.parent.name: p for p in args.audit_directory.glob("src_*/candidates.jsonl")}
    for directory in args.extra_directory:
        paths.update({p.parent.name: p for p in directory.glob("src_*/candidates.jsonl")})
    for path in sorted(paths.values()):
        for line in path.read_text().splitlines():
            raw = json.loads(line)
            raw["extracted_fields"] = {k:ExtractedField(**v) for k,v in raw.get("extracted_fields",{}).items()}
            raw["pdf_urls"] = tuple(raw.get("pdf_urls",[]))
            candidate = EventCandidate(**raw)
            # Re-evaluate saved input with the corrected field rules.
            fields = extract_rule_values(candidate.block_text, title_hint=candidate.title_hint) if candidate.discovery_method in {"html_heading_block", "html_event_table", "nara_heading_table", "shizuoka_event_row", "fukui_public_block"} else {}
            candidate = replace(candidate, extracted_fields=fields)
            candidates.append(candidate)
    CandidateIngestor(service, "snapshot").ingest(candidates)
    headers = snapshot["Events"][0]
    verified = json.loads(args.verified_json.read_text()) if args.verified_json else []
    # Explicit source-checked structured amendments, never publication by AI score.
    for amendment in verified:
        matches = [(i,row) for i,row in enumerate(snapshot["Events"][1:],2)
                   if len(row) > headers.index("primary_official_url") and row[headers.index("primary_official_url")] == amendment["primary_official_url"]]
        if len(matches) != 1:
            raise ValueError("Verified amendment must match exactly one event")
        i,row = matches[0]
        row.extend([""] * (len(headers)-len(row)))
        for name,value in {**amendment,"publication_status":"公開","review_status":"未確認","review_label":"あり",
            "fee_verified":False,"last_verified_at":datetime.now(UTC).isoformat(),
            "review_reason_display":"参加条件・単位の詳細は公式情報を確認してください"}.items():
            row[headers.index(name)] = value
        if not row[headers.index("event_start_at")] and not row[headers.index("stream_start_at")]:
            raise ValueError("Verified publication has no date")
        service.batchUpdate(body={"data":[{"range":f"Events!A{i}:AY{i}","values":[row]}]})
    rows = [dict(zip(headers,r), __row_number=i) for i,r in enumerate(snapshot["Events"][1:],2) if r]
    expired = archive_expired_rows(rows, as_of=datetime.now(UTC))
    for i in expired:
        row = snapshot["Events"][i-1]
        row.extend([""] * (len(headers)-len(row)))
        row[headers.index("publication_status")] = "アーカイブ"
        row[headers.index("archived_at")] = datetime.now(UTC).isoformat()
        service.batchUpdate(body={"data":[{"range":f"Events!A{i}:AY{i}","values":[row]}]})
    payload = {"writes":list(service.writes.values()),
        "counts":{k:len(v)-1 for k,v in snapshot.items()},"archived":len(expired)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    all_events = [dict(zip(headers,row)) for row in snapshot["Events"][1:] if row]
    public = build_public_payload(event_records_from_rows(all_events), include_archived=True)
    (args.output.parent / "restart-public.json").write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output":str(args.output),"counts":payload["counts"],"archived":len(expired),"writes":len(payload["writes"])}))


if __name__ == "__main__": main()
