#!/usr/bin/env python3
"""asia_latam disk guard (2026-10-18, HF uploads stalled): every 30 s check free space on /workspace.
free < --pause-gb (37)  -> SIGSTOP every asia_latam writer process (python, cwd under pipeline/scrapers/asia_latam),
free > --resume-gb (40) -> SIGCONT the ones this guard stopped.  Logs to staging/asia_latam/_logs/disk_guard.log;
state + pause flag in staging/asia_latam/_state/supervisor/DISK_PAUSED (json: since, free_gb, pids).
Never stopped: supervisor.py, gzip_processed.py (it frees space), wb_wait.py, this guard, and any process that at that
moment holds an fd on a shared lock (pipeline/archive/_ratelimit/*, the scanned-PDF queue lock) -> retried next tick,
so a paused job can never hold the box-wide Wayback/CC slot. SIGSTOPped jobs stay 'alive', so the supervisor does
not relaunch them. One instance (flock). Stop: touch _state/supervisor/DISK_GUARD_STOP (resumes everything first)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, json, os, signal, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam"))
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
SV = STAGE / "_state" / "supervisor"
FLAG, STOPF, LOG = SV / "DISK_PAUSED", SV / "DISK_GUARD_STOP", STAGE / "_logs" / "disk_guard.log"
SKIP = ("supervisor.py", "gzip_processed.py", "wb_wait.py", "disk_guard.py")


def log(m):
    with open(LOG, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {m}\n")


def free_gb():
    s = os.statvfs("/workspace"); return s.f_bavail * s.f_frsize / 1e9


def writers():
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == os.getpid():
            continue
        try:
            cmd = open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf8", "ignore")
            cwd = os.readlink(f"/proc/{p}/cwd")
        except OSError:
            continue
        if "python" in cmd.split(" ")[0] and cwd.startswith(str(ROOT)) and not any(s in cmd for s in SKIP):
            out.append((int(p), cmd.strip()[:120]))
    return out


def _lock_inodes():
    ino = set()
    for d in ((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/archive/_ratelimit"), str(STAGE)):
        try:
            for n in os.listdir(d):
                if n.endswith((".lock", ".qlock")):
                    ino.add(os.stat(os.path.join(d, n)).st_ino)
        except OSError:
            pass
    return ino


def holds_lock(pid):
    """True if pid currently HOLDS (not waits on) a flock on a shared rate-limit lock or the scanned-PDF queue lock."""
    ino = _lock_inodes()
    try:
        for ln in open("/proc/locks"):
            if "->" in ln:
                continue                          # blocked waiter, not holder
            f = ln.split()
            if len(f) >= 6 and f[1] == "FLOCK" and f[4] == str(pid) and int(f[5].split(":")[-1]) in ino:
                return True
    except OSError:
        pass
    return False


def main():
    pause_gb = float(sys.argv[sys.argv.index("--pause-gb") + 1]) if "--pause-gb" in sys.argv else 37.0
    resume_gb = float(sys.argv[sys.argv.index("--resume-gb") + 1]) if "--resume-gb" in sys.argv else 40.0
    lk = open(SV / "disk_guard.lock", "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("disk_guard already running"); return
    lk.write(str(os.getpid())); lk.flush()
    st = json.loads(FLAG.read_text()) if FLAG.exists() else None
    stopped = set(st["pids"]) if st else set()
    log(f"start pid={os.getpid()} pause<{pause_gb}GB resume>{resume_gb}GB free={free_gb():.1f}GB paused={bool(st)}")
    last_note = 0
    while not STOPF.exists():
        fr = free_gb()
        if fr < pause_gb or (stopped and fr <= resume_gb):
            new = []
            for pid, cmd in writers():
                if pid in stopped:
                    continue
                if holds_lock(pid):
                    continue                      # retried next tick
                try:
                    os.kill(pid, signal.SIGSTOP); stopped.add(pid); new.append(f"{pid}:{cmd}")
                except ProcessLookupError:
                    pass
            if new or not FLAG.exists():
                st = {"since": (st or {}).get("since") or datetime.now().isoformat(timespec="seconds"), "free_gb": round(fr, 1),
                      "pids": sorted(stopped)}
                FLAG.write_text(json.dumps(st)); log(f"PAUSE free={fr:.1f}GB stopped {len(new)}: {new}")
            elif time.time() - last_note > 1800:
                last_note = time.time(); log(f"still paused free={fr:.1f}GB pids={sorted(stopped)}")
        elif stopped and fr > resume_gb:
            for pid in sorted(stopped):
                try:
                    os.kill(pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            log(f"RESUME free={fr:.1f}GB continued {sorted(stopped)} (paused since {(st or {}).get('since')})")
            stopped = set(); st = None; FLAG.unlink(missing_ok=True)
        time.sleep(30)
    for pid in stopped:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
    FLAG.unlink(missing_ok=True); STOPF.unlink(missing_ok=True)
    log(f"stop (DISK_GUARD_STOP); resumed {sorted(stopped)}")


if __name__ == "__main__":
    main()
