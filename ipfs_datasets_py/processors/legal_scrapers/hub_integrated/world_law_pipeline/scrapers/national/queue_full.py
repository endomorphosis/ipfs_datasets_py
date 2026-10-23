#!/usr/bin/env python3
"""Run full national collectors from a priority queue, at most MAX_CONC at once (distinct hosts).
Resumable: re-running skips CCs whose _logs/full/<CC>.log ends with FINISHED.
Usage: queue_full.py CC:collector.py [CC:collector.py ...]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
LOGS = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_logs/full"))
MAX_CONC = int(os.environ.get("MAX_CONC", "5"))
jobs = [a.split(":") for a in sys.argv[1:]]
running = {}
def finished(cc):
    p = LOGS / f"{cc}.log"
    return p.exists() and p.read_text(errors="ignore").rstrip().endswith("FINISHED")
pending = [j for j in jobs if not finished(j[0])]
while pending or running:
    for cc, p in list(running.items()):
        if p.poll() is not None:
            print(time.strftime("%F %T"), "done", cc, p.returncode, flush=True); running.pop(cc)
    while pending and len(running) < MAX_CONC:
        cc, coll = pending.pop(0)
        p = subprocess.Popen([str(HERE / "run_full.sh"), cc, coll], start_new_session=True)
        running[cc] = p
        print(time.strftime("%F %T"), "start", cc, coll, "pid", p.pid, flush=True)
    time.sleep(30)
print(time.strftime("%F %T"), "queue empty", flush=True)
