#!/usr/bin/env python3
"""Memsafe Estonia encode: stream texts from corpus parquet in chunks (no full texts list)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gc, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
sys.path.insert(0, "/workspace/country-laws-ir")

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from country_laws_ir.auth import configure_hf
from country_laws_ir.build import CACHE, REPORTS, _log, record_progress
from country_laws_ir.mem import MemAbort, checkpoint, mem_available_gib, rss_gib
from country_laws_ir.vectors import DIMENSION, MODEL_NAME, embeddings_available

SLUG = "estonia"
TIP = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
TIP_SHORT = TIP[:12]
CORPUS_CKPT = CACHE / f"{SLUG}_corpus_{TIP_SHORT}.parquet"
CKPT = CACHE / "embeddings" / f"{SLUG}_{TIP_SHORT}.npy"
LOG = Path(f"/workspace/country-laws-ir/reports/{SLUG}_encode_{TIP_SHORT}.log")
CHUNK = 4096
BATCH = 64


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # append if relaunch
    log_f = LOG.open("a", encoding="utf-8")

    class Tee:
        def write(self, d):
            sys.__stdout__.write(d); sys.__stdout__.flush()
            log_f.write(d); log_f.flush()
        def flush(self):
            sys.__stdout__.flush(); log_f.flush()

    sys.stdout = Tee(); sys.stderr = Tee()
    notes: list = []
    try:
        checkpoint("encode_memsafe_start", log=_log, notes=notes)
        if not embeddings_available():
            raise SystemExit("torch/ST unavailable")
        if not CORPUS_CKPT.is_file():
            raise SystemExit(f"missing corpus {CORPUS_CKPT}")
        n = int(pq.ParquetFile(CORPUS_CKPT).metadata.num_rows)
        _log(f"encode memsafe n={n} mem={mem_available_gib():.2f}G rss={rss_gib():.2f}G")
        CKPT.parent.mkdir(parents=True, exist_ok=True)
        meta_path = CKPT.with_suffix(".json")
        out = np.zeros((n, DIMENSION), dtype=np.float32)
        done = 0
        if CKPT.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if int(meta.get("n") or 0) == n:
                cached = np.load(CKPT)
                if cached.shape[0] <= n and cached.shape[1] == DIMENSION:
                    done = int(cached.shape[0])
                    out[:done] = cached.astype(np.float32, copy=False)
                    _log(f"embeddings resume {done}/{n}")
        if done >= n:
            _log("encode already complete")
        else:
            configure_hf()
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(MODEL_NAME, device="cpu")
            # column projection to limit RAM
            cols = [c for c in ("title", "instrument_title", "body", "source_id", "instrument_id", "document_index") if c in pq.read_schema(CORPUS_CKPT).names]
            # read in row-groups / batches aligned to document_index order
            pf = pq.ParquetFile(CORPUS_CKPT)
            # assume corpus already sorted by document_index 0..n-1
            # load only slices via pandas iloc after memory-map columns needed
            # Use iterative row-group read:
            row_cursor = 0
            for rg in range(pf.num_row_groups):
                table = pf.read_row_group(rg, columns=cols)
                df = table.to_pandas()
                del table
                # process in CHUNK sub-batches
                for start in range(0, len(df), CHUNK):
                    end = min(start + CHUNK, len(df))
                    global_start = row_cursor + start
                    global_end = row_cursor + end
                    if global_end <= done:
                        continue
                    local_from = max(0, done - global_start)
                    part = df.iloc[start + local_from : end]
                    texts = []
                    for rec in part.itertuples(index=False):
                        title = getattr(rec, "title", None) or getattr(rec, "instrument_title", "") or ""
                        body = getattr(rec, "body", "") or ""
                        sid = getattr(rec, "source_id", "") or getattr(rec, "instrument_id", "")
                        texts.append(f"{title}\n{body[:4000]}".strip() or title or sid)
                    if not texts:
                        continue
                    # encode in BATCH
                    emb_parts = []
                    for i in range(0, len(texts), BATCH):
                        emb_parts.append(model.encode(texts[i:i+BATCH], batch_size=BATCH, show_progress_bar=False, convert_to_numpy=True))
                    emb = np.vstack(emb_parts).astype(np.float32)
                    write_from = done
                    write_to = done + len(emb)
                    assert write_to <= n
                    out[write_from:write_to] = emb
                    done = write_to
                    # atomic-ish checkpoint
                    tmp = CKPT.with_suffix(".npy.tmp")
                    np.save(tmp, out[:done])
                    # np.save adds .npy; handle
                    if tmp.exists():
                        os.replace(tmp, CKPT)
                    elif Path(str(tmp) + ".npy").exists():
                        os.replace(str(tmp) + ".npy", CKPT)
                    meta_path.write_text(json.dumps({
                        "n": n, "done": done, "dim": DIMENSION, "model": MODEL_NAME,
                        "updated_utc": datetime.now(timezone.utc).isoformat(),
                    }) + "\n")
                    checkpoint(f"embeddings@{done}", row=done, log=_log, notes=notes)
                    _log(f"encoded {done}/{n} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
                    del texts, emb, emb_parts, part
                    gc.collect()
                row_cursor += len(df)
                del df
                gc.collect()
            # final save full
            np.save(CKPT.with_suffix(".npy.tmp"), out)
            # fix np.save naming
            tmp = Path(str(CKPT) + ".tmp.npy")
            if CKPT.with_suffix(".npy.tmp.npy").exists():
                os.replace(CKPT.with_suffix(".npy.tmp.npy"), CKPT)
            elif tmp.exists():
                os.replace(tmp, CKPT)
            else:
                np.save(str(CKPT).replace(".npy", ""), out)  # np.save adds .npy
            meta_path.write_text(json.dumps({
                "n": n, "done": n, "dim": DIMENSION, "model": MODEL_NAME,
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }) + "\n")
        result = {
            "country": SLUG,
            "corpus_n": n,
            "emb_done": n,
            "ckpt": str(CKPT),
            "corpus_ckpt": str(CORPUS_CKPT),
            "mem_end_gib": round(mem_available_gib(), 2),
            "rss_end_gib": round(rss_gib(), 2),
            "collectors_sigterm": notes,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "via": "estonia_encode_memsafe",
            "phase": "encode_complete",
        }
        (REPORTS / f"{SLUG}_encode_{TIP_SHORT}_result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
        record_progress({"event": "estonia_encode_done", "corpus_n": n, "tip": TIP_SHORT})
        print(json.dumps(result, indent=2, default=str))
        return 0
    except MemAbort as e:
        _log(f"abort: {e}")
        return 2
    finally:
        try:
            log_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
