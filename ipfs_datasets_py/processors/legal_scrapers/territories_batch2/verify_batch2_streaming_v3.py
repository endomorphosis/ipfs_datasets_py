#!/usr/bin/env python3
"""Verify staged Batch2 upload_ready* parquets with pyarrow + datasets streaming.
3.2 GiB MemAvailable floor (not 4.2). Skips packages with HOLD_DO_NOT_UPLOAD.md.
"""
from __future__ import annotations
import json, os, pathlib, resource, sys, time

sys.path.insert(0, "/workspace/staging/territories_batch2_20261105")
from batch2_common_v3 import (  # noqa: E402
    ROOT,
    guard,
    install_guard,
    mem_available_gib,
    peak_rss_mb,
    write_json_x,
)

install_guard()
guard("verify_start")

os.environ.update(
    MALLOC_ARENA_MAX="2",
    PYTHONDONTWRITEBYTECODE="1",
    USE_TORCH="0",
    USE_TF="0",
    USE_JAX="0",
    OPENBLAS_NUM_THREADS="1",
    OMP_NUM_THREADS="1",
    HF_DATASETS_OFFLINE="1",
    HF_HUB_OFFLINE="1",
)
tmpdir = ROOT / "validation_runtime"
tmpdir.mkdir(parents=True, exist_ok=True)
os.environ["HF_DATASETS_CACHE"] = str(tmpdir / "datasets_cache_v3")
os.environ["HF_HUB_CACHE"] = str(tmpdir / "hub_cache_v3")

import pyarrow.parquet as pq
from datasets import load_dataset

results = []
# Discover packages
packages = []
for code in ["BQ", "CX", "CC", "HM", "TK", "MP", "VI"]:
    for name in ["upload_ready_v2", "upload_ready", "local_review_only"]:
        p = ROOT / code / name
        if p.is_dir() and (p / "data").is_dir():
            packages.append((code, p))
# RO delta
ro = pathlib.Path("/workspace/staging/ro_id_delta_check_20261105")
if (ro / "data").is_dir():
    packages.append(("RO", ro))

for code, ready in packages:
    hold = (ready / "HOLD_DO_NOT_UPLOAD.md").exists() or (
        ready / "HOLD_RIGHTS_UNRESOLVED.md"
    ).exists()
    for p in sorted((ready / "data").glob("*.parquet")):
        guard(f"verify_{code}")
        md = pq.read_metadata(str(p))
        rows = md.num_rows
        if rows <= 0:
            raise SystemExit(f"ZERO_ROW_PARQUET {p}")
        # min text via streaming batches
        pf = pq.ParquetFile(str(p), pre_buffer=False, buffer_size=0)
        min_text = None
        text_col = "text" if "text" in pf.schema_arrow.names else None
        if text_col:
            for batch in pf.iter_batches(batch_size=32, columns=[text_col], use_threads=False):
                for t in batch.column(0).to_pylist():
                    n = len((t or "").strip())
                    min_text = n if min_text is None else min(min_text, n)
        ds = load_dataset("parquet", data_files=str(p), split="train", streaming=True)
        sample = 0
        for _ in ds:
            sample += 1
            if sample >= 5:
                break
        result = {
            "territory": code,
            "package": str(ready),
            "path": str(p),
            "pyarrow_rows": rows,
            "min_text_chars": min_text,
            "datasets_streaming_sample_rows": sample,
            "hold_do_not_upload": hold,
            "datasets_version": __import__("datasets").__version__,
        }
        results.append(result)
        print("VERIFIED", result, flush=True)

out = ROOT / "verified_datasets_streaming_v3.json"
if out.exists():
    out = ROOT / f"verified_datasets_streaming_v3_{int(time.time())}.json"
write_json_x(
    out,
    {
        "results": results,
        "peak_rss_mb": peak_rss_mb(),
        "mem_available_gib": mem_available_gib(),
        "completed_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    },
)
print("VALIDATION_DONE", len(results), "rss", peak_rss_mb(), flush=True)
