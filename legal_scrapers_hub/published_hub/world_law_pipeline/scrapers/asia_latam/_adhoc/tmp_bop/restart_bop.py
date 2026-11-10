#!/usr/bin/env python3
"""Restart es_bop backward runs at a checkpoint boundary so they load the new es_places resolver.
Kill = SIGTERM right after the newest log line is a 'checkpoint' line (<2 s old) and no .tmp file is pending."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, glob, time, signal, subprocess, sys
ES = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/es")
STG = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam")
RUNS = [(3094017, "bocm", 3), (3193202, "borm,gipuzkoa,cordoba,huesca", 5), (3207040, "soria", 5),
        (3397417, "caceres", 5), (3411186, "avila,guadalajara,lugo", 5), (3461451, "ourense,cadiz", 5)]
def alive(p): return os.path.exists(f"/proc/{p}")
def tmp_pending(): return glob.glob(f"{STG}/ES/.*.tmp*") or glob.glob(f"{STG}/_unmatched/ES/.*.tmp*")
def launch(args):
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    subprocess.Popen(["setsid", "nohup", f"{ES}/run_bop.sh", *args], cwd=ES, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
for pid, gz, fd in RUNS:
    if alive(pid):
        log = os.readlink(f"/proc/{pid}/fd/1"); t0 = time.time()
        while time.time() - t0 < 1800:
            last = open(log, "rb").read()[-400:].decode("utf8", "ignore").strip().splitlines()[-1]
            if "checkpoint" in last and time.time() - os.path.getmtime(log) < 2 and not tmp_pending():
                break
            time.sleep(0.3)
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not alive(pid): break
            time.sleep(0.2)
        if alive(pid): os.kill(pid, signal.SIGKILL)
        print(time.strftime("%H:%M:%S"), "stopped", pid, "after:", last[:120], flush=True)
    time.sleep(61)                                   # distinct log file name (minute resolution)
    launch(["--gazettes", gz, "--flush-days", str(fd)])
    print(time.strftime("%H:%M:%S"), "relaunched", gz, flush=True)
# forward runner is sleeping between passes -> safe to restart anytime
os.kill(3464782, signal.SIGTERM); time.sleep(3)
subprocess.Popen(["bash", "-c", f"cd {ES} && MALLOC_ARENA_MAX=2 setsid nohup python3 -u es_bop.py --forward --every-hours 6 --gazettes bocm,borm,caceres,gipuzkoa,cordoba,granada,leon,huesca,soria,avila,guadalajara,lugo,ourense,cadiz,castellon >> {STG}/_logs/es_bop_forward_$(date +%Y%m%d_%H%M).log 2>&1 &"])
print(time.strftime("%H:%M:%S"), "forward relaunched", flush=True)
