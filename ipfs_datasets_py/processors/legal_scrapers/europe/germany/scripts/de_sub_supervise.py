#!/usr/bin/env python3
"""DE third-collector strict 3-strike supervisor (CoS 2026-10-18 15:28 PT). Mirrors nlm2_supervise.py.
- 3-strike STOP (log 'STOP 3 consecutive', rc 4): BACKOFF_UNTIL (+600s), wait 600s, relaunch via de_sub_launch_guarded.py --after-backoff.
  2nd 3-strike stop within 2h -> HOLD_DE (both marker dirs) + PIN dep_status=HOLD_2STRIKE_2h, no relaunch.
- 'DE range complete' -> DE_DONE marker, PIN dep_status=DONE, collectors recount, exit.
- drop-DE-first: if a MEMTERM appears in NL-M or NLM2 logs after DE start while DE runs -> STOP_DE + SIGTERM DE (dep_status=DROPPED_MEMPRESSURE).
- other exits (MEMTERM of DE, markers) -> PIN dep_status=ENDED_nonstrike; exit (DE is not auto-relaunched)."""
import os,sys,time,json,glob,subprocess,re,signal
R='/workspace/legal-corpora/de_subnational'; L='/workspace/logs'; ST=f'{R}/strikes.json'; PINS=[f'{L}/HOLD_AT_PIN.state',f'{L}/soft_lean/HOLD_AT_PIN.state']; CFG=f'{L}/second_collector.json'
PG_DE=r'de_sub_collect\.py full'
def log(s): open(f'{L}/de_sub_supervise.log','a').write(time.strftime('%F %T ')+s+'\n')
def pg(p): return [l for l in subprocess.run(['pgrep','-af',p],capture_output=True,text=True).stdout.strip().splitlines() if 'pgrep' not in l]
def live(): return len(pg(r'nl_municipal_collect\.py full'))+len(pg(r'nlm2_collect\.py full'))+len(pg(PG_DE))
def atomic_json(p,d):
    t=p+'.desup.tmp'; open(t,'w').write(json.dumps(d,indent=1)); json.load(open(t)); os.replace(t,p)
def pin(u):
    for p in PINS:
        try: d=json.load(open(p))
        except Exception as e: log(f'PIN read fail {p} {e}; skip'); continue
        d.update(u); d['dep_ts']=time.strftime('%Y-%m-%dT%H:%M:%S%z'); atomic_json(p,d)
    try:
        c=json.load(open(CFG)); c['collectors']=u.get('collectors',c.get('collectors')); c['dep_pid']=u.get('dep_pid',c.get('dep_pid')); c['dep_status']=u.get('dep_status',c.get('dep_status')); atomic_json(CFG,c)
    except Exception as e: log(f'CFG update fail {e}')
def newest():
    g=sorted(glob.glob(f'{L}/de_subnational_collect_2*.log')); return g[-1] if g else None
def txt(l): return open(l,errors='replace').read()
def is_stop(l): return ' STOP 3 consecutive' in txt(l)
def ts_(x): return time.mktime(time.strptime(x,'%Y-%m-%d %H:%M:%S'))
def other_memterm(since):
    for pat in ('/workspace/logs/nl_municipal_collect_*.log','/workspace/logs/nlm2_collect_*.log'):
        for f in glob.glob(pat):
            if os.path.getmtime(f)<since: continue
            for line in open(f,errors='replace'):
                m=re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)',line)
                if m and ts_(m.group(1))>=since and re.search(r'MEMTERM|MEMGUARD TERM',line): return f'{os.path.basename(f)}: {line.strip()[:140]}'
    return None
T0=time.time(); log('supervisor start pid %d'%os.getpid())
while True:
    time.sleep(20)
    p=pg(PG_DE)
    if p:
        mt=other_memterm(T0)
        if mt:
            for m in (f'{R}/STOP_DE',f'{L}/STOP_DE'): open(m,'a').write(time.strftime('%F %T %Z')+' drop-DE-first: '+mt+'\n')
            for l in p:
                try: os.kill(int(l.split()[0]),signal.SIGTERM)
                except Exception: pass
            time.sleep(5); pin({'dep_status':'DROPPED_MEMPRESSURE','dep_pid':None,'collectors':live(),'dep_drop_reason':mt}); log('drop-DE-first: '+mt); sys.exit(0)
        continue
    l=newest()
    if not l: log('no log; exit'); sys.exit(0)
    time.sleep(5)
    if 'DE range complete' in txt(l):
        open(f'{R}/DE_DONE','w').write(time.strftime('%F %T')+' '+l+'\n'); pin({'dep_status':'DONE','dep_pid':None,'collectors':live()}); log('range complete '+l); sys.exit(0)
    if not is_stop(l):
        log('collector ended without 3-strike (%s); supervisor exits (DE not auto-relaunched)'%os.path.basename(l)); pin({'dep_status':'ENDED_nonstrike','dep_pid':None,'collectors':live()}); sys.exit(0)
    st=json.load(open(ST)) if os.path.exists(ST) else {'stops':[]}; now=time.time(); prev=[t for t in st['stops'] if now-t<=7200]
    st['stops'].append(now); json.dump(st,open(ST,'w'))
    log('3-strike STOP in %s (prior within 2h: %d)'%(l,len(prev)))
    if prev:
        for m in (f'{R}/HOLD_DE',f'{L}/HOLD_DE'): open(m,'a').write(time.strftime('%F %T %Z')+' second 3-strike stop within 2h\n')
        pin({'dep_status':'HOLD_2STRIKE_2h','dep_pid':None,'collectors':live(),'dep_hold_reason':'second 3-strike stop within 2h (CoS 2026-10-18)'}); log('HOLD set, no relaunch'); sys.exit(0)
    open(f'{R}/BACKOFF_UNTIL','w').write(str(now+600)); pin({'dep_status':'BACKOFF_600s','dep_pid':None,'collectors':live()})
    time.sleep(600)
    if any(os.path.exists(m) for m in (f'{R}/STOP_DE',f'{R}/HOLD_DE',f'{L}/STOP_DE',f'{L}/HOLD_DE')): log('marker present after backoff; exit'); sys.exit(0)
    r=subprocess.run(['/workspace/venv/bin/python','/workspace/scripts/de_sub_launch_guarded.py','--after-backoff'],capture_output=True,text=True); log('relaunch rc=%d %s'%(r.returncode,r.stdout[-300:].replace('\n',' | ')))
    if r.returncode: sys.exit(1)
    T0=time.time()
