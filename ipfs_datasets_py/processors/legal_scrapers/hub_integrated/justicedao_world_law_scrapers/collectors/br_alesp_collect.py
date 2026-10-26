#!/usr/bin/env python3
"""BR ALESP — São Paulo state normas (open ZIP)
SKELETON — offline prep only. Network fetch paths are stubs; do NOT launch without Watchdog slot-OK + CoS GO.
Uses /workspace/scripts/strict_mem_guard.py (NL-M thresholds). pa_exit_guard only on offline build/verify/push.

CoS 2026-10-06 ~2:05 PM PT: alone-required (never with NL-M); at GO take ALL tipos from
the open ZIP dump (not Lei-only) — dump/parse, not crawl.

Modes:
  guard_dryrun | dry-run | dryrun   offline simulated memory traces (no network)
  selftest                          offline layout/config/state checks (no network)
  status                            print state.json
  pack                              offline index layout helper
  verify | build                    offline shard verify (pa_exit_guard)
  push                              stub (pa_exit_guard); no HF push
  collect                           REFUSES — skeleton has no network body

Heavy work: nice -n 19 /workspace/venv/bin/python br_alesp_collect.py …
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, time, gzip, hashlib
from pathlib import Path

sys.path.insert(0, '/workspace/scripts')
import strict_mem_guard as SG

ROOT = Path('{_CORPORA}/br_alesp')
CFG_PATH = ROOT / 'bralesp_config.json'
STATE_PATH = ROOT / 'state.json'
INDEX = ROOT / 'index' / 'laws_shards'
STOP = ROOT / 'STOP_BRALESP'
PAUSE = ROOT / 'PAUSE_BRALESP'
TOKEN = ROOT / 'COS_GO_BRALESP'
DELAY_FLOOR = 2.0
SLOT = 'alone-required'
EXPECTED = 254063
LABEL = 'br_alesp'

def log(*a):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), '[' + LABEL + ']', *a, flush=True)

def ensure_layout():
    for p in (ROOT, ROOT / 'index', INDEX, ROOT / 'review', ROOT / 'build', ROOT / 'out', ROOT / 'dist', ROOT / 'ref', ROOT / 'evidence'):
        p.mkdir(parents=True, exist_ok=True)
    if not CFG_PATH.exists():
        cfg = SG.load_cfg(overrides={'delay_s': DELAY_FLOOR}, delay_floor=DELAY_FLOOR)
        cfg['_note'] = LABEL + ' STRICT guard matching NL-M; delay floor ' + str(DELAY_FLOOR) + '; slot=' + SLOT
        SG.atomic_json(str(CFG_PATH), cfg)
    if not STATE_PATH.exists():
        SG.atomic_json(str(STATE_PATH), dict(
            created=time.strftime('%Y-%m-%dT%H:%M:%S%z'), slug=LABEL, status='PREP',
            cursor=None, packed=0, expected=EXPECTED, slot=SLOT,
            note='skeleton only; collector not launched',
        ))

def selftest():
    ensure_layout()
    cfg = SG.load_cfg(str(CFG_PATH), delay_floor=DELAY_FLOOR)
    assert cfg['pause_memavail'] == 3584
    assert cfg['resume_memavail'] == 4200
    assert cfg['resume_hold_s'] == 30
    assert cfg['hard_term_memavail'] == 3000
    assert float(cfg['hard_term_sustain_s']) == 5.0
    assert cfg['instant_term_memavail'] == 2500
    assert cfg['rss_limit_mb'] == 300
    assert cfg['max_pause_s'] == 900
    assert cfg['delay_s'] >= DELAY_FLOOR
    st = json.load(open(STATE_PATH))
    assert st.get('slug') == LABEL
    shard = INDEX / (LABEL + '_selftest_0000.jsonl.gz')
    rec = dict(id=LABEL.upper() + '-SELFTEST-0', title='selftest placeholder', text='', meta=dict(selftest=True))
    with gzip.open(shard, 'wt', encoding='utf-8') as g:
        g.write(json.dumps(rec, ensure_ascii=False) + '\n')
    man = dict(
        shards=[dict(name=shard.name, n=1, sha256=hashlib.sha256(open(shard, 'rb').read()).hexdigest())],
        selftest=True, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    SG.atomic_json(str(INDEX / 'manifest.json'), man)
    g = SG.StrictGuard(cfg, stop_file=str(STOP), pause_file=str(PAUSE), log=log)
    m = g.check()
    log('selftest OK', 'memavail', m, 'cfg.delay', cfg['delay_s'], 'slot', SLOT)
    return 0

def status():
    ensure_layout()
    print(json.dumps(json.load(open(STATE_PATH)), indent=1, ensure_ascii=False))
    return 0

def collect_stub(argv):
    ensure_layout()
    if STOP.exists():
        log('STOP file present', STOP); return 2
    if (not TOKEN.exists()) and ('--i-have-cos-go' not in argv):
        log('REFUSE: no CoS GO token', TOKEN, 'and no --i-have-cos-go; skeleton will not fetch')
        return 3
    log('REFUSE: collect body is a skeleton — network fetch not implemented. Prep only.')
    return 4

def pack_offline():
    ensure_layout()
    log('pack_offline: index ready at', INDEX)
    return 0

def verify_offline():
    ensure_layout()
    man_p = INDEX / 'manifest.json'
    if not man_p.exists():
        log('verify: no manifest yet'); return 1
    man = json.load(open(man_p))
    bad = []
    for s in man.get('shards', []):
        p = INDEX / s['name']
        if not p.exists():
            bad.append(('missing', s['name'])); continue
        h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        if h != s.get('sha256'):
            bad.append(('sha', s['name'], h, s.get('sha256')))
    out = dict(ok=not bad, bad=bad, shards=len(man.get('shards', [])))
    print(json.dumps(out, indent=1))
    return 0 if not bad else 1

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__); return 1
    cmd = argv[0]
    if cmd in ('guard_dryrun', 'dry-run', 'dryrun'):
        cfg = SG.load_cfg(str(CFG_PATH) if CFG_PATH.exists() else None,
                          overrides={'delay_s': DELAY_FLOOR}, delay_floor=DELAY_FLOOR)
        return 0 if SG.guard_dryrun(cfg, label=LABEL) else 1
    if cmd == 'selftest':
        return selftest()
    if cmd == 'status':
        return status()
    if cmd == 'pack':
        return pack_offline()
    if cmd in ('verify', 'build'):
        import pa_exit_guard as EG
        return EG.run_guarded(verify_offline)
    if cmd == 'push':
        import pa_exit_guard as EG
        def _push():
            log('push stub: offline prep only — no HF push implemented')
            return 4
        return EG.run_guarded(_push)
    if cmd == 'collect':
        return collect_stub(argv)
    print(__doc__); return 1

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
