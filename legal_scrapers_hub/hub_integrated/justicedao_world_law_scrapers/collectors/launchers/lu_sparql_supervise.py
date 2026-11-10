#!/usr/bin/env python3
"""US local supervisor (crash-tolerant). Runs lu_sparql_collect.py full in a loop. rc0 DONE/rc2 stop -> exit. rc3 MEMTERM -> wait MemAvail>=4200 held 30s, relaunch
(cap 12 relaunches / 6h -> HOLD). Strikes are per host inside the collector (host held, run continues); rc4 kept for compatibility (10-min cool-off, 2nd in 2h -> HOLD).
rc5/other -> 10-min wait, counts toward cap. STOP/HOLD markers honoured."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, time, subprocess, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from strict_mem_guard import memavail
B = str(_CORPORA) + '/lu_legilux/rc2'; STOPS = [f'{B}/STOP_LU_RC2', f'{B}/NOCHUNK30_unused', '/workspace/logs/STOP_LU_RC2', f'{B}/HOLD_LU_RC2', '/workspace/logs/HOLD_LU_RC2']
LEDGER = f'{B}/supervisor_state.json'; CAP = 12
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), 'SUP', *a, flush=True)
def stopped(): return [s for s in STOPS if os.path.exists(s)]
def st(): 
    try: return json.load(open(LEDGER))
    except Exception: return dict(launches=[], strike_stops=[])
def save(d): json.dump(d, open(LEDGER + '.tmp', 'w')); os.replace(LEDGER + '.tmp', LEDGER)
def hold(why):
    open(f'{B}/HOLD_LU_RC2', 'a').write(time.strftime('%F %T %Z ') + why + '\n'); log('HOLD', why); sys.exit(0)
def sleep_chk(s):
    t = time.time() + s
    while time.time() < t:
        if stopped(): log('stop marker during wait', stopped()); sys.exit(0)
        time.sleep(5)
while True:
    if stopped(): log('stop markers present', stopped()); sys.exit(0)
    if os.path.exists(f'{B}/LU_RC2_DONE'): log('DONE marker'); sys.exit(0)
    d = st(); now = time.time(); d['launches'] = [x for x in d['launches'] if now - x < 6 * 3600]
    if len(d['launches']) >= CAP: hold('relaunch cap 12/6h reached')  # cap fix CoS GO 17:47 PT Oct 22: allows exactly 12
    d['launches'].append(now); save(d)
    log('launch collector', 'n6h', len(d['launches']), 'mem', memavail())
    rc = subprocess.call([sys.executable, '/workspace/scripts/lu_sparql_collect.py'])
    log('collector rc', rc)
    if rc in (0, 2): sys.exit(0)
    if rc == 4:
        d = st(); d['strike_stops'] = [x for x in d.get('strike_stops', []) if time.time() - x < 2 * 3600]
        if d['strike_stops']: d['strike_stops'].append(time.time()); save(d); hold('2nd strike stop (403/429/503) within 2h')
        d['strike_stops'].append(time.time()); save(d); log('strike stop -> 10-min cool-off'); sleep_chk(600); continue
    if rc == 3:
        log('MEMTERM -> wait MemAvail>=4200 held 30s'); ok = None
        while True:
            if stopped(): sys.exit(0)
            m = memavail()
            if m >= 4200: ok = ok or time.time()
            else: ok = None
            if ok and time.time() - ok >= 30: break
            time.sleep(5)
        continue
    sleep_chk(600)
