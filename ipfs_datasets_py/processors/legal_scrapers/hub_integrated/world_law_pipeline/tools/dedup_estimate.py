#!/usr/bin/env python3
"""DRY-RUN estimate of the NEW-row duplicate checks (xdedup.py). Read-only; writes only a JSON report.

staging : every file run_loop.discover() would pick up -> per country: rows, old_repo matches (both repos),
          cross_place pointers (municipal; vs published index + other staged places).  Upper bound: rows whose
          doc_id is already published in their place are not touched by the live check.
published: world_municipal_law rows already on the Hub (state/dedup/mun_published.sqlite sources:
          /workspace/mun_all.jsonl URLs + local out/ text hashes) and world_national_law rows
          (/workspace/nat_rows2.jsonl): extra copies across places and rows whose URL is in an old repo.
          COUNT ONLY - these published duplicates are not modified.
Usage: dedup_estimate.py [--out state/dedup/estimate_<ts>.json] [--skip-staging] [--skip-published]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, json, sys, time
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dedup_index as DX
import xdedup as XD
import schema as S
import run_loop as RL


def staging_pass(rep):
    files = [f for f in RL.discover(Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging")), 0, None) if not f.get("bad_name")]
    old = XD.OldRepoCheck()
    pub = DX.PubIndex()
    rows, oldm = Counter(), Counter()
    mun = []
    t0 = time.time()
    for f in files:
        kind = "national" if S.is_national_key(f["key"]) else "municipal"
        if kind == "municipal":
            mun.append((f["cc"], f["key"], f["path"]))
        for _, rec in RL._iter_staged_tolerant(f["path"]):
            if not isinstance(rec, dict):
                continue
            rows[(kind, f["cc"])] += 1
            if old.match(rec):
                oldm[(kind, f["cc"])] += 1
    print(f"staging: {len(files)} files, {sum(rows.values())} rows, old-repo scan {time.time()-t0:.0f}s", flush=True)
    st = Counter()
    plan = XD.plan_cross_place(mun, RL._iter_staged_tolerant, pub, stats=st)
    xp = Counter(); xk = Counter(); xpub = Counter()
    for (cc, key), d in plan.items():
        for did, p in d.items():
            xp[cc] += 1; xk[(cc, p["duplicate_key"])] += 1
            if p["duplicate_of"].count("/") >= 2 and pub.exists():
                pass
    rep["staging"] = {"files": len(files), "seconds": round(time.time() - t0),
                      "rows": {f"{k}/{c}": n for (k, c), n in sorted(rows.items())},
                      "old_repo": {f"{k}/{c}": n for (k, c), n in sorted(oldm.items())},
                      "cross_place": dict(sorted(xp.items())),
                      "cross_place_by_key": {f"{c}/{k}": n for (c, k), n in sorted(xk.items())},
                      "published_outranked_by_new_amt_rows": st.get("xdedup_published_outranked", 0)}


def published_pass(rep, mun_scan, nat_scan):
    old = DX.old_url_index()
    by_u = defaultdict(set); per_cc = Counter(); oldm = Counter(); seen = set()
    for fn in mun_scan:
        for line in open(fn):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ref = r.get("f", "")
            m = __import__("re").search(r"data/([A-Z]{2})/(?:[^/]+/)*?([^/]+?)(?:\.s\d{4,})?_html\.parquet$", ref)
            if not m:
                continue
            cc, key = m.group(1), m.group(2)
            k = (cc, key, r.get("did"))
            if k in seen:
                continue
            seen.add(k)
            per_cc[cc] += 1
            u = DX.norm_url(r.get("url"))
            if not u:
                continue
            by_u[u].add((cc, key))
            if old.get(u):
                oldm[cc] += 1
    xu = Counter()
    for u, places in by_u.items():
        if len(places) > 1:
            xu[sorted(places)[0][0]] += len(places) - 1
    by_u.clear()
    # text-hash duplicates across places among locally available published parquet
    import sqlite3
    xh = Counter()
    if DX.MUN_PUB_DB.exists():
        pass  # ph keeps one ref per hash; cross-place text dups are counted from local out below
    import pyarrow.parquet as pq
    th = defaultdict(set)
    for p in sorted(Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/world_law/data")).rglob("*_html.parquet")):
        m = __import__("re").search(r"data/([A-Z]{2})/(?:[^/]+/)*?([^/]+?)(?:\.s\d{4,})?_html\.parquet$", str(p))
        try:
            for b in pq.ParquetFile(str(p)).iter_batches(batch_size=512, columns=["text"]):
                for t in b.column(0).to_pylist():
                    h = DX.text_hash(t)
                    if h:
                        th[h].add((m.group(1), m.group(2)))
        except Exception:  # noqa: BLE001
            continue
    for h, places in th.items():
        if len(places) > 1:
            xh[sorted(places)[0][0]] += len(places) - 1
    th.clear()
    nat_old = Counter(); nat_rows = Counter(); nseen = set()
    for fn in nat_scan:
        for line in open(fn):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            m = __import__("re").search(r"data/([A-Z]{2})/", r.get("f", ""))
            if not m:
                continue
            cc = m.group(1)
            k = (r.get("f"), r.get("did"), r.get("url"), r.get("th"))
            if k in nseen:
                continue
            nseen.add(k)
            nat_rows[cc] += 1
            repo = old.get(DX.norm_url(r.get("url")))
            if repo and not (r.get("hf") and DX.repo_slug(r["hf"]) == DX.repo_slug(repo)):
                nat_old[cc] += 1
    rep["published"] = {"municipal_rows_scanned": per_cc, "municipal_cross_place_url_extra_copies": dict(xu),
                        "municipal_cross_place_texthash_extra_copies_local_out": dict(xh),
                        "municipal_url_in_old_repo": dict(oldm),
                        "national_rows_scanned": dict(nat_rows), "national_url_in_old_repo_not_own_import": dict(nat_old)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DX.STATE_DIR / f"estimate_{time.strftime('%Y%m%dT%H%M')}.json"))
    ap.add_argument("--skip-staging", action="store_true")
    ap.add_argument("--skip-published", action="store_true")
    ap.add_argument("--mun-scan", nargs="*", default=["/workspace/mun_all.jsonl"])
    ap.add_argument("--nat-scan", nargs="*", default=["/workspace/nat_rows2.jsonl"])
    a = ap.parse_args()
    rep = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if not a.skip_staging:
        staging_pass(rep)
        Path(a.out).write_text(json.dumps(rep, indent=1, default=dict))
    if not a.skip_published:
        published_pass(rep, a.mun_scan, a.nat_scan)
    Path(a.out).write_text(json.dumps(rep, indent=1, default=dict))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
