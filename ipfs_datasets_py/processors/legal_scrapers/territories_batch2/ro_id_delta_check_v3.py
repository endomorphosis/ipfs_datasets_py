#!/usr/bin/env python3
"""Offline RO ID-delta vs live endomorphosis/ipfs_romania_laws (streaming IDs only).
Leaves aml_ro untouched. Stages report + optional additive shard under
/workspace/staging/ro_id_delta_check_20261105/.
"""
from __future__ import annotations
import json, os, pathlib, sys, time

sys.path.insert(0, "/workspace/staging/territories_batch2_20261105")
from batch2_common_v3 import (  # noqa: E402
    copy_sanitized_script,
    guard,
    install_guard,
    mem_available_gib,
    peak_rss_mb,
    write_json_x,
    write_text_x,
)

install_guard()
guard("ro_start")

OUT = pathlib.Path("/workspace/staging/ro_id_delta_check_20261105")
OUT.mkdir(parents=True, exist_ok=True)
LOCAL_IDS = pathlib.Path("/workspace/staging/territories_batch2_20261105/raw/ro_local_ids.txt")
INSTR = pathlib.Path("/workspace/legal-corpora/ro/instruments")

# Load local IDs (already enumerated 81876)
local = set()
with LOCAL_IDS.open(encoding="utf-8") as f:
    for line in f:
        lid = line.strip()
        if lid:
            local.add(lid)
print("RO_LOCAL_IDS", len(local), "rss", peak_rss_mb(), flush=True)
guard("ro_after_local")

# Stream live HF IDs only
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("USE_TORCH", "0")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
# Allow network for HF streaming metadata/parquet footers
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("HF_DATASETS_OFFLINE", None)

live = set()
method = None
try:
    from datasets import load_dataset

    guard("ro_hf_stream_start")
    ds = load_dataset(
        "endomorphosis/ipfs_romania_laws",
        split="train",
        streaming=True,
    )
    # Prefer projecting id; datasets may still materialize other cols per row
    n = 0
    for row in ds:
        guard(f"ro_hf_{n}")
        rid = row.get("id")
        if rid:
            live.add(str(rid))
        n += 1
        if n % 5000 == 0:
            print("RO_HF_PROGRESS", n, "unique", len(live), "rss", peak_rss_mb(), flush=True)
    method = f"datasets.load_dataset streaming rows={n}"
except Exception as e:  # noqa: BLE001
    print("RO_HF_DATASETS_FAIL", e, flush=True)
    # Fallback: huggingface_hub list + parquet column projection via pyarrow
    try:
        from huggingface_hub import HfFileSystem
        import pyarrow.parquet as pq

        fs = HfFileSystem()
        files = [
            f
            for f in fs.glob("datasets/endomorphosis/ipfs_romania_laws/**/*.parquet")
            if "/data/" in f or f.endswith(".parquet")
        ]
        method = f"HfFileSystem parquet projection files={len(files)}"
        for fp in files:
            guard("ro_pq_file")
            # open via hf://
            pf = pq.ParquetFile(fs.open(fp), pre_buffer=False, buffer_size=0)
            # column projection
            cols = [c for c in pf.schema_arrow.names if c == "id"]
            if not cols:
                cols = [pf.schema_arrow.names[0]]
            for batch in pf.iter_batches(batch_size=512, columns=cols, use_threads=False):
                guard("ro_pq_batch")
                for v in batch.column(0).to_pylist():
                    if v is not None:
                        live.add(str(v))
            print("RO_HF_FILE", fp, "live", len(live), "rss", peak_rss_mb(), flush=True)
    except Exception as e2:  # noqa: BLE001
        write_json_x(
            OUT / "ro_delta_report.json",
            {
                "error": "could_not_stream_live_ids",
                "datasets_error": str(e),
                "hub_error": str(e2),
                "local_ids": len(local),
                "peak_rss_mb": peak_rss_mb(),
            },
        )
        raise SystemExit("RO_LIVE_ID_STREAM_FAILED")

only_local = sorted(local - live)
only_live = sorted(live - local)
print(
    "RO_DELTA",
    "local",
    len(local),
    "live",
    len(live),
    "only_local",
    len(only_local),
    "only_live",
    len(only_live),
    flush=True,
)

# Inspect only_local for valid full-text (>=100 chars)
net_new = []
stubs = []
for lid in only_local:
    guard("ro_inspect")
    # local files named like ro-49788.json
    candidates = [
        INSTR / f"{lid}.json",
        INSTR / f"{lid.replace('ro-', 'ro-')}.json",
    ]
    # also try if lid already has .json
    path = None
    for c in candidates:
        if c.exists():
            path = c
            break
    if path is None:
        # try glob-less direct
        alt = INSTR / f"{lid}.json"
        if alt.exists():
            path = alt
    if path is None:
        stubs.append({"id": lid, "reason": "missing_local_file"})
        continue
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as ex:  # noqa: BLE001
        stubs.append({"id": lid, "reason": f"json_error:{ex}"})
        continue
    text = (obj.get("text") or obj.get("body") or obj.get("content") or "").strip()
    if not text and isinstance(obj.get("articles"), list):
        text = "\n".join(
            str(a.get("text") or "") for a in obj["articles"] if isinstance(a, dict)
        ).strip()
    if len(text) >= 100:
        net_new.append(
            {
                "id": lid,
                "title": obj.get("title") or obj.get("name") or lid,
                "text": text,
                "jurisdiction_code": "RO",
                "country": "RO",
                "language": obj.get("language") or "ro",
                "source_url": obj.get("source_url") or obj.get("url"),
                "source_type": "local_ro_instruments_delta",
                "license": obj.get("license") or "see upstream Romanian official source provenance",
                "local_path": str(path),
            }
        )
    else:
        stubs.append({"id": lid, "reason": "short_or_empty", "text_len": len(text)})

report = {
    "local_ids": len(local),
    "live_ids": len(live),
    "method": method,
    "only_local_count": len(only_local),
    "only_live_count": len(only_live),
    "only_local_ids_sample": only_local[:50],
    "only_live_ids_sample": only_live[:50],
    "net_new_fulltext_ge100": len(net_new),
    "stubs_or_missing": len(stubs),
    "stubs_sample": stubs[:30],
    "aml_ro_touched": False,
    "peak_rss_mb": peak_rss_mb(),
    "mem_available_end_gib": mem_available_gib(),
    "completed_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
}
write_json_x(OUT / "ro_delta_report.json", report)

if net_new:
    import pyarrow as pa
    import pyarrow.parquet as pq

    data = OUT / "data"
    data.mkdir(parents=True, exist_ok=True)
    outp = data / "laws_ro_delta_20261105.parquet"
    if outp.exists():
        raise SystemExit("DELTA_PARQUET_EXISTS")
    pq.write_table(pa.Table.from_pylist(net_new), str(outp), compression="zstd")
    write_json_x(
        OUT / "validation.json",
        {
            "laws_rows": len(net_new),
            "min_law_text_chars": min(len(r["text"]) for r in net_new),
            "additive_shard": True,
            "target_hf_repo": "endomorphosis/ipfs_romania_laws",
            "push": "NOT_PUSHED",
        },
    )
    print("RO_DELTA_SHARD", len(net_new), flush=True)
else:
    write_text_x(
        OUT / "NO_ADDITIVE_SHARD.md",
        "No net-new valid full-text laws (>=100 chars) beyond live HF IDs. "
        "Four-row difference appears to be duplicates/stubs/missing — see ro_delta_report.json.\n",
    )
    print("RO_NO_ADDITIVE_SHARD", flush=True)

# Always stage scrapers_and_normalizers
for src in [
    pathlib.Path(__file__),
    pathlib.Path("/workspace/staging/territories_batch2_20261105/batch2_common_v3.py"),
]:
    copy_sanitized_script(src, OUT / "scrapers_and_normalizers" / src.name)

print("RO_DONE", report, flush=True)
