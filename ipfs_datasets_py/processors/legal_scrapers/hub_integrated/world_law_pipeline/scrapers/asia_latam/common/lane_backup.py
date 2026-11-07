"""asia_latam backup + memory-emergency loop (2026-11-01, after the 13:27 PT restore). One copy (flock).
Every 2 h: tarball of scrapers/asia_latam (+ supervisor_jobs.json) and a gzip tar of the small checkpoints
(_state files <= 200 MB; larger ones only listed in a summary) -> /cursor/stores/<store>/asia_latam/{code,state}/ (fallback
/home/box/asia_latam_backups); keeps the last 3 of each (only our own backup copies are rotated; nothing else deleted).
Every 60 s: MemAvailable < 800 MB -> SIGINT the largest lane python worker (clean checkpoint stop; rr relaunches later)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, os, signal, subprocess, sys, time
from pathlib import Path
LANE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/asia_latam")); STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/asia_latam"))
ST = STAGE / "_state"; LOGF = STAGE / "_logs" / "lane_backup.log"
STORE = Path("/cursor/stores/store-95d4d697-b187-4c00-a6c6-ef2cea2fa3e8"); FALLBACK = Path("/home/box/asia_latam_backups")
SMALL_MAX = 200 * 1024 * 1024; EVERY_S = 2 * 3600; MEM_MIN_MB = 800
SKIP = ("supervisor.py", "disk_guard.py", "arch_queue.py", "lane_backup.py", "gzip_processed.py")

def log(m):
    with open(LOGF, "a") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")

def root():
    try:
        (STORE / "asia_latam").mkdir(parents=True, exist_ok=True); return STORE / "asia_latam"
    except OSError:
        return FALLBACK

def backup():
    r = root(); ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for d in ("code", "state"): (r / d).mkdir(parents=True, exist_ok=True)
    code = r / "code" / f"asia_latam_code_{ts}.tgz"
    subprocess.run(["tar", "czf", str(code), "--exclude=__pycache__", "-C", str(LANE.parent), LANE.name], check=True, timeout=1800)
    small, big = [], []
    for p in ST.rglob("*"):
        if p.is_file(): (big if p.stat().st_size > SMALL_MAX else small).append(p)
    lst = r / "state" / f".list_{ts}"; lst.write_text("\n".join(str(p.relative_to(STAGE)) for p in small) + "\n_bop_registry_es.csv\n_archive_queue_asia_latam.csv\n")
    stf = r / "state" / f"asia_latam_state_{ts}.tgz"
    subprocess.run(["tar", "czf", str(stf), "--ignore-failed-read", "-C", str(STAGE), "-T", str(lst)], timeout=3600)
    lst.unlink()
    (r / "state" / f"large_files_summary_{ts}.txt").write_text("\n".join(f"{p.stat().st_size}\t{p}" for p in big) or "none\n")
    for d, pat in ((r / "code", "asia_latam_code_*.tgz"), (r / "state", "asia_latam_state_*.tgz"), (r / "state", "large_files_summary_*.txt")):
        for old in sorted(d.glob(pat))[:-3]: old.unlink()
    log(f"backup ok {r} code={code.stat().st_size >> 10}KB state={stf.stat().st_size >> 10}KB large_listed={len(big)}")

def workers():
    out = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit(): continue
        try:
            cwd = os.readlink(p / "cwd"); cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            rss = int([l for l in open(p / "status") if l.startswith("VmRSS")][0].split()[1])
        except (OSError, IndexError): continue
        if cwd.startswith(str(LANE)) and "python" in cmd and not any(s in cmd for s in SKIP): out.append((rss, int(p.name), cmd))
    return sorted(out, reverse=True)

def main():
    lk = open(ST / "supervisor" / "lane_backup.lock", "w")
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: print("already running"); sys.exit(0)
    last = 0
    while True:
        try:
            ma = int([l for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0].split()[1]) // 1024
            if ma < MEM_MIN_MB and workers():
                rss, pid, cmd = workers()[0]; os.kill(pid, signal.SIGINT); log(f"mem emergency {ma}MB -> SIGINT {pid} {cmd[:80]}")
            if time.time() - last >= EVERY_S:
                last = time.time(); backup()
        except Exception as e:  # noqa: BLE001
            log(f"error {type(e).__name__}: {e}")
        time.sleep(60)

if __name__ == "__main__":
    if "--once" in sys.argv: backup()
    else: main()
