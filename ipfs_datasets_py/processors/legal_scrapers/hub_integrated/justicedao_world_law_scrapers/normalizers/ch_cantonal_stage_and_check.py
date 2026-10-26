#!/usr/bin/env python3
"""Stage CH hub + cantonal append (NO upload) and never-thin pre-check vs hub tip. Streamed / chunked."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, hashlib, json, os, shutil, sys, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
from huggingface_hub import HfApi
REPO = "endomorphosis/ipfs_switzerland_laws"; TIP = "25cd3f9f14d6e6ee5453bb5ab36a9c2d6e8f8c1c"
SNAP = Path(f"/workspace/country-laws-ir/cache/hf/hub/datasets--endomorphosis--ipfs_switzerland_laws/snapshots/{TIP}")
PARSED = _CORPORA / "ch_cantonal" / "parsed"
TS = time.strftime("%Y%m%dT%H%M%S"); STAGE = Path(f"{_CORPORA}/hf-staging/ipfs_switzerland_laws_cantonal_{TS}")
CANTONS = sys.argv[1].split(",")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()
def mem_ok():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable"):
            if int(ln.split()[1]) <= 3.5 * 1024 * 1024: print("MEM GUARD stop"); sys.exit(3)
            return
def jsonl(p):
    with gzip.open(p, "rt") as f:
        for ln in f: yield json.loads(ln)
def merge(old_path, new_path, kind, old_ids):
    pf = pq.ParquetFile(old_path); schema = pf.schema_arrow
    w = pq.ParquetWriter(new_path, schema, compression="zstd")
    for i in range(pf.metadata.num_row_groups):
        w.write_table(pf.read_row_group(i)); mem_ok()
    added = {}; coll = 0; new_ids = set(); buf = []
    def flush():
        if buf: w.write_table(pa.Table.from_pylist(buf, schema=schema), row_group_size=2000); buf.clear(); mem_ok()
    for c in CANTONS:
        n = 0
        for r in jsonl(PARSED / f"{c}_{kind}.jsonl.gz"):
            if r["id"] in old_ids or r["id"] in new_ids: coll += 1; continue
            new_ids.add(r["id"]); buf.append(r); n += 1
            if len(buf) >= (500 if kind == "laws" else 5000): flush()
        added[c] = n
    flush(); w.close()
    return added, coll
def compare_prefix(old_path, new_path):
    old = pq.ParquetFile(old_path); new = pq.ParquetFile(new_path)
    it = new.iter_batches(batch_size=1000); buf = None; mism = 0; rows = 0; ids = set()
    for ob in old.iter_batches(batch_size=1000):
        need = ob.num_rows; parts = []
        while need > 0:
            if buf is None or buf.num_rows == 0: buf = next(it)
            t = min(need, buf.num_rows); parts.append(buf.slice(0, t)); buf = buf.slice(t); need -= t
        for col in ob.schema.names:
            a = ob.column(col).to_pylist(); b = [x for p in parts for x in p.column(col).to_pylist()]
            mism += sum(1 for x, y in zip(a, b) if x != y)
        ids.update(ob.column("id").to_pylist()); rows += ob.num_rows
    allnew = set()
    for nb in new.iter_batches(batch_size=20000, columns=["id"]): allnew.update(nb.column("id").to_pylist())
    return {"old_rows": old.metadata.num_rows, "new_rows": new.metadata.num_rows, "old_rows_compared": rows,
            "old_row_field_mismatches": mism, "old_ids_missing": len(ids - allnew), "unique_ids_before": len(ids),
            "unique_ids_after": len(allnew), "schema_equal": old.schema_arrow.equals(new.schema_arrow)}
def main():
    api = HfApi(token=os.environ.get("HF_TOKEN")); info = api.dataset_info(REPO, files_metadata=True)
    live_files = {s.rfilename: s for s in info.siblings}
    shutil.copytree(SNAP, STAGE, symlinks=False)
    for q in STAGE.rglob("*"): q.chmod(0o755 if q.is_dir() else 0o644)
    old_law_ids = set(pq.read_table(SNAP / "data/laws.parquet", columns=["id"]).column("id").to_pylist())
    old_art_ids = set(pq.read_table(SNAP / "data/articles.parquet", columns=["id"]).column("id").to_pylist())
    la, lc = merge(SNAP / "data/laws.parquet", STAGE / "data/laws.parquet", "laws", old_law_ids)
    aa, ac = merge(SNAP / "data/articles.parquet", STAGE / "data/articles.parquet", "articles", old_art_ids)
    for f in ["ch_cantonal_collect_lexwork.py", "ch_cantonal_collect_other.py", "ch_cantonal_parse_lexwork.py", "ch_cantonal_parse_other.py", "ch_cantonal_common.py"]:
        shutil.copy2(f"/workspace/scripts/{f}", STAGE / "scrapers" / f)
    chk = {"live_tip": info.sha, "tip_unchanged": info.sha == TIP}
    lf = live_files.get("data/laws.parquet"); chk["laws_sha256_live"] = lf.lfs.sha256 if lf and lf.lfs else None
    chk["laws_sha256_staged"] = sha(STAGE / "data/laws.parquet"); chk["laws_identical"] = chk["laws_sha256_staged"] == chk["laws_sha256_live"]
    af = live_files.get("data/articles.parquet"); chk["articles_sha256_live"] = af.lfs.sha256 if af and af.lfs else None
    chk["articles_sha256_staged"] = sha(STAGE / "data/articles.parquet")
    staged = {str(p.relative_to(STAGE)) for p in STAGE.rglob("*") if p.is_file()}
    chk["files_removed"] = sorted(set(live_files) - staged); chk["files_added"] = sorted(staged - set(live_files))
    chk["laws"] = compare_prefix(SNAP / "data/laws.parquet", STAGE / "data/laws.parquet")
    chk["articles"] = compare_prefix(SNAP / "data/articles.parquet", STAGE / "data/articles.parquet")
    chk["id_collisions_skipped"] = {"laws": lc, "articles": ac}
    ok = lambda d: d["old_row_field_mismatches"] == 0 and d["old_ids_missing"] == 0 and d["schema_equal"] and d["old_rows_compared"] == d["old_rows"] and d["new_rows"] >= d["old_rows"]
    chk["PASS"] = bool(chk["tip_unchanged"] and not chk["files_removed"] and ok(chk["laws"]) and ok(chk["articles"]) and lc == 0 and ac == 0)
    meta = {"repo": REPO, "base_tip": TIP, "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "uploaded": False,
            "method": "append-only: federal rows first and unchanged, cantonal rows appended (jurisdiction CH-<canton>)",
            "cantonal_laws_added": la, "cantonal_articles_added": aa, "never_thin": chk}
    (STAGE / "PACK_META.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps({"stage": str(STAGE), **meta}, indent=2, ensure_ascii=False))
if __name__ == "__main__": main()
