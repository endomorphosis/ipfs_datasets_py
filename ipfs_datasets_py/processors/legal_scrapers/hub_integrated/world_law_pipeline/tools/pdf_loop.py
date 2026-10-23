#!/usr/bin/env python3
"""Detached scanned-PDF upload loop (replaces the hourly-only upload in pdf_step.py).

  nohup /workspace/hf-venv/bin/python tools/pdf_loop.py >> state/pdf_loop.log 2>&1 &     (or: pdf_loop.py --start)

Every --interval seconds (default 300), or within --poll seconds of a new staging/pdf/_manifest/batch_NNNN.ready,
runs tools/upload_pdfs.py as a child process (own process group) which pushes every ready batch, verifies it,
deletes it locally and writes .pushed. Idempotent: verified files are skipped via state/pdf_ledger.jsonl.

Safety:
  * singleton: flock on state/pdf_loop.lock + pidfile state/pdf_loop.pid; heartbeat in state/pdf_loop.status.json
  * per-commit timeout inside upload_pdfs (--commit-timeout); watchdog here kills a child that prints nothing for
    --stall-min minutes or runs longer than --max-run-min, then retries (up to --retries per cycle)
  * stale state/pdf_upload.lock: the lock is a kernel flock (freed when its holder dies); if it is held by a live
    upload_pdfs that started more than --stale-lock-min minutes ago, that holder is killed and the lock taken over
  * memory: no child is started while MemAvailable < --min-mem-gb (run_loop's MEM_LOW_GB floor); the child also
    checks before every batch
  * never touches state/run_loop.lock: the pdf_ref backfill (run_loop) stays on the hourly pdf_step path
  * alert: state/alerts/pdf_staging_over_6gb.json while staging/pdf > --alert-gb, removed once below
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
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
ALERT_NAME = "pdf_staging_over_6gb.json"
DEAD_ALERT_NAME = "pdf_loop_dead.json"
MEM_LOW_GB = 1.5
_STOP = {"flag": False}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] pdf_loop[{os.getpid()}]: {msg}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mem_available_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024 / 1e9
    except OSError:
        pass
    return float("inf")


def atomic_write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + f".{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(p)


def pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # zombies count as dead
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def pid_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- staging status / alert
def ready_batches(stage: Path) -> List[str]:
    md = stage / "_manifest"
    if not md.is_dir():
        return []
    out = []
    for p in md.glob("batch_*.ready"):
        b = p.name[: -len(".ready")]
        if (md / f"{b}.jsonl").exists() and not (md / f"{b}.pushed").exists():
            out.append(b)
    return sorted(out)


def dir_bytes(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for fn in files:
            try:
                total += os.lstat(os.path.join(root, fn)).st_size
            except OSError:
                pass
    return total


def staging_status(stage: Path, now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    rb = ready_batches(stage)
    ages = []
    for b in rb:
        try:
            ages.append(now - (stage / "_manifest" / f"{b}.ready").stat().st_mtime)
        except OSError:
            pass
    size = dir_bytes(stage) if stage.exists() else 0
    return {"at": utc_now(), "staging": str(stage), "staging_bytes": size, "staging_gb": round(size / 1e9, 3),
            "ready_batches": rb, "ready_count": len(rb),
            "oldest_ready_age_min": round(max(ages) / 60, 1) if ages else None}


def update_alert(state: Path, st: Dict[str, Any], alert_gb: float = 6.0, source: str = "pdf_loop") -> bool:
    """Write state/alerts/pdf_staging_over_6gb.json while staging > alert_gb; remove it once below. True = alerting."""
    p = state / "alerts" / ALERT_NAME
    if st["staging_bytes"] > alert_gb * 1e9:
        prev = {}
        try:
            prev = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
        atomic_write(p, json.dumps({**st, "threshold_gb": alert_gb, "source": source,
                                    "first_seen_at": prev.get("first_seen_at") or st["at"]}, indent=1) + "\n")
        return True
    if p.exists():
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        return False
    return False


# ---------------------------------------------------------------- liveness (shared with pdf_step)
def loop_status(state: Path, max_heartbeat_age_s: float = 900) -> Dict[str, Any]:
    """{'alive': bool, 'pid':..., 'reason':...}: pid from state/pdf_loop.pid, must be a live pdf_loop process whose
    heartbeat (state/pdf_loop.status.json) is fresh, or which holds state/pdf_loop.lock."""
    pf = state / "pdf_loop.pid"
    try:
        pid = int(pf.read_text().split()[0])
    except Exception:  # noqa: BLE001
        return {"alive": False, "pid": None, "reason": "no pidfile"}
    if not pid_alive(pid) or "pdf_loop" not in pid_cmdline(pid):
        return {"alive": False, "pid": pid, "reason": "pid not running"}
    hb_age = None
    try:
        hb = json.loads((state / "pdf_loop.status.json").read_text())
        hb_age = time.time() - float(hb.get("heartbeat_ts", 0))
    except Exception:  # noqa: BLE001
        pass
    if hb_age is None or hb_age > max_heartbeat_age_s:
        return {"alive": False, "pid": pid, "reason": f"stale heartbeat ({hb_age and round(hb_age)}s)",
                "heartbeat_age_s": hb_age}
    return {"alive": True, "pid": pid, "heartbeat_age_s": round(hb_age)}


def start_detached(state: Path, python: str = sys.executable, extra: Optional[List[str]] = None) -> int:
    """nohup-style start: new session, stdout/stderr appended to state/pdf_loop.log. Returns the child pid."""
    state.mkdir(parents=True, exist_ok=True)
    logf = open(state / "pdf_loop.log", "ab")
    cmd = ["nohup", python, str(Path(__file__).resolve()), "--state", str(state)] + list(extra or [])
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                         cwd=str(PIPE), start_new_session=True, close_fds=True)
    logf.close()
    return p.pid


# ---------------------------------------------------------------- upload lock
def upload_lock_holder(state: Path) -> Optional[Dict[str, Any]]:
    """None if state/pdf_upload.lock is free, else the holder info (pid/started_at from the lock JSON)."""
    lp = state / "pdf_upload.lock"
    f = open(lp, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        return None
    except BlockingIOError:
        try:
            info = json.loads(lp.read_text() or "{}")
        except Exception:  # noqa: BLE001
            info = {}
        return info
    finally:
        f.close()


def _age_s(iso: Optional[str]) -> Optional[float]:
    try:
        return time.time() - datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return None


def break_stale_upload_lock(state: Path, stale_s: float, kill=os.kill) -> str:
    """'free' | 'held' (fresh holder) | 'broken' (killed a stale holder) | 'unknown' (held, no usable holder info)."""
    h = upload_lock_holder(state)
    if h is None:
        return "free"
    pid, age = h.get("pid"), _age_s(h.get("started_at"))
    if pid and not pid_alive(pid):
        return "held"  # holder just exited (or a forked child keeps the fd); flock frees itself
    if pid and age is not None and age > stale_s and "upload_pdfs" in pid_cmdline(pid):
        log(f"stale pdf_upload.lock: holder pid {pid} started {age / 60:.0f} min ago (> {stale_s / 60:.0f}); killing")
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                kill(pid, sig)
            except ProcessLookupError:
                break
            for _ in range(30):
                if not pid_alive(pid):
                    break
                time.sleep(1)
            if not pid_alive(pid):
                break
        return "broken"
    return "held" if pid else "unknown"


# ---------------------------------------------------------------- one guarded upload run
def run_upload(cmd: List[str], log_path: Path, stall_s: float, max_run_s: float, poll_s: float = 5.0,
               heartbeat=None) -> Dict[str, Any]:
    """Run cmd in its own process group with output to log_path; kill the group if no output for stall_s or
    total runtime > max_run_s. Returns {'rc', 'killed', 'reason', 'seconds'}."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as lf:
        t0 = time.time()
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT, cwd=str(PIPE),
                             start_new_session=True, env={**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
        last_size, last_change = log_path.stat().st_size, time.time()
        reason = None
        while True:
            try:
                rc = p.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            sz = log_path.stat().st_size
            if sz != last_size:
                last_size, last_change = sz, now
            if heartbeat:
                heartbeat(phase="uploading", child_pid=p.pid)
            if now - last_change > stall_s:
                reason = f"stalled: no output for {(now - last_change) / 60:.1f} min"
            elif now - t0 > max_run_s:
                reason = f"exceeded max runtime {max_run_s / 60:.0f} min"
            if _STOP["flag"] and reason is None:
                reason = "loop stopping"
            if reason:
                log(f"watchdog: killing upload pid {p.pid} ({reason})")
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(p.pid, sig)
                    except ProcessLookupError:
                        break
                    try:
                        p.wait(timeout=30)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                rc = p.wait()
                break
    return {"rc": rc, "killed": reason is not None, "reason": reason, "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- main loop
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=str(BASE))
    ap.add_argument("--state", default=str(BASE / "state"))
    ap.add_argument("--staging", default=None, help="default <base>/staging/pdf")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--interval", type=float, default=300, help="seconds between full upload cycles")
    ap.add_argument("--poll", type=float, default=20, help="seconds between checks for a new .ready")
    ap.add_argument("--commit-timeout", type=float, default=25 * 60)
    ap.add_argument("--stall-min", type=float, default=35, help="kill the upload child after this long silent")
    ap.add_argument("--max-run-min", type=float, default=240, help="hard cap for one upload child")
    ap.add_argument("--retries", type=int, default=2, help="retries per cycle after a watchdog kill / failure")
    ap.add_argument("--stale-lock-min", type=float, default=120,
                    help="kill a live upload_pdfs holding pdf_upload.lock for longer than this")
    ap.add_argument("--min-mem-gb", type=float, default=MEM_LOW_GB)
    ap.add_argument("--alert-gb", type=float, default=6.0)
    ap.add_argument("--refresh-manifest-every", type=float, default=3600,
                    help="pass --refresh-manifest to upload_pdfs at most this often (s)")
    ap.add_argument("--once", action="store_true", help="one cycle, then exit (tests / manual)")
    ap.add_argument("--start", action="store_true", help="start detached (nohup) unless already alive, then exit")
    ap.add_argument("--status", action="store_true", help="print liveness + staging status JSON and exit")
    ap.add_argument("--upload-cmd", default=None, help=argparse.SUPPRESS)  # tests: replace the upload child
    a = ap.parse_args(argv)
    state = Path(a.state)
    stage = Path(a.staging) if a.staging else Path(a.base) / "staging" / "pdf"
    state.mkdir(parents=True, exist_ok=True)

    if a.status:
        print(json.dumps({"loop": loop_status(state), "staging": staging_status(stage)}, indent=1))
        return 0
    if a.start:
        ls = loop_status(state)
        if ls["alive"]:
            print(json.dumps({"started": False, **ls}))
            return 0
        extra = [x for x in (argv if argv is not None else sys.argv[1:]) if x != "--start"]
        pid = start_detached(state, a.python, extra)
        print(json.dumps({"started": True, "pid": pid, "log": str(state / "pdf_loop.log")}))
        return 0

    lockf = open(state / "pdf_loop.lock", "a+")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another pdf_loop holds state/pdf_loop.lock; exiting")
        return 0
    atomic_write(state / "pdf_loop.pid", f"{os.getpid()}\n")
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, lambda *_: _STOP.__setitem__("flag", True))
    started = utc_now()
    status: Dict[str, Any] = {"pid": os.getpid(), "started_at": started, "cycles": 0, "batches_pushed": 0}

    def heartbeat(**kw):
        status.update(kw, heartbeat_at=utc_now(), heartbeat_ts=time.time())
        atomic_write(state / "pdf_loop.status.json", json.dumps(status, indent=1) + "\n")

    log(f"started (interval {a.interval:.0f}s, poll {a.poll:.0f}s, commit timeout {a.commit_timeout:.0f}s, "
        f"stall {a.stall_min:g} min, stale lock {a.stale_lock_min:g} min, mem floor {a.min_mem_gb:g} GB, "
        f"alert > {a.alert_gb:g} GB)")
    last_cycle, last_refresh, seen = 0.0, 0.0, set()
    try:
        while not _STOP["flag"]:
            st = staging_status(stage)
            alerting = update_alert(state, st, a.alert_gb)
            heartbeat(phase="idle", staging_gb=st["staging_gb"], ready=st["ready_count"],
                      oldest_ready_age_min=st["oldest_ready_age_min"], alert=alerting)
            new_ready = set(st["ready_batches"]) - seen
            due = time.time() - last_cycle >= a.interval
            if st["ready_batches"] and (new_ready or due):
                cycle(a, state, stage, st, status, heartbeat, last_refresh)
                if time.time() - last_refresh >= a.refresh_manifest_every:
                    last_refresh = time.time()
                last_cycle = time.time()
                st2 = staging_status(stage)
                update_alert(state, st2, a.alert_gb)
                seen = set(st2["ready_batches"])  # left-overs wait for the next interval, not a hot loop
            elif due:
                last_cycle = time.time()
            if a.once:
                break
            for _ in range(int(max(1, a.poll))):
                if _STOP["flag"]:
                    break
                time.sleep(1)
    finally:
        heartbeat(phase="stopped")
        log("stopping")
        try:
            if (state / "pdf_loop.pid").read_text().split()[0] == str(os.getpid()):
                (state / "pdf_loop.pid").unlink()
        except Exception:  # noqa: BLE001
            pass
    return 0


def cycle(a, state: Path, stage: Path, st: Dict[str, Any], status: Dict[str, Any], heartbeat, last_refresh) -> None:
    status["cycles"] += 1
    log(f"cycle {status['cycles']}: {st['ready_count']} ready ({', '.join(st['ready_batches'])}), "
        f"staging {st['staging_gb']:.2f} GB, MemAvailable {mem_available_gb():.2f} GB")
    for attempt in range(a.retries + 1):
        if _STOP["flag"]:
            return
        avail = mem_available_gb()
        if avail < a.min_mem_gb:
            log(f"MEM_LOW MemAvailable={avail:.2f}GB < {a.min_mem_gb:g}GB: skipping this cycle")
            return
        lk = break_stale_upload_lock(state, a.stale_lock_min * 60)
        if lk in ("held", "unknown"):
            log(f"pdf_upload.lock {lk} by another uploader ({upload_lock_holder(state)}); next cycle")
            return
        if a.upload_cmd:
            cmd = json.loads(a.upload_cmd)
        else:
            cmd = [a.python, str(HERE / "upload_pdfs.py"), "--base", a.base, "--state", str(state),
                   "--staging", str(stage), "--commit-timeout", str(a.commit_timeout),
                   "--min-mem-gb", str(a.min_mem_gb)]
            if time.time() - last_refresh >= a.refresh_manifest_every:
                cmd.append("--refresh-manifest")
        before = set(st["ready_batches"])
        heartbeat(phase="uploading", attempt=attempt + 1)
        r = run_upload(cmd, state / "pdf_loop_upload.log", a.stall_min * 60, a.max_run_min * 60,
                       heartbeat=heartbeat)
        after = set(ready_batches(stage))
        pushed = sorted(before - after)
        status["batches_pushed"] += len(pushed)
        status["last_run"] = {**r, "at": utc_now(), "pushed": pushed, "left": sorted(after)}
        log(f"upload rc={r['rc']} in {r['seconds']:.0f}s, pushed {pushed or 'none'}, still ready {sorted(after)}"
            + (f", killed: {r['reason']}" if r["killed"] else ""))
        if r["rc"] == 0 and not r["killed"] or not after:
            return
        if r["rc"] == 3:  # child's own MEM_LOW stop
            return
        time.sleep(min(60, 10 * (attempt + 1)))
        st = staging_status(stage)


if __name__ == "__main__":
    sys.exit(main())
