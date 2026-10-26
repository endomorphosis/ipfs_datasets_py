#!/usr/bin/env python3
"""READ-ONLY build of state/dedup/old_urls.sqlite from older Hub datasets named ipfs_*_laws /
ipfs_*_municipal_laws (endomorphosis + justicedao) plus /workspace/old_urls.jsonl.
Only URL columns are read (parquet column projection over HfFileSystem). Writes to a .tmp db, then
os.replace() -> atomic.  Usage: build_old_url_index.py [--repos-file F] [--max-files-per-repo N]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, csv, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dedup_index as DX

URL_COLS = ("source_url", "url", "canonical_law_url", "official_url", "law_url", "original_url")
FORBIDDEN = {"endomorphosis/american_municipal_law"}
NAME = re.compile(r"^(endomorphosis|justicedao)/ipfs_[a-z0-9_]+_laws$")


def repos_from_inventory(p):
    out = []
    for r in csv.DictReader(open(p)):
        n = r["repo"]
        if NAME.match(n) and not n.endswith("_ir") and n not in FORBIDDEN and n not in ("world_municipal_law", "world_national_law"):
            out.append(n)
    return sorted(set(out))


def scan(repo, max_files):
    from huggingface_hub import HfApi, HfFileSystem
    import pyarrow.parquet as pq
    a, fs = HfApi(), HfFileSystem()
    res = {"repo": repo, "files": 0, "rows": 0, "urls": set(), "err": None}
    try:
        files = [f.path for f in a.list_repo_tree(repo, repo_type="dataset", recursive=True)
                 if f.path.endswith(".parquet") and "article" not in f.path.lower() and "chunk" not in f.path.lower()
                 and "embedding" not in f.path.lower()]
        for fp in sorted(files)[:max_files]:
            pf = pq.ParquetFile(fs.open(f"datasets/{repo}/{fp}"))
            cols = [c for c in URL_COLS if c in pf.schema_arrow.names]
            res["files"] += 1; res["rows"] += pf.metadata.num_rows
            if cols:
                t = pf.read(columns=cols)
                for c in cols:
                    for v in t.column(c).to_pylist():
                        n = DX.norm_url(v)
                        if n:
                            res["urls"].add(n)
    except Exception as e:  # noqa: BLE001
        res["err"] = repr(e)[:300]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default="/workspace/hf_inventory_endomorphosis_justicedao.csv")
    ap.add_argument("--seed", default="/workspace/old_urls.jsonl")
    ap.add_argument("--out", default=str(DX.OLD_URLS_DB))
    ap.add_argument("--max-files-per-repo", type=int, default=400)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip", nargs="*", default=[])
    a = ap.parse_args()
    out = Path(a.out); tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = DX.create_db(tmp, ["CREATE TABLE u(url TEXT PRIMARY KEY, repo TEXT) WITHOUT ROWID",
                             "CREATE TABLE repos(repo TEXT PRIMARY KEY, files INT, rows INT, urls INT, err TEXT, via TEXT)"])
    seeded = set()
    for line in open(a.seed):
        o = json.loads(line)
        urls = {DX.norm_url(u) for u in o.get("urls") or []} - {None}
        con.executemany("INSERT OR IGNORE INTO u VALUES(?,?)", [(u, o["repo"]) for u in sorted(urls)])
        con.execute("INSERT OR REPLACE INTO repos VALUES(?,?,?,?,?,?)", (o["repo"], o.get("files"), o.get("rows"), len(urls), o.get("err"), "old_urls.jsonl"))
        seeded.add(o["repo"])
    con.commit()
    todo = [r for r in repos_from_inventory(a.inventory) if r not in seeded and r not in a.skip]
    print(f"seeded {len(seeded)} repos; scanning {len(todo)} from the Hub", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(lambda x: scan(x, a.max_files_per_repo), todo):
            con.executemany("INSERT OR IGNORE INTO u VALUES(?,?)", [(u, r["repo"]) for u in sorted(r["urls"])])
            con.execute("INSERT OR REPLACE INTO repos VALUES(?,?,?,?,?,?)", (r["repo"], r["files"], r["rows"], len(r["urls"]), r["err"], "hub"))
            con.commit()
            print(f'{time.time()-t0:7.0f}s {r["repo"]} files={r["files"]} rows={r["rows"]} urls={len(r["urls"])} {r["err"] or ""}', flush=True)
    con.execute("VACUUM"); con.close()
    os.replace(tmp, out)
    print("done", out, flush=True)


if __name__ == "__main__":
    main()
