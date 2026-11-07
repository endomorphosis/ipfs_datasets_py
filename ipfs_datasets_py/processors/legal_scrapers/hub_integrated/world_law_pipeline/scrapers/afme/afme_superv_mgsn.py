#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""Persistent afme supervisor for MG + SN only (ML stays on hourly w13 watch).

* Single-instance via flock on staging/afme/_state/superv_mgsn/superv_mgsn.lock
* Writes ACTIVE while running so afme_chain_w13.sh skips SN/MG (ML only) — no overlap
* One scrape/archive worker at a time; refuses to launch if another afme MG/SN worker is alive
* On expected deferral (live host down, CC cool-down, Wayback breaker open): exponential backoff
  initial AFME_SUPERV_BACKOFF_INIT_S (default 1200 = 20 min, range 900–1800), cap 6 h
* Respects disk_check (hardened) and MemAvailable >= 2 GiB before each launch
* Respects archive breaker: still runs afme_arch (CC first; Wayback skipped when breaker open)
* Exits 0 when STOP is touched, or when every target is status=complete (no deferred work left)
* Touch staging/afme/_state/superv_mgsn/STOP for a clean stop (in-flight child finishes)

State: staging/afme/_state/superv_mgsn/state.json
Log:   staging/afme/_logs/superv_mgsn.log
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, fcntl, json, os, signal, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/out"))
import afme_common as C

OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/out"))
PY = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/.venv_afme/bin/python"))
STATE_DIR = C.STAGE / "_state" / "superv_mgsn"
LOCK_PATH = STATE_DIR / "superv_mgsn.lock"
ACTIVE_PATH = STATE_DIR / "ACTIVE"
STOP_PATH = STATE_DIR / "STOP"
STATE_PATH = STATE_DIR / "state.json"
LOG_PATH = C.LOGS / "superv_mgsn.log"

TARGETS = ("MG", "SN")  # ML intentionally excluded — hourly w13 watch owns ML
BACKOFF_INIT = float(os.environ.get("AFME_SUPERV_BACKOFF_INIT_S", "1200"))  # 20 min
BACKOFF_CAP = float(os.environ.get("AFME_SUPERV_BACKOFF_CAP_S", str(6 * 3600)))
POLL_S = float(os.environ.get("AFME_SUPERV_POLL_S", "60"))
MEM_FLOOR_MB = 2048

# cmdline substrings that count as an overlapping afme worker for MG/SN
WORKER_SIGS = (
    "afme_mg_cnlegis.py",
    "afme_mg_resume.sh",
    "afme_live.py SN",
    "afme_live.py MG",
    "afme_arch.py MG",
    "afme_arch.py SN",
    "afme_chain_w13.sh",
    "afme_superv_mgsn.py",  # another supervisor copy
)


def log(msg: str) -> None:
    line = f"{C.utc_iso()} [superv_mgsn] {msg}"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    # Also echo to stderr for nohup.out without duplicating into LOG_PATH.
    print(line, file=sys.stderr, flush=True)


def mem_avail_mb() -> int:
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    st = {"targets": {}, "started_utc": C.utc_iso()}
    for cc in TARGETS:
        st["targets"][cc] = {
            "status": "pending",          # pending|deferred|complete
            "backoff_s": BACKOFF_INIT,
            "next_retry_at": 0.0,         # due immediately
            "last_outcome": None,
            "last_run_utc": None,
            "runs": 0,
        }
    return st


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def acquire_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "w", encoding="utf-8")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    fh.write(f"pid={os.getpid()} utc={C.utc_iso()}\n")
    fh.flush()
    return fh


def list_workers(exclude_pid: int | None = None) -> list[tuple[int, str]]:
    """Running processes matching WORKER_SIGS (excluding this supervisor pid)."""
    me = exclude_pid if exclude_pid is not None else os.getpid()
    found = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return found
    for sp in pids:
        pid = int(sp)
        if pid == me:
            continue
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "afme_superv_mgsn.py" in cmd and pid != me:
            found.append((pid, cmd.strip()))
            continue
        for sig in WORKER_SIGS:
            if sig == "afme_superv_mgsn.py":
                continue
            if sig in cmd:
                found.append((pid, cmd.strip()))
                break
    return found



def schedule_deferred(t: dict, note: str) -> None:
    """Record deferral and set next_retry_at with exponential backoff (init..cap)."""
    cur = float(t.get("backoff_s") or BACKOFF_INIT)
    if cur < BACKOFF_INIT:
        cur = BACKOFF_INIT
    # On the first deferral after reset, wait `cur`; then grow for the following one.
    wait = min(cur, BACKOFF_CAP)
    t["status"] = "deferred"
    t["last_outcome"] = f"deferred:{note}"
    t["next_retry_at"] = time.time() + wait
    t["backoff_s"] = min(cur * 2, BACKOFF_CAP)
    t["last_run_utc"] = C.utc_iso()


def schedule_ok(t: dict, note: str, *, complete: bool) -> None:
    t["last_outcome"] = note
    t["last_run_utc"] = C.utc_iso()
    t["backoff_s"] = BACKOFF_INIT
    if complete:
        t["status"] = "complete"
        t["next_retry_at"] = float("inf")
    else:
        # success-ish but still may have work later (e.g. partial) — mild recheck
        t["status"] = "pending"
        t["next_retry_at"] = time.time() + BACKOFF_INIT


def deferred_lines(cc: str) -> int:
    p = C.DONE / f"arch_{cc}.deferred.tsv"
    if not p.exists():
        return 0
    # count lines newer than last run? use whole file size as signal of recent deferrals:
    # afme_arch appends each run; we check mtime vs start of this attempt in run_* 
    return sum(1 for _ in p.open(encoding="utf-8") if _.strip())


def run_cmd(argv: list[str], log_fh) -> int:
    log(f"exec: {' '.join(argv)}")
    p = subprocess.run(argv, cwd=str(OUT), stdout=log_fh, stderr=subprocess.STDOUT, env={
        **os.environ, "ARCHIVE_LANE": "afme", "AFME_AS_LIMIT_MB": os.environ.get("AFME_AS_LIMIT_MB", "1200"),
        "PYTHONUNBUFFERED": "1",
    })
    return p.returncode


def ensure_arch_todo(cc: str, urls: list[str]) -> Path:
    todo = C.DONE / f"arch_todo_{cc}.tsv"
    C.DONE.mkdir(parents=True, exist_ok=True)
    existing = []
    if todo.exists():
        existing = [ln.rstrip("\n") for ln in todo.open(encoding="utf-8") if ln.strip()]
    seen = {ln.split("\t")[1] for ln in existing if "\t" in ln}
    lines = list(existing)
    for u in urls:
        if u not in seen:
            lines.append(f"iso:{cc}\t{u}")
            seen.add(u)
    tmp = todo.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(tmp, todo)
    return todo


def run_mg(log_fh) -> str:
    """Returns outcome token: complete|deferred|error."""
    before = deferred_lines("MG")
    rc = run_cmd([str(PY), "-u", "afme_mg_cnlegis.py"], log_fh)
    if rc != 0:
        ensure_arch_todo("MG", [
            "https://www.cnlegis.gov.mg/",
            "https://www.cnlegis.gov.mg/page_find_direct_mots_texte/",
        ])
        run_cmd([str(PY), "-u", "afme_arch.py", "MG", "--urls-file", str(C.DONE / "arch_todo_MG.tsv")], log_fh)
    run_cmd([str(PY), "-u", "afme_stage.py", "MG"], log_fh)
    after = deferred_lines("MG")
    # complete only when live succeeded and archive did not add new deferrals
    if rc == 0 and after <= before:
        return "complete"
    return "deferred"


def run_sn(log_fh) -> str:
    before = deferred_lines("SN")
    run_cmd([str(PY), "-u", "afme_live.py", "SN"], log_fh)
    todo = C.DONE / "arch_todo_SN.tsv"
    if not todo.exists() or todo.stat().st_size == 0:
        ensure_arch_todo("SN", [
            "https://www.jo.gouv.sn/",
            "https://www.jo.gouv.sn/spip.php?page=recherche&recherche=commune",
        ])
    rc_arch = run_cmd([str(PY), "-u", "afme_arch.py", "SN", "--urls-file", str(C.DONE / "arch_todo_SN.tsv")], log_fh)
    run_cmd([str(PY), "-u", "afme_stage.py", "SN"], log_fh)
    after = deferred_lines("SN")
    # Expected path today: live SSL fail + archive CC/Wayback deferral → keep retrying.
    if after > before or rc_arch != 0:
        return "deferred"
    # Arch finished without new deferrals (captures fetched or hard miss marked done).
    return "complete"


def pick_due(st: dict, now: float) -> str | None:
    due = []
    for cc in TARGETS:
        t = st["targets"][cc]
        if t.get("status") == "complete":
            continue
        if float(t.get("next_retry_at") or 0) <= now:
            due.append(cc)
    if not due:
        return None
    # Prefer the one idle longest (lowest next_retry_at), stable order MG then SN on ties
    due.sort(key=lambda c: (float(st["targets"][c].get("next_retry_at") or 0), TARGETS.index(c)))
    return due[0]


def all_complete(st: dict) -> bool:
    return all(st["targets"][cc].get("status") == "complete" for cc in TARGETS)


def guards_ok() -> bool:
    if mem_avail_mb() < MEM_FLOOR_MB:
        log(f"mem guard: MemAvailable {mem_avail_mb()} MB < {MEM_FLOOR_MB}; waiting")
        return False
    try:
        C.disk_check()
    except C.DiskLow as e:
        log(f"disk guard: {e}; waiting")
        return False
    return True


def main(once: bool = False) -> int:
    lock = acquire_lock()
    if lock is None:
        print("another superv_mgsn holds the lock; exit", flush=True)
        return 5
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    C.LOGS.mkdir(parents=True, exist_ok=True)
    ACTIVE_PATH.write_text(f"pid={os.getpid()} utc={C.utc_iso()}\n", encoding="utf-8")
    st = load_state()
    save_state(st)
    log(f"start pid={os.getpid()} targets={list(TARGETS)} backoff_init={BACKOFF_INIT}s cap={BACKOFF_CAP}s")

    stopping = {"flag": False}

    def _on_sig(signum, frame):
        stopping["flag"] = True
        log(f"signal {signum}; will stop after current unit")

    signal.signal(signal.SIGTERM, _on_sig)
    signal.signal(signal.SIGINT, _on_sig)

    try:
        while True:
            # Reload state each tick (survives external edits; keeps lock/ACTIVE).
            st = load_state()
            if STOP_PATH.exists() or stopping["flag"]:
                log("STOP requested; exiting cleanly")
                return 0
            if all_complete(st):
                log("all targets complete; exiting cleanly")
                return 0
            if not guards_ok():
                if once:
                    return 3
                time.sleep(POLL_S)
                continue
            others = list_workers()
            # allow only ourselves; any other matching worker blocks launch
            if others:
                log(f"worker(s) already running; not duplicating: {others[:3]}")
                if once:
                    return 6
                time.sleep(POLL_S)
                continue
            now = time.time()
            cc = pick_due(st, now)
            if cc is None:
                # sleep until soonest next_retry
                nxt = min(float(st["targets"][c].get("next_retry_at") or now + POLL_S)
                          for c in TARGETS if st["targets"][c].get("status") != "complete")
                sleep_for = max(1.0, min(POLL_S, nxt - now))
                log(f"nothing due; sleep {sleep_for:.0f}s (next at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(nxt))})")
                if once:
                    return 0
                time.sleep(sleep_for)
                continue

            t = st["targets"][cc]
            t["runs"] = int(t.get("runs") or 0) + 1
            log(f"=== run {cc} attempt#{t['runs']} (backoff next would be {t.get('backoff_s')}s) ===")
            unit_log = C.LOGS / f"superv_mgsn_{cc}_{C.utc_ts()}.log"
            with unit_log.open("a", encoding="utf-8") as fh:
                fh.write(f"start {C.utc_iso()} cc={cc}\n")
                try:
                    outcome = run_mg(fh) if cc == "MG" else run_sn(fh)
                except C.DiskLow as e:
                    log(f"{cc} aborted by disk: {e}")
                    outcome = "deferred"
                    fh.write(f"disk_abort {e}\n")
            log(f"{cc} outcome={outcome} unit_log={unit_log}")
            if outcome == "complete":
                schedule_ok(t, "complete", complete=True)
                log(f"{cc} marked complete; remaining={[c for c in TARGETS if st['targets'][c].get('status')!='complete']}")
            else:
                schedule_deferred(t, outcome)
                nxt = t["next_retry_at"]
                log(f"{cc} deferred; next_retry_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(nxt))} "
                    f"next_backoff_s={t['backoff_s']:.0f} (cap={BACKOFF_CAP:.0f})")
            save_state(st)
            if once:
                return 0 if outcome == "complete" else 2
            # brief pause before considering the other target
            time.sleep(min(5.0, POLL_S))
    finally:
        try:
            ACTIVE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except Exception:
            pass
        log("supervisor exit")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run at most one due target then exit")
    ap.add_argument("--status", action="store_true", help="print state.json and exit")
    a = ap.parse_args()
    if a.status:
        st = load_state()
        print(json.dumps(st, indent=2))
        sys.exit(0)
    sys.exit(main(once=a.once))
