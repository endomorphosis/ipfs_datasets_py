#!/usr/bin/env python3
"""Lean memsafe encode for EE municipal IR (tip 9ef422a2a38a). Recipe = spain_encode_memsafe_ed0ac217106e.py:
pf.iter_batches(batch_size=512), BATCH 8, memmap work file. No collector shedding (mem.checkpoint not used).
Watchdog: MemAvail < 3500 MB -> abort (exit 3); the wrapper's trap removes PAUSE_CZ."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gc, json, os, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
import numpy as np
import pyarrow.parquet as pq

SLUG = "estonia_municipal"; TIP = "9ef422a2a38a8c35418e6b6f0192c87bb4130db2"; TS = TIP[:12]
BUILD = Path(f"/workspace/country-laws-ir/build/{SLUG}_{TS}")
CORPUS = BUILD / "cache" / f"{SLUG}_corpus_{TS}.parquet"
CKPT = BUILD / "cache" / "embeddings" / f"{SLUG}.npy"
RESULT = Path(f"/workspace/country-laws-ir/reports/{SLUG}_encode_{TS}_result.json")
CHUNK = 512; BATCH = 8; ABORT_MB = 3500; DIM = 384; MODEL = "thenlper/gte-small"
STATE = {"min_mb": 10**9, "abort": False}

def avail_mb() -> int:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return -1

def log(msg):
    print(f"[{datetime.now().astimezone().strftime('%H:%M:%S %Z')}] {msg}", flush=True)

def watchdog():
    while True:
        m = avail_mb(); STATE["min_mb"] = min(STATE["min_mb"], m)
        if 0 <= m < ABORT_MB:
            STATE["abort"] = True
            log(f"WATCHDOG ABORT MemAvail={m}MB < {ABORT_MB}MB")
            RESULT.write_text(json.dumps({"phase": "aborted_low_mem", "mem_mb": m, "min_mem_mb": STATE["min_mb"]}) + "\n")
            sys.stdout.flush(); os._exit(3)
        time.sleep(0.5)

def main() -> int:
    threading.Thread(target=watchdog, daemon=True).start()
    import torch
    torch.set_num_threads(4)
    from sentence_transformers import SentenceTransformer
    from numpy.lib.format import open_memmap
    pf = pq.ParquetFile(CORPUS); n = pf.metadata.num_rows
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    work = CKPT.with_name(CKPT.stem + ".work.npy")
    out = open_memmap(work, mode="w+", dtype=np.float32, shape=(n, DIM))
    log(f"encode start n={n} mem={avail_mb()}MB")
    model = SentenceTransformer(MODEL, device="cpu")
    cols = [c for c in ("title", "instrument_title", "body", "source_id", "instrument_id") if c in pf.schema_arrow.names]
    done = 0
    for rb in pf.iter_batches(batch_size=CHUNK, columns=cols):
        df = rb.to_pandas(); del rb
        texts = []
        for rec in df.itertuples(index=False):
            title = getattr(rec, "title", None) or getattr(rec, "instrument_title", "") or ""
            body = getattr(rec, "body", "") or ""
            sid = getattr(rec, "source_id", "") or getattr(rec, "instrument_id", "")
            texts.append(f"{title}\n{body[:4000]}".strip() or title or sid)
        parts = []
        for i in range(0, len(texts), BATCH):
            if STATE["abort"]: return 3
            parts.append(model.encode(texts[i:i + BATCH], batch_size=BATCH, show_progress_bar=False,
                                      convert_to_numpy=True, normalize_embeddings=True))
        emb = np.vstack(parts).astype(np.float32)
        out[done:done + len(emb)] = emb; done += len(emb); out.flush()
        log(f"encoded {done}/{n} mem={avail_mb()}MB min={STATE['min_mb']}MB")
        del df, texts, parts, emb; gc.collect()
    assert done == n, (done, n)
    out.flush(); del out; gc.collect()
    os.replace(work, CKPT)
    arr = np.load(CKPT, mmap_mode="r")
    ok = bool(arr.shape == (n, DIM) and np.isfinite(arr).all() and (np.abs(np.linalg.norm(arr, axis=1) - 1) < 1e-3).all())
    CKPT.with_suffix(".json").write_text(json.dumps({"n": n, "done": n, "dimension": DIM, "model_name": MODEL,
        "ts": datetime.now(timezone.utc).isoformat(), "via": "estonia_municipal_encode_memsafe"}) + "\n")
    res = {"country": SLUG, "tip": TIP, "corpus_n": n, "emb_done": done, "emb_ok": ok, "ckpt": str(CKPT),
           "min_mem_mb": STATE["min_mb"], "mem_end_mb": avail_mb(), "batch": BATCH, "chunk": CHUNK,
           "finished": datetime.now().astimezone().isoformat(), "phase": "encode_complete"}
    RESULT.write_text(json.dumps(res, indent=2) + "\n"); print(json.dumps(res, indent=2))
    return 0 if ok else 4

if __name__ == "__main__":
    raise SystemExit(main())
