#!/workspace/venv/bin/python
"""DE subnational = THIRD collector (CoS order 2026-10-18 15:28 PT; collect+stage only, NO publish). Script: de_sub_collect.py full NW,NWSUP,SN,HB,BB (resume from raw cache).
Refuses: STOP_DE/HOLD_DE/DE_DONE, FALLBACK_ONE_COLLECTOR, STOP_DE written by fallback, DE already running, NL-M main or NLM2 not running, 3 collectors already
(max 3 total), 3-strike BACKOFF active (10 min; supervisor passes --after-backoff), cap 12 launches/6h, MemAvail < 4200 (5000 with --first).
On launch: nice 10, setsid, log /workspace/logs/de_subnational_collect_<ts>.log; registers dep_* keys + collectors in BOTH PINs and second_collector.json; starts de_sub_supervise.py.
Usage: de_sub_launch_guarded.py [--first] [--dry-run] [--after-backoff]"""
import os,sys,json,time,subprocess
R='/workspace/legal-corpora/de_subnational'; L='/workspace/logs'; LED=f'{L}/de_sub_relaunch.json'; CFG=f'{L}/second_collector.json'
STOPS=[f'{R}/STOP_DE',f'{R}/HOLD_DE',f'{L}/STOP_DE',f'{L}/HOLD_DE',f'{R}/DE_DONE']; FALL='/workspace/legal-corpora/cz_sbirkapp/FALLBACK_ONE_COLLECTOR'
BO=f'{R}/BACKOFF_UNTIL'; CAP=12; WIN=6*3600; PINS=[f'{L}/HOLD_AT_PIN.state',f'{L}/soft_lean/HOLD_AT_PIN.state']
LANDS='NW,NWSUP,BB'; PG_DE=r'de_sub_collect\.py full'  # CoS GO 2026-10-25 09:41: BB,NW,SN; SN TLS probe fail
def pg(p): return [l for l in subprocess.run(['pgrep','-af',p],capture_output=True,text=True).stdout.strip().splitlines() if 'pgrep' not in l and 'launch_guarded' not in l]
def ma():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])//1024
def live(): return len(pg(r'nl_municipal_collect\.py full'))+len(pg(r'nlm2_collect\.py full'))+len(pg(PG_DE))
def atomic_json(p,d,sfx):
    t=p+sfx; open(t,'w').write(json.dumps(d,indent=1)); json.load(open(t)); os.replace(t,p)
def pin(u):
    for p in PINS:
        d=json.load(open(p)); d.update(u); atomic_json(p,d,'.de.tmp')
def cfg(u):
    d=json.load(open(CFG)); d.update(u); atomic_json(CFG,d,'.de.tmp')
def main():
    dry='--dry-run' in sys.argv; first='--first' in sys.argv; afterbo='--after-backoff' in sys.argv
    led=json.load(open(LED)) if os.path.exists(LED) else dict(launches=[])
    now=time.time(); recent=[x for x in led['launches'] if now-x['t']<WIN]; why=[]
    for s in STOPS:
        if os.path.exists(s): why.append(os.path.basename(s)+' present')
    if os.path.exists(FALL): why.append('FALLBACK_ONE_COLLECTOR marker present')
    if pg(PG_DE): why.append('DE already running')
    pass  # NL-M main gate removed 2026-10-25 (NLM2 is the primary)
    if not pg(r'nlm2_collect\.py full'): why.append('NLM2 not running (DE is only the third slot)')
    if live()>=3: why.append('3 collectors already running (max 3 total)')
    try:
        if float(open(BO).read().strip())>now and not afterbo: why.append('3-strike BACKOFF active until '+time.strftime('%T',time.localtime(float(open(BO).read()))))
    except Exception: pass
    if len(recent)>=CAP: why.append(f'cap {len(recent)}/{CAP} per 6h')
    need=5000 if first else 4200
    if ma()<need: why.append(f'MemAvail {ma()} < {need}')
    if why: print('REFUSED:','; '.join(why)); return 3
    if dry: print('DRY-RUN OK: would launch DE (recent %d/%d, MemAvail %s, live collectors %d)'%(len(recent),CAP,ma(),live())); return 0
    ts=time.strftime('%Y%m%dT%H%M%S'); log=f'{L}/de_subnational_collect_{ts}.log'
    env=dict(os.environ,MALLOC_ARENA_MAX='2')
    f=open(log,'ab')
    p=subprocess.Popen(['nice','-n','10','/workspace/venv/bin/python','-u','/workspace/scripts/de_sub_collect.py','full',LANDS],stdout=f,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env,start_new_session=True,cwd='/workspace')
    led['launches'].append(dict(t=now,pt=time.strftime('%F %T %Z'),pid=p.pid,log=log)); atomic_json(LED,led,'.tmp')
    if not pg(r'de_sub_supervise\.py'):
        subprocess.Popen(['setsid','nohup','/workspace/venv/bin/python','-u','/workspace/scripts/de_sub_supervise.py'],stdout=open(f'{L}/de_sub_supervise.out','ab'),stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,cwd='/workspace')
    time.sleep(6)
    if p.poll() is not None: print('LAUNCH FAILED: collector exited rc',p.returncode,'log',log); return 1
    iso=time.strftime('%Y-%m-%dT%H:%M:%S%z'); n=live()
    u=dict(collectors=n,dep_status='RUNNING',dep_name='DE_SUBNATIONAL',dep_pid=p.pid,dep_log=log,dep_started=iso,dep_root=R,dep_lands='NW(+NWSUP),SN,HB,BB',
           dep_hosts='recht.nrw.de, www.revosax.sachsen.de, www.transparenz.bremen.de, bravors.brandenburg.de',dep_launcher='/workspace/scripts/de_sub_launch_guarded.py',
           dep_script='/workspace/scripts/de_sub_collect.py',dep_supervisor='/workspace/scripts/de_sub_supervise.py',
           dep_rules='collect+stage only, NO publish; robots honored; delay>=1.0s/host (BB 20s); guard pause3584/resume4200x30s hard<1500x10s instant<1000 rss<300MB; 3x403/429/503 -> STOP, 10-min backoff, HOLD_DE on 2nd stop within 2h; cap 12/6h; fallback drops DE first',
           dep_go='CoS order 2026-10-18 15:28 PT (third collector launch gate)',dep_ts=iso)
    if first: u['third_collector_since']=iso
    pin(u)
    cfg(dict(collectors=n,max_collectors=3,dep_name='DE_SUBNATIONAL',dep_pid=p.pid,dep_log=log,dep_started=iso,dep_pgrep=PG_DE,dep_log_glob=f'{L}/de_subnational_collect_*.log',
             dep_stop_markers=[f'{R}/STOP_DE',f'{R}/HOLD_DE',f'{L}/STOP_DE',f'{L}/HOLD_DE'],dep_done_markers=[f'{R}/DE_DONE'],dep_launcher='/workspace/scripts/de_sub_launch_guarded.py',
             dep_supervisor='/workspace/scripts/de_sub_supervise.py',dep_pin_prefix='dep_',dep_since=iso if first else json.load(open(CFG)).get('dep_since',iso),
             fallback_order=['DE_SUBNATIONAL','NLM2'],fallback_rule='drop DE first: under memory pressure (MemAvail<2500 at a fallback check, or any NL-M/NLM2 MEMTERM after DE start) write STOP_DE + SIGTERM DE before any NLM2 fallback; a full fallback (FALLBACK_ONE_COLLECTOR) stops DE and NLM2. DE is never auto-relaunched by the tick.'))
    print('LAUNCHED pid',p.pid,'log',log,'collectors',n); return 0
sys.exit(main())
