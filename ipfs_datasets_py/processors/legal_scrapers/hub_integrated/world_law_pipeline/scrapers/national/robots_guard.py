#!/usr/bin/env python3
"""Stop queued full runs whose primary source failed the RFC 9309 robots re-check
(robots.txt unreachable => disallow-all). Kills the run_full.sh process group when it starts."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, signal, subprocess, time
from pathlib import Path
DENY = {"PE": "busquedas.elperuano.pe robots.txt unreachable (TLS) => disallow-all",
        "KW": "kuwaitalyawm.media.gov.kw robots.txt unreachable (TLS) => disallow-all"}
LOGS = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_logs/full"))
done = set()
while len(done) < len(DENY):
    out = subprocess.run(["ps", "-eo", "pid,pgid,args"], capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3 or "run_full.sh" not in parts[2]: continue
        args = parts[2].split()
        try: cc = args[args.index(next(a for a in args if a.endswith("run_full.sh"))) + 1]
        except Exception: continue
        if cc in DENY and cc not in done:
            os.killpg(int(parts[1]), signal.SIGTERM)
            with open(LOGS / f"{cc}.log", "a") as f:
                f.write(f"=== {time.strftime('%F %T %Z')} STOPPED by robots_guard: {DENY[cc]}\n=== BLOCKED-ROBOTS FINISHED\n")
            print(time.strftime("%F %T"), "stopped", cc, flush=True); done.add(cc)
    time.sleep(10)
