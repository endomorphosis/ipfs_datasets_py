#!/usr/bin/env python3
"""IT_MFR_PAGE2 supervisor (crash-tolerant). Runs fr_scdl_collect.py full in a loop.
rc0 DONE -> exit. rc2 stopfile -> exit. rc3 MEMTERM -> wait MemAvail>=4200 held 30s (poll 5s), relaunch (cap 12 relaunches / 6h -> HOLD).
rc4 strike stop -> 10-min cool-off then relaunch; a 2nd strike stop within 2h -> write HOLD_IT_MFR_PAGE2 and exit (tell CoS).
rc5/other -> 10-min wait, counts toward cap. STOP/HOLD markers honoured."""
import os, sys, time, subprocess, json
sys.path.insert(0, '/workspace/scripts'); from strict_mem_guard import memavail
B = '/workspace/legal-corpora/it_normattiva_mfr_page2'; STOPS = [f'{B}/STOP_IT_MFR_PAGE2', '/workspace/logs/STOP_IT_MFR_PAGE2', f'{B}/HOLD_IT_MFR_PAGE2', '/workspace/logs/HOLD_IT_MFR_PAGE2']
LEDGER = f'{B}/supervisor_state.json'
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), 'SUP', *a, flush=True)
def stopped(): return [s for s in STOPS if os.path.exists(s)]
def st(): 
    try: return json.load(open(LEDGER))
    except Exception: return dict(launches=[], strike_stops=[])
def save(d): json.dump(d, open(LEDGER + '.tmp', 'w')); os.replace(LEDGER + '.tmp', LEDGER)
def hold(why):
    open(f'{B}/HOLD_IT_MFR_PAGE2', 'a').write(time.strftime('%F %T %Z ') + why + '\n'); log('HOLD', why); sys.exit(0)
def sleep_chk(s):
    t = time.time() + s
    while time.time() < t:
        if stopped(): log('stop marker during wait', stopped()); sys.exit(0)
        time.sleep(5)
while True:
    if stopped(): log('stop markers present', stopped()); sys.exit(0)
    if os.path.exists(f'{B}/IT_MFR_PAGE2_DONE'): log('DONE marker'); sys.exit(0)
    d = st(); now = time.time(); d['launches'] = [x for x in d['launches'] if now - x < 6 * 3600]
    if len(d['launches']) >= 12: hold('relaunch cap 12/6h reached')
    d['launches'].append(now); save(d)
    log('launch collector', 'n6h', len(d['launches']), 'mem', memavail())
    rc = subprocess.call([sys.executable, '/workspace/scripts/add_collect.py', '/workspace/legal-corpora/it_normattiva_mfr_page2/jobs.json', 'full'])
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
