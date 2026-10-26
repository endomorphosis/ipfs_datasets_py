#!/usr/bin/env python3
"""Equivalent of `nl_municipal_collect.py hcreport` (same hc_report code, offline, no network) with file-read throttling:
the box's sand-host daemon balloons ~+1GB RSS under fast bulk reads of restored files, which tripped the collector's MEMGUARD (3584MB).
check_one is wrapped: ~5ms per row, pause while MemAvail < 4200MiB until >= 4400MiB; hard abort if MemAvail <= 3000MiB (offline check, not a collector; the periodic box-store-sync balloon dips to ~3.55G even when idle)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import importlib.util, time, sys
spec = importlib.util.spec_from_file_location('nlc', '/workspace/scripts/nl_municipal_collect.py'); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
def nonet(*a, **k): raise RuntimeError('network disabled')
C.F.get = nonet; C.load_cfg(quiet=True); C.AUTH = C.Authorities()
_orig = C.check_one; n = [0]; t0 = time.time()
def guard():
    m = C.memavail()
    if m <= 3000: C.log(f"ABORT MemAvail={m}MB <= 3000"); sys.exit(3)
    if m < 4200:
        w = 0
        while C.memavail() < 4400 and w < 900:
            time.sleep(5); w += 5
            if C.memavail() <= 3000: C.log("ABORT MemAvail <= 3000 while paused"); sys.exit(3)
        C.log(f'paused {w}s, MemAvail now {C.memavail()}MB')
def check_one(r):
    n[0] += 1; time.sleep(0.005)
    if n[0] % 50 == 0: guard()
    if n[0] % 2000 == 0: C.log('all-collected check', n[0], f'{time.time()-t0:.0f}s', f'mem={C.memavail()}MB rss={C.rss_mb()}MB')
    return _orig(r)
C.check_one = check_one
C.log('START hcreport (throttled) mem', C.memavail(), 'authorities_current', C.AUTH.n_current)
C.hc_report()
