#!/usr/bin/env python3
"""Evict local data parquet of out/ and out_national/ that is verified identical on the Hub and >= 2h old.

Standalone: evict_out.py [--dry-run|--apply] [--min-age-hours 2]  (takes the run_loop flock, waiting for a running
run_loop to finish; run_loop calls out_store.evict() itself after prune while already holding it).
See out_store.py for the checks and the rehydrate path that brings evicted files back on demand.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse, fcntl, json, os, sys, time
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "tools"))
import schema as S  # noqa: E402
import out_store as OST  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))


def evict_all(state: Path, out_dir: Path, out_national: Path, repo: str, national_repo: str, api, apply: bool,
              min_age_s: float = OST.MIN_AGE_S, log=print):
    import prune_processed as PP
    cache = PP.ShaCache(state / "prune_out_sha_cache.json")
    res = {}
    try:
        res["municipal"] = OST.evict(out_dir, repo, state, api, min_age_s, apply, sha_cache=cache, national=False, log=log)
        res["national"] = OST.evict(out_national, national_repo, state, api, min_age_s, apply, sha_cache=cache,
                                    national=True, log=log)
    finally:
        cache.save()
    res["bytes_evicted"] = sum(r.get("bytes_evicted", 0) for r in res.values() if isinstance(r, dict))
    res["eligible_bytes"] = sum(r.get("eligible_bytes", 0) for r in res.values() if isinstance(r, dict))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--min-age-hours", type=float, default=OST.MIN_AGE_S / 3600)
    ap.add_argument("--wait-lock", type=float, default=3600)
    a = ap.parse_args(argv)
    state = BASE / "state"
    lock = open(state / "run_loop.lock", "a")  # same flock as run_loop / prune_processed
    t0 = time.time()
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() - t0 > a.wait_lock:
                print("run_loop lock busy; giving up")
                return 2
            time.sleep(10)
    try:
        from huggingface_hub import HfApi
        res = evict_all(state, BASE / "out", BASE / "out_national", S.REPO_ID, S.NATIONAL_REPO_ID, HfApi(),
                        apply=a.apply, min_age_s=a.min_age_hours * 3600)
        res["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with (state / "evict_runs.jsonl").open("a") as f:
            f.write(json.dumps(res) + "\n")
        print(json.dumps({k: res[k] for k in ("bytes_evicted", "eligible_bytes")}))
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
