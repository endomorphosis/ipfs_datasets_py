#!/usr/bin/env python3
"""CZ T2 guarded (re)launcher, Stage 1 parallelism (CoS GO 2026-10-15). Never launches NL-M. Never launches if NL-M is not running
(NL-M relaunch has priority via nlm_launch_after_crisis5.py; CZ must never be started from a failed gate in the same tick).
Refuses: STOP_CZ present, FALLBACK_ONE_COLLECTOR marker, CZ already running, cap 12 per rolling 6h, NOCHUNK3 (3 consecutive launches with no cursor progress),
MemAvail not >=4200 held 5 min (memhold5.py), id_bpk running, PIN collectors>=2 (collector itself also checks).
Usage: cz_t2_launch_guarded.py [--dry-run] [--skip-gate]
"""
import os, sys, json, time, subprocess, re
B='/workspace/legal-corpora/cz_sbirkapp'; L='/workspace/logs'; LED=f'{L}/cz_t2_relaunch.json'
FALL=f'{B}/FALLBACK_ONE_COLLECTOR'; STOP=f'{B}/STOP_CZ'; CUR=f'{B}/t2/cursor.json'
CAP=12; WIN=6*3600
def pg(p): return subprocess.run(['pgrep','-af',p],capture_output=True,text=True).stdout.strip().splitlines()
def running(p): return [l for l in pg(p) if 'pgrep' not in l and 'launch_guarded' not in l]
def ma():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])//1024
def cur_done():
    try: return int(json.load(open(CUR)).get('done',0))
    except Exception: return -1
def main():
    dry='--dry-run' in sys.argv; skipgate='--skip-gate' in sys.argv
    led=json.load(open(LED)) if os.path.exists(LED) else dict(launches=[])
    now=time.time(); led['launches']=[x for x in led['launches'] if now-x['t']<30*86400]
    recent=[x for x in led['launches'] if now-x['t']<WIN]
    why=[]
    if os.path.exists(STOP): why.append('STOP_CZ present')
    if os.path.exists(FALL): why.append('FALLBACK_ONE_COLLECTOR marker present')
    if running(r'cz_sbirkapp_collect\.py (t1|t2|full)( |$)'): why.append('CZ collector already running')
    if not running(r'nl_municipal_collect\.py'): why.append('NL-M not running (NL-M relaunch first; no simultaneous launch)')
    if running(r'id_bpk_collect\.py'): why.append('ID process running')
    if len(recent)>=CAP: why.append(f'cap {len(recent)}/{CAP} per 6h')
    last3=led['launches'][-3:]
    if len(last3)==3 and all(x.get('done_at_launch')==last3[0].get('done_at_launch') for x in last3) and cur_done()==last3[0].get('done_at_launch'):
        why.append('NOCHUNK3: 3 consecutive launches without cursor progress')
    if ma()<4200: why.append(f'MemAvail {ma()} < 4200')
    if why:
        print('REFUSED:', '; '.join(why)); return 3
    if not skipgate and not dry:
        r=subprocess.run(['/workspace/venv/bin/python','/workspace/scripts/memhold5.py','660']); 
        if r.returncode!=0: print('REFUSED: memhold5 5-min gate not met'); return 3
    if dry:
        print('DRY-RUN OK: would launch CZ T2 (recent launches %d/%d, cursor done %s, MemAvail %s)'%(len(recent),CAP,cur_done(),ma())); return 0
    tok=open(f'{B}/COS_GO_T2').readline().strip()
    ts=time.strftime('%Y%m%dT%H%M%S'); log=f'{L}/cz_t2_collect_{ts}.log'
    U='/workspace/usr/usr'
    env=dict(os.environ, MALLOC_ARENA_MAX='2', CZP_LOG=log, CZ_USR_ROOT='/workspace/usr', TESSDATA_PREFIX=U+'/share/tesseract-ocr/5/tessdata',
             PATH=U+'/bin:'+os.environ.get('PATH',''), LD_LIBRARY_PATH=U+'/lib/x86_64-linux-gnu'+(':'+os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else ''))  # user-space debs, CZ collector only
    f=open(log,'ab')
    p=subprocess.Popen(['nice','-n','5','/workspace/venv/bin/python','-u','/workspace/scripts/cz_sbirkapp_collect.py','t2','--cos-go',tok],
        stdout=f,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env,start_new_session=True,cwd='/workspace')
    led['launches'].append(dict(t=now,pt=time.strftime('%Y-%m-%d %H:%M:%S %Z'),pid=p.pid,log=log,done_at_launch=cur_done()))
    tmp=LED+'.tmp'; json.dump(led,open(tmp,'w'),indent=1); os.replace(tmp,LED)
    open(f'{L}/cz_t2_restarts.log','a').write(f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')} CZ T2 guarded launch pid {p.pid} log {log} (Stage 1 parallel with NL-M)\n")
    print('LAUNCHED pid',p.pid,'log',log); return 0
sys.exit(main())
