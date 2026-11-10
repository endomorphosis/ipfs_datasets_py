#!/usr/bin/env python3
"""Guarded launcher IT_NORMATTIVA_MFR (PREPPED, NOT launched). Refuses: markers, already running, previous queue entry (second_collector.json) not DONE, >=3 collectors, MemAvail<4608, dryrun fail."""
import os, sys, time, json, subprocess
sys.path.insert(0, '/workspace/scripts'); from strict_mem_guard import memavail
B = '/workspace/legal-corpora/it_normattiva_mfr'; J = f'{B}/jobs.json'
pg = lambda rx: bool(subprocess.run(['pgrep', '-f', rx], capture_output=True).stdout.strip())
if [s for s in [f'{B}/STOP_IT_NORMATTIVA_MFR', '/workspace/logs/STOP_IT_NORMATTIVA_MFR', f'{B}/HOLD_IT_NORMATTIVA_MFR', '/workspace/logs/HOLD_IT_NORMATTIVA_MFR'] if os.path.exists(s)]: print('REFUSE markers'); sys.exit(1)
if pg(r'add_collect\.py.*it_normattiva_mfr/|it_normattiva_mfr_supervise'): print('REFUSE already running'); sys.exit(1)
Q = json.load(open('/workspace/logs/second_collector.json'))['queued_next']; i = [q['name'] for q in Q].index('IT_NORMATTIVA_MFR')
prev = Q[i - 1] if i else None
if prev and not any(os.path.exists(m) for m in prev.get('done_markers', [])): print('REFUSE predecessor not done', prev['name']); sys.exit(1)
n = sum(pg(rx) for rx in [r'nl_municipal_collect|nlm_.*collect\.py full', r'nlm2_collect\.py full', r'es_seue_collect\.py', r'fr_scdl_collect\.py', r'it_dait_collect\.py', r'add_collect\.py', r'us_.*collect\.py'])
if n >= 3: print('REFUSE 3 collectors running'); sys.exit(1)
m = memavail()
if m < 4608: print('REFUSE MemAvail', m); sys.exit(1)
if subprocess.call([sys.executable, '/workspace/scripts/add_collect.py', J, 'dryrun'], stdout=subprocess.DEVNULL) != 0: print('REFUSE dryrun failed'); sys.exit(1)
ts = time.strftime('%Y%m%dT%H%M%S'); lg = f'/workspace/logs/it_normattiva_mfr_collect_{ts}.log'
p = subprocess.Popen([sys.executable, '/workspace/scripts/it_normattiva_mfr_supervise.py'], stdout=open(lg, 'a'), stderr=subprocess.STDOUT, start_new_session=True, cwd='/workspace')
print('LAUNCHED supervisor pid', p.pid, 'log', lg, 'MemAvail', m)
