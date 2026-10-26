#!/usr/bin/env python3
"""Normalize -> validate -> hold/override -> write (sharded) -> upload loop for endomorphosis/world_municipal_law
and endomorphosis/world_national_law.

Routing (since 2026-10-11): places with an iso:* place_id (place_key iso_*: country, adm1, supranational; see
SCHEMA.md §3) go to --national-repo (local state --out-national, default <out>/../out_national); every other place
(municipal, county, water board, ...) goes to --repo (local state --out). Each repo gets the same layout: its own
world_law/data, metadata, manifests, places.parquet and README card.

Scans /workspace/world_law/staging/<bot>/<CC>/<place_key>[.<batch>].(jsonl|parquet) (see SCHEMA.md).
Per place (all bots together), staged files are applied OLDEST -> NEWEST, ordered by the UTC timestamp
embedded in the batch name (iso_FR.20261011T003234Zp0001, iso_FR.archive<ts>p0001, <key>.full.<ts>,
<key>.full.archive-policy<ts>, <key>.<src>-p0001-<ts>, ...), falling back to file mtime; ties -> part no.,
mtime, name. Newer batch wins per (place, doc_id); a `.full` batch replaces the whole place.

Each row is:
  * quarantined if listed in state/doc_overrides.json (with the override's reason),
  * HELD (never published) if schema.hold_reason() says so -> held/<bot>/<CC>/<file>.<run>.held.jsonl,
    and removed from the place even if an older batch / existing file had it,
  * quarantined if it fails validation (quarantine/<bot>/<CC>/<file>.<run>.rejects.jsonl),
  * otherwise normalized (incl. optional provenance columns) and spooled to disk.
Places are written streaming from the spool into out/world_law/data/{CC}[/{b}]/{place_key}_html.parquet (S.html_path), or into
{place_key}.s0001_html.parquet, .s0002_... when over SHARD_MAX_ROWS rows / ~SHARD_MAX_BYTES. Stale files of a
re-sharded or emptied place are deleted locally and CommitOperationDelete'd in the SAME Hub commit.
Then metadata JSON, places.parquet, the card, a manifest (sha256), one commit per <=500 ops (<=200 when memory is
low), and RIGHT AFTER EACH COMMIT the staged files of its places are ledgered and
MOVED to processed/<bot>/<CC>/ (never deleted). Memory guard: MemAvailable (/proc/meminfo) is checked before
each place build and each commit; below --mem-low-gb (1.5) it gc's and waits --mem-wait s, then stops cleanly
(MEM_LOW): no new builds/commits, finished commits fully bookkept, the rest stays staged for the next run.

Local data parquet is on demand (out_store.py): after prune, places verified identical on the Hub and >= 2h old
are evicted from out*/ (record in state/evicted_out.jsonl; metadata JSONs stay); a place that needs merging, or a
country's national index for cross-lane dedupe, re-downloads its evicted files sha-verified first, else is skipped.
Safe to rerun: a ledger (state/ledger.jsonl) records sha256 of every processed file; a lock prevents
concurrent runs.

  run_loop.py --once --dry-run      # writes only under state/dryrun_<ts>/ (incl. held/ + planned_commit*.jsonl), no upload
  run_loop.py --once                # one real pass
  run_loop.py --once --no-upload    # write out/ + move files, but don't upload
  run_loop.py --interval 600        # loop (no --once); don't use as a daemon without asking
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import calendar
import fcntl
import hashlib
import json
import os
import pickle
import re
import shutil
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import schema as S  # noqa: E402
from normalize import normalize_record, rows_to_table  # noqa: E402
import dedupe as DD  # noqa: E402
import dedup_index as DX  # noqa: E402
import xdedup as XD  # noqa: E402
import out_store as OS_  # noqa: E402
from card import PHASE1_COUNTRIES, build_card  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
# network timeouts for huggingface_hub (read at import time); the commit watchdog below is the hard backstop
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
_CC_DIR = re.compile(r"^[A-Z]{2}$")
_FNAME = re.compile(r"^(?P<key>[A-Za-z0-9_\-]+)(?P<batch>(\.[A-Za-z0-9_\-]+)*)\.(?P<ext>jsonl|parquet)$")
_TS = re.compile(r"(20\d{2})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(?:\d*)Z?")
# part number: p0001 / b00051 / s0001, also right after the timestamp's "Z" (…T103649Zp0038, …Zp0001)
_PART = re.compile(r"(?:^|[^A-Za-z]|(?<=\dZ))[pbs](\d{3,6})(?![0-9])")
MAX_OPS_PER_COMMIT = 500
WRITE_BATCH_ROWS = 500
WRITE_BATCH_BYTES = 8 * 1024 * 1024
FORBIDDEN_REPOS = {"endomorphosis/american_municipal_law", "justicedao/american_municipal_law"}
COMMIT_RETRIES = 6  # per commit; backoff 30s, 60s, 120s, ... (rate limits / 5xx / network)


def create_commit_with_retry(api, **kw):
    """create_commit with retries on 429 / 5xx / network errors. A retried commit is safe: identical file
    contents are deduplicated by the Hub, and staged files are only moved after every commit succeeded."""
    delay = 30
    for attempt in range(1, COMMIT_RETRIES + 1):
        try:
            return api.create_commit(**kw)
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            retryable = status is None or status == 429 or status >= 500
            if "too many files per directory" in str(e).lower():
                retryable = False  # deterministic Hub limit; handled by the DIR_FULL retry in commit_repo
            if not retryable or attempt == COMMIT_RETRIES:
                raise
            ra = getattr(getattr(e, "response", None), "headers", {}) or {}
            wait = int(ra.get("Retry-After", delay)) if str(ra.get("Retry-After", "")).isdigit() else delay
            log(f"WARN commit attempt {attempt} failed ({status}: {str(e)[:200]}); retrying in {wait}s")
            time.sleep(wait)
            delay = min(delay * 2, 900)


COMMIT_TIMEOUT_S = 20 * 60   # hard per-commit watchdog (incl. upload / xet finalize)
RUN_DEADLINE_S = 50 * 60     # after this no new commit is started; the run finishes and releases the lock
HEARTBEAT_S = 60
STALE_LOCK_S = 90 * 60
_LOCK = {"f": None, "info": {}}


class CommitTimeout(RuntimeError):
    pass


def heartbeat(**kw) -> None:
    """Rewrite the lock file's JSON (pid, start, heartbeat, phase) while holding the flock."""
    f = _LOCK["f"]
    _LOCK["info"].update(kw, heartbeat_at=S.utc_now_iso())
    if f is None:
        return
    try:
        f.seek(0)
        f.truncate()
        f.write(json.dumps(_LOCK["info"]) + "\n")
        f.flush()
    except OSError:
        pass


def lock_holder_report(lock_path: Path, state: Path) -> Optional[Dict[str, Any]]:
    """Called when the lock is busy: report a stale holder (no heartbeat for > STALE_LOCK_S). Never kills it."""
    try:
        info = json.loads(lock_path.read_text() or "{}")
    except Exception:
        info = {}
    hb = info.get("heartbeat_at") or info.get("started_at")
    age = None
    if hb:
        age = time.time() - calendar.timegm(time.strptime(hb[:19], "%Y-%m-%dT%H:%M:%S"))
    alive = None
    if info.get("pid"):
        try:
            os.kill(int(info["pid"]), 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    rep = {"at": S.utc_now_iso(), "holder": info, "heartbeat_age_s": round(age) if age is not None else None,
           "pid_alive": alive, "stale": bool(age is not None and age > STALE_LOCK_S)}
    if rep["stale"]:
        msg = (f"STALE_LOCK holder pid={info.get('pid')} run={info.get('run_id')} started={info.get('started_at')} "
               f"last heartbeat {round(age / 60)} min ago (phase {info.get('phase')}); NOT killed; please check")
        log(msg)
        print(msg, flush=True)
        (state / "stale_lock_alert.json").write_text(json.dumps(rep, indent=2) + "\n")
    return rep


def _commit_landed(api, repo: str, message: str) -> Optional[str]:
    try:
        for c in api.list_repo_commits(repo, repo_type="dataset"):
            if (c.title or "").strip() == message.strip():
                return c.commit_id
    except Exception as e:  # noqa: BLE001
        log(f"WARN could not list {repo} commits to check a timed-out commit: {e}")
    return None


LISTING_TIMEOUT_S = 10 * 60  # watchdog per read-only Hub listing attempt (a stalled socket once hung a run 40+ min)


def guarded_list_files(api, repo: str, timeout_s: float = LISTING_TIMEOUT_S, attempts: int = 2):
    """api.list_repo_files in a daemon thread with a watchdog; retries once, then raises TimeoutError."""
    import threading
    for attempt in range(1, attempts + 1):
        box: Dict[str, Any] = {}

        def _run():
            try:
                box["ok"] = api.list_repo_files(repo, repo_type="dataset")
            except BaseException as e:  # noqa: BLE001
                box["err"] = e

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        th.join(timeout_s)
        if th.is_alive():
            log(f"WARN hub listing for {repo} attempt {attempt} timed out after {timeout_s:.0f}s; abandoned")
            continue
        if "err" in box:
            raise box["err"]
        return box["ok"]
    raise TimeoutError(f"hub listing for {repo} timed out {attempts}x")


PREFIX_LISTING_TIMEOUT_S = 4 * 60   # stall watchdog per scoped listing attempt: max seconds with no new entries
PREFIX_LISTING_TOTAL_S = 25 * 60    # hard cap per attempt (a big country dir is many 1000-entry pages)
PREFIX_LISTING_WORKERS = 4          # countries listed in parallel
PREFIX_LISTING_ATTEMPTS = 4
PREFIX_LISTING_BACKOFF_S = 5.0       # 5, 10, 20 s between attempts


class ListingFailed(RuntimeError):
    pass


def _guarded(fn, timeout_s: float, label: str):
    """Run fn() in a daemon thread with a watchdog; raise TimeoutError if it stalls."""
    import threading
    box: Dict[str, Any] = {}

    def _run():
        try:
            box["ok"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["err"] = e
    th = threading.Thread(target=_run, name=f"list-{label}", daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        raise TimeoutError(f"{label} stalled > {timeout_s:.0f}s")
    if "err" in box:
        raise box["err"]
    return box["ok"]


def _iter_with_stall_watchdog(make_iter, files_only: bool, stall_s: float, total_s: float, label: str) -> set:
    """Consume a (paginated) listing iterator in a daemon thread. Abandoned (TimeoutError) when no new entry
    arrives for stall_s, or after total_s overall. Returns the complete set or raises."""
    import threading
    box: Dict[str, Any] = {"out": set(), "t": time.time()}

    def _run():
        try:
            for e in make_iter():
                is_dir = type(e).__name__ == "RepoFolder" or getattr(e, "type", None) == "directory"
                if files_only != is_dir:
                    box["out"].add(e.path)
                box["t"] = time.time()
            box["done"] = True
        except BaseException as e:  # noqa: BLE001
            box["err"] = e
    th = threading.Thread(target=_run, name=f"list-{label}", daemon=True)
    t0 = time.time()
    th.start()
    while th.is_alive():
        th.join(min(5.0, stall_s))
        now = time.time()
        if th.is_alive() and (now - box["t"] > stall_s or now - t0 > total_s):
            raise TimeoutError(f"{label} stalled ({len(box['out'])} entries so far, "
                               f"{now - box['t']:.0f}s since last, {now - t0:.0f}s total)")
    if "err" in box:
        raise box["err"]
    return set(box["out"])


def _is_not_found(e: BaseException) -> bool:
    try:
        from huggingface_hub.utils import EntryNotFoundError
        if isinstance(e, EntryNotFoundError):
            return True
    except Exception:  # noqa: BLE001
        pass
    resp = getattr(e, "response", None)
    return getattr(resp, "status_code", None) == 404 and "RepositoryNotFound" not in type(e).__name__


def list_prefix(api, repo: str, prefix: str, files_only: bool = True, timeout_s: Optional[float] = None,
                attempts: Optional[int] = None, backoff_s: Optional[float] = None, recursive: bool = False) -> set:
    """COMPLETE non-recursive listing of one repo directory (all pages), watchdog + retries + exponential backoff.
    A missing directory (404 EntryNotFound) is a complete, empty answer. Anything else that still fails after
    the retries raises ListingFailed: the caller must skip the affected places (never guess, never use a cache)."""
    timeout_s = PREFIX_LISTING_TIMEOUT_S if timeout_s is None else timeout_s
    attempts = PREFIX_LISTING_ATTEMPTS if attempts is None else attempts
    backoff_s = PREFIX_LISTING_BACKOFF_S if backoff_s is None else backoff_s
    last = None
    for a in range(1, attempts + 1):
        try:
            return _iter_with_stall_watchdog(
                lambda: api.list_repo_tree(repo, path_in_repo=prefix, recursive=recursive, repo_type="dataset"),
                files_only, timeout_s, PREFIX_LISTING_TOTAL_S, f"{repo}:{prefix}")
        except Exception as e:  # noqa: BLE001
            if _is_not_found(e):
                return set()
            last = e
            log(f"WARN listing {repo}:{prefix} attempt {a}/{attempts} failed: {str(e)[:200]}")
            if a < attempts:
                time.sleep(backoff_s * (2 ** (a - 1)))
    raise ListingFailed(f"{repo}:{prefix}: {last}")


def scoped_hub_listing(api, repo: str, ccs) -> Tuple[set, set]:
    """List only world_law/data/<CC>/ and world_law/metadata/<CC>/ for the countries this run touches.
    Returns (files, failed_ccs). Flat countries are listed non-recursively; bucketed countries
    (S.BUCKETED_COUNTRIES: data/<CC>/<b>/...) recursively, so their bucket files AND any legacy flat files are
    seen. For a cc not in failed_ccs the listing of its places is complete."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    files, failed = set(), set()
    prefixes = {(cc, f"{S.ROOT}/{sub}/{cc}") for cc in ccs for sub in ("data", "metadata")}
    heartbeat(phase=f"hub listing {repo} ({len(ccs)} countries)")
    with ThreadPoolExecutor(max_workers=PREFIX_LISTING_WORKERS) as ex:
        futs = {ex.submit(list_prefix, api, repo, pre, recursive=cc in S.BUCKETED_COUNTRIES): (cc, pre)
                for cc, pre in sorted(prefixes)}
        for fu in as_completed(futs):
            cc, pre = futs[fu]
            try:
                got = fu.result()
                files |= got
                log(f"listed {repo}:{pre}: {len(got)} files")
            except ListingFailed as e:
                log(f"ERROR scoped listing failed for {repo} {cc}; its places are skipped this run "
                    f"(files stay staged): {e}")
                failed.add(cc)
            heartbeat(phase=f"hub listing {repo}")
    files = {f for f in files if f.split("/")[2] not in failed}
    return files, failed


def hub_countries(api, repo: str, state: Path) -> set:
    """Country dirs under world_law/data (one small non-recursive listing) for the dataset card only. On failure
    falls back to the last known set (cards only; NEVER used for deletes)."""
    cache = state / f"hub_countries_{repo.replace('/', '__')}.json"
    try:
        got = {Path(d).name for d in list_prefix(api, repo, f"{S.ROOT}/data", files_only=False)}
        cache.write_text(json.dumps(sorted(got)) + "\n")
        return got
    except ListingFailed as e:
        log(f"WARN country listing failed for {repo} ({e}); card uses last known countries")
        try:
            return set(json.loads(cache.read_text()))
        except Exception:  # noqa: BLE001
            return set()



# ---- HF per-directory file limit (10,000 files per repo dir). Big countries are hash-bucketed (S.place_dir);
# this guard defers places whose dir (data/<CC>/, data/<CC>/<b>/, metadata/...) would pass DIR_FULL_LIMIT. ----
HUB_DIR_LIMIT = 10_000
DIR_FULL_LIMIT = 9_900       # a place that would push any of its dirs past this is deferred (DIR_FULL)
NEAR_LIMIT_FILES = 7_000     # dirs with more files than this are reported as near the limit
_TOO_MANY_RE = re.compile(r"too many files per directory", re.I)
_DIR_RE = re.compile(r"(?:world_law/)?(data|metadata)/([A-Za-z][A-Za-z0-9_-]{1,15})(?=/|\b)")


def _dir_key(rel: str) -> Optional[str]:
    """'data/FR' or 'data/FR/ab' for a file under world_law/data|metadata; None otherwise."""
    parts = rel.split("/")
    if parts[0] != S.ROOT or len(parts) not in (4, 5) or parts[1] not in ("data", "metadata"):
        return None
    return "/".join(parts[1:-1])


def hub_dir_counts(hub_files) -> Counter:
    """{'data/FR': n, 'data/FR/ab': n, 'metadata/IT/0c': n, ...}: files directly in each dir (scoped listing)."""
    c: Counter = Counter()
    for f in hub_files:
        k = _dir_key(f)
        if k:
            c[k] += 1
    return c


def plan_dir_full(place_adds: Dict[Tuple[str, str], List[str]], hub_files, limit: int = DIR_FULL_LIMIT,
                  base: Optional[Counter] = None) -> Tuple[set, Counter, Counter]:
    """Walk places in sorted order; a place whose NEW files (rels not already on the Hub) would push ANY of its
    dirs (flat data/<CC>/ or bucket data/<CC>/<b>/, and metadata) over `limit` is deferred as a whole. Returns
    (deferred places, deferred count per cc, projected dir counts incl. accepted places)."""
    counts = Counter(base) if base is not None else hub_dir_counts(hub_files)
    hub = hub_files if isinstance(hub_files, (set, frozenset)) else set(hub_files)
    deferred, per_cc, seen = set(), Counter(), set()
    for ck in sorted(place_adds):
        new: Counter = Counter()
        for rel in place_adds[ck]:
            k = _dir_key(rel)
            if not k or rel in hub or rel in seen:
                continue
            new[k] += 1
        if any(counts[d] + n > limit for d, n in new.items()):
            deferred.add(ck)
            per_cc[ck[0]] += 1
            continue
        counts.update(new)
        seen.update(place_adds[ck])
    return deferred, per_cc, counts


def cc_max_dir(counts, cc: str) -> int:
    """Largest file count of any data/metadata dir of country cc."""
    return max([n for k, n in counts.items() if k.split("/")[1] == cc] or [0])


def parse_too_many_files(err) -> Optional[set]:
    """None if `err` is not HF's per-directory limit error; else the set of countries named in it (may be empty)."""
    msg = str(err)
    resp = getattr(err, "response", None)
    try:
        msg += " " + (resp.text or "")
    except Exception:  # noqa: BLE001
        pass
    if not _TOO_MANY_RE.search(msg):
        return None
    return {m.group(2) for m in _DIR_RE.finditer(msg)}


def near_limit_report(counts, threshold: int = NEAR_LIMIT_FILES) -> Dict[str, Dict[str, int]]:
    """{dir: {files, headroom}} for every dir (e.g. 'data/IT' or 'data/FR/ab') above threshold."""
    return {d: {"files": n, "headroom": HUB_DIR_LIMIT - n} for d, n in sorted(counts.items()) if n > threshold}


def guarded_commit(api, timeout_s: float, deadline: float, label: str, **kw):
    """create_commit_with_retry in a daemon thread with a watchdog. On timeout the attempt is abandoned; the Hub
    history is checked (commit messages are unique per run/part) and, if it did not land, retried ONCE (if the
    run deadline allows). Raises CommitTimeout after the second timeout. Logs heartbeat lines while waiting."""
    import threading
    msg = kw["commit_message"]
    for attempt in (1, 2):
        box: Dict[str, Any] = {}

        def work():
            try:
                box["ok"] = create_commit_with_retry(api, **kw)
            except BaseException as e:  # noqa: BLE001
                box["err"] = e
        th = threading.Thread(target=work, name=f"commit-{label}-{attempt}", daemon=True)
        t0 = time.time()
        th.start()
        while th.is_alive():
            th.join(min(HEARTBEAT_S, max(0.05, timeout_s - (time.time() - t0))))
            el = time.time() - t0
            if th.is_alive():
                if el >= timeout_s:
                    break
                log(f"heartbeat: {label} attempt {attempt} running {el:.0f}s")
                heartbeat(phase=f"commit {label} attempt {attempt}", commit_running_s=round(el))
        if not th.is_alive():
            if "err" in box:
                raise box["err"]
            return box["ok"]
        log(f"ERROR commit {label} attempt {attempt} timed out after {timeout_s:.0f}s; abandoned")
        cid = _commit_landed(api, kw["repo_id"], msg)
        if cid:
            log(f"... but it landed on the Hub as {cid}; not re-committing")
            return SimpleNamespace(oid=cid, commit_url=f"https://huggingface.co/datasets/{kw['repo_id']}/commit/{cid}")
        if attempt == 1 and time.time() >= deadline:
            log("run deadline passed; not retrying")
            break
        if attempt == 1:
            log(f"retrying {label} once")
    raise CommitTimeout(f"{label}: commit timed out twice (or deadline) and did not land")


def _seed_tree(src: Path, dst: Path) -> None:
    """Dry-run seed of an out/ tree: hard links (no extra disk; every write in run_loop is tmp+replace or unlink,
    so the real files are never modified through a link), falling back to copies across filesystems."""
    def link_or_copy(a, b):
        try:
            os.link(a, b)
        except OSError:
            shutil.copy2(a, b)
    shutil.copytree(src, dst, copy_function=link_or_copy)


DISK_WARN_GB = 15.0  # below: log + state/disk_alert.json + DISK_LOW line
DISK_STOP_GB = 8.0   # below: build no new places this run (commits of already-built places still finish)


def disk_free_gb(path: Path = Path("/")) -> float:
    return shutil.disk_usage(str(path)).free / 1e9


def disk_guard(state: Path, warn_gb: float, stop_gb: float, free_gb: Optional[float] = None) -> Dict[str, Any]:
    """Check free space on /. Returns {"free_gb", "level": ok|low|critical, "skip_builds"}; writes/clears
    state/disk_alert.json and prints a DISK_LOW line the hourly routine can grep for."""
    free = disk_free_gb() if free_gb is None else free_gb
    level = "critical" if free < stop_gb else "low" if free < warn_gb else "ok"
    res = {"at": S.utc_now_iso(), "free_gb": round(free, 2), "warn_gb": warn_gb, "stop_gb": stop_gb,
           "level": level, "skip_builds": level == "critical"}
    alert = state / "disk_alert.json"
    if level == "ok":
        if alert.exists():
            alert.replace(state / "disk_alert.cleared.json")
            log(f"disk ok again ({free:.1f} GB free); alert cleared")
        return res
    tmp = alert.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, indent=2) + "\n")
    tmp.replace(alert)
    msg = (f"DISK_LOW free={free:.1f}GB on / (warn<{warn_gb:g}GB, stop<{stop_gb:g}GB) level={level}"
           + (": skipping new place builds this run" if level == "critical" else ""))
    log(msg)
    print(msg, flush=True)
    return res


MEM_LOW_GB = 1.5          # MemAvailable below this before a place build / commit: gc + wait, then stop cleanly
MEM_WAIT_S = 60.0         # how long to wait (polling) for memory to come back before stopping
MEM_SMALL_CHUNK_GB = 2.0  # MemAvailable below this when planning commits: use MEM_SMALL_CHUNK_OPS per commit
MEM_SMALL_CHUNK_OPS = 200


def mem_available_gb() -> float:
    """MemAvailable from /proc/meminfo in GB (inf if unreadable)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024 / 1e9
    except OSError:
        pass
    return float("inf")


def rss_mb() -> int:
    """Current VmRSS of this process (MB) and peak (VmHWM)."""
    cur = hwm = 0
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                cur = int(line.split()[1]) // 1024
            elif line.startswith("VmHWM:"):
                hwm = int(line.split()[1]) // 1024
    except OSError:
        pass
    return cur, hwm


def release_memory() -> None:
    """gc + give freed heap back to the OS (glibc malloc_trim) + arrow pool release."""
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass
    try:
        import pyarrow as pa
        pa.default_memory_pool().release_unused()
    except Exception:  # noqa: BLE001
        pass


def mem_guard(where: str, low_gb: float, wait_s: float, stats: Counter, avail_fn=None, sleep_fn=None) -> bool:
    """True if MemAvailable >= low_gb (after gc + waiting up to wait_s). Otherwise logs/prints MEM_LOW, sets
    stats["mem_low_stop"] and returns False: the caller must stop starting new work (builds / commits) and only
    finish bookkeeping for what is already done."""
    avail_fn = avail_fn or mem_available_gb
    sleep_fn = sleep_fn or time.sleep
    a = avail_fn()
    stats["mem_min_available_gb"] = round(min(stats.get("mem_min_available_gb", a), a), 2)
    if a >= low_gb:
        return True
    release_memory()
    waited = 0.0
    while True:
        a = avail_fn()
        if a >= low_gb:
            log(f"mem: MemAvailable recovered to {a:.2f} GB before {where} (waited {waited:.0f}s)")
            stats["mem_low_waits"] += 1
            return True
        if waited >= wait_s:
            break
        step = min(5.0, wait_s - waited)
        sleep_fn(step)
        waited += step
    msg = (f"MEM_LOW MemAvailable={a:.2f}GB < {low_gb:g}GB before {where} (waited {waited:.0f}s); "
           f"stopping cleanly: no new builds/commits, bookkeeping for finished commits is done, rest stays staged")
    log(msg)
    print(msg, flush=True)
    stats["mem_low_stop"] = 1
    stats["mem_low_stop_at"] = where
    return False


def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


class StagedVanished(Exception):
    """A staged file disappeared (moved/removed by its lane) between discovery and read."""


def _iter_staged_tolerant(path):
    """S.iter_staged_records, but a staged file that vanished before it could be opened yields nothing."""
    try:
        yield from S.iter_staged_records(path)
    except FileNotFoundError:
        if Path(path).exists():
            raise
        log(f"WARN staged file vanished before read (dedupe index): {path}")


# ---------------------------------------------------------------------------
# batch ordering
# ---------------------------------------------------------------------------
def batch_order(batch: str, mtime: float, name: str) -> Tuple[float, int, float, str, str]:
    """Sort key: (epoch of the UTC timestamp in the batch name, else mtime; part no.; mtime; name; ts source)."""
    m = _TS.search(batch or "")
    if m:
        y, mo, d, hh, mi, ss = m.groups()
        try:
            ts = float(calendar.timegm((int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0))))
            src = "name"
        except (ValueError, OverflowError):
            ts, src = mtime, "mtime"
    else:
        ts, src = mtime, "mtime"
    pm = _PART.findall(batch or "")
    part = int(pm[-1]) if pm else 0
    return (ts, part, mtime, name, src)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def discover(staging: Path, min_age: float, bots: Optional[List[str]]) -> List[Dict[str, Any]]:
    out = []
    now = time.time()
    if not staging.exists():
        return out
    for bot_dir in sorted(staging.iterdir()):
        if not bot_dir.is_dir() or bot_dir.name.startswith(("_", ".")):
            continue
        if bot_dir.name == "pdf":  # staging/pdf/ = scanned-PDF contract (tools/upload_pdfs.py, PDF_STAGING.md)
            continue
        if bots and bot_dir.name not in bots:
            continue
        for cc_dir in sorted(bot_dir.iterdir()):
            if not cc_dir.is_dir() or not _CC_DIR.match(cc_dir.name):
                continue
            for f in sorted(cc_dir.iterdir()):
                if not f.is_file() or f.name.startswith(("_", ".")) or f.name.endswith(".tmp"):
                    continue
                m = _FNAME.match(f.name)
                if not m:
                    if f.suffix in (".jsonl", ".parquet"):
                        out.append({"path": f, "bot": bot_dir.name, "cc": cc_dir.name, "bad_name": True})
                    continue
                try:
                    st = f.stat()
                except FileNotFoundError:  # moved/removed by its lane between listing and stat: skip this run
                    log(f"WARN staged file vanished during discovery: {f}")
                    continue
                if now - st.st_mtime < min_age:
                    continue
                batch = m.group("batch") or ""
                parts = batch.split(".")
                out.append({"path": f, "bot": bot_dir.name, "cc": cc_dir.name, "key": m.group("key"),
                            "full": "full" in parts, "mtime": st.st_mtime, "size": st.st_size,
                            "order": batch_order(batch, st.st_mtime, f.name), "bad_name": False})
    return out


# ---------------------------------------------------------------------------
# ledger / overrides
# ---------------------------------------------------------------------------
def load_ledger(path: Path, rels: Optional[set] = None) -> set:
    """{(bot, rel, sha256)} from the ledger. With `rels`, only entries for those staged rels are kept (the ledger is
    300+ MB / 500k lines; holding all of it cost ~0.5 GB)."""
    seen = set()
    enc = {json.dumps(r)[1:-1] for r in rels} if rels is not None else None
    if path.exists():
        with path.open() as f:
            for line in f:
                if enc is not None:
                    i = line.find('"rel": "')
                    if i >= 0 and line[i + 8:line.find('"', i + 8)] not in enc:
                        continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if rels is None or r.get("rel") in rels:
                    seen.add((r["bot"], r["rel"], r["sha256"]))
    return seen


def load_overrides(path: Path) -> Dict[Tuple[str, str, str], str]:
    """{(CC, place_key, doc_id): reason} from state/doc_overrides.json ("quarantine" list)."""
    out: Dict[Tuple[str, str, str], str] = {}
    if path.exists():
        d = json.loads(path.read_text())
        for e in d.get("quarantine", []):
            out[(e["country_code"], e["place_key"], str(e["doc_id"]))] = e.get("reason") or "doc_overrides"
    return out


def append_jsonl(path: Path, rec: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def move_unique(src: Path, dst_dir: Path) -> Optional[Path]:
    """Move src into dst_dir under a non-colliding name. Returns None (and moves nothing) when src vanished,
    i.e. a lane moved/removed the staged file while this run was processing it."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        dst = dst_dir / f"{src.name}.{utc_ts()}"
        i = 1
        while dst.exists():
            dst = dst_dir / f"{src.name}.{utc_ts()}.{i}"
            i += 1
    try:
        shutil.move(str(src), str(dst))
    except FileNotFoundError:
        if Path(src).exists():  # src is still there: a genuine destination problem, not the staging race
            raise
        if dst.exists() and not Path(src).exists():
            pass  # (copy fallback finished but unlink raced: the file did land in dst)
        else:
            log(f"WARN staged file vanished before move: {src}")
            return None
    return dst


def _slim(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v) for k, v in rec.items()}


# ---------------------------------------------------------------------------
# per-place build (runs in a worker process; streaming, constant memory per doc)
# ---------------------------------------------------------------------------
_REHYDRATE_DL: Dict[str, Any] = {}  # tests inject a mock Hub: {"fn": download(repo, rel, local_dir), "hub": lookup(repo, rels)}


def _existing_local_files(out_dir: Path, cc: str, key: str) -> List[Path]:
    return S.local_place_files(out_dir, cc, key)


def _iter_existing(paths: List[Path]):
    """Rows of already-published local/Hub files (v1.0.0 and v1.1.0 files are upgraded with null provenance / pdf_ref)."""
    import pyarrow.parquet as pq
    for p in paths:
        pf = pq.ParquetFile(str(p))
        names = pf.schema_arrow.names
        if names not in (S.HTML_COLUMNS, S.V11_HTML_COLUMNS, S.LEGACY_HTML_COLUMNS):
            raise RuntimeError(f"existing {p} has columns {names}")
        for b in pf.iter_batches(batch_size=256):
            for r in b.to_pylist():
                yield {c: r.get(c) for c in S.HTML_COLUMNS}


def _cc_of_key(pk: str) -> str:
    """Country code of a place key: iso_US-CA -> US, iso_FR -> FR, else the leading <CC>_ segment."""
    m = re.match(r"^iso_([A-Z]{2})(?:-[A-Z0-9]{1,3})?$", pk) or re.match(r"^([A-Z]{2})_.+", pk)
    if not m:
        raise ValueError(f"cannot derive country code from place key {pk!r}")
    return m.group(1)


def load_pdf_refs(state: Path, cc: str, key: str) -> Dict[str, str]:
    """{doc_id: pdf_ref} of one place from state/pdf_refs/<CC>/<place_key>.json (written by tools/upload_pdfs.py
    after Hub sha256 verification). Per-place files keep this memory-safe."""
    p = Path(state) / "pdf_refs" / cc / f"{key}.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
        return {str(k): str(v) for k, v in d.items() if v}
    except (OSError, ValueError) as e:
        log(f"WARN pdf_refs {p}: {e!r}")
        return {}


def build_place(job: Dict[str, Any]) -> Dict[str, Any]:
    cc, key, files = job["cc"], job["key"], job["files"]
    out_dir, scratch = Path(job["out_dir"]), Path(job["scratch"])
    quarantine, held_dir = Path(job["quarantine"]), Path(job["held"])
    run_id, overrides = job["run_id"], job["overrides"]
    res: Dict[str, Any] = {"cc": cc, "key": key, "files": [], "error": None, "stats": Counter(),
                           "held_by": Counter(), "written": [], "deleted": [], "place": {}, "meta": None}
    spool_path = scratch / "spool" / f"{cc}__{key}.pkl"
    spool_path.parent.mkdir(parents=True, exist_ok=True)
    index: Dict[str, Tuple[int, int, int]] = {}   # doc_id -> (offset, length, doc_order)
    flags: Dict[str, Tuple[bool, bool, bool, bool]] = {}  # doc_id -> (archived, archived_restricted, incomplete, unofficial)
    st = res["stats"]
    try:
        with spool_path.open("w+b") as spool:
            pidx = DD.PrimaryIndex.from_obj(job["primary_index"]) if job.get("primary_index") else None
            dedupe_log: List[Dict[str, Any]] = []
            staged_ids: set = set()
            # NEW-row duplicate checks (xdedup.py): old-repo URL index (both repos) + cross-place plan (municipal)
            xj = job.get("xdedup") or {}
            xcfg = xj.get("cfg") or {}
            xplan = xj.get("plan") or {}
            xold = XD.OldRepoCheck(Path(xj["old_db"])) if xj.get("old_db") and xcfg.get("old_repo", "off") != "off" else None
            existing_ids: set = set()
            ptr_log: List[Dict[str, Any]] = []
            xkeys: List[Tuple[Optional[str], Optional[str], str]] = []
            res["xkeys"] = xkeys

            xpending: Dict[str, Tuple[str, str, str, str]] = {}  # doc_id -> hit, decided after all files
            ptr_ids: set = set()   # doc_ids in index whose row is already a pointer row (no full content)

            def xdup(row, rec):
                """Find a duplicate hit for a NEW row (doc_id not already published here).  The row is kept in
                full for now; the hit is applied (pointer/skip/tag) only after the whole place is read, and only
                if that would not leave the place with zero full rows (no-empty rule, 2026-10-20)."""
                did = str(row.get("doc_id"))
                xpending.pop(did, None)
                if did in existing_ids:
                    return row
                hit = None
                if xold is not None:
                    repo_m = xold.match(rec)
                    if repo_m:
                        hit = (repo_m, "old_repo", "source_url", xcfg.get("old_repo", "pointer"))
                if hit is None and did in xplan and xcfg.get("cross_place", "off") != "off":
                    p = xplan[did]
                    hit = (p["duplicate_of"], "cross_place", p["duplicate_key"], xcfg.get("cross_place", "pointer"))
                if hit is None:
                    return row
                xpending[did] = hit
                return row
            override_log: List[Dict[str, Any]] = []

            def dup_of(rec) -> bool:
                """Cross-lane content dedupe: an hf: import that is the same document as a primary record."""
                if pidx is None or not DD.is_import(rec):
                    return False
                m = pidx.match(rec)
                if not m:
                    return False
                st["dedupe_cross_lane_dropped"] += 1
                st[f"dedupe_cross_lane_by_{m[0]}"] += 1
                dedupe_log.append({"cc": cc, "place_key": key, "doc_id": rec.get("doc_id"), "reason": m[0],
                                   "kept_primary": m[1], "source": rec.get("source"),
                                   "source_url": rec.get("source_url")})
                did = rec.get("doc_id")
                if did is not None:
                    index.pop(str(did), None)
                    flags.pop(str(did), None)
                return True

            def put(row):
                b = pickle.dumps(row, protocol=5)
                off = spool.seek(0, 2)
                spool.write(b)
                index[row["doc_id"]] = (off, len(b), row["doc_order"])
                pol = set((row.get("source_policy") or "").split(";"))
                if XD.POINTER_POLICY in pol:
                    ptr_ids.add(row["doc_id"])
                else:
                    ptr_ids.discard(row["doc_id"])
                arch = bool(row.get("archive_source") or row.get("archive_url"))
                restricted = arch and bool(pol & {"archived_robots_disallowed", "noarchive_meta", "noindex_meta"})
                flags[row["doc_id"]] = (arch, restricted, row.get("content_complete") is False,
                                        row.get("source_official") is False)

            any_full = any(f["full"] for f in files)
            hub_existing = [f for f in job["hub_files"] if S.is_place_data_file(f, cc, key)]
            if any_full and (xold is not None or xplan):
                # a full snapshot does not load the published rows; collect their doc_ids so they are never
                # pointer-tagged (published rows are not rewritten). Not knowable -> checks off for this place.
                loc = _existing_local_files(out_dir, cc, key)
                if hub_existing and not loc:
                    xold, xplan = None, {}
                    st["xdedup_place_skipped_unknown_published"] += 1
                else:
                    try:
                        import pyarrow.parquet as _pq
                        for _p in loc:
                            existing_ids.update(str(x) for x in _pq.read_table(str(_p), columns=["doc_id"]).column(0).to_pylist())
                    except Exception:  # noqa: BLE001
                        xold, xplan = None, {}
                        st["xdedup_place_skipped_unknown_published"] += 1
            if not any_full:
                # on-demand local parquet: files this place's metadata lists that we evicted (verified) are
                # re-downloaded + sha-checked before merging; any failure raises -> place skipped, files stay staged
                state_dir = Path(job["state"]) if job.get("state") else None
                if state_dir is not None:
                    miss = OS_.evicted_missing(out_dir, state_dir, job["repo"], cc, key).get((cc, key))
                    if miss:
                        if not job.get("hub_download"):
                            raise OS_.RehydrateError(f"local parquet evicted and downloads disabled: {miss}")
                        OS_.rehydrate(job["repo"], out_dir, state_dir, miss, download=_REHYDRATE_DL.get("fn"), log=log,
                                              hub_lookup=_REHYDRATE_DL.get("hub"))
                        st["places_rehydrated"] += 1
                        st["files_rehydrated"] += len(miss)
                existing_local = _existing_local_files(out_dir, cc, key)
                src_paths = list(existing_local)
                if not src_paths and hub_existing:
                    if not job.get("hub_download") or state_dir is None:
                        raise OS_.RehydrateError(f"local parquet missing, Hub has {sorted(hub_existing)}; "
                                                 "not building from partial data")
                    src_paths = OS_.rehydrate(job["repo"], out_dir, state_dir, sorted(hub_existing),
                                              download=_REHYDRATE_DL.get("fn"), log=log,
                                              hub_lookup=_REHYDRATE_DL.get("hub"))
                    st["places_rehydrated"] += 1
                    st["files_rehydrated"] += len(src_paths)
                for r in _iter_existing(src_paths):
                    did_e = str(r.get("doc_id")) if r.get("doc_id") not in (None, "") else None
                    ov_e = overrides.get((cc, key, did_e)) if did_e else None
                    if ov_e:  # an override also removes an already-published row when the place is rebuilt
                        st["override_removed_existing"] += 1
                        override_log.append({"cc": cc, "place_key": key, "doc_id": did_e, "reason": ov_e,
                                             "where": "existing", "source_url": r.get("source_url")})
                        continue
                    if dup_of(r):
                        st["rows_existing_deduped"] += 1
                        continue
                    if did_e is not None:
                        existing_ids.add(did_e)
                    put(r)
                    st["rows_existing"] += 1

            for f in files:
                path = Path(f["path"])
                fr = {"path": str(path), "rel": f["rel"], "bot": f["bot"], "sha256": f["sha256"],
                      "action": "processed", "rows": 0, "held": 0, "rejected": 0, "quarantined_override": 0,
                      "ts_source": f["order"][4]}
                default_ra = datetime.fromtimestamp(f["mtime"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if not path.exists():  # moved/removed by its lane after discovery: skip it this run
                    fr.update(action="vanished", reason="staged file vanished before read")
                    st["files_vanished_before_read"] += 1
                    log(f"WARN staged file vanished before read: {path}")
                    res["files"].append(fr)
                    continue
                if f["full"]:
                    prev = set(index)
                    saved_index, saved_flags = dict(index), dict(flags)
                    index.clear()
                    flags.clear()
                seen_here = set()
                rejects, held_rows = [], []
                try:
                    for idx, (line_no, rec) in enumerate(S.iter_staged_records(path)):
                        if isinstance(rec, str):
                            rejects.append({"line": line_no, "reasons": [rec], "record": None})
                            continue
                        did = str(rec.get("doc_id")) if rec.get("doc_id") not in (None, "") else None
                        if did is not None:
                            seen_here.add(did)
                        ov = overrides.get((cc, key, did)) if did else None
                        if ov:
                            rejects.append({"line": line_no, "reasons": [f"doc_override:{ov}"], "record": _slim(rec)})
                            fr["quarantined_override"] += 1
                            index.pop(did, None)
                            flags.pop(did, None)
                            continue
                        hr = S.hold_reason(rec)
                        if hr:
                            held_rows.append({"source": f["rel"], "line": line_no, "doc_id": did,
                                              "place_id": rec.get("place_id"), "reason": hr,
                                              "source_policy": S.source_policies(rec), "record": rec})
                            res["held_by"][hr] += 1
                            if did is not None:
                                index.pop(did, None)
                                flags.pop(did, None)
                            continue
                        row, pf = normalize_record(rec, default_order=idx, default_retrieved_at=default_ra)
                        errs = S.validate_record(row, normalized=True)
                        if row.get("country_code") and row["country_code"] != cc:
                            errs.append(f"country_dir_mismatch:{row['country_code']}!={cc}")
                        if row.get("place_id"):
                            try:
                                pk = S.place_key(row["place_id"], row.get("gnis"), row.get("country_code"))
                                if pk != key:
                                    errs.append(f"place_key_mismatch_with_filename:{pk}!={key}")
                            except ValueError as e:
                                errs.append(str(e))
                        if rec.get("cid") and row.get("cid") and rec["cid"] != row["cid"]:
                            errs.append("bot_cid_differs_from_computed (omit cid; the pipeline computes it)")
                        if errs:
                            rejects.append({"line": line_no, "reasons": errs, "record": _slim(rec)})
                            continue
                        if dup_of(rec):
                            fr["deduped"] = fr.get("deduped", 0) + 1
                            continue
                        row = xdup(row, rec)  # never None: the hit (if any) is applied after all files
                        if row["doc_id"] in staged_ids:  # exact CID collision (same place_key+doc_id) within the lane
                            st["dedupe_cid_collision_replaced"] += 1
                        staged_ids.add(row["doc_id"])
                        if xj.get("collect_keys") and row["doc_id"] not in xpending and row.get("text") and \
                                "duplicate_pointer" not in (row.get("source_policy") or ""):
                            xkeys.append((DX.norm_url(row.get("source_url")), DX.text_hash(row.get("text")),
                                          f"{cc}/{key}/{row['doc_id']}"))
                        for k, v in pf.items():
                            res["place"][k] = v  # newest file wins (files are in order)
                        put(row)
                        fr["rows"] += 1
                except FileNotFoundError as e:
                    if path.exists():
                        raise
                    # vanished between the exists() check and open(): nothing was read from it, so undo a full
                    # snapshot's reset (else the place would be published empty) and skip it this run
                    if f["full"]:
                        index.clear(); index.update(saved_index)
                        flags.clear(); flags.update(saved_flags)
                    fr.update(action="vanished", reason=f"staged file vanished before read: {e}")
                    st["files_vanished_before_read"] += 1
                    log(f"WARN staged file vanished before read: {path}")
                    res["files"].append(fr)
                    continue
                except Exception as e:  # unreadable file
                    fr.update(action="quarantine_file", reason=f"unreadable:{type(e).__name__}:{e}")
                    st["files_unreadable"] += 1
                    res["files"].append(fr)
                    continue
                if f["full"]:
                    dropped = prev - seen_here
                    fr["full_dropped_docs"] = len(dropped)
                    st["docs_dropped_by_full"] += len(dropped)
                fr["held"], fr["rejected"] = len(held_rows), len(rejects)
                st["rows_ok"] += fr["rows"]
                st["rows_held"] += len(held_rows)
                st["rows_rejected"] += len(rejects)
                st["rows_quarantined_override"] += fr["quarantined_override"]
                if rejects:
                    qd = quarantine / f["bot"] / cc
                    qd.mkdir(parents=True, exist_ok=True)
                    with (qd / f"{path.name}.{run_id}.rejects.jsonl").open("w", encoding="utf-8") as q:
                        for rj in rejects:
                            q.write(json.dumps({"source": f["rel"], **rj}, ensure_ascii=False, default=str) + "\n")
                if held_rows:
                    hd = held_dir / f["bot"] / cc
                    hd.mkdir(parents=True, exist_ok=True)
                    with (hd / f"{path.name}.{run_id}.held.jsonl").open("w", encoding="utf-8") as h:
                        for hrw in held_rows:
                            h.write(json.dumps(hrw, ensure_ascii=False, default=str) + "\n")
                res["files"].append(fr)

            # ---- xdedup decision (no-empty rule, 2026-10-20): skip/pointer/tag is applied only if the place
            # keeps >= 1 full row (existing published rows + new rows); otherwise ALL its rows stay in full ----
            live = {d: h for d, h in xpending.items() if d in index}
            if live:
                strip = {d for d, h in live.items() if XD.strips_content(h[3])}
                full_left = sum(1 for d in index if d not in ptr_ids and d not in strip)
                keep_all = XD.would_empty(full_left, len(strip))
                if keep_all:
                    st["xdedup_places_kept_would_be_emptied"] += 1
                    st["xdedup_rows_kept_would_be_emptied"] += len(live)
                for d, h in live.items():
                    off, ln, _o = index[d]
                    spool.seek(off)
                    row = pickle.loads(spool.read(ln))
                    if keep_all:
                        ptr_log.append({"cc": cc, "place_key": key, "doc_id": d, "check": h[1], "key": h[2],
                                        "duplicate_of": h[0], "mode": "kept_place_would_be_emptied",
                                        "source_url": row.get("source_url")})
                        if xj.get("collect_keys") and row.get("text") and \
                                "duplicate_pointer" not in (row.get("source_policy") or ""):
                            xkeys.append((DX.norm_url(row.get("source_url")), DX.text_hash(row.get("text")),
                                          f"{cc}/{key}/{d}"))
                        continue
                    st[f"xdedup_{h[1]}_{h[3]}"] += 1
                    ptr_log.append({"cc": cc, "place_key": key, "doc_id": d, "check": h[1], "key": h[2],
                                    "duplicate_of": h[0], "mode": h[3], "source_url": row.get("source_url")})
                    row = XD.apply_pointer(row, h[0], h[1], h[2], h[3])
                    if row is None:  # mode "skip"
                        st["xdedup_rows_skipped"] += 1
                        index.pop(d, None)
                        flags.pop(d, None)
                        ptr_ids.discard(d)
                        continue
                    put(row)
            if files and all(fr_.get("action") == "vanished" for fr_ in res["files"]):
                # every staged file of this place vanished: nothing new to publish, so don't rewrite/commit it
                res["skipped_vanished"] = True
                return res
            res["override_removed_ids"] = sorted(x["doc_id"] for x in override_log)
            if override_log:
                od = quarantine / "_override_existing" / cc
                od.mkdir(parents=True, exist_ok=True)
                with (od / f"{key}.{run_id}.removed.jsonl").open("w", encoding="utf-8") as q:
                    for x in override_log:
                        q.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
            if ptr_log:
                pd_ = quarantine / "_dedupe" / cc
                pd_.mkdir(parents=True, exist_ok=True)
                with (pd_ / f"{key}.{run_id}.pointers.jsonl").open("w", encoding="utf-8") as q:
                    for x in ptr_log:
                        q.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
            if xold is not None:
                xold.idx.close()
            if dedupe_log:
                dd = quarantine / "_dedupe" / cc
                dd.mkdir(parents=True, exist_ok=True)
                with (dd / f"{key}.{run_id}.dedupe.jsonl").open("w", encoding="utf-8") as q:
                    for x in dedupe_log:
                        q.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
            # ---- write (sharded, streaming) ----
            data_dir = out_dir / S.place_dir("data", cc, key)
            old_local = {p.relative_to(out_dir).as_posix() for p in _existing_local_files(out_dir, cc, key)}
            old_all = old_local | set(hub_existing)
            if not index:
                res["empty"] = True
                res["deleted"] = sorted(old_all)
                return res
            import pyarrow as pa
            import pyarrow.parquet as pq
            pa.set_memory_pool(pa.system_memory_pool())  # return memory to the OS between places
            order = sorted(index.items(), key=lambda kv: (kv[1][2], kv[0]))
            data_dir.mkdir(parents=True, exist_ok=True)
            tmp_paths: List[Path] = []
            writer, shard_rows, total, batch, batch_bytes = None, 0, 0, [], 0
            sch = S.html_schema()

            def flush():
                nonlocal writer, shard_rows, batch, batch_bytes
                if not batch:
                    return
                if writer is None:
                    tp = data_dir / f".{key}.part{len(tmp_paths) + 1:04d}.{run_id}.tmp"
                    tmp_paths.append(tp)
                    writer = pq.ParquetWriter(str(tp), sch, compression="zstd")
                writer.write_table(rows_to_table(batch))
                shard_rows += len(batch)
                batch, batch_bytes = [], 0
                if shard_rows >= S.SHARD_MAX_ROWS or tmp_paths[-1].stat().st_size >= S.SHARD_MAX_BYTES:
                    writer.close()
                    writer, shard_rows = None, 0

            pdf_refs = load_pdf_refs(Path(job["state"]), cc, key) if job.get("state") else {}
            n_arch = n_restr = n_incomplete = n_unofficial = 0
            for did, (off, ln, _o) in order:
                spool.seek(off)
                row = pickle.loads(spool.read(ln))
                if did in pdf_refs:  # v1.2.0 pdf_ref (tools/upload_pdfs.py); else keep the published value
                    if row.get("pdf_ref") != pdf_refs[did]:
                        st["pdf_ref_set"] += 1
                    row["pdf_ref"] = pdf_refs[did]
                batch.append(row)
                batch_bytes += ln
                total += 1
                a, r_, inc, uo = flags.get(did, (False, False, False, False))
                n_arch += a; n_restr += r_; n_incomplete += inc; n_unofficial += uo
                if (len(batch) >= WRITE_BATCH_ROWS or batch_bytes >= WRITE_BATCH_BYTES
                        or shard_rows + len(batch) >= S.SHARD_MAX_ROWS):
                    flush()
            flush()
            if writer is not None:
                writer.close()
            if len(tmp_paths) == 1:
                finals = [S.html_path(cc, key)]
            else:
                finals = [S.shard_path(cc, key, i + 1) for i in range(len(tmp_paths))]
            for tp, rel in zip(tmp_paths, finals):
                tp.replace(out_dir / rel)
            for rel in sorted(old_local - set(finals)):  # stale local shards of this place
                (out_dir / rel).unlink(missing_ok=True)
            res["deleted"] = sorted(old_all - set(finals))
            nbytes, nrows = 0, 0
            want = S.html_schema()
            for rel in finals:  # rows were validated before spooling; re-check schema + counts (no full re-read)
                pf_ = pq.ParquetFile(str(out_dir / rel))
                if not pf_.schema_arrow.equals(want, check_metadata=False):
                    raise RuntimeError(f"post-write schema mismatch {rel}")
                nrows += pf_.metadata.num_rows
                nbytes += (out_dir / rel).stat().st_size
            if nrows != total:
                raise RuntimeError(f"post-write row count {nrows} != {total}")
            res["written"] = [(rel, None) for rel in finals]
            res["rows"] = total
            res["bytes"] = nbytes
            res["doc_stats"] = {"docs": total, "archived": n_arch, "archived_restricted": n_restr,
                                "content_incomplete": n_incomplete, "source_unofficial": n_unofficial}
            # first row (for metadata defaults)
            spool.seek(order[0][1][0])
            first = pickle.loads(spool.read(order[0][1][1]))
            res["first"] = {k: first.get(k) for k in ("place_id", "gnis", "source_platform")}
            return res
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
        res["traceback"] = traceback.format_exc()
        return res
    finally:
        try:
            spool_path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# main pass
# ---------------------------------------------------------------------------
def write_metadata(out_dir: Path, cc: str, key: str, res: Dict[str, Any], now_ms: int) -> Tuple[Path, str, Dict]:
    meta_rel = S.metadata_path(cc, key)
    meta_local = out_dir / meta_rel
    first = res["first"]
    old_src = next((q for q in [meta_local] + [out_dir / r for r in S.legacy_metadata_paths(cc, key)] if q.exists()), None)
    old_meta = json.loads(old_src.read_text()) if old_src is not None else {}
    pl = {**{k: old_meta.get(k) for k in S.PLACE_FIELDS if old_meta.get(k)}, **res["place"]}
    n = res["rows"]
    files = [r for r, _ in res["written"]]
    meta = {
        "place_id": first["place_id"], "place_key": key,
        "qid": pl.get("qid") or (first["place_id"][3:] if first["place_id"].startswith("wd:") else None),
        "gnis": first.get("gnis"), "country_code": cc, "iso_3166_2": pl.get("iso_3166_2"),
        "admin_level": pl.get("admin_level") or ("country" if first["place_id"] == f"iso:{cc}" else
                                                  "adm1" if first["place_id"].startswith(f"iso:{cc}-") else None),
        "place_name": pl.get("place_name"), "platform": pl.get("platform") or first.get("source_platform"),
        "platform_place_id": pl.get("platform_place_id"), "total_docs": n, "total_sections": n,
        "last_updated": now_ms, "schema_version": S.SCHEMA_VERSION,
        "html_files": files, "n_shards": len(files),
        "doc_stats": res["doc_stats"],
    }
    if pl.get("state_code") or cc == "US":
        meta["state_code"] = pl.get("state_code")
    meta_local.parent.mkdir(parents=True, exist_ok=True)
    tmp = meta_local.with_name(meta_local.name + ".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(meta_local)
    return meta_local, meta_rel, meta


PLACES_DROP_FRAC = 0.01     # places.parquet may shrink by at most 1% (or PLACES_DROP_ABS rows) vs the Hub's
PLACES_DROP_ABS = 10
META_DROP_FRAC = 0.05       # local metadata places of this repo may be at most 5% (or PLACES_DROP_ABS) fewer than the Hub's rows of it
_HUB_PLACES: Dict[str, Any] = {}  # tests inject {"fn": callable(api, repo, scratch) -> (total, owned) | None}


def hub_places_counts(api, repo: str, scratch: Path) -> Optional[Tuple[int, int]]:
    """(total rows, rows whose source_repo == repo) of the Hub's current world_law/places.parquet; None when the
    repo has no places.parquet yet. Any other failure raises (the caller blocks the commit)."""
    if _HUB_PLACES.get("fn"):
        return _HUB_PLACES["fn"](api, repo, scratch)
    import pyarrow.parquet as pq
    from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError
    dl = getattr(api, "hf_hub_download", None)
    if dl is None:
        from huggingface_hub import hf_hub_download as dl
    try:
        p = dl(repo, f"{S.ROOT}/places.parquet", repo_type="dataset", local_dir=str(scratch / "hub_places" / repo.replace("/", "__")))
    except (EntryNotFoundError, RepositoryNotFoundError):
        return None  # new repo / no places.parquet yet: nothing on the Hub to shrink
    t = pq.read_table(p, columns=["source_repo"])
    owned = sum(1 for v in t.column("source_repo").to_pylist() if v in (None, repo))
    return t.num_rows, owned


def places_guard(api, repo: str, scratch: Path, n_rows: int, n_meta: int, args) -> Optional[str]:
    """None if the new places.parquet may be committed, else a BLOCKED message. Blocks when the new places.parquet
    has fewer rows than the Hub's beyond max(PLACES_DROP_ABS, PLACES_DROP_FRAC) or the local metadata count of this
    repo is more than META_DROP_FRAC below the Hub's rows of this repo (e.g. out/ lost its metadata in a restore).
    --allow-places-shrink overrides (intentional mass deletion)."""
    if getattr(args, "allow_places_shrink", False):
        return None
    if api is None and not _HUB_PLACES.get("fn"):
        return None  # no Hub access (dry run without api): nothing would be committed anyway
    try:
        hub = hub_places_counts(api, repo, scratch)
    except Exception as e:  # noqa: BLE001
        return f"BLOCKED {repo}: cannot read the Hub places.parquet to check for shrinkage ({e!r}); nothing committed"
    if hub is None:
        return None
    hub_total, hub_owned = hub
    frac = getattr(args, "places_drop_frac", PLACES_DROP_FRAC)
    tol = max(PLACES_DROP_ABS, int(hub_total * frac))
    if n_rows < hub_total - tol:
        return (f"BLOCKED {repo}: new places.parquet has {n_rows} rows vs {hub_total} on the Hub "
                f"(drop {hub_total - n_rows} > tolerance {tol}); local out/ metadata looks incomplete; nothing committed. "
                f"Restore out/world_law/metadata from the Hub (or pass --allow-places-shrink if intended)")
    mtol = max(PLACES_DROP_ABS, int(hub_owned * META_DROP_FRAC))
    if hub_owned and n_meta < hub_owned - mtol:
        return (f"BLOCKED {repo}: only {n_meta} local metadata places vs {hub_owned} rows of this repo on the Hub "
                f"(drop {hub_owned - n_meta} > tolerance {mtol}); nothing committed. Restore out/world_law/metadata from the Hub "
                f"(or pass --allow-places-shrink if intended)")
    return None


def commit_repo(kind: str, R: Dict[str, Any], args, api, scratch: Path, run_id: str, stats: Counter,
                dry: bool, bookkeep=None) -> Tuple[bool, List[str]]:
    """places.parquet + card + manifest for ONE repo from its local out tree, then <=500-op commits.
    Returns (ok, commit ids). Stats keys are prefixed with the repo kind for the national repo.
    bookkeep(places: set of (cc, key), ids: list) is called RIGHT AFTER each successful commit (and for places
    whose chunk needs no Hub op), so a kill later in the run never leaves committed places unledgered.
    Before each commit the memory guard runs; on MEM_LOW no further commit is started."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    repo, out_dir, adds, deletes, hub_files = R["repo"], R["out"], R["adds"], R["deletes"], R["hub_files"]
    pre = "" if kind == "municipal" else f"{kind}_"
    root = out_dir / S.ROOT
    # DIR_FULL guard (HF: 10,000 files per directory): count the touched countries' Hub dirs from the scoped
    # listing; places that would push data/<CC>/ or metadata/<CC>/ over DIR_FULL_LIMIT are deferred (files stay
    # staged, nothing of them is committed or listed in places.parquet).
    place_adds: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for _l, rel, extra in adds:
        place_adds[(extra.get("country_code") or rel.split("/")[2], extra.get("place_key") or rel)].append(rel)
    dir_counts0 = hub_dir_counts(hub_files)
    deferred, dfull, dir_counts = plan_dir_full(place_adds, hub_files, DIR_FULL_LIMIT, base=dir_counts0)
    R["deferred"] = set(deferred)
    R["dir_counts"] = dict(sorted(dir_counts0.items()))
    R["dir_full_by_country"] = dict(dfull)
    if deferred:
        for cc_, n in sorted(dfull.items()):
            log(f"DIR_FULL {repo}: {n} place(s) in {cc_} deferred (fullest {cc_} dir: {cc_max_dir(dir_counts0, cc_)} "
                f"files; limit {DIR_FULL_LIMIT}); their files stay staged")
        stats[pre + "places_deferred_dir_full"] += len(deferred)
        adds = [a for a in adds if (a[2].get("country_code") or a[1].split("/")[2],
                                    a[2].get("place_key") or a[1]) not in deferred]
        R["places_noop"] = [ck for ck in (R.get("places_noop") or ()) if ck not in deferred]
    recs, card_stats = [], defaultdict(Counter)
    for mp in S.iter_local_metadata(root):
        m = json.loads(mp.read_text())
        if (kind == "national") != S.is_national_key(m["place_key"]):
            continue  # never list the other repo's places (e.g. leftovers from before the split)
        if (m["country_code"], m["place_key"]) in R["deferred"]:
            continue  # DIR_FULL: not on the Hub, not listed
        files = m.get("html_files") or [S.html_path(m["country_code"], m["place_key"])]
        recs.append({c: m.get(c) for c in S.PLACES_COLUMNS if c not in ("html_path", "metadata_path", "n_shards", "source_repo", "source_paths", "has_local_data")}
                    | {"html_path": files[0] if len(files) == 1 else S.shard_glob(m["country_code"], m["place_key"]),
                       "metadata_path": S.metadata_path(m["country_code"], m["place_key"]),
                       "n_shards": len(files), "source_repo": repo, "source_paths": None,
                       "has_local_data": True})
        ds = m.get("doc_stats") or {"docs": m.get("total_docs") or 0}
        card_stats[m["country_code"]].update(ds)
        card_stats[m["country_code"]]["places"] += 1
    if kind == "municipal" and repo == S.REPO_ID and not getattr(args, "no_us_pointers", False):
        # pointer rows for the US corpus (kept in american_municipal_law); refreshed from its listing at most daily
        import us_pointers
        heartbeat(phase="us pointers")
        have = {r["place_id"] for r in recs}
        ptr = [r for r in us_pointers.pointer_rows(Path(args.state)) if r["place_id"] not in have]
        recs.extend(ptr)
        stats["us_pointer_rows"] = len(ptr)
    places_local = root / "places.parquet"
    root.mkdir(parents=True, exist_ok=True)
    tmp = places_local.with_name("places.parquet.tmp")
    pq.write_table(pa.Table.from_pylist(recs, schema=S.places_schema()), str(tmp), compression="zstd")
    tmp.replace(places_local)
    n_meta = sum(1 for r in recs if r.get("source_repo") == repo)
    blocked = places_guard(api, repo, scratch, len(recs), n_meta, args)
    if blocked:
        log(blocked)
        print(blocked, flush=True)
        stats[pre + "blocked"] = 1
        stats["blocked"] = 1
        R["blocked"] = blocked
        if not dry:
            return False, []

    countries = {c for c in card_stats} | set(R.get("hub_countries") or ()) | {
        f.split("/")[2] for f in hub_files if f.startswith(f"{S.ROOT}/data/") and f.count("/") >= 3}
    if kind == "municipal":
        countries |= set(PHASE1_COUNTRIES)
    readme = out_dir / "README.md"
    tmp = readme.with_name("README.md.tmp")
    tmp.write_text(build_card(countries, {k: dict(v) for k, v in card_stats.items()}, kind=kind))
    tmp.replace(readme)

    man_rel = f"{S.ROOT}/manifests/drop_{run_id}_manifest.jsonl"
    man_local = out_dir / man_rel
    man_local.parent.mkdir(parents=True, exist_ok=True)
    built_at = S.utc_now_iso()
    with man_local.open("w") as f:
        for local, rel, extra in adds + [(places_local, f"{S.ROOT}/places.parquet", {"rows": len(recs)})]:
            f.write(json.dumps({"path_in_repo": rel, "sha256": sha256_file(local), "bytes": local.stat().st_size,
                                "rows": extra.get("rows"), "place_id": extra.get("place_id"),
                                "place_key": extra.get("place_key"), "country_code": extra.get("country_code"),
                                "source_files": extra.get("source_files"), "built_at": built_at,
                                "schema_version": S.SCHEMA_VERSION, "repo": repo}, ensure_ascii=False) + "\n")
        for rel, why in deletes:
            f.write(json.dumps({"path_in_repo": rel, "deleted": True, "reason": why, "built_at": built_at,
                                "schema_version": S.SCHEMA_VERSION, "repo": repo}) + "\n")
    # Commit plan: each place's adds AND its stale-file deletes stay in the same chunk/commit.
    by_place: Dict[Tuple[str, str], List[Tuple[str, Any]]] = defaultdict(list)
    for local, rel, extra in adds:
        by_place[(extra.get("country_code") or rel.split("/")[2], extra.get("place_key") or rel)].append(("add", (local, rel)))
    for rel, why in deletes:
        pk = Path(rel).name.split("_html.parquet")[0].split(".s0")[0]
        pk = pk[:-5] if pk.endswith(".json") else pk
        by_place[(rel.split("/")[2], pk)].append(("delete", rel))
    rel_place = {v[1] if k == "add" else v: ck for ck, g in by_place.items() for k, v in g}
    for ck in R.get("places_noop") or ():  # places with nothing to publish/delete still need bookkeeping
        by_place.setdefault(ck, [])
    tail = [("add", (places_local, f"{S.ROOT}/places.parquet")), ("add", (man_local, man_rel)),
            ("add", (readme, "README.md"))]
    max_ops = MAX_OPS_PER_COMMIT
    avail = mem_available_gb()
    if avail < getattr(args, "mem_small_chunk_gb", MEM_SMALL_CHUNK_GB):
        max_ops = min(max_ops, getattr(args, "mem_small_chunk_ops", MEM_SMALL_CHUNK_OPS))
        log(f"mem: MemAvailable {avail:.2f} GB -> commit chunks of <= {max_ops} ops")
        stats[pre + "small_commit_chunks"] = 1
    chunks, cur, cur_places, chunk_places = [], [], set(), []
    for ck in sorted(by_place):
        g = by_place[ck]
        if cur and len(cur) + len(g) > max_ops - len(tail):
            chunks.append(cur)
            chunk_places.append(cur_places)
            cur, cur_places = [], set()
        cur.extend(g)
        cur_places.add(ck)
    cur.extend(tail)
    chunks.append(cur)
    chunk_places.append(cur_places)
    plan = scratch / ("planned_commit.jsonl" if kind == "municipal" else f"planned_commit_{kind}.jsonl")
    with plan.open("w") as pf:
        for ci, ch in enumerate(chunks):
            for k, v in ch:
                pf.write(json.dumps({"repo": repo, "commit": ci + 1, "op": k,
                                     "path_in_repo": v[1] if k == "add" else v}) + "\n")
    stats[pre + "files_to_upload"] += sum(1 for ch in chunks for k, _ in ch if k == "add")
    stats[pre + "hub_deletes_planned"] += len(deletes)
    stats[pre + "commits_planned"] += len(chunks)
    ids: List[str] = []
    if dry or args.no_upload:
        log(f"{'DRY-RUN' if dry else 'NO-UPLOAD'}: would commit {sum(1 for ch in chunks for k, _ in ch if k == 'add')} "
            f"adds + {len(deletes)} deletes in {len(chunks)} commit(s) to {repo} (plan: {plan})")
        if bookkeep:
            for cp in chunk_places:
                bookkeep(cp, ids)
        return True, ids
    if repo in FORBIDDEN_REPOS:
        raise SystemExit(f"refusing to write to {repo}")
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete
    try:
        for ci, ch in enumerate(chunks):
            if time.time() >= args._deadline:
                log(f"ERROR run deadline reached before {repo} part {ci + 1}/{len(chunks)}; "
                    f"stopping, its staged files are left in place for the next run")
                stats[pre + "deadline_stop"] = 1
                return False, ids
            if not mem_guard(f"commit {kind} {ci + 1}/{len(chunks)}", args.mem_low_gb, args.mem_wait, stats):
                stats[pre + "mem_low_commits_skipped"] = len(chunks) - ci
                log(f"MEM_LOW: {repo} parts {ci + 1}..{len(chunks)} not committed; their staged files stay for the next run")
                return False, ids
            heartbeat(phase=f"commit {kind} {ci + 1}/{len(chunks)}")
            # ops reference local FILES (path_or_fileobj=str path): huggingface_hub streams them, never bytes in RAM
            ops = [CommitOperationAdd(path_in_repo=v[1], path_or_fileobj=str(v[0])) if k == "add"
                   else CommitOperationDelete(path_in_repo=v) for k, v in ch
                   if (k == "add" or v in hub_files) and rel_place.get(v[1] if k == "add" else v) not in R["deferred"]]
            chunk_places[ci] = {ck for ck in chunk_places[ci] if ck not in R["deferred"]}
            if not ops:
                if bookkeep:
                    bookkeep(chunk_places[ci], ids)
                continue
            msg = f"world_law drop {run_id}: {len(R['places_written'])} places (part {ci + 1}/{len(chunks)})"
            try:
                c = guarded_commit(api, args.commit_timeout, args._deadline, f"{kind} {ci + 1}/{len(chunks)}",
                                   repo_id=repo, repo_type="dataset", operations=ops, commit_message=msg)
            except Exception as e:  # noqa: BLE001
                bad = parse_too_many_files(e)
                if bad is None or isinstance(e, CommitTimeout):
                    raise
                ch_ccs = {rel_place[o.path_in_repo][0] for o in ops if o.path_in_repo in rel_place}
                if not bad:  # dirs not named: defer the chunk's countries that are closest to the limit
                    bad = {cc_ for cc_ in ch_ccs if cc_max_dir(dir_counts, cc_) >= DIR_FULL_LIMIT - MAX_OPS_PER_COMMIT}
                bad &= ch_ccs
                if not bad:
                    raise
                newly = {ck for ck in by_place if ck[0] in bad} - R["deferred"]
                R["deferred"] |= newly
                for ck in newly:
                    R["dir_full_by_country"][ck[0]] = R["dir_full_by_country"].get(ck[0], 0) + 1
                stats[pre + "places_deferred_dir_full"] += len(newly)
                stats[pre + "dir_full_commit_retries"] += 1
                log(f"DIR_FULL {repo}: commit rejected (too many files per directory) for {sorted(bad)}; "
                    f"deferring {len(newly)} place(s) and retrying once without them")
                # places.parquet must not list the deferred places
                recs[:] = [r for r in recs if (r.get("country_code"), r.get("place_key")) not in R["deferred"]]
                tmp = places_local.with_name("places.parquet.tmp")
                pq.write_table(pa.Table.from_pylist(recs, schema=S.places_schema()), str(tmp), compression="zstd")
                tmp.replace(places_local)
                ops = [o for o in ops if rel_place.get(o.path_in_repo) not in R["deferred"]]
                chunk_places[ci] = {ck for ck in chunk_places[ci] if ck not in R["deferred"]}
                if not ops:
                    if bookkeep:
                        bookkeep(chunk_places[ci], ids)
                    continue
                c = guarded_commit(api, args.commit_timeout, args._deadline, f"{kind} {ci + 1}/{len(chunks)} retry",
                                   repo_id=repo, repo_type="dataset", operations=ops,
                                   commit_message=msg + " [dir-full retry]")
            log(f"committed {len(ops)} ops to {repo} ({ci + 1}/{len(chunks)}): {c.commit_url}")
            stats[pre + "commits"] += 1
            ids.append(getattr(c, "oid", None) or str(c.commit_url).rsplit("/", 1)[-1])
            del ops, c
            if bookkeep:
                heartbeat(phase=f"bookkeeping {kind} {ci + 1}/{len(chunks)}")
                bookkeep(chunk_places[ci], ids)  # ledger + move NOW, not at the end of the run
            release_memory()
        return True, ids
    except Exception as e:
        if isinstance(e, CommitTimeout):
            stats[pre + "commit_timeout"] = 1
        log(f"ERROR upload to {repo} failed, its staged files are left in place for retry: {e}")
        stats[pre + "upload_failed"] = 1
        return False, ids


def run_once(args) -> Dict[str, Any]:
    staging, out_base = Path(args.staging), Path(args.out)
    dry = args.dry_run
    run_id = utc_ts()
    args._deadline = time.time() + args.run_deadline
    heartbeat(run_id=run_id, phase="start")
    state = Path(args.state)
    nat_base = Path(args.out_national) if args.out_national else out_base.parent / "out_national"
    if dry:
        scratch = state / f"dryrun_{run_id}"
        out_dir, quarantine, processed, held = scratch / "out", scratch / "quarantine", scratch / "processed", scratch / "held"
        nat_dir = scratch / "out_national"
        scratch.mkdir(parents=True, exist_ok=True)
        for b, d in ((out_base, out_dir), (nat_base, nat_dir)):
            if (b / S.ROOT).exists():  # seed with the real out trees (hard-linked, never written through)
                _seed_tree(b / S.ROOT, d / S.ROOT)
    else:
        scratch = state / f"work_{run_id}"
        scratch.mkdir(parents=True, exist_ok=True)
        out_dir, quarantine, processed, held = out_base, Path(args.quarantine), Path(args.processed), Path(args.held)
        nat_dir = nat_base
    # repo routing: municipal (args.repo, out_dir) / national (args.national_repo, nat_dir)
    repos = {"municipal": {"repo": args.repo, "out": out_dir}, "national": {"repo": args.national_repo, "out": nat_dir}}
    kind_of = lambda key: "national" if S.is_national_key(key) else "municipal"  # noqa: E731
    ledger_path = state / "ledger.jsonl"
    heartbeat(phase="discover")
    overrides = load_overrides(Path(args.overrides))

    disk = disk_guard(state, args.disk_warn_gb, args.disk_stop_gb)
    items = [] if disk["skip_builds"] else discover(staging, args.min_age, args.bot)
    stats: Counter = Counter()
    stats["disk_free_gb_start"] = disk["free_gb"]
    if disk["skip_builds"]:
        stats["disk_skipped_builds"] = 1
    stats["files_found"] = len(items)
    log(f"found {len(items)} completed staged files" + (f" (dry-run scratch {scratch})" if dry else ""))
    if args.max_files:
        items = sorted(items, key=lambda d: d.get("order", (0,)))[: args.max_files]
    heartbeat(phase="ledger")
    ledger = load_ledger(ledger_path, rels={str(it["path"].relative_to(staging)) for it in items})

    api = None
    for kind, R in repos.items():
        R["hub_files"], R["hub_countries"] = set(), set()
    if not args.no_hub_listing:
        from huggingface_hub import HfApi
        api = HfApi()

    file_results: List[Dict[str, Any]] = []
    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for it in items:
        p: Path = it["path"]
        rel = str(p.relative_to(staging))
        if it.get("bad_name"):
            file_results.append({**it, "rel": rel, "action": "quarantine_file",
                                 "reason": "bad_filename (want <place_key>[.<batch>].jsonl)"})
            stats["files_bad_name"] += 1
            continue
        try:
            digest = sha256_file(p)
        except FileNotFoundError:  # moved/removed by its lane after discovery: skip it this run
            log(f"WARN staged file vanished before hashing: {p}")
            stats["files_vanished_before_read"] += 1
            continue
        it["sha256"], it["rel"] = digest, rel
        if (it["bot"], rel, digest) in ledger:
            file_results.append({**it, "action": "already_processed"})
            stats["files_already_processed"] += 1
            continue
        groups[(it["cc"], it["key"])].append(it)
    # --rebuild-places: rebuild these places from their published rows (+ any staged files) without staging
    # anything, e.g. so new doc_overrides apply to already-published rows (counted override_removed_existing)
    for pk in (getattr(args, "rebuild_places", None) or []):
        try:
            if "/" in pk:  # "CC/place_key" (needed for wd_Q* / gnis keys, whose country isn't in the key)
                cc_r, pk = pk.split("/", 1)
                cc_r = cc_r.strip().upper()
                if not re.match(r"^[A-Z]{2}$", cc_r):
                    raise ValueError(f"bad country code in {cc_r}/{pk}")
            else:
                cc_r = _cc_of_key(pk)
        except ValueError as e:
            log(f"WARN --rebuild-places {pk}: {e}")
            stats["rebuild_places_invalid"] += 1
            continue
        if (cc_r, pk) not in groups:
            groups[(cc_r, pk)] = []
        stats["rebuild_places_requested"] += 1
    stats["ts_from_name"] = sum(1 for g in groups.values() for f in g if f["order"][4] == "name")
    stats["ts_from_mtime"] = sum(1 for g in groups.values() for f in g if f["order"][4] == "mtime")

    # cross-lane dedupe: primary-record index per country that has hf: imports staged for the national repo
    import_ccs = sorted({cc for (cc, key), fl in groups.items() if kind_of(key) == "national"
                         and any(".hf" in Path(f["path"]).name for f in fl)})
    pindex: Dict[str, Any] = {}
    for cc in import_ccs:
        heartbeat(phase=f"dedupe index {cc}")
        staged_primary = [(key, Path(f["path"])) for (c2, key), fl in groups.items() if c2 == cc
                          and kind_of(key) == "national" for f in fl if ".hf" not in Path(f["path"]).name]
        try:
            # evicted national parquet of this country is re-downloaded (verified) first, else the index would
            # silently miss primary records; a failure raises -> imports for cc are held this pass
            ev_miss = OS_.evicted_missing(nat_dir, state, args.national_repo, cc, national=True)
            if ev_miss and api is None:
                raise OS_.RehydrateError(f"{len(ev_miss)} evicted national places in {cc}, no Hub access")
            for _pk, miss in sorted(ev_miss.items()):
                OS_.rehydrate(args.national_repo, nat_dir, state, miss, download=_REHYDRATE_DL.get("fn"), log=log,
                                              hub_lookup=_REHYDRATE_DL.get("hub"))
                stats["dedupe_places_rehydrated"] += 1
            pi = DD.build_index(cc, nat_dir / S.ROOT, staged_primary, _iter_staged_tolerant)
            pindex[cc] = pi.to_obj()
            stats["dedupe_index_keys"] += len(pi)
        except Exception as e:  # noqa: BLE001
            log(f"WARN dedupe index for {cc} failed: {e!r}; imports for {cc} are held this pass")
            stats["dedupe_index_failed"] += 1
            for k in [k for k in groups if k[0] == cc and kind_of(k[1]) == "national"]:
                groups.pop(k)

    # NEW-row duplicate checks (xdedup.py, 2026-10-19): config + cross-place plan for municipal places
    xcfg = XD.load_config()
    old_db = DX.STATE_DIR / "old_urls.sqlite"
    xplan_all: Dict[Tuple[str, str], Dict[str, Dict[str, str]]] = {}
    if xcfg.get("old_repo", "off") != "off" and not old_db.exists():
        log(f"WARN xdedup: {old_db} missing; old-repo URL check disabled this run")
    if xcfg.get("cross_place", "off") != "off":
        mun_staged = [(cc, key, Path(f["path"])) for (cc, key), fl in sorted(groups.items())
                      if kind_of(key) == "municipal" for f in fl]
        if mun_staged:
            heartbeat(phase="xdedup prepass")
            pub = DX.PubIndex(DX.STATE_DIR / "mun_published.sqlite") if args.repo == S.REPO_ID else None
            try:
                xplan_all = XD.plan_cross_place(mun_staged, _iter_staged_tolerant, pub,
                                                budget_s=float(xcfg.get("prepass_budget_s", 1200)), stats=stats)
                stats["xdedup_plan_rows"] = sum(len(v) for v in xplan_all.values())
            except Exception as e:  # noqa: BLE001  (never blocks the run; check skipped this pass)
                log(f"WARN xdedup cross-place prepass failed: {e!r}; cross-place check skipped this run")
                stats["xdedup_prepass_failed"] += 1
                xplan_all = {}
            finally:
                if pub is not None:
                    pub.close()

    # Scoped Hub listing: only data/<CC>/ + metadata/<CC>/ of the countries this run touches, per repo
    # (replaces the full recursive listing of the ~100 GB repo that timed out / 504ed). A country whose listing
    # fails after retries is skipped: its staged files are left in staging for the next run.
    if api is not None:
        for kind, R in repos.items():
            ccs = {cc for (cc, key) in groups if kind_of(key) == kind}
            if not ccs:
                continue
            files, failed = scoped_hub_listing(api, R["repo"], ccs)
            R["hub_files"] = files
            stats[("" if kind == "municipal" else kind + "_") + "hub_listed_countries"] = len(ccs) - len(failed)
            if failed:
                skipped = [k for k in groups if k[0] in failed and kind_of(k[1]) == kind]
                for k in skipped:
                    groups.pop(k)
                stats["places_skipped_listing_failed"] += len(skipped)
                stats["countries_skipped_listing_failed"] += len(failed)
                log(f"skipped {len(skipped)} {kind} places in {sorted(failed)} (listing failed); files stay staged")
            R["hub_countries"] = hub_countries(api, R["repo"], state)

    jobs = []
    for (cc, key), fl in sorted(groups.items()):
        fl.sort(key=lambda d: d["order"][:4])
        R = repos[kind_of(key)]
        jobs.append({"cc": cc, "key": key, "out_dir": str(R["out"]), "scratch": str(scratch),
                     "quarantine": str(quarantine), "held": str(held), "run_id": run_id,
                     "overrides": {k: v for k, v in overrides.items() if k[0] == cc and k[1] == key},
                     "hub_files": sorted(f for f in R["hub_files"] if S.is_place_data_file(f, cc, key)),
                     "hub_download": api is not None, "repo": R["repo"], "state": str(state),
                     "primary_index": pindex.get(cc) if kind_of(key) == "national" else None,
                     "xdedup": {"cfg": xcfg, "old_db": str(old_db) if old_db.exists() else None,
                                "plan": xplan_all.get((cc, key)) or {},
                                "collect_keys": kind_of(key) == "municipal" and args.repo == S.REPO_ID and not dry},
                     "files": [{k: (str(v) if k == "path" else v) for k, v in f.items()} for f in fl]})
    log(f"{len(jobs)} places to build with {args.workers} worker(s) "
        f"({sum(1 for j in jobs if S.is_national_key(j['key']))} -> {args.national_repo})")

    results: List[Dict[str, Any]] = []
    xkeys_by_place: Dict[Tuple[str, str], list] = {}
    per_cc: Dict[str, Counter] = defaultdict(Counter)
    held_table: Counter = Counter()

    def consume(res):
        if res.get("xkeys"):
            xkeys_by_place[(res["cc"], res["key"])] = res["xkeys"]
        res.pop("xkeys", None)
        results.append(res)
        c = per_cc[res["cc"]]
        for fr in res["files"]:
            bot = fr["bot"]
            file_results.append({**fr, "path": Path(fr["path"]), "cc": res["cc"], "place": res["key"]})
        for k, v in res["stats"].items():
            stats[k] += v
            c[k] += v
        for reason, n in res["held_by"].items():
            held_table[(res["cc"], reason)] += n
        if res.get("error"):
            log(f"ERROR place {res['cc']}/{res['key']}: {res['error']}")
            stats["places_failed"] += 1
        if len(results) % 500 == 0:
            log(f"... {len(results)}/{len(jobs)} places (rss {rss_mb()[0]} MB, avail {mem_available_gb():.2f} GB)")

    if args.workers > 1:
        if not mem_guard("build pool start", args.mem_low_gb, args.mem_wait, stats):
            jobs = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(build_place, jobs, chunksize=4):
                consume(res)  # (multi-worker runs are only guarded at the start of the run)
    else:
        mem_stopped = False
        for j in jobs:
            if disk_free_gb() < args.disk_stop_gb:
                stats["disk_stopped_builds_midrun"] += 1
                stats["places_deferred_disk"] += 1
                continue  # staged files stay in staging/ and are retried next run
            if mem_stopped or not mem_guard(f"build {j['cc']}/{j['key']}", args.mem_low_gb, args.mem_wait, stats):
                mem_stopped = True
                stats["places_deferred_mem"] += 1
                continue  # staged files stay in staging/ and are retried next run
            heartbeat(phase=f"build {j['cc']}/{j['key']}")
            consume(build_place(j))
            j.clear()  # drop the job's file list / overrides / dedupe index reference
    jobs.clear()
    pindex.clear()
    release_memory()
    # held rows per bot/country/reason (from the files' held counts)
    held_by_bot: Counter = Counter()
    for fr in file_results:
        if fr.get("held"):
            held_by_bot[(fr["bot"], fr["cc"])] += fr["held"]

    now_ms = int(time.time() * 1000)
    for R in repos.values():
        R["adds"], R["deletes"], R["places_written"], R["places_noop"] = [], [], [], []
    places_written = []
    for res in results:
        cc, key = res["cc"], res["key"]
        if res.get("error"):
            continue
        if res.get("skipped_vanished"):
            stats["places_skipped_all_files_vanished"] += 1
            continue
        R = repos[kind_of(key)]
        adds, deletes, out_dir_r, hub_files = R["adds"], R["deletes"], R["out"], R["hub_files"]
        if res.get("empty"):
            stats["places_empty_after_hold_or_full"] += 1
            per_cc[cc]["places_empty"] += 1
            meta_rel = S.metadata_path(cc, key)
            for rel in res["deleted"]:
                deletes.append((rel, "place has no publishable rows"))
                (out_dir_r / rel).unlink(missing_ok=True)
            for mrel in [meta_rel] + S.legacy_metadata_paths(cc, key):
                if (out_dir_r / mrel).exists() or mrel in hub_files:
                    deletes.append((mrel, "place has no publishable rows"))
                    (out_dir_r / mrel).unlink(missing_ok=True)
            if not res["deleted"] and not any(d[0] == meta_rel for d in deletes):
                R["places_noop"].append((cc, key))
            continue
        meta_local, meta_rel, meta = write_metadata(out_dir_r, cc, key, res, now_ms)
        for lrel in S.legacy_metadata_paths(cc, key):  # place moved to the bucketed layout: drop the flat JSON
            if (out_dir_r / lrel).exists() or lrel in hub_files:
                deletes.append((lrel, "legacy layout (moved to hash bucket)"))
                (out_dir_r / lrel).unlink(missing_ok=True)
        extra = {"rows": res["rows"], "place_id": meta["place_id"], "place_key": key, "country_code": cc,
                 "source_files": [f["rel"] for f in res["files"]]}
        for rel, _ in res["written"]:
            adds.append((out_dir_r / rel, rel, extra))
        adds.append((meta_local, meta_rel, {**extra, "rows": None}))
        for rel in res["deleted"]:
            deletes.append((rel, "stale shard after re-shard"))
        places_written.append((cc, key))
        R["places_written"].append((cc, key))
        stats["places_written"] += 1
        stats["bytes_written"] += res["bytes"]
        stats["shards_written"] += len(res["written"])
        stats["places_sharded"] += len(res["written"]) > 1
        c = per_cc[cc]
        c["places"] += 1
        c["docs"] += res["rows"]
        c["bytes"] += res["bytes"]
        c["files_out"] += len(res["written"])
        c["places_sharded"] += len(res["written"]) > 1
        for k, v in res["doc_stats"].items():
            if k != "docs":
                c[k] += v

    failed_places = {(r["cc"], r["key"]) for r in results if r.get("error")}
    results.clear()

    # files of each place (processed rows only; failed places stay staged)
    files_by_place: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for fr in file_results:
        if fr["action"] == "processed" and (fr["cc"], fr.get("place")) not in failed_places:
            files_by_place[(fr["cc"], fr["place"])].append(fr)

    # quarantined / already-processed files don't depend on any commit: move them first
    for fr in file_results:
        if fr["action"] == "processed":
            continue
        p: Path = fr["path"]
        if fr["action"] == "vanished":
            stats["files_vanished_skipped"] += 1
            continue
        if not dry and not p.exists():  # superseded/removed by its producer during the run: nothing to move
            log(f"WARN staged file vanished before move ({fr['action']}): {p}")
            stats["files_vanished_before_move"] += 1
            continue
        if fr["action"] == "quarantine_file":
            qdir = quarantine / fr["bot"] / fr["cc"]
            if dry:
                qdir.mkdir(parents=True, exist_ok=True)
                (qdir / f"{p.name}.reason.txt").write_text(fr["reason"] + "\n")
                stats["would_quarantine_files"] += 1
                continue
            dst = move_unique(p, qdir)
            if dst is None:
                stats["files_vanished_before_move"] += 1
                continue
            dst.with_name(dst.name + ".reason.txt").write_text(fr["reason"] + "\n")
            stats["files_quarantined"] += 1
            continue
        if dry:
            stats["would_move_to_processed"] += 1
            continue
        if move_unique(p, processed / fr["bot"] / fr["cc"]) is None:
            stats["files_vanished_before_move"] += 1
            continue
        stats["files_moved_to_processed"] += 1
    file_results.clear()

    def bookkeep_for(kind: str):
        repo = repos[kind]["repo"]

        def bookkeep(places, ids):
            """Ledger + move the staged files of `places` right after their commit landed (ids so far)."""
            if kind == "municipal" and not dry:  # newly published rows join the cross-place index
                try:
                    n = XD.add_published_keys(DX.STATE_DIR / "mun_published.sqlite",
                                              [k for ck in places for k in xkeys_by_place.pop(ck, [])])
                    stats["xdedup_pub_index_added"] += n
                except Exception as e:  # noqa: BLE001
                    log(f"WARN xdedup: could not extend the published index: {e!r}")
            for ck in sorted(places):
                for fr in files_by_place.pop(ck, []):
                    if dry:
                        stats["would_move_to_processed"] += 1
                        continue
                    p: Path = fr["path"]
                    # (a re-run after a kill may find it already moved; a lane may have removed it meanwhile.
                    # Its rows are committed either way, so it is still ledgered as handled)
                    if p.exists() and move_unique(p, processed / fr["bot"] / fr["cc"]) is None:
                        stats["files_vanished_before_move"] += 1
                    append_jsonl(ledger_path, {"bot": fr["bot"], "rel": fr["rel"], "sha256": fr["sha256"],
                                               "rows": fr.get("rows"), "held": fr.get("held"),
                                               "rejected": fr.get("rejected"), "at": S.utc_now_iso(),
                                               "repo": repo, "cc": fr["cc"], "place_key": fr.get("place"),
                                               "commit_ids": list(ids)})
                    stats["files_moved_to_processed"] += 1
        return bookkeep

    failed_kinds: set = set()
    commit_ids: List[str] = []
    commit_ids_by_repo: Dict[str, List[str]] = {}
    t_start = time.time()
    heartbeat(phase="commit")
    for kind, R in repos.items():
        bk = bookkeep_for(kind)
        if not (R["adds"] or R["deletes"]):
            bk({ck for ck in files_by_place if kind_of(ck[1]) == kind}, [])  # nothing to publish for this repo
            continue
        ok, ids = commit_repo(kind, R, args, api, scratch, run_id, stats, dry, bookkeep=bk)
        commit_ids += ids
        commit_ids_by_repo[R["repo"]] = ids
        if not ok:
            failed_kinds.add(kind)
        else:  # places of this repo not in any chunk (should not happen) are still safe: their ops all landed
            bk({ck for ck in files_by_place if kind_of(ck[1]) == kind and ck not in R.get("deferred", ())}, ids)
    stats["files_left_staged_uncommitted"] = sum(len(v) for v in files_by_place.values())
    dir_full = {R["repo"]: R["dir_full_by_country"] for R in repos.values() if R.get("dir_full_by_country")}
    stats["files_left_staged_dir_full"] = sum(len(v) for ck, v in files_by_place.items()
                                              if any(ck in R.get("deferred", ()) for R in repos.values()))
    files_by_place.clear()
    release_memory()

    prune_res = None
    if not dry:
        shutil.rmtree(scratch, ignore_errors=True)  # every commit's bookkeeping is done; scratch is no longer needed
    do_prune = not args.no_prune and api is not None
    if stats.get("blocked"):
        do_prune = False  # a BLOCKED run touches nothing else (out/ is suspect)
    if do_prune and (stats.get("mem_low_stop") or mem_available_gb() < args.mem_low_gb):
        release_memory()
        if stats.get("mem_low_stop") or mem_available_gb() < args.mem_low_gb:
            msg = f"MEM_LOW MemAvailable={mem_available_gb():.2f}GB: skipping prune this run (nothing is lost)"
            log(msg)
            print(msg, flush=True)
            stats["prune_skipped_mem"] = 1
            do_prune = False
    if do_prune:
        heartbeat(phase="prune")
        try:
            sys.path.insert(0, str(_HERE / "tools"))
            import prune_processed as PP
            prune_res = PP.prune(state=state, out_dir=out_base, out_national=nat_base, processed=Path(args.processed),
                                 repo=args.repo, national_repo=args.national_repo, apply=not dry, api=api, log=log)
            stats["prune_files"] = prune_res.get("pruned", 0) if not dry else prune_res.get("eligible", 0)
            stats["prune_bytes"] = prune_res.get("bytes_freed", 0) if not dry else prune_res.get("eligible_bytes", 0)
        except Exception as e:  # pruning never fails a run
            log(f"WARN prune failed: {e!r}")
            stats["prune_failed"] = 1
    evict_res = None
    if do_prune and not dry and not getattr(args, "no_evict", False):
        heartbeat(phase="evict")
        try:
            sys.path.insert(0, str(_HERE / "tools"))
            import evict_out as EV
            evict_res = EV.evict_all(state, out_base, nat_base, args.repo, args.national_repo, api, apply=True, log=log)
            stats["evict_bytes"] = evict_res["bytes_evicted"]
        except Exception as e:  # eviction never fails a run (nothing is deleted unless verified)
            log(f"WARN evict failed: {e!r}")
            stats["evict_failed"] = 1
    summary = {"at": S.utc_now_iso(), "dry_run": dry, "repo": args.repo, "national_repo": args.national_repo,
               **dict(stats),
               "places_written_by_repo": {R["repo"]: len(R["places_written"]) for R in repos.values()},
               "commit_ids_by_repo": commit_ids_by_repo,
               "DIR_FULL": dir_full,
               "near_limit": {R["repo"]: near_limit_report(Counter(R.get("dir_counts") or {})) for R in repos.values()},
               "held_by_bot_country": {f"{b}/{c}": n for (b, c), n in sorted(held_by_bot.items())},
               "held_by_country_reason": {f"{c}/{r}": n for (c, r), n in sorted(held_table.items())},
               "per_country": {cc: dict(v) for cc, v in sorted(per_cc.items())},
               "blocked": [R["blocked"] for R in repos.values() if R.get("blocked")],
               "commit_ids": commit_ids, "upload_seconds": round(time.time() - t_start, 1),
               "disk": {**disk, "free_gb_end": round(disk_free_gb(), 2)}, "prune": prune_res, "evict": evict_res,
               "places": [f"{c}/{k}" for c, k in places_written][:50], "scratch": str(scratch),
               "rss_mb": rss_mb()[0], "peak_rss_mb": rss_mb()[1], "mem_available_gb_end": round(mem_available_gb(), 2)}
    if not dry:
        append_jsonl(state / "runs.jsonl", summary)
    else:
        (scratch / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log("summary " + json.dumps({k: v for k, v in summary.items() if k not in ("per_country", "places")}, default=str))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", default=str(BASE / "staging"))
    ap.add_argument("--out", default=str(BASE / "out"))
    ap.add_argument("--processed", default=str(BASE / "processed"))
    ap.add_argument("--quarantine", default=str(BASE / "quarantine"))
    ap.add_argument("--held", default=str(BASE / "held"), help="rows held back by source policy (never uploaded)")
    ap.add_argument("--state", default=str(BASE / "state"))
    ap.add_argument("--overrides", default=str(BASE / "state" / "doc_overrides.json"))
    ap.add_argument("--repo", default=S.REPO_ID, help="municipal / local places")
    ap.add_argument("--national-repo", default=S.NATIONAL_REPO_ID, help="iso:* places (country, adm1, supranational)")
    ap.add_argument("--out-national", default=None, help="local state of --national-repo (default: <out>/../out_national)")
    ap.add_argument("--bot", action="append", help="only these staging/<bot> dirs")
    ap.add_argument("--min-age", type=float, default=5.0, help="seconds since rename before pickup")
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1, help="parallel place builders (memory: ~1 place each)")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--interval", type=float, default=600.0)
    ap.add_argument("--dry-run", action="store_true", help="scratch dir only; no upload, no moves")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-hub-listing", action="store_true", help="don't list the Hub repo (offline / tests)")
    ap.add_argument("--no-us-pointers", action="store_true", help="omit the US pointer rows from places.parquet")
    ap.add_argument("--commit-timeout", type=float, default=COMMIT_TIMEOUT_S, help="hard per-commit watchdog (s)")
    ap.add_argument("--run-deadline", type=float, default=RUN_DEADLINE_S, help="no new commits after this many s")
    ap.add_argument("--disk-warn-gb", type=float, default=DISK_WARN_GB)
    ap.add_argument("--disk-stop-gb", type=float, default=DISK_STOP_GB)
    ap.add_argument("--mem-low-gb", type=float, default=MEM_LOW_GB,
                    help="MemAvailable floor before each place build / commit (gc + wait, then MEM_LOW stop)")
    ap.add_argument("--mem-wait", type=float, default=MEM_WAIT_S, help="seconds to wait for memory before MEM_LOW stop")
    ap.add_argument("--mem-small-chunk-gb", type=float, default=MEM_SMALL_CHUNK_GB,
                    help=f"below this MemAvailable, commit chunks of <= --mem-small-chunk-ops ops")
    ap.add_argument("--mem-small-chunk-ops", type=int, default=MEM_SMALL_CHUNK_OPS)
    ap.add_argument("--allow-places-shrink", action="store_true",
                    help="skip the BLOCKED guard (places.parquet / metadata shrink vs the Hub) for an intended mass delete")
    ap.add_argument("--places-drop-frac", type=float, default=PLACES_DROP_FRAC,
                    help="tolerated places.parquet row drop vs the Hub (fraction; min %d rows)" % PLACES_DROP_ABS)
    ap.add_argument("--no-evict", action="store_true", help="keep verified local data parquet (out_store.evict)")
    ap.add_argument("--rebuild-places", action="append", default=[], metavar="PLACE_KEY",
                    help="also rebuild this place (e.g. iso_US-CA, or CC/place_key such as NL/wd_Q727) from its published rows even with nothing "
                         "staged, so doc_overrides apply to existing rows; repeatable, or comma-separated")
    ap.add_argument("--rebuild-places-file", default=None,
                    help="file with one PLACE_KEY per line to rebuild (e.g. the pdf_ref backfill from tools/pdf_step.py)")
    ap.add_argument("--no-prune", action="store_true", help="skip verified pruning of processed/ (tools/prune_processed.py)")
    args = ap.parse_args(argv)
    args.rebuild_places = [k.strip() for v in args.rebuild_places for k in v.split(",") if k.strip()]
    if args.rebuild_places_file:
        args.rebuild_places += [ln.strip() for ln in Path(args.rebuild_places_file).read_text().splitlines()
                                if ln.strip() and not ln.startswith("#")]
    if args.repo in FORBIDDEN_REPOS or args.national_repo in FORBIDDEN_REPOS:
        raise SystemExit(f"refusing to write to {args.repo} / {args.national_repo}")
    if args.repo == args.national_repo:
        raise SystemExit("--repo and --national-repo must differ")
    Path(args.state).mkdir(parents=True, exist_ok=True)
    lock_path = Path(args.state) / "run_loop.lock"
    lock = open(lock_path, "a+")  # never truncate: the holder's pid/heartbeat JSON lives here
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        rep = lock_holder_report(lock_path, Path(args.state))
        log(f"another run_loop holds the lock; exiting (holder {json.dumps(rep.get('holder') if rep else None)})")
        lock.close()
        return 2
    _LOCK["f"] = lock
    _LOCK["info"] = {"pid": os.getpid(), "started_at": S.utc_now_iso(), "argv": sys.argv[1:]}
    heartbeat(phase="locked")
    while True:
        summ = run_once(args) or {}
        if summ.get("blocked"):
            for b in summ["blocked"]:
                print(b, flush=True)
            if args.once or args.dry_run:
                return 3
        if args.once or args.dry_run:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
