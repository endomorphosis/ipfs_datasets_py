#!/usr/bin/env python3
"""Generate span evidence rows and upload them to the span-cache dataset.

The resume checkpoint is left in place. Pending queue text is not uploaded.
A generated row is not a legal admit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")


def main() -> int:
    from ipfs_datasets_py.logic.autoformal.span_agreement import FEDERAL_SPAN_CACHE, sample_federal_spans
    from ipfs_datasets_py.logic.autoformal.span_evidence import (
        EVIDENCE_REPO_PATH,
        DEFAULT_REPOSITORY_ID,
        demonstration_spans,
        generate_span_evidence,
        publish_span_evidence,
        write_span_evidence_parquet,
    )

    parser = argparse.ArgumentParser(description="publish a small span-evidence parquet")
    parser.add_argument("--output", type=Path, default=Path("/tmp/ipfs-uscode-autoformal/span-evidence.parquet"))
    parser.add_argument("--cache", default=FEDERAL_SPAN_CACHE)
    parser.add_argument("--federal", type=int, default=4)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--lake-limit", type=int, default=8)
    parser.add_argument("--lake-successes", type=int, default=8)
    parser.add_argument("--no-federal", action="store_true")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()

    spans = demonstration_spans()
    if not args.no_federal and args.federal > 0:
        try:
            sampled = sample_federal_spans(
                args.cache,
                count=max(args.federal * 16, 32),
                seed=args.seed,
                status="gap",
            )
        except Exception as exc:
            sampled = []
            print(f"FEDERAL sample_error={type(exc).__name__} admitted=false formalized=false", flush=True)
        else:
            # Short statute-at-large scraps carry no formula. Prefer a sentence.
            rich = [row for row in sampled if len(str(row.get("text") or "").split()) >= 8]
            sampled = (rich or sampled)[: args.federal]
            print(f"FEDERAL sampled={len(sampled)} seed={args.seed} admitted=false formalized=false", flush=True)
        spans.extend(sampled)
    rows = generate_span_evidence(
        spans,
        lake_limit=args.lake_limit,
        lake_successes=args.lake_successes,
    )
    written = write_span_evidence_parquet(rows, args.output)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["consensus"] or "missing")] = counts.get(str(row["consensus"] or "missing"), 0) + 1
    print(
        "EVIDENCE "
        f"rows={written['row_count']} bytes={written['bytes']} sha256={written['sha256']} "
        f"consensus={json.dumps(counts, sort_keys=True)} "
        f"admitted=false formalized=false jsonl_written=false",
        flush=True,
    )
    for row in rows:
        formulas = json.loads(row["formulas_json"])
        predicates = [str(item.get("predicate") or "") for item in formulas[:4]]
        print(
            "ROW "
            f"id={row['source_span_id']} legal_id={row['legal_id']} status={row['status']} "
            f"consensus={row['consensus']} lake={row['lake_disposition']} lake_ok={row['lake_ok']} "
            f"cosine={row['cosine_similarity']} reconstruction={row['reconstruction_loss']} "
            f"compression={row['ir_compression_loss']} cross_entropy={row['cross_entropy_loss']} "
            f"measurements={row['measurements']} predicates={','.join(predicates)} "
            f"admitted=false formalized=false",
            flush=True,
        )
    receipt = publish_span_evidence(args.output, upload=args.upload)
    print(
        "PUBLISH "
        f"uploaded={str(bool(receipt['uploaded'])).lower()} dry_run={str(bool(receipt['dry_run'])).lower()} "
        f"repo={DEFAULT_REPOSITORY_ID} path={EVIDENCE_REPO_PATH} "
        f"admitted=false formalized=false",
        flush=True,
    )
    if not args.upload:
        return 0
    from huggingface_hub import hf_hub_download

    local = hf_hub_download(DEFAULT_REPOSITORY_ID, EVIDENCE_REPO_PATH, repo_type="dataset")
    import pyarrow.parquet as pq

    table = pq.read_table(local)
    missing = [name for name in rows[0] if name not in table.column_names] if rows else []
    remote = table.to_pylist()
    ids = {str(item["source_span_id"]) for item in remote}
    expected = {str(item["source_span_id"]) for item in rows}
    admitted = any(item["admitted"] or item["formalized"] for item in remote)
    print(
        "VERIFY "
        f"remote_rows={table.num_rows} columns={len(table.column_names)} missing={len(missing)} "
        f"ids_match={str(ids == expected).lower()} admitted={str(admitted).lower()} "
        f"formalized=false",
        flush=True,
    )
    return 0 if ids == expected and not missing and not admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
