"""Single lane archive queue (reconstructed 2026-11-01 after the 13:27 PT restore): runs the archive steps ONE at a time,
in order, then loops (every step is resumable from its own _archive_work state; the shared Wayback breaker/limiter in
arch_common decides pacing). Clean stop: touch _archive_work/_STOP_arch_queue. One copy (flock)."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, subprocess, sys, time
from pathlib import Path

ARCH = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/arch"))
W = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_archive_work"))
LOGD = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_logs/archive"))
PY = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/venv/bin/python")
STEPS = [("id_bpk", ["id_bpk.py", "--pdf-lookup"]), ("jp_arch", ["jp_arch.py"]),
         ("w3f_es_robots", ["es_arch.py", "--set", "robots", "--max-kb", "3000"]),   # pontevedra, huelva, laspalmas, boib
         ("w3f_es_blocked", ["es_arch.py"]),                                          # incl. BORM (CAPTCHA) archive copies
         ("w3f_sites", ["sites_arch.py", "--targets", "au,za"]), ("w3f_mx", ["mx_arch.py"]),
         ("w3f_mx_gaz", ["mx_gaz_arch.py"]),                                          # 12 MX gazettes blocked live (2026-11-02)
         ("w3f_sede", ["sede_arch.py"])]
MAX_STEP_S = 3 * 3600


def main():
    LOGD.mkdir(parents=True, exist_ok=True)
    lk = open(W / "arch_queue.lock", "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("arch_queue already running"); sys.exit(0)
    while not (W / "_STOP_arch_queue").exists():
        for name, cmd in STEPS:
            if (W / "_STOP_arch_queue").exists():
                break
            ts = time.strftime("%Y%m%d_%H%M")
            with open(LOGD / f"{name}_{ts}.log", "w") as lf:
                p = subprocess.Popen([PY, "-u"] + cmd, cwd=ARCH, stdout=lf, stderr=subprocess.STDOUT,
                                     env={"ARCHIVE_LANE": "asia_latam", "PATH": "/usr/bin:/bin"})
                try:
                    rc = p.wait(timeout=MAX_STEP_S)
                except subprocess.TimeoutExpired:
                    p.send_signal(2)
                    try:
                        rc = p.wait(timeout=300)
                    except subprocess.TimeoutExpired:
                        p.terminate(); rc = p.wait()
            print(time.strftime("%F %T"), name, "rc", rc, flush=True)
            time.sleep(30)
        time.sleep(1800)


if __name__ == "__main__":
    main()
