"""Sweep step 1 (local): scan law-row files in staging/*, out/*, out_national/*, processed/* (read-only) for PDF-like docs
with empty/near-empty text. Output: staging/pdf/_state/sweep_work/local_rows.jsonl (newest version per (place_id, doc_id))."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import gzip, json, os, re, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
import sweep_common as S

PAT = re.compile(rb"(?i)pdf")
ROOTS = ["staging", "out", "out_national", "processed"]
SKIP_TOP = {"staging/pdf", "staging/ocr", "processed/ocr"}

def files():
    for root in ROOTS:
        for dp, dns, fns in os.walk(S.WL / root):
            rel = os.path.relpath(dp, S.WL)
            dns[:] = [d for d in dns if not d.startswith((".", "_")) and f"{rel}/{d}" not in SKIP_TOP and d != "__pycache__"]
            for fn in fns:
                if fn.startswith(("_", ".")): continue
                if fn.endswith((".jsonl", ".jsonl.gz", ".parquet")): yield os.path.join(dp, fn)

def row_out(r, tl, f, mt):
    u = S.pdf_url(r)
    if not u: return None
    why = S.classify(r, tl)
    o = {"k": [r.get("place_id"), r.get("doc_id")], "mt": mt, "f": f}
    if why:
        o.update(doc_id=r["doc_id"], place_id=r["place_id"], country_code=r.get("country_code"), source_url=r.get("source_url"),
                 pdf_url=u, archive_url=r.get("archive_url"), original_url=r.get("original_url"),
                 source_policy=r.get("source_policy"), content_complete=r.get("content_complete"), text_len=tl, why=why)
    return o

def scan(f):
    out = []
    try:
        mt = os.path.getmtime(f)
        if f.endswith(".parquet"):
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(f); names = set(pf.schema_arrow.names)
            if not {"doc_id", "place_id", "source_url"} <= names: return out
            cols = [c for c in ("doc_id", "place_id", "country_code", "source_url", "original_url", "archive_url", "content_format",
                                "content_complete", "source_policy", "pdf_ref", "extra_metadata", "text") if c in names]
            for g in range(pf.num_row_groups):
                t = pf.read_row_group(g, columns=cols)
                import pyarrow.compute as pc
                tl = pc.utf8_length(t.column("text")).to_pylist() if "text" in names else [0] * t.num_rows
                t = t.drop(["text"]) if "text" in names else t
                for r, n in zip(t.to_pylist(), tl):
                    if r.get("doc_id") and r.get("place_id"):
                        o = row_out(r, n or 0, f, mt)
                        if o: out.append(o)
            return out
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rb") as fh:
            for ln in fh:
                if not PAT.search(ln): continue
                try: r = json.loads(ln)
                except ValueError: continue
                if not isinstance(r, dict) or not r.get("doc_id") or not r.get("place_id") or not r.get("source_url"): continue
                if "text" not in r and "content_format" not in r: continue      # not a law row (queue/log)
                o = row_out(r, len((r.get("text") or "").strip()), f, mt)
                if o: out.append(o)
    except Exception as x:  # noqa
        out.append({"err": f, "x": repr(x)[:200]})
    return out

if __name__ == "__main__":
    os.nice(10)
    fl = list(files()); print("files", len(fl), flush=True)
    best = {}; errs = 0
    with Pool(3, maxtasksperchild=200) as p:
        for i, res in enumerate(p.imap_unordered(scan, fl, chunksize=8)):
            for o in res:
                if "err" in o: errs += 1; continue
                k = tuple(o["k"])
                if k not in best or o["mt"] >= best[k]["mt"]: best[k] = o
            if i % 2000 == 0: print(i, len(best), flush=True)
    S.WORK.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(S.WORK / "local_rows.jsonl.tmp", "w") as w:
        for o in best.values():
            if "why" in o: w.write(json.dumps(o, ensure_ascii=False) + "\n"); n += 1
    os.replace(S.WORK / "local_rows.jsonl.tmp", S.WORK / "local_rows.jsonl")
    print("pdf_like", len(best), "candidates", n, "errors", errs, flush=True)
