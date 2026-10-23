"""Move the flat world_law/{data,metadata}/<CC>/ files of hash-bucketed countries (schema.BUCKETED_COUNTRIES)
into world_law/{data,metadata}/<CC>/<b>/ on the Hub and in the local out/ tree.

Per batch of places, ONE Hub commit: data parquet -> CommitOperationCopy (server-side, no re-upload) + Delete of
the flat path; metadata JSON -> Add of the rewritten JSON (html_files point at the bucket paths) + Delete of the
flat JSON. Right after each commit the local tree follows (data moved, metadata rewritten with the SAME bytes as
uploaded, so out_store.evict's blob-id check still matches) and state/evicted_out.jsonl rels are rewritten (so
rehydrate / prune keep working). Every moved file is logged to state/bucket_migration.jsonl. Resumable: the plan
is re-derived from a fresh listing. Holds state/run_loop.lock (flock) for the whole run; stops before starting a
commit inside the hourly window (minutes --quiet-from..--quiet-to PT). Never touches american_municipal_law.

    python tools/migrate_buckets.py --dry-run          # counts + plan only
    python tools/migrate_buckets.py --apply [--cc FR] [--places-per-commit 200]
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import fcntl
import json
import os
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
import schema as S  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
FORBIDDEN = {"endomorphosis/american_municipal_law", "justicedao/american_municipal_law"}
LOG_NAME = "bucket_migration.jsonl"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _key_of(name: str) -> Optional[str]:
    if name.endswith(".json"):
        return name[:-5]
    if name.endswith("_html.parquet"):
        k = name[: -len("_html.parquet")]
        if ".s" in k and k.rsplit(".s", 1)[1].isdigit():
            k = k.rsplit(".s", 1)[0]
        return k
    return None


def plan_moves(hub_files: Iterable[str], cc: str) -> Dict[Tuple[str, str], Dict[str, List[Tuple[str, str]]]]:
    """{(cc, key): {"data": [(old, new)], "metadata": [(old, new)]}} for flat files of bucketed places."""
    plan: Dict[Tuple[str, str], Dict[str, List[Tuple[str, str]]]] = {}
    for f in sorted(hub_files):
        parts = f.split("/")
        if len(parts) != 4 or parts[0] != S.ROOT or parts[1] not in ("data", "metadata") or parts[2] != cc:
            continue
        key = _key_of(parts[3])
        if not key or not S.is_bucketed(cc, key):
            continue
        new = f"{S.place_dir(parts[1], cc, key)}/{parts[3]}"
        plan.setdefault((cc, key), {"data": [], "metadata": []})[parts[1]].append((f, new))
    return plan


def new_rel(rel: str, cc: str, key: str) -> str:
    """Flat rel of a bucketed place -> its bucket rel (other rels unchanged)."""
    parts = rel.split("/")
    if len(parts) == 4 and parts[0] == S.ROOT and parts[2] == cc and S.is_bucketed(cc, key):
        return f"{S.place_dir(parts[1], cc, key)}/{parts[3]}"
    return rel


def rewrite_meta_bytes(raw: bytes, cc: str, key: str) -> bytes:
    m = json.loads(raw.decode("utf-8"))
    m["html_files"] = [new_rel(r, cc, key) for r in (m.get("html_files") or [])]
    return (json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def rewrite_evicted(recs: List[dict], repo: str, places: Set[Tuple[str, str]]) -> Tuple[List[dict], int]:
    out, n = [], 0
    for r in recs:
        if r.get("repo") == repo and (r.get("cc"), r.get("place_key")) in places:
            nr = new_rel(r["rel"], r["cc"], r["place_key"])
            if nr != r["rel"]:
                r = {**r, "rel": nr, "rel_before_bucket": r["rel"]}
                n += 1
        out.append(r)
    return out, n


def git_blob_id_bytes(b: bytes) -> str:
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def list_cc(api, repo: str, cc: str) -> Dict[str, object]:
    """{path: RepoFile} of every file under world_law/data/<cc>/ and world_law/metadata/<cc>/ (recursive)."""
    out = {}
    for sub in ("data", "metadata"):
        try:
            for e in api.list_repo_tree(repo, path_in_repo=f"{S.ROOT}/{sub}/{cc}", recursive=True, repo_type="dataset"):
                if type(e).__name__ != "RepoFolder":
                    out[e.path] = e
        except Exception as e:  # noqa: BLE001
            if getattr(getattr(e, "response", None), "status_code", None) == 404:
                continue
            raise
    return out


def dir_counts(paths: Iterable[str]) -> Counter:
    return Counter(p.rsplit("/", 1)[0] for p in paths)


def summarize(paths, cc) -> Dict[str, int]:
    paths = list(paths)
    dc = dir_counts(paths)
    return {"data": sum(1 for p in paths if p.split("/")[1] == "data"),
            "metadata": sum(1 for p in paths if p.split("/")[1] == "metadata"),
            "flat_data": dc.get(f"{S.ROOT}/data/{cc}", 0), "flat_metadata": dc.get(f"{S.ROOT}/metadata/{cc}", 0),
            "bucket_dirs": sum(1 for d in dc if d.count("/") == 3), "max_dir": max(dc.values() or [0])}


def in_quiet_window(qfrom: int, qto: int, now: Optional[float] = None) -> bool:
    m = time.localtime(now).tm_min  # box clock is America/Los_Angeles
    return qfrom <= m < qto


def migrate_local_leftovers(out_dir: Path, ccs, still_flat_on_hub: Set[Tuple[str, str]], mig_log: Path) -> Counter:
    """Local-only flat files of bucketed countries (e.g. DIR_FULL-deferred places never uploaded): move into
    the bucket dirs and rewrite their metadata html_files. Places migrated on the Hub were handled per batch."""
    st = Counter()
    root = out_dir / S.ROOT
    for cc in ccs:
        for sub in ("data", "metadata"):
            d = root / sub / cc
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if not p.is_file():
                    continue
                key = _key_of(p.name)
                if not key or not S.is_bucketed(cc, key) or (cc, key) in still_flat_on_hub:
                    continue
                dst = out_dir / S.place_dir(sub, cc, key) / p.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if sub == "metadata":
                    dst.write_bytes(rewrite_meta_bytes(p.read_bytes(), cc, key))
                    p.unlink()
                else:
                    os.replace(p, dst)
                st[f"local_only_{sub}"] += 1
                with mig_log.open("a") as f:
                    f.write(json.dumps({"at": S.utc_now_iso(), "kind": "local_only", "cc": cc, "place_key": key,
                                        "old": str(p.relative_to(out_dir)), "new": str(dst.relative_to(out_dir))}) + "\n")
    return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=S.REPO_ID)
    ap.add_argument("--out", default=str(BASE / "out"))
    ap.add_argument("--state", default=str(BASE / "state"))
    ap.add_argument("--cc", action="append", help="default: every country in schema.BUCKETED_COUNTRIES")
    ap.add_argument("--places-per-commit", type=int, default=200, help="~4 ops per place")
    ap.add_argument("--max-commits", type=int, default=0)
    ap.add_argument("--quiet-from", type=int, default=25, help="no commit starts from this minute (PT) ...")
    ap.add_argument("--quiet-to", type=int, default=36, help="... to this minute (hourly run_loop window)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.repo in FORBIDDEN:
        raise SystemExit(f"refusing to touch {a.repo}")
    ccs = sorted(a.cc or S.BUCKETED_COUNTRIES)
    bad = [c for c in ccs if c not in S.BUCKETED_COUNTRIES]
    if bad:
        raise SystemExit(f"{bad} not in schema.BUCKETED_COUNTRIES; add them there first")
    out_dir, state = Path(a.out), Path(a.state)
    from huggingface_hub import HfApi, CommitOperationAdd, CommitOperationCopy, CommitOperationDelete, hf_hub_download
    import run_loop as RL
    lock_path = state / "run_loop.lock"
    lock = open(lock_path, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"run_loop.lock is held: {lock_path.read_text()[:300]}; not migrating")
        return 2
    RL._LOCK["f"] = lock
    RL._LOCK["info"] = {"pid": os.getpid(), "started_at": S.utc_now_iso(), "argv": ["migrate_buckets"] + sys.argv[1:]}
    RL.heartbeat(phase="migrate_buckets listing")
    api = HfApi()
    mig_log = state / LOG_NAME
    ev_path = state / "evicted_out.jsonl"
    report = {"repo": a.repo, "ccs": ccs, "before": {}, "after": {}, "commits": [], "moved": Counter(),
              "meta_downloaded": 0, "stopped": None}
    tmpd = Path(tempfile.mkdtemp(prefix="migb_", dir=str(state)))
    try:
        for cc in ccs:
            files = list_cc(api, a.repo, cc)
            report["before"][cc] = summarize(files, cc)
            log(f"{cc} before: {report['before'][cc]}")
            plan = plan_moves(files, cc)
            log(f"{cc}: {len(plan)} places to move")
            if a.dry_run or not a.apply:
                continue
            keys = sorted(plan)
            for i in range(0, len(keys), a.places_per_commit):
                if a.max_commits and len(report["commits"]) >= a.max_commits:
                    report["stopped"] = "max_commits"; break
                if in_quiet_window(a.quiet_from, a.quiet_to):
                    report["stopped"] = f"quiet window :{a.quiet_from}-:{a.quiet_to} PT"
                    log(f"stopping before a commit: {report['stopped']} (resumable)"); break
                batch = keys[i:i + a.places_per_commit]
                ops, meta_new, moves = [], {}, []
                for ck in batch:
                    _, key = ck
                    for old, new in plan[ck]["data"]:
                        ops.append(CommitOperationCopy(src_path_in_repo=old, path_in_repo=new))
                        ops.append(CommitOperationDelete(path_in_repo=old))
                        moves.append(("data", ck, old, new))
                    for old, new in plan[ck]["metadata"]:
                        loc = next((q for q in (out_dir / old, out_dir / new) if q.exists()), None)
                        raw = loc.read_bytes() if loc is not None else None
                        hub_blob = getattr(files[old], "blob_id", None)
                        if raw is None or git_blob_id_bytes(raw) != hub_blob:
                            raw = Path(hf_hub_download(a.repo, old, repo_type="dataset",
                                                       local_dir=str(tmpd))).read_bytes()
                            report["meta_downloaded"] += 1
                        body = rewrite_meta_bytes(raw, cc, key)
                        meta_new[new] = (body, old, loc)
                        ops.append(CommitOperationAdd(path_in_repo=new, path_or_fileobj=body))
                        ops.append(CommitOperationDelete(path_in_repo=old))
                        moves.append(("metadata", ck, old, new))
                RL.heartbeat(phase=f"migrate_buckets {cc} commit {len(report['commits']) + 1}")
                msg = (f"world_law: move {cc} into hash buckets ({len(batch)} places, {i + len(batch)}/{len(keys)}) "
                       f"[{RL._LOCK['info']['started_at']}]")
                c = RL.guarded_commit(api, 600, time.time() + 3600, f"migrate {cc}", repo_id=a.repo,
                                      repo_type="dataset", operations=ops, commit_message=msg)
                cid = getattr(c, "oid", None) or str(c.commit_url).rsplit("/", 1)[-1]
                report["commits"].append(cid)
                log(f"committed {len(ops)} ops ({cc} {i + len(batch)}/{len(keys)}): {cid}")
                # local tree follows the Hub, right away
                at = S.utc_now_iso()
                with mig_log.open("a") as lf:
                    for sub, ck, old, new in moves:
                        if sub == "data":
                            src, dst = out_dir / old, out_dir / new
                            if src.exists():
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                os.replace(src, dst)
                                report["moved"]["local_data"] += 1
                        else:
                            body, _old, loc = meta_new[new]
                            dst = out_dir / new
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            dst.write_bytes(body)
                            (out_dir / old).unlink(missing_ok=True)
                            report["moved"]["local_metadata"] += 1
                        report["moved"][f"hub_{sub}"] += 1
                        lf.write(json.dumps({"at": at, "repo": a.repo, "commit": cid, "cc": ck[0], "place_key": ck[1],
                                             "kind": sub, "old": old, "new": new}) + "\n")
                if ev_path.exists():
                    recs = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
                    recs, n = rewrite_evicted(recs, a.repo, set(batch))
                    if n:
                        tmp = ev_path.with_name(ev_path.name + ".tmp")
                        tmp.write_text("".join(json.dumps(r) + "\n" for r in recs))
                        os.replace(tmp, ev_path)
                        report["moved"]["evict_records"] += n
            if report["stopped"]:
                break
        still_flat: Set[Tuple[str, str]] = set()
        for cc in ccs:
            files = list_cc(api, a.repo, cc)
            report["after"][cc] = summarize(files, cc)
            still_flat |= set(plan_moves(files, cc))
            log(f"{cc} after: {report['after'][cc]}")
        if a.apply:  # local-only flat files; places still flat on the Hub keep their local flat files
            report["moved"].update(migrate_local_leftovers(out_dir, ccs, still_flat, mig_log))
            # reconcile eviction records of every bucketed place already moved on the Hub (also covers batches
            # whose local follow-up was lost, e.g. a killed run)
            if ev_path.exists():
                recs = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
                moved = {(r.get("cc"), r.get("place_key")) for r in recs if r.get("repo") == a.repo
                         and r.get("cc") in ccs} - still_flat
                recs, n = rewrite_evicted(recs, a.repo, moved)
                if n:
                    tmp = ev_path.with_name(ev_path.name + ".tmp")
                    tmp.write_text("".join(json.dumps(r) + "\n" for r in recs))
                    os.replace(tmp, ev_path)
                    report["moved"]["evict_records_reconciled"] = n
            # local metadata must be byte-identical to the Hub's (out_store.evict compares git blob ids)
            mism = 0
            for cc in ccs:
                hub = list_cc(api, a.repo, cc)
                for path, e in hub.items():
                    if path.split("/")[1] == "metadata" and (out_dir / path).exists():
                        from out_store import git_blob_id
                        mism += git_blob_id(out_dir / path) != getattr(e, "blob_id", None)
            report["local_metadata_blob_mismatch"] = mism
    finally:
        import shutil
        shutil.rmtree(tmpd, ignore_errors=True)
        RL.heartbeat(phase="migrate_buckets done")
    report["moved"] = dict(report["moved"])
    log("report " + json.dumps(report))
    with (state / "bucket_migration_runs.jsonl").open("a") as f:
        f.write(json.dumps({"at": S.utc_now_iso(), **report}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
