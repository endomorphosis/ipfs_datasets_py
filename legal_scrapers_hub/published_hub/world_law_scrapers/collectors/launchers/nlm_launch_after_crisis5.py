#!/usr/bin/env python3
"""NL-M only relaunch on Watchdog crisis-#5 GO (2026-10-06 6:21 AM PT). Mirrors nlm_hotpatch_restart.py launch half."""
import os, re, sys, time, json, subprocess, datetime
# 2026-10-07 (CoS 3:51 PM PT): resume hi is DERIVED from the scan (no hard-coded cursor). Flags:
#   --dry-run (or NLM_DRYRUN=1): print derived hi + checks, start nothing.
#   --go: required to launch while a PIN nlm_status says HOLD (pass only on an explicit Watchdog/CoS GO).
#   NLM_SCAN_OVERRIDE=<dir>: TEST ONLY, honoured with --dry-run only.
# 2026-10-10 (CoS 7:25 PM PT GO, crash-tolerant mode; Watchdog auto-relaunch after MEMTERM, cap 6 per rolling 6h):
#   stale *.tmp in the scan dir (SIGKILL leftovers) are deleted + logged when no collector runs (no refusal);
#   derived hi is authoritative over PIN nlm_next_hi (difference logged); HOLD refusal only bypassed by --go, and after a
#   launch nlm_status=RUNNING_crash_tolerant (collector writes MEMTERM_crash_tolerant) so a plain re-run works;
#   each launch appends {time_pt,pid,resume_hi} to nlm_relaunches in GATE and one line to nlm_restarts.log; >=6 in 6h -> CAP refusal.
# 2026-10-12 (CoS 10:59 PM PT, host flip to 600ce615): ledger-aware resume. LEDGER remote_covered {hi_top,hi_bottom} = chunk-hi range held on
#   OTHER disks. derive() jumps over it when the local contiguous run from TOPHI ends exactly at hi_top (local chunks inside it are allowed),
#   then continues the contiguous walk below hi_bottom; resume hi = (lowest contiguous chunk) - 200. Collector gets NLM_SKIP_HI so it never
#   re-scrapes the declared range. --start-hi N: explicit start; must be on the 200 grid, <= local_lowest-200, with N+200..local_lowest-200
#   fully inside the ledger range, and == ledger-derived hi if local chunks exist below the range. All other refusals unchanged. Marker written.
LEDGER='/workspace/legal-corpora/nl_municipal/disk_ranges.json'; MARKER='/workspace/legal-corpora/nl_municipal/index/START_HI_OVERRIDE.marker'
START_HI=None
if '--start-hi' in sys.argv[1:]:
    try: START_HI=int(sys.argv[sys.argv.index('--start-hi')+1])
    except Exception: print('LAUNCH REFUSE: --start-hi needs an integer', flush=True); sys.exit(2)
DRY='--dry-run' in sys.argv[1:] or os.environ.get('NLM_DRYRUN')=='1'; GO='--go' in sys.argv[1:]
SCAN='/workspace/legal-corpora/nl_municipal/index/scan'; PIN='/workspace/logs/soft_lean/HOLD_AT_PIN.state'
PINS=['/workspace/logs/HOLD_AT_PIN.state', PIN]; TOPHI=767599; STEP=200
GATE='/workspace/logs/soft_lean/nlm_gate_crisis5.json'; CAP_N=24; CAP_S=6*3600  # CoS 2026-10-11 5:18 AM PT: cap 24 per rolling 6h (was 12 since 2026-10-10 9:38 PM)
NOCHUNK_N=3  # CoS 2026-10-11 5:18 AM PT: HOLD if the last 3 finished runs each wrote no chunk (<200 ids)
if os.environ.get('NLM_GATE_OVERRIDE') and DRY: GATE=os.environ['NLM_GATE_OVERRIDE']
STOPS=['/workspace/legal-corpora/nl_municipal/STOP_NLM', '/workspace/logs/STOP_NLM']
if os.environ.get('NLM_SCAN_OVERRIDE'):
    if not DRY: sys.exit('REFUSE: NLM_SCAN_OVERRIDE is test-only and allowed only with --dry-run')
    SCAN=os.environ['NLM_SCAN_OVERRIDE']
if os.environ.get('NLM_GATE_OVERRIDE'):
    if not DRY: sys.exit('REFUSE: NLM_GATE_OVERRIDE is test-only and allowed only with --dry-run')
RLOG='/workspace/logs/nlm_restarts.log'; PY='/workspace/venv/bin/python'; SCRIPT='/workspace/scripts/nl_municipal_collect.py'
def now_pt(): return datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
def ts(): return time.strftime('%Y-%m-%d %H:%M:%S')
def say(s):
    l=ts()+' LAUNCH '+s; print(l,flush=True); open(RLOG,'a').write(l+'\n')
def coll(): return [int(p) for p in subprocess.run(['pgrep','-f','nl_municipal_collect.py full'],capture_output=True,text=True).stdout.split() if int(p)!=os.getpid()]
def refuse(msg): print(f'{ts()} LAUNCH REFUSE: {msg}', flush=True); sys.exit(2)
def derive(scan):
    """-> (resume_hi, n_chunks, top, bottom, stale_tmps); refuses on a gap / stray chunk outside the contiguous run from TOPHI."""
    names=os.listdir(scan); tmps=[f for f in names if f.endswith('.tmp')]
    his=sorted((int(f[:6]) for f in names if re.fullmatch(r'\d{6}\.jsonl\.gz', f)), reverse=True)
    if not his: refuse(f'no chunks in {scan}')
    if his[0]!=TOPHI: refuse(f'top chunk {his[0]} != expected top {TOPHI}')
    hi=TOPHI; run=[]
    while hi>=1 and os.path.exists(f'{scan}/{hi:06d}.jsonl.gz'): run.append(hi); hi-=STEP
    REM['local_lowest_above']=run[-1]; inrem=set()
    if REM.get('top') is not None and hi==REM['top']:
        inrem={h for h in his if REM['bottom']<=h<=REM['top']}; hi=REM['bottom']-STEP; REM['used']=True
        while hi>=1 and os.path.exists(f'{scan}/{hi:06d}.jsonl.gz'): run.append(hi); hi-=STEP
    stray=sorted(set(his)-set(run)-inrem, reverse=True)
    if stray: refuse(f'gap in scan run: contiguous {run[0]}..{run[-1]} ({len(run)} chunks) then missing {run[-1]-STEP}, but {len(stray)} chunk(s) below/off-grid exist: {stray[:5]}')
    return hi, len(run), run[0], run[-1], tmps
def recent_launches():
    try: L=json.load(open(GATE)).get('nlm_relaunches') or []
    except FileNotFoundError: L=[]
    now=time.time(); n=0
    for e in L:
        try:
            if now-datetime.datetime.fromisoformat(e['time_pt']).timestamp()<=CAP_S: n+=1
        except Exception: pass
    return n, len(L)
def gate_append(entry):
    """atomic read-merge-replace of GATE: append to nlm_relaunches, all other keys untouched"""
    try: d=json.load(open(GATE))
    except FileNotFoundError: d={}
    d.setdefault('nlm_relaunches', []).append(entry)
    t=GATE+'.nlmlaunch.tmp'; open(t,'w').write(json.dumps(d,indent=2)); os.replace(t,GATE)
def pin_merge(u):
    """atomic merge of nlm_* / collectors keys into BOTH PIN files"""
    assert all(k.startswith('nlm_') or k=='collectors' for k in u), u
    for pp in PINS:
        try: d=json.load(open(pp))
        except Exception: d={}
        d.update(u); t=pp+'.nlm.tmp'; open(t,'w').write(json.dumps(d,indent=1)); os.replace(t,pp)
def nochunk_streak(running):
    """count consecutive most-recent FINISHED launches whose log has no 'CHUNK written' line"""
    try: L=json.load(open(GATE)).get('nlm_relaunches') or []
    except FileNotFoundError: L=[]
    n=0; det=[]
    for e in reversed(L):
        if e.get('pid') in running: continue
        lg=e.get('log')
        try: wrote='CHUNK written' in open(lg,errors='replace').read()
        except Exception: wrote=True  # unreadable log: don't count toward HOLD
        if wrote: break
        n+=1; det.append(f"{e.get('pid')}@{e.get('time_pt')}")
    return n, det
REM={}
try:
    _r=json.load(open(LEDGER)).get('remote_covered') or {}
    if _r: REM={'top':int(_r['hi_top']),'bottom':int(_r['hi_bottom'])}
    if REM and not (REM['top']>=REM['bottom'] and (TOPHI-REM['top'])%STEP==0 and (TOPHI-REM['bottom'])%STEP==0): print(f'LAUNCH REFUSE: ledger remote_covered off-grid {REM}', flush=True); sys.exit(2)
except FileNotFoundError: pass
running=coll()
hi, nchunks, top, bottom, tmps = derive(SCAN)
tmp_action='none'
if tmps:
    if running: refuse(f'{len(tmps)} .tmp in {SCAN} while collector {running} is running: {tmps[:5]}')
    if DRY: tmp_action=f'would delete stale {tmps[:5]} (dry-run: untouched)'
    else:
        for f in tmps: os.unlink(os.path.join(SCAN,f))
        tmp_action=f'deleted stale {tmps[:5]}'; say(f'STALE_TMP {tmp_action} in {SCAN} (no collector running)')
SKIP=None
if REM.get('used'): SKIP=(REM['top'], REM['bottom'])
if START_HI is not None:
    LL=REM.get('local_lowest_above')
    if (TOPHI-START_HI)%STEP or START_HI<1: refuse(f'--start-hi {START_HI} off the 200-id grid from {TOPHI}')
    if START_HI>LL-STEP: refuse(f'--start-hi {START_HI} > local lowest {LL} - {STEP}')
    if START_HI<LL-STEP:
        if not REM or not (REM['top']==LL-STEP and START_HI+STEP>=REM['bottom']): refuse(f'--start-hi {START_HI}: range {START_HI+STEP}..{LL-STEP} not covered by ledger remote_covered {REM or "absent"}')
        SKIP=(LL-STEP, START_HI+STEP)
    if REM.get('used') and nchunks and bottom<REM['bottom'] and START_HI!=hi: refuse(f'--start-hi {START_HI} != ledger-derived {hi} (local chunks exist below remote range)')
    print(f'{ts()} LAUNCH START_HI override {START_HI} (derived {hi}) skip={SKIP}', flush=True); hi=START_HI
# 2026-10-14 (CoS BOM fix): targeted id-list rescan. If RESCAN_DIR/state.json has status 'pending', launch the collector with
#   NLM_IDLIST=<effective list> (= CoS list U every manifest_parse_fail id in index/scan chunks, regenerated atomically each launch while pending).
#   The collector writes RESCAN_DIR/<hi>.jsonl.gz, marks state 'done' when complete, then continues the main scan in-process. Status 'done'
#   (or no state file) -> plain main-scan launch as before. Cap / NOCHUNK3 / STOP / HOLD refusals are unchanged; rescan chunks log 'CHUNK written'.
RESCAN_DIR='/workspace/legal-corpora/nl_municipal/index/rescan_bom'; RESCAN_SRC='/workspace/legal-corpora/nl_municipal/index/rescan_manifest_bom_20261014.txt'
RESCAN_LIST=RESCAN_DIR+'/idlist_effective.txt'; RESCAN_MODE=False; RESCAN_N=0
try: _rs=json.load(open(RESCAN_DIR+'/state.json')).get('status')
except FileNotFoundError: _rs=None
if _rs=='pending':
    import gzip
    _ids={int(x) for x in open(RESCAN_SRC).read().split() if x.strip().isdigit()}; _n0=len(_ids)
    for f in os.listdir(SCAN):
        if re.fullmatch(r'\d{6}\.jsonl\.gz', f):
            with gzip.open(f'{SCAN}/{f}','rt') as fh:
                for l in fh:
                    if '"manifest_parse_fail"' in l: _ids.add(json.loads(l)['id'])
    RESCAN_MODE=True; RESCAN_N=len(_ids)
    if not DRY:
        _t=RESCAN_LIST+'.tmp'; open(_t,'w').write(''.join(f'{i}\n' for i in sorted(_ids,reverse=True))); os.replace(_t,RESCAN_LIST)
    print(f'{ts()} LAUNCH RESCAN_BOM pending: ids={RESCAN_N} (CoS list {_n0} + scan parse_fail extra {RESCAN_N-_n0}) list={RESCAN_LIST}', flush=True)
elif _rs is not None: print(f'{ts()} LAUNCH RESCAN_BOM state={_rs} -> main scan', flush=True)
pin_hi={}
for pp in PINS:
    try: d=json.load(open(pp))
    except Exception: continue
    if d.get('nlm_next_hi') is not None: pin_hi[pp]=int(d['nlm_next_hi'])
bad=[f'{pp}={v}' for pp,v in pin_hi.items() if v!=hi]
holds=[]
for pp in PINS:
    try: st=str(json.load(open(pp)).get('nlm_status') or '')
    except Exception: continue
    if 'HOLD' in st.upper(): holds.append(f'{pp}: nlm_status={st}')
stops=[f for f in STOPS if os.path.exists(f)]
n6, nall = recent_launches()
print(f"{ts()} LAUNCH CHECK scan={SCAN} chunks={nchunks} top={top} bottom={bottom} derived_resume_hi={hi} tmp={len(tmps)} tmp_action={tmp_action} gap=none remote_skip={SKIP} start_hi={START_HI} "
      f"pin_nlm_next_hi={pin_hi or 'absent'} pin_match={not bad} stopfiles={stops or 'none'} hold={holds or 'none'} collectors_running={running or 'none'} "
      f"launches_6h={n6}/{CAP_N} launches_total={nall} go_flag={GO} dry_run={DRY}", flush=True)
if bad: print(f'{ts()} LAUNCH NOTE: PIN nlm_next_hi {bad} differs from derived {hi}; derived hi is authoritative', flush=True)
if stops: refuse(f'STOP file(s) present: {stops}')
if n6>=CAP_N: refuse(f'CAP: {n6} launches logged in the last 6h (cap {CAP_N}) in {GATE}; no relaunch')
nc, ncdet = nochunk_streak(running)
print(f'{ts()} LAUNCH NOCHUNK_STREAK={nc}/{NOCHUNK_N} {ncdet}', flush=True)
if nc>=NOCHUNK_N:
    if not DRY:
        pin_merge({'nlm_status':'HOLD_NOCHUNK3_crash_tolerant','collectors':0}); say(f'NOCHUNK3 HOLD set: last {nc} runs wrote no chunk {ncdet}')
    refuse(f'NOCHUNK3: last {nc} finished runs each wrote no chunk (<200 ids) {ncdet}; HOLD set, wake CoS')
if DRY: print(f'{ts()} LAUNCH DRY-RUN OK: mode={"RESCAN_BOM idlist="+RESCAN_LIST+" ids="+str(RESCAN_N) if RESCAN_MODE else "main_scan"}', flush=True)
if DRY: print(f'{ts()} LAUNCH DRY-RUN OK: would resume at hi {hi}; nothing started', flush=True); sys.exit(0)
if running: refuse(f'collector already present {running}')
if holds and not GO: refuse(f'HOLD in PIN ({holds}); relaunch needs an explicit GO (--go)')
if bad: say(f'PIN_OVERRIDE derived hi {hi} used; PIN had {bad}')
stamp=time.strftime('%Y%m%dT%H%M%S'); NEW=f'/workspace/logs/nl_municipal_collect_{stamp}.log'
open(NEW,'w').write(f'{ts()} RESTART reason="crash-tolerant NL-M only, strict ({"--go" if GO else "relaunch"})" cursor_next_hi={hi}\n')
env={k:v for k,v in os.environ.items() if k not in ('NLM_NO_PIN','NLM_MAX_WALL_S','NLM_MAX_CHUNKS','NLM_TOP','NLM_HC_MAX_CHUNKS','NLM_BUILD_SRC')}
env['NLM_CRASH_TOLERANT']='1'
env.pop('NLM_IDLIST', None)
if RESCAN_MODE: env['NLM_IDLIST']=RESCAN_LIST
env.pop('NLM_SKIP_HI', None)
if SKIP: env['NLM_SKIP_HI']=f'{SKIP[0]}:{SKIP[1]}'
if START_HI is not None or SKIP:
    _t=MARKER+'.tmp'; open(_t,'w').write(json.dumps(dict(time_pt=now_pt(),start_hi=START_HI,resume_hi=hi,skip_hi=SKIP,ledger=LEDGER,local_lowest_above=REM.get('local_lowest_above'),go=GO,boot_id=open('/proc/sys/kernel/random/boot_id').read().strip(),note='CoS 10:59 PM PT Oct 12: skip range held on other disks; no chunks faked or deleted'),indent=1)); os.replace(_t,MARKER)
started=now_pt()
subprocess.Popen(['setsid','nohup',PY,'-u',SCRIPT,'full'],stdout=open(NEW,'a'),stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env,cwd='/workspace',start_new_session=True)
time.sleep(8); new=None
for q in coll():
    try:
        if open(f'/proc/{q}/cmdline').read().startswith(PY): new=q
    except Exception: pass
start=[l for l in open(NEW).read().splitlines() if ' START full ' in l]
try: gate_append(dict(time_pt=datetime.datetime.now().astimezone().isoformat(timespec='seconds'), pid=new, resume_hi=hi, skip_hi=SKIP, start_hi=START_HI, log=NEW, go=GO, start_line=bool(start), mode=('rescan_bom' if RESCAN_MODE else 'main')))
except Exception as e: print(f'{ts()} LAUNCH gate append failed {e!r}', flush=True)
say(f'mode={"RESCAN_BOM ids="+str(RESCAN_N) if RESCAN_MODE else "main_scan"} new_pid={new} next_hi={hi} log={NEW} start_line={bool(start)} launches_6h={n6+1}/{CAP_N} mode=crash_tolerant go={GO}')
if new and start:
    pin_merge(dict(collectors=1,nlm_status='RUNNING_crash_tolerant',nlm_pid=new,nlm_log=NEW,nlm_cursor_id=hi,nlm_next_hi=hi,nlm_started=started,nlm_started_pt=started,
      nlm_phase=f'crash-tolerant full resume from chunks (next hi {hi}); STRICT 3584/4200x30s, debounced 3000/5s, instant 2500; NL-M only; Watchdog auto-relaunch cap {CAP_N}/6h',
      nlm_restart=f'crash-tolerant launch: new_pid {new} at next_hi {hi} ({now_pt()})',nlm_ended_pt=None,nlm_ts=now_pt()))
    say('PIN updated (both)')
else: sys.exit(1)
