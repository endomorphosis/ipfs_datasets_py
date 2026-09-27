#!/usr/bin/env python3
"""Queue 51-jurisdiction statute spans, one DuckDB cache per state or territory.

Corpus rows with ``satisfies_exact_51_gate`` are partitioned by
``jurisdiction_code``. Several jurisdictions run at once. Each jurisdiction
owns its cache file, so workers do not share a DuckDB lock. A queued span is
not a legal admit. JSONL is not written.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

REPO = "justicedao/open-us-law-sparse-graphrag"
REVISION = "6a8b4c2938693e5bb004c3b48e85f53924eb856c"
HF_REPO = "justicedao/open-us-law-span-cache"
HF_PATH = "autoformal/statutes/state-span-manifest.parquet"


def _shards() -> list[str]:
    from huggingface_hub import HfApi

    names = HfApi().list_repo_files(REPO, repo_type="dataset", revision=REVISION)
    return sorted(name for name in names if name.startswith("data/corpus/part-") and name.endswith(".parquet"))


def partition_shard(job: tuple[str, str]) -> dict[str, int]:
    """Write one shard's gated rows into per-jurisdiction parquet parts."""

    import pyarrow as pa
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    shard, dest = job
    marker = Path(dest) / "_shards" / (Path(shard).stem + ".done")
    if marker.exists():
        return json.loads(marker.read_text(encoding="utf-8"))
    path = hf_hub_download(REPO, shard, repo_type="dataset", revision=REVISION)
    table = pq.read_table(
        path,
        columns=["entry_cid", "heading", "hierarchy", "jurisdiction_code", "legal_id", "release_point", "satisfies_exact_51_gate", "text"],
    )
    grouped: dict[str, list[dict]] = {}
    for row in table.to_pylist():
        if row.get("satisfies_exact_51_gate") is not True or not str(row.get("text") or "").strip():
            continue
        code = str(row.get("jurisdiction_code") or "").strip() or "UNKNOWN"
        hierarchy = row.get("hierarchy") or {}
        grouped.setdefault(code, []).append(
            {
                "canonical_citation": str(row.get("heading") or row.get("legal_id") or ""),
                "entry_cid": str(row.get("entry_cid") or ""),
                "jurisdiction_code": code,
                "legal_id": str(row.get("legal_id") or ""),
                "release_point": str(row.get("release_point") or ""),
                "section": str((hierarchy or {}).get("section") or ""),
                "text": str(row.get("text") or ""),
                "title": str((hierarchy or {}).get("title") or code),
            }
        )
    counts: dict[str, int] = {}
    for code, rows in grouped.items():
        folder = Path(dest) / "parts" / code
        folder.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), folder / f"{Path(shard).stem}.parquet")
        counts[code] = len(rows)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(counts), encoding="utf-8")
    print(f"PARTITION shard={shard} jurisdictions={len(counts)} admitted=false formalized=false", flush=True)
    return counts


def _parse_document(document: dict) -> list[dict]:
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import inventory_uscode_documents

    document = dict(document)
    document["release_id"] = REVISION
    ledger = inventory_uscode_documents([document], query="open-us-law-51", release_id=REVISION)
    return list(ledger.get("spans") or [])


def process_state(job: tuple[str, str]) -> dict[str, int | str | bool]:
    """Enqueue one jurisdiction. This process is the only writer of its cache."""

    code, dest = job
    import pyarrow.parquet as pq

    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    folder = Path(dest) / "states" / code
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "DONE"
    if done.exists():
        return json.loads(done.read_text(encoding="utf-8"))
    cache = SpanCache(folder / "span-cache.duckdb")
    documents = 0
    spans = 0
    try:
        parts = sorted((Path(dest) / "parts" / code).glob("*.parquet"))
        for part in parts:
            table = pq.read_table(part)
            rows = table.to_pylist()
            parsed: list[dict] = []
            for row in rows:
                parsed.extend(_parse_document(row))
                documents += 1
            spans += cache.enqueue(parsed)
        stats = cache.stats()
        receipt = {
            "admitted": False,
            "documents": documents,
            "formalized": False,
            "jurisdiction": code,
            "pending": stats["pending"],
            "sealed": stats["sealed"],
            "spans": spans,
        }
        done.write_text(json.dumps(receipt), encoding="utf-8")
        print(
            f"STATE jurisdiction={code} documents={documents} spans={spans} "
            f"pending={stats['pending']} admitted=false formalized=false",
            flush=True,
        )
        return receipt
    finally:
        cache.close()


def _write_manifest(receipts: list[dict], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "admitted": False,
            "documents": int(item.get("documents") or 0),
            "formalized": False,
            "jurisdiction": str(item.get("jurisdiction") or ""),
            "pending": int(item.get("pending") or 0),
            "sealed": int(item.get("sealed") or 0),
            "spans": int(item.get("spans") or 0),
        }
        for item in receipts
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--upload", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.autoformal.worker_budget import worker_budget

    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    workers = worker_budget()
    shards = _shards()
    print(
        f"START shards={len(shards)} workers={workers} gate=satisfies_exact_51_gate "
        f"admitted=false formalized=false",
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        counts = list(pool.map(partition_shard, [(shard, str(work)) for shard in shards], chunksize=1))
    codes = sorted({code for item in counts for code in item})
    print(f"JURISDICTIONS count={len(codes)} codes={','.join(codes)}", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        receipts = list(pool.map(process_state, [(code, str(work)) for code in codes], chunksize=1))
    manifest = work / "state-span-manifest.parquet"
    _write_manifest(receipts, manifest)
    uploaded = False
    if args.upload:
        try:
            from huggingface_hub import HfApi

            api = HfApi()
            api.create_repo(HF_REPO, repo_type="dataset", exist_ok=True)
            api.upload_file(
                path_or_fileobj=str(manifest),
                path_in_repo=HF_PATH,
                repo_id=HF_REPO,
                repo_type="dataset",
                commit_message="open us law spans by jurisdiction",
            )
            uploaded = True
        except Exception as exc:
            print(f"HF upload deferred error={type(exc).__name__}", flush=True)
    print(
        f"STAGE states_queued jurisdictions={len(receipts)} uploaded={str(uploaded).lower()} "
        f"manifest={manifest} admitted=false formalized=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
