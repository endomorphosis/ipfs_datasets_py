#!/usr/bin/env python3
"""Stage SI extract (no upload) + never-thin pre-check vs current hub tip. Streamed, low memory."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib, json, os, shutil, sys, time
from pathlib import Path
import pyarrow.parquet as pq
from huggingface_hub import HfApi

REPO = "endomorphosis/ipfs_slovenia_laws"
TIP = "93611719fbb1ee0a9f21051f8f74ed1a2cbb9f16"
SNAP = Path(f"/workspace/country-laws-ir/cache/hf/hub/datasets--endomorphosis--ipfs_slovenia_laws/snapshots/{TIP}")
WORK = _CORPORA / "si" / "extract"
TS = time.strftime("%Y%m%dT%H%M%S")
STAGE = Path(f"{_CORPORA}/hf-staging/ipfs_slovenia_laws_extract_{TS}")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    info = api.dataset_info(REPO, files_metadata=True)
    live_tip = info.sha
    live_files = {s.rfilename: s for s in info.siblings}
    shutil.copytree(SNAP, STAGE, symlinks=False)
    for q in STAGE.rglob("*"):
        q.chmod(0o755 if q.is_dir() else 0o644)
    shutil.copy2(WORK / "articles_merged.parquet", STAGE / "data" / "articles.parquet")
    shutil.copy2("/workspace/scripts/si_split_hub_text.py", STAGE / "scrapers" / "si_split_hub_text.py")
    st = json.loads((WORK / "split_stats.json").read_text())
    # never-thin
    chk = {"live_tip": live_tip, "tip_unchanged": live_tip == TIP}
    lf = live_files.get("data/laws.parquet")
    live_laws_sha = lf.lfs.sha256 if lf is not None and lf.lfs else None
    chk["laws_sha256_staged"] = sha(STAGE / "data" / "laws.parquet")
    chk["laws_sha256_live"] = live_laws_sha
    chk["laws_identical"] = chk["laws_sha256_staged"] == live_laws_sha
    staged_files = {str(p.relative_to(STAGE)) for p in STAGE.rglob("*") if p.is_file()}
    chk["files_removed"] = sorted(set(live_files) - staged_files)
    old = pq.ParquetFile(SNAP / "data" / "articles.parquet"); new = pq.ParquetFile(STAGE / "data" / "articles.parquet")
    n_old = old.metadata.num_rows; chk["old_rows"] = n_old; chk["new_rows"] = new.metadata.num_rows
    # first n_old rows byte-identical (streamed compare)
    it_new = new.iter_batches(batch_size=1000); buf = None; mism = 0; cmp_rows = 0
    old_ids = set()
    for ob in old.iter_batches(batch_size=1000):
        need = ob.num_rows; parts = []
        while need > 0:
            if buf is None or buf.num_rows == 0:
                buf = next(it_new)
            take = min(need, buf.num_rows); parts.append(buf.slice(0, take)); buf = buf.slice(take); need -= take
        for c in ob.schema.names:
            a = ob.column(c).to_pylist(); b = [x for p in parts for x in p.column(c).to_pylist()]
            mism += sum(1 for x, y in zip(a, b) if x != y)
        old_ids.update(ob.column("id").to_pylist()); cmp_rows += ob.num_rows
    chk["old_rows_compared"] = cmp_rows; chk["old_row_field_mismatches"] = mism
    new_ids = set(); dup_new = 0
    for nb in new.iter_batches(batch_size=5000, columns=["id"]):
        new_ids.update(nb.column("id").to_pylist())
    chk["old_ids_missing"] = len(old_ids - new_ids)
    chk["unique_ids_before"] = len(old_ids); chk["unique_ids_after"] = len(new_ids)
    chk["schema_equal"] = old.schema_arrow.equals(new.schema_arrow)
    chk["PASS"] = bool(chk["tip_unchanged"] and chk["laws_identical"] and not chk["files_removed"]
                       and mism == 0 and chk["old_ids_missing"] == 0 and chk["schema_equal"] and cmp_rows == n_old)
    meta = {"repo": REPO, "base_tip": TIP, "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "uploaded": False,
            "method": "local split of hub laws.text (uradni-list.si snapshot); no crawl", "split_stats": st, "never_thin": chk}
    (STAGE / "PACK_META.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps({"stage": str(STAGE), **chk}, indent=2))


if __name__ == "__main__":
    main()
