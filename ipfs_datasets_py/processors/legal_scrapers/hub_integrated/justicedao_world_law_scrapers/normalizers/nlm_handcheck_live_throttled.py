#!/usr/bin/env python3
"""Stock `nl_municipal_collect.py handcheck` path (main() replicated for MODE=handcheck: mkdirs, load_cfg, SIGTERM handler, MEMGUARD thread,
Authorities, then C.handcheck() = scan('handcheck', max_chunks=NLM_HC_MAX_CHUNKS, quota=hc_quota) + hc_report) with ONE change:
the offline all-collected re-check (check_one over every ok row) is read-throttled (~20ms/row; pause while MemAvail < 4200MiB until >= 4400MiB),
because bulk reads of restored files balloon the box's sand-host daemon by ~1GB and trip MEMGUARD (3584MB). Live scan code is untouched."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import importlib.util, time, os, threading, signal
spec = importlib.util.spec_from_file_location('nlc', '/workspace/scripts/nl_municipal_collect.py'); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
C.MODE = 'handcheck'
for d in (C.RAWM, C.RAWX, C.RAWX.parent / 'stop', C.OUTA, C.OUTL, C.SCAN, C.PROBE): d.mkdir(parents=True, exist_ok=True)
C.load_cfg(quiet=True); signal.signal(signal.SIGTERM, C._on_sigterm)
threading.Thread(target=C._mg, daemon=True).start(); C.AUTH = C.Authorities()
C.log('START', 'handcheck(throttled-report)', 'pid', os.getpid(), f'mem={C.memavail()}MB', 'host', C.HOST, 'delay', C.DELAY, 'rss_limit_mb', C.RSS_MB, 'term_memavail_mb', C.TERM_MB, 'top', C.TOP, 'max_chunks', os.environ.get('NLM_HC_MAX_CHUNKS', '12'), 'authorities_current', C.AUTH.n_current)
_orig = C.check_one; n = [0]; t0 = [None]
def check_one(r):
    if t0[0] is None: t0[0] = time.time(); C.log('all-collected re-check start (throttled)')
    n[0] += 1; time.sleep(0.02)
    if n[0] % 50 == 0 and C.memavail() < 4200:
        w = 0
        while C.memavail() < 4400 and w < 900: time.sleep(5); w += 5
        C.log(f'paused {w}s, MemAvail now {C.memavail()}MB')
    if n[0] % 2000 == 0: C.log('all-collected check', n[0], f'{time.time()-t0[0]:.0f}s', f'mem={C.memavail()}MB rss={C.rss_mb()}MB')
    return _orig(r)
C.check_one = check_one
try: C.handcheck()
except C.Stop as e: C.log('STOP', e)
except C.Terminated as e: C.log('TERMINATED cleanly', e)
C.log('END handcheck', 'nreq', C.F.nreq, C.F.stats)
