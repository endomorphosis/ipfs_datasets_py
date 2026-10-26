#!/usr/bin/env python3
"""Verified pruning of processed/ staging sources (+ per-bot confirmed_batches lists).

A file processed/<bot>/<CC>/<name>[.gz] is deleted only when ALL hold:
  1. <bot> is in the configured list (state/prune_config.json {"bots": [...]}; fallback DEFAULT_BOTS = all lanes:
     eu national web asia_latam afme sasia_ru eap ph ocr id_jdih states ukie (id_jdih/states/ukie added 2026-10-17)).
  2. Its content sha256 (of the decompressed bytes for .gz) matches a ledger entry for the same
     bot/CC/name, and that ledger entry is >= MIN_AGE_H (default 2h, i.e. >= 2 hourly cycles) old.
  3. The commit that included its place landed: the first non-dry run summary in state/runs.jsonl at or
     after the ledger timestamp (or the entry's own commit_ids, for ledger lines written since 2026-10-11)
     has a commit id for that repo, and that id is in the Hub repo's commit history.
  4. Every parquet currently built for its place (local out/ or out_national/ data/<CC>/<key>*_html.parquet,
     at least one) exists on the Hub (routing: iso_* -> national repo) with the same sha256 and size.
Before a delete a line goes to state/pruned_manifest.jsonl (bot, path, sha256, bytes, rows, doc_ids hash,
place_key, hub commit, hub files+sha); the ledger is never touched, so a re-staged identical file is
still skipped by run_loop (ledger key bot+rel+sha256).
Files that pass checks 2-4 (any age) are listed in state/confirmed_batches/<bot>.jsonl so scraper lanes
know which of their own working/raw files for those batches they may remove.

Standalone: prune_processed.py [--dry-run|--apply]  (takes the run_loop lock; run_loop calls prune()
itself while already holding it).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse, collections, fcntl, gzip, hashlib, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
import schema as S  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
# fallback only when state/prune_config.json is missing (the config is the source of truth)
DEFAULT_BOTS = ["eu", "national", "web", "asia_latam", "afme", "sasia_ru", "eap", "ph", "ocr", "id_jdih", "states", "ukie"]
MIN_AGE_H = 2.0
_FNAME = re.compile(r"^(?P<key>[A-Za-z0-9_\-]+)(?:\.(?P<batch>[^/]+?))?\.(?:jsonl|parquet)$")
_SUFFIX = re.compile(r"\.(jsonl|parquet)(?:\.\d{8}T\d{6}Z(?:\.\d+)?)?$")  # move_unique collision suffix


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> float:
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def load_config(state: Path) -> Dict[str, Any]:
    p = state / "prune_config.json"
    if not p.exists():
        cfg = {"bots": DEFAULT_BOTS, "min_age_hours": MIN_AGE_H,
               "note": "bots whose processed/ files may be pruned; asia_latam and web excluded until their "
                       "bots confirm (jp/reemit_d1law.py, arch/pe_pdf.py, arch/policy_reemit.py, web/robots_audit.py)"}
        p.write_text(json.dumps(cfg, indent=2) + "\n")
    cfg = json.loads(p.read_text())
    cfg.setdefault("bots", DEFAULT_BOTS)
    cfg.setdefault("min_age_hours", MIN_AGE_H)
    return cfg


def original_name(name: str) -> str:
    """processed file name -> staged name (strip .gz and move_unique's .<ts>[.<i>] suffix)."""
    if name.endswith(".gz"):
        name = name[:-3]
    return _SUFFIX.sub(lambda m: "." + m.group(1), name)


def open_bytes(p: Path):
    return gzip.open(p, "rb") if p.name.endswith(".gz") else p.open("rb")


def content_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open_bytes(p) as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class ShaCache:
    """sha256 cache keyed by (path, size, mtime_ns) so hourly runs don't re-hash GBs."""
    def __init__(self, path: Path):
        self.path, self.d, self.dirty = path, {}, False
        try:
            self.d = json.loads(path.read_text())
        except Exception:
            self.d = {}

    def get(self, p: Path, fn) -> str:
        st = p.stat()
        k = str(p)
        sig = [st.st_size, st.st_mtime_ns]
        e = self.d.get(k)
        if e and e[:2] == sig:
            return e[2]
        v = fn(p)
        self.d[k] = sig + [v]
        self.dirty = True
        return v

    def save(self, keep: Optional[set] = None):
        if keep is not None:
            self.d = {k: v for k, v in self.d.items() if k in keep}
            self.dirty = True
        if self.dirty:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d))
            tmp.replace(self.path)


def rows_and_doc_hash(p: Path):
    ids = []
    if original_name(p.name).endswith(".parquet"):
        import pyarrow.parquet as pq
        t = pq.read_table(p, columns=["doc_id"])
        ids = [str(x) for x in t.column("doc_id").to_pylist()]
    else:
        with open_bytes(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        ids.append(str(json.loads(line).get("doc_id")))
                    except Exception:
                        ids.append("<unparseable>")
    return len(ids), hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


_LEDGER_KEEP = ("bot", "rel", "sha256", "rows", "at", "repo", "commit_ids")


def load_ledger_index(state: Path, wanted: Optional[set] = None):
    """(bot, rel) -> [entry]. Streams the (300+ MB) ledger and, when `wanted` is given, keeps only those keys
    (and only the fields prune needs): the old full in-memory index peaked at >2.5 GB RSS (OOM 2026-10-14)."""
    idx = collections.defaultdict(list)  # (bot, rel) -> [entry]
    rels = {json.dumps(r)[1:-1] for _, r in wanted} if wanted is not None else None  # as encoded in the line
    with (state / "ledger.jsonl").open() as f:
        for line in f:
            if rels is not None:
                i = line.find('"rel": "')
                if i >= 0:
                    j = line.find('"', i + 8)
                    if line[i + 8:j] not in rels:
                        continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            k = (e["bot"], e["rel"])
            if wanted is not None and k not in wanted:
                continue
            idx[k].append({x: e[x] for x in _LEDGER_KEEP if x in e} if wanted is not None else e)
    return idx


def _ckey(rel: str, sha: str, encoded: bool = False) -> bytes:
    if not encoded:
        rel = json.dumps(rel)[1:-1]
    return hashlib.blake2b(f"{rel}\0{sha}".encode(), digest_size=16).digest()


def merge_confirmed(path: Path, recs: List[Dict[str, Any]], apply: bool):
    """Add new confirmed records to a confirmed_batches/<bot>.jsonl (append-only, deduped on (rel, sha256)).
    Streaming: only 16-byte key digests of the existing (200+ MB) file are held in memory, and the file is only
    appended to (one fsync'd write), never rewritten. Records are no longer globally sorted. Returns (total, added)."""
    seen = set()
    n = 0
    if path.exists():
        with path.open() as f:
            for line in f:
                i = line.find('"rel": "')
                j = line.find('"sha256": "')
                try:
                    if i < 0 or j < 0:
                        raise ValueError
                    k = _ckey(line[i + 8:line.index('"', i + 8)], line[j + 11:line.index('"', j + 11)], True)
                except ValueError:
                    try:
                        r = json.loads(line)
                        k = _ckey(r["rel"], r["sha256"])
                    except Exception:
                        continue
                seen.add(k)
                n += 1
    out = []
    for r in recs:
        k = _ckey(r["rel"], r["sha256"])
        if k in seen:
            continue
        seen.add(k)
        out.append(json.dumps({**r, "confirmed_at": utc_now_iso()}) + "\n")
    if apply and out:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write("".join(out))
            f.flush()
            os.fsync(f.fileno())
    return n + len(out), len(out)


def load_runs(state: Path):
    runs = []
    p = state / "runs.jsonl"
    if p.exists():
        for line in p.open():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("dry_run") and r.get("at"):
                runs.append((parse_iso(r["at"]), r))
    runs.sort(key=lambda x: x[0])
    return runs


def commit_for(entry: Dict[str, Any], runs) -> Optional[str]:
    """The commit that carried this ledger entry's place (own field, else the run that wrote it)."""
    repo = entry.get("repo") or S.REPO_ID
    if entry.get("commit_ids"):
        return entry["commit_ids"][-1]
    t = parse_iso(entry["at"])
    for ts, r in runs:
        if ts + 1 >= t:
            ids = (r.get("commit_ids_by_repo") or {}).get(repo) or (r.get("commit_ids") if r.get("repo") == repo else None)
            return ids[-1] if ids else None
    return None


def local_parquets(out_dir: Path, cc: str, key: str) -> List[Path]:
    return S.local_place_files(out_dir, cc, key)  # flat and bucketed layouts


class Hub:
    """Read-only Hub lookups (commit history + per-path lfs sha256/size), cached per call of prune()."""
    def __init__(self, api):
        self.api, self.commits, self.info = api, {}, {}

    def has_commit(self, repo: str, cid: str) -> bool:
        if repo not in self.commits:
            self.commits[repo] = {c.commit_id for c in self.api.list_repo_commits(repo, repo_type="dataset")}
        return cid in self.commits[repo]

    def prefetch(self, repo: str, paths: List[str]):
        need = [p for p in paths if (repo, p) not in self.info]
        for i in range(0, len(need), 200):
            chunk = need[i:i + 200]
            for x in chunk:
                self.info[(repo, x)] = None
            for it in self.api.get_paths_info(repo, chunk, repo_type="dataset", expand=True):
                lfs = getattr(it, "lfs", None)
                if lfs is not None:
                    self.info[(repo, it.path)] = (lfs.sha256, lfs.size)

    def file(self, repo: str, path: str):
        if (repo, path) not in self.info:
            self.prefetch(repo, [path])
        return self.info[(repo, path)]


def prune(base: Path = BASE, state: Optional[Path] = None, out_dir: Optional[Path] = None,
          out_national: Optional[Path] = None, processed: Optional[Path] = None, repo: str = S.REPO_ID,
          national_repo: str = S.NATIONAL_REPO_ID, apply: bool = False, api=None, now: Optional[float] = None,
          log=print) -> Dict[str, Any]:
    state = state or base / "state"
    out_dir = out_dir or base / "out"
    out_national = out_national or out_dir.parent / "out_national"
    processed = processed or base / "processed"
    now = now or time.time()
    cfg = load_config(state)
    bots, min_age = list(cfg["bots"]), float(cfg["min_age_hours"]) * 3600
    runs = load_runs(state)
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi()
    hub = Hub(api)
    src_cache = ShaCache(state / "prune_sha_cache.json")
    out_cache = ShaCache(state / "prune_out_sha_cache.json")
    st = collections.Counter()
    found = []
    for bot in bots:
        bdir = processed / bot
        if not bdir.is_dir():
            continue
        for cc_dir in sorted(bdir.iterdir()):
            if not cc_dir.is_dir():
                continue
            for p in sorted(cc_dir.iterdir()):
                if not p.is_file():
                    continue
                st["files_seen"] += 1
                orig = original_name(p.name)
                m = _FNAME.match(orig)
                if not m:
                    st["skip_bad_name"] += 1
                    continue
                found.append((bot, cc_dir.name, m.group("key"), p, orig))
    ledger = load_ledger_index(state, wanted={(b, f"{b}/{cc}/{o}") for b, cc, _k, _p, o in found})
    cands = []
    for bot, cc, key, p, orig in found:
        entries = ledger.get((bot, f"{bot}/{cc}/{orig}"))
        if not entries:
            st["skip_no_ledger"] += 1
            continue
        cands.append((bot, cc, key, p, orig, entries))
    del found, ledger
    # group per place to batch Hub lookups
    confirmed = collections.defaultdict(list)
    places = collections.defaultdict(list)
    for c in cands:
        places[(c[1], c[2])].append(c)
    place_ok: Dict = {}
    by_repo_paths = collections.defaultdict(list)
    place_files = {}
    import out_store as OST
    evicted = OST.load_evicted(state)
    for (cc, key) in places:
        nat = S.is_national_key(key)
        od, rp = (out_national, national_repo) if nat else (out_dir, repo)
        files = local_parquets(od, cc, key)
        if not files:
            # local parquet evicted (verified identical on the Hub): the eviction record's sha256/size stands in
            # for the local file, for exactly the files the current metadata JSON lists
            try:
                listed = json.loads((od / S.metadata_path(cc, key)).read_text()).get("html_files") or []
            except Exception:
                listed = []
            if listed and all((rp, r) in evicted and not (od / r).exists() for r in listed):
                files = [("evicted", r, evicted[(rp, r)]) for r in listed]
        place_files[(cc, key)] = (rp, od, files)
        by_repo_paths[rp] += [f[1] if isinstance(f, tuple) else str(f.relative_to(od)) for f in files]
    for rp, paths in by_repo_paths.items():
        hub.prefetch(rp, paths)
    for (cc, key), (rp, od, files) in place_files.items():
        if not files:
            place_ok[(cc, key)] = (False, "no_local_parquet", [])
            continue
        hf, ok, why = [], True, ""
        for f in files:
            if isinstance(f, tuple):
                rel, size, local_sha = f[1], f[2]["bytes"], f[2]["sha256"]
            else:
                rel, size = str(f.relative_to(od)), f.stat().st_size
                local_sha = None
            h = hub.file(rp, rel)
            if h is None:
                ok, why = False, "hub_file_missing"
                break
            if h[1] != size or h[0] != (local_sha or out_cache.get(f, file_sha256)):
                ok, why = False, "hub_sha_or_size_mismatch"
                break
            hf.append({"path": rel, "sha256": h[0], "size": size, **({"evicted": True} if local_sha else {})})
        place_ok[(cc, key)] = (ok, why, hf, rp)
    manifest = state / "pruned_manifest.jsonl"
    freed = 0
    keep_src = set()
    for bot, cc, key, p, orig, entries in cands:
        try:
            sha = src_cache.get(p, content_sha256)
        except Exception as e:
            st["skip_unreadable"] += 1
            log(f"prune: unreadable {p}: {e}")
            continue
        keep_src.add(str(p))
        ent = [e for e in entries if e.get("sha256") == sha]
        if not ent:
            st["skip_sha_not_in_ledger"] += 1
            continue
        e = ent[-1]
        cid = commit_for(e, runs)
        lrepo = e.get("repo") or repo
        if not cid:
            st["skip_no_commit_record"] += 1
            continue
        if not hub.has_commit(lrepo, cid):
            st["skip_commit_not_on_hub"] += 1
            continue
        pk = place_ok[(cc, key)]
        if not pk[0]:
            st["skip_" + pk[1]] += 1
            continue
        rec = {"bot": bot, "rel": e["rel"], "cc": cc, "place_key": key, "batch": orig[len(key) + 1:].rsplit(".", 1)[0],
               "sha256": sha, "rows": e.get("rows"), "ledger_at": e["at"], "hub_repo": pk[3], "hub_commit": cid,
               "hub_files": pk[2]}
        confirmed[bot].append(rec)
        st["confirmed"] += 1
        if now - parse_iso(e["at"]) < min_age:
            st["skip_too_young"] += 1
            continue
        nbytes = p.stat().st_size
        st["eligible"] += 1
        st["eligible_bytes"] += nbytes
        if not apply:
            continue
        rows, dh = rows_and_doc_hash(p)
        mrec = {"pruned_at": utc_now_iso(), "bot": bot, "path": str(p), "bytes": nbytes, "sha256": sha,
                "file_sha256": file_sha256(p) if p.name.endswith(".gz") else sha, "rows": rows,
                "doc_ids_sha256": dh, "place_key": key, "country_code": cc, "ledger_rel": e["rel"],
                "ledger_at": e["at"], "hub_repo": pk[3], "hub_commit": cid, "hub_files": pk[2]}
        with manifest.open("a") as f:
            f.write(json.dumps(mrec) + "\n")
            f.flush()
            os.fsync(f.fileno())
        p.unlink()
        keep_src.discard(str(p))
        freed += nbytes
        st["pruned"] += 1
    src_cache.save(keep=keep_src)
    out_cache.save()
    # confirmed batches: merge with previous lists (pruned files stay listed)
    cdir = state / "confirmed_batches"
    cdir.mkdir(exist_ok=True)
    cfiles = {}
    for bot in bots:
        path = cdir / f"{bot}.jsonl"
        n, new = merge_confirmed(path, confirmed.get(bot, []), apply)
        cfiles[bot] = {"path": str(path), "batches": n, "added": new}
    res = {"at": utc_now_iso(), "apply": apply, "bots": bots, "min_age_hours": cfg["min_age_hours"],
           **dict(st), "bytes_freed": freed, "confirmed_batches": cfiles}
    log("prune " + json.dumps(res))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--wait-lock", type=float, default=3600)
    a = ap.parse_args(argv)
    state = BASE / "state"
    lock = open(state / "run_loop.lock", "a")
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
        res = prune(apply=a.apply)
        with (state / "prune_runs.jsonl").open("a") as f:
            f.write(json.dumps(res) + "\n")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
