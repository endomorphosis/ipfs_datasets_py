#!/usr/bin/env python3
"""READ-ONLY build of state/dedup/mun_published.sqlite: source URL + text hash of already-published
world_municipal_law rows -> "<CC>/<place_key>/<doc_id>".
Sources: a Hub row scan JSONL (default /workspace/mun_all.jsonl: {"f","url","did"}) for URLs, and the
local out/ parquet (text available) for URLs + text hashes.  First ref per key wins, local parquet in
sorted order.  Written to .tmp then os.replace().
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, json, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dedup_index as DX
import pyarrow.parquet as pq

_F = re.compile(r"data/([A-Z]{2})/(?:[^/]+/)*?([^/]+?)(?:\.s\d{4,})?_html\.parquet$")


def ref_of(path, did):
    m = _F.search(path)
    return f"{m.group(1)}/{m.group(2)}/{did}" if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", nargs="*", default=["/workspace/mun_all.jsonl"])
    ap.add_argument("--out-root", default=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/world_law/data"))
    ap.add_argument("--out", default=str(DX.MUN_PUB_DB))
    a = ap.parse_args()
    out = Path(a.out); tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = DX.create_db(tmp, ["CREATE TABLE pu(url TEXT PRIMARY KEY, ref TEXT) WITHOUT ROWID",
                             "CREATE TABLE ph(th TEXT PRIMARY KEY, ref TEXT) WITHOUT ROWID",
                             "CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)"])
    n_local = n_scan = 0
    for p in sorted(Path(a.out_root).rglob("*_html.parquet")):
        try:
            pf = pq.ParquetFile(str(p))
        except Exception as e:  # noqa: BLE001
            print("skip", p, e); continue
        cols = [c for c in ("doc_id", "source_url", "text") if c in pf.schema_arrow.names]
        for b in pf.iter_batches(batch_size=512, columns=cols):
            U, H = [], []
            for r in b.to_pylist():
                ref = ref_of(str(p), r.get("doc_id"))
                if not ref:
                    continue
                u = DX.norm_url(r.get("source_url")); h = DX.text_hash(r.get("text"))
                if u: U.append((u, ref))
                if h: H.append((h, ref))
                n_local += 1
            con.executemany("INSERT OR IGNORE INTO pu VALUES(?,?)", U)
            con.executemany("INSERT OR IGNORE INTO ph VALUES(?,?)", H)
        con.commit()
    for s in a.scan:
        if not os.path.exists(s):
            continue
        U = []
        for line in open(s):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ref = ref_of(r.get("f", ""), r.get("did"))
            u = DX.norm_url(r.get("url"))
            if ref and u:
                U.append((u, ref)); n_scan += 1
            if len(U) >= 50000:
                con.executemany("INSERT OR IGNORE INTO pu VALUES(?,?)", U); U = []
        con.executemany("INSERT OR IGNORE INTO pu VALUES(?,?)", U); con.commit()
    con.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", [("local_rows", str(n_local)), ("scan_rows", str(n_scan)),
                                                                 ("built_at", __import__("datetime").datetime.now().isoformat())])
    con.commit(); con.execute("VACUUM"); con.close()
    os.replace(tmp, out)
    print("done", out, "local_rows", n_local, "scan_rows", n_scan)


if __name__ == "__main__":
    main()
