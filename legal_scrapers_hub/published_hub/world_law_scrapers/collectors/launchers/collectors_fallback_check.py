#!/usr/bin/env python3
"""2-collector fallback check (CoS rule 2026-10-15). Fall back to ONE collector (NL-M only) ONLY on: MEMTERM of either collector since the second launch,
OOM kill, MemAvail<1500 sustained 60s, or <2500 sustained 300s. Brief dips (~2.2G, sand-host) that recover are exempt.
Exit 0 = ok; exit 10 = fallback triggered (reason printed; it touches STOP_CZ + FALLBACK_ONE_COLLECTOR). NL-M is never touched. Caller sends CoS note (SendToAgent, priority false).
Sampling: only if current MemAvail<2500 it samples at 1s up to 300s (returns early when recovered). Usage: collectors_fallback_check.py [--since 'YYYY-MM-DD HH:MM:SS']"""
import os,sys,time,glob,re,subprocess
B='/workspace/legal-corpora/cz_sbirkapp'
def ma():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])//1024
def trig(why):
    open(f'{B}/STOP_CZ','a').close(); open('/workspace/legal-corpora/ee_municipal/STOP_EE','a').close(); open(f'{B}/FALLBACK_ONE_COLLECTOR','w').write(time.strftime('%F %T %Z')+' '+why+'\n')
    print('FALLBACK TRIGGERED:',why); sys.exit(10)
since=sys.argv[sys.argv.index('--since')+1] if '--since' in sys.argv else None
if since is None:
    try: since=open('/workspace/logs/second_collector_since.txt').read().strip()
    except Exception: since=None
if since:
    for pat in ('/workspace/logs/cz_t2_collect_*.log','/workspace/logs/ee_t2_collect_*.log','/workspace/logs/nl_municipal_collect_*.log'):
        for f in glob.glob(pat):
            if os.path.getmtime(f)<time.mktime(time.strptime(since,'%Y-%m-%d %H:%M:%S')): continue
            for l in open(f,errors='replace'):
                m=re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)',l)
                if m and m.group(1)>=since and re.search(r'MEMTERM|MEMGUARD TERM|Killed|OOM',l): trig(f'{os.path.basename(f)}: {l.strip()[:160]}')
r=subprocess.run("dmesg 2>/dev/null | grep -iE 'out of memory|oom-kill' | tail -1",shell=True,capture_output=True,text=True).stdout.strip()
if r and since:
    mm=re.match(r'\[\s*([\d.]+)\]',r)
    if mm:
        up=float(open('/proc/uptime').read().split()[0]); age=up-float(mm.group(1))   # seconds ago
        if age < time.time()-time.mktime(time.strptime(since,'%Y-%m-%d %H:%M:%S')): trig('OOM kill: '+r[:160])
if ma()<2500:
    t0=time.time(); l60=l300=None
    while time.time()-t0<300:
        m=ma(); n=time.time()
        if m<2500: l300=l300 or n
        else: l300=None; 
        if m<1500: l60=l60 or n
        else: l60=None
        if l60 and n-l60>=60: trig(f'MemAvail<1500 sustained 60s ({m})')
        if l300 and n-l300>=300: trig(f'MemAvail<2500 sustained 300s ({m})')
        if m>=4200 or (l300 is None and time.time()-t0>10 and m>=2500): break
        time.sleep(1)
print('ok MemAvail',ma())
