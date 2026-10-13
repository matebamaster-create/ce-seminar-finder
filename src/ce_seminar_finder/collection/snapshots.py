"""Resume from private candidate snapshots, never from public Actions artifacts."""
from __future__ import annotations

import json
import hashlib

from ce_seminar_finder.extraction.refinement import candidate_from_payload
from ce_seminar_finder.sheets.requests import execute_idempotent

SNAPSHOT_METHOD = "private_candidate_v1"


def read_candidate_snapshots(service, spreadsheet_id):
    api = service.spreadsheets().values()
    documents = execute_idempotent(api.get(spreadsheetId=spreadsheet_id, range="Documents!A:Q")).get("values", [])
    chunks = execute_idempotent(api.get(spreadsheetId=spreadsheet_id, range="DocumentTextChunks!A:G")).get("values", [])
    if not documents or not chunks:
        return []
    headers, *rows = documents
    hashes = {row["document_id"]: row.get("sha256") for values in rows
              if (row := dict(zip(headers, values))).get("extraction_method") == SNAPSHOT_METHOD}
    ids = set(hashes)
    text_by_id = {id_: [] for id_ in ids}
    headers, *rows = chunks
    for values in rows:
        row = dict(zip(headers, values))
        if row.get("document_id") in ids:
            text_by_id[row["document_id"]].append((int(row["chunk_index"]), str(row.get("text", ""))))
    candidates = []
    for id_ in sorted(ids):
        parts = text_by_id[id_]
        if not parts:
            raise ValueError("Private candidate snapshot is incomplete")
        text = "".join(text for _, text in sorted(parts))
        if hashlib.sha256(text.encode()).hexdigest() != hashes[id_]:
            raise ValueError("Private candidate snapshot checksum mismatch")
        payload = json.loads(text)
        candidates.append(candidate_from_payload(payload))
    return candidates
