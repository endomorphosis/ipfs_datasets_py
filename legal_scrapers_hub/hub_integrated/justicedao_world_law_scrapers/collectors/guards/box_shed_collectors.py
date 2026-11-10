#!/usr/bin/env python3
"""Shed excess scrape workers under RAM pressure.
MAX is total scrape workers including protected deepeners.
Only targets collect_*.py / it_deepen / at_deepen — never IR package scripts.
Post-DO defaults: protect IT+AT deepen; drop MM/IS-reg/TH first.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, signal, subprocess, sys, time

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 6
if MAX < 0:
    MAX = 0

KILL_FIRST = (
    "collect_mm.py", "collect_is_reglugerdir.py", "collect_th.py", "collect_mt.py",
    "collect_kw.py", "collect_lt.py", "collect_ve.py", "collect_af.py", "collect_ci.py",
    "collect_et.py", "collect_tz.py", "collect_ug.py", "collect_rw.py", "collect_ma.py",
    "collect_cn.py", "collect_hr.py",
)
PIN = ("collect_at.py", "collect_dk.py", "collect_ie.py", "collect_gr.py")

def is_scrape_worker(cmd: str) -> bool:
    if "run_collector_cc.sh" in cmd:
        return False
    if "/tmp/" in cmd and ("_ir/" in cmd or "staged" in cmd or "package" in cmd):
        return False
    if "do_ir_resume" in cmd or "package_resume" in cmd:
        return False
    if "country-laws-ir" in cmd and "deepen" not in cmd:
        return False
    return ("collect_" in cmd) or ("it_deepen" in cmd) or ("at_deepen" in cmd)

def is_protected(cmd: str) -> bool:
    if MAX <= 0:
        return False
    # DO widen ≤6: protect AT deepen + DK; 0-arts rotate may return but shed first under pressure
    return ("at_deepen" in cmd) or ("collect_dk.py" in cmd)

rows = []
for line in subprocess.check_output(["ps", "-eo", "pid,cmd"], text=True).splitlines()[1:]:
    if "/workspace/venv/bin/python" not in line and "python -u" not in line:
        continue
    cmd = line.split(None, 1)[1] if " " in line else ""
    if not is_scrape_worker(cmd):
        continue
    pid = int(line.split(None, 1)[0])
    try:
        et = int(subprocess.check_output(["ps", "-p", str(pid), "-o", "etimes="], text=True).strip() or "0")
    except Exception:
        continue
    rows.append({"pid": pid, "etime": et, "cmd": cmd, "protected": is_protected(cmd)})

protected = sorted([r for r in rows if r["protected"]], key=lambda x: -x["etime"])
workers = [r for r in rows if not r["protected"]]

def is_kill_first(cmd):
    return any(k in cmd for k in KILL_FIRST)

def is_pin(cmd):
    return any(p in cmd for p in PIN)

pinned = sorted([r for r in workers if is_pin(r["cmd"])], key=lambda x: -x["etime"])
middle = sorted([r for r in workers if not is_pin(r["cmd"]) and not is_kill_first(r["cmd"])], key=lambda x: -x["etime"])
first_out = sorted([r for r in workers if is_kill_first(r["cmd"])], key=lambda x: -x["etime"])

keep = set()
for r in protected:
    if len(keep) >= MAX:
        break
    keep.add(r["pid"])
for r in pinned + middle + first_out:
    if len(keep) >= MAX:
        break
    keep.add(r["pid"])

to_kill = [r for r in rows if r["pid"] not in keep]
print(f"shed total={len(rows)} keep={sorted(keep)} kill={[r['pid'] for r in to_kill]}")
for r in to_kill:
    try:
        os.kill(r["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(2)
for r in to_kill:
    try:
        os.kill(r["pid"], 0)
        os.kill(r["pid"], signal.SIGKILL)
        print(f"SIGKILL {r['pid']}")
    except ProcessLookupError:
        pass
