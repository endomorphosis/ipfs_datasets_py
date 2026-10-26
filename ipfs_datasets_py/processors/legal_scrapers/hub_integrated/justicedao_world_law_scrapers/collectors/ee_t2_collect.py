#!/usr/bin/env python3
"""EE T2 — Riigi Teataja in-force KOV /akt/
SKELETON — offline prep only. Network fetch paths are stubs; do NOT launch without Watchdog slot-OK + CoS GO.
Uses /workspace/scripts/strict_mem_guard.py (NL-M thresholds). pa_exit_guard only on offline build/verify/push.

CoS 2026-10-06 ~2:11 PM PT: net-new only — exclude every akt-id in T1 tip 9ef422a2a38a
(frozen exclude list: ref/ee_t1_akt_ids_20261006.txt, 939 rt_ref_id values).
Discovery = /akt/ in-force KOV listing. Exclude list wired; verifier blocker cleared.

Modes:
  guard_dryrun | dry-run | dryrun   offline simulated memory traces (no network)
  selftest                          offline layout/config/state/exclude checks (no network)
  status                            print state.json
  pack                              offline index layout helper
  verify | build                    offline shard verify (pa_exit_guard)
  push                              stub (pa_exit_guard); no HF push
  collect                           REFUSES — skeleton has no network body

Heavy work: nice -n 19 /workspace/venv/bin/python ee_t2_collect.py …
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

ROOT = Path('{_CORPORA}/ee_municipal/t2')
CFG_PATH = ROOT / 'ee_t2_config.json'
STATE_PATH = ROOT / 'state.json'
INDEX = ROOT / 'index' / 'laws_shards'
STOP = ROOT / 'STOP_EE_T2'
PAUSE = ROOT / 'PAUSE_EE_T2'
TOKEN = ROOT / 'COS_GO_EE_T2'
EXCLUDE_PATH = ROOT / 'ref' / 'ee_t1_akt_ids_20261006.txt'
T1_TIP_SHA = '9ef422a2a38a'
EXPECTED_EXCLUDE = 939
DELAY_FLOOR = 1.5
SLOT = 'slot-filler'
EXPECTED = 11045
LABEL = 'ee_municipal_t2'

def log(*a):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), '[' + LABEL + ']', *a, flush=True)

def load_exclude_set(path: Path = EXCLUDE_PATH) -> set[str]:
    """Load frozen T1 rt_ref_id exclude set (one id per line). Net-new discovery must skip all of these."""
    if not path.is_file():
        raise FileNotFoundError('EE T2 exclude list missing: ' + str(path))
    ids: set[str] = set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                ids.add(s)
    return ids

def filter_net_new(candidate_ids, exclude: set[str] | None = None) -> list[str]:
    """Return candidate akt ids with every T1 exclude id removed (net-new only)."""
    ex = exclude if exclude is not None else load_exclude_set()
    return [str(i) for i in candidate_ids if str(i) not in ex]

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

def assert_exclude_wired():
    """Offline: load exclude set and assert expected count (no network)."""
    ex = load_exclude_set()
    n = len(ex)
    assert n == EXPECTED_EXCLUDE, 'exclude len %s != expected %s (path %s)' % (n, EXPECTED_EXCLUDE, EXCLUDE_PATH)
    # Sanity: filter drops excluded ids
    sample = list(ex)[:3] + ['__net_new_probe__']
    kept = filter_net_new(sample, ex)
    assert kept == ['__net_new_probe__'], 'filter_net_new failed: %r' % (kept,)
    return ex

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
    ex = assert_exclude_wired()
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
    log('selftest OK', 'memavail', m, 'cfg.delay', cfg['delay_s'], 'slot', SLOT,
        'exclude', len(ex), 'tip', T1_TIP_SHA, 'path', str(EXCLUDE_PATH))
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
    # Wire exclude even on stub path so discovery/collect contract is frozen offline
    try:
        ex = assert_exclude_wired()
    except Exception as e:
        log('REFUSE: exclude list not wired', e)
        return 5
    log('exclude set loaded', len(ex), 'from', EXCLUDE_PATH, 'tip', T1_TIP_SHA,
        '— collect/discovery MUST call filter_net_new / skip these ids')
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
        ex = assert_exclude_wired()
        log('guard_dryrun exclude OK', len(ex), 'path', str(EXCLUDE_PATH), 'tip', T1_TIP_SHA)
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
