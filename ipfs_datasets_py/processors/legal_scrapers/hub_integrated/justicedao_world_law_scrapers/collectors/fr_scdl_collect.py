#!/usr/bin/env python3
"""FR municipal T1 — 28 SCDL délibérations datasets (Licence Ouverte / ODbL)
SKELETON — offline prep only. Network fetch paths are stubs; do NOT launch without Watchdog slot-OK + CoS GO.
Uses /workspace/scripts/strict_mem_guard.py (NL-M thresholds). pa_exit_guard only on offline build/verify/push.

CoS 2026-10-06 ~2:11 PM PT: ONLY collect the frozen 28-id allow-list
(ref/fr_scdl_28_allowlist_20261006.json — 21 lov2 + 6 fr-lo + 1 odc-odbl; skip 18 notspecified).
Hard-fail if asked to collect outside the list. Status READY (no launch until CoS GO).

Modes:
  guard_dryrun | dry-run | dryrun   offline simulated memory traces (no network)
  selftest                          offline layout/config/state/allowlist checks (no network)
  status                            print state.json
  pack                              offline index layout helper
  verify | build                    offline shard verify (pa_exit_guard)
  push                              stub (pa_exit_guard); no HF push
  collect                           REFUSES — skeleton has no network body

Heavy work: nice -n 19 /workspace/venv/bin/python fr_scdl_collect.py …
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

ROOT = Path('{_CORPORA}/fr_scdl_deliberations')
CFG_PATH = ROOT / 'frscdl_config.json'
STATE_PATH = ROOT / 'state.json'
INDEX = ROOT / 'index' / 'laws_shards'
STOP = ROOT / 'STOP_FRSCDL'
PAUSE = ROOT / 'PAUSE_FRSCDL'
TOKEN = ROOT / 'COS_GO_FRSCDL'
ALLOWLIST_PATH = ROOT / 'ref' / 'fr_scdl_28_allowlist_20261006.json'
ALLOWLIST_MD = ROOT / 'ref' / 'fr_scdl_28_allowlist_20261006.md'
EXPECTED_ALLOW = 28
EXPECTED_LICENCE = {'lov2': 21, 'fr-lo': 6, 'odc-odbl': 1}
DELAY_FLOOR = 1.0
SLOT = 'slot-filler'
EXPECTED = 28
LABEL = 'fr_scdl_deliberations'

def log(*a):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), '[' + LABEL + ']', *a, flush=True)

def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict:
    """Load frozen 28-dataset allow-list. Returns dict with ids (set), licence_counts, datasets."""
    if not path.is_file():
        raise FileNotFoundError('FR SCDL allow-list missing: ' + str(path))
    data = json.load(open(path, encoding='utf-8'))
    datasets = data.get('datasets') or []
    ids = {str(d['dataset_id']) for d in datasets if d.get('dataset_id')}
    lic: dict[str, int] = {}
    for d in datasets:
        lid = d.get('licence_id') or 'unknown'
        lic[lid] = lic.get(lid, 0) + 1
    return dict(
        ids=ids,
        licence_counts=lic,
        datasets=datasets,
        meta=data,
        path=str(path),
    )

def assert_allowlist_wired():
    """Offline: load allow-list and assert 28 ids + licence split (no network)."""
    al = load_allowlist()
    n = len(al['ids'])
    assert n == EXPECTED_ALLOW, 'allowlist len %s != expected %s (path %s)' % (n, EXPECTED_ALLOW, ALLOWLIST_PATH)
    # Prefer file's own licence_counts when present; also check derived
    file_lic = (al['meta'] or {}).get('licence_counts') or al['licence_counts']
    for k, v in EXPECTED_LICENCE.items():
        got = int(file_lic.get(k, 0))
        assert got == v, 'licence %s count %s != expected %s' % (k, got, v)
    for k, v in EXPECTED_LICENCE.items():
        got = int(al['licence_counts'].get(k, 0))
        assert got == v, 'derived licence %s count %s != expected %s' % (k, got, v)
    return al

def assert_ids_allowed(requested_ids, allow_ids: set[str] | None = None) -> None:
    """Hard-fail if any requested dataset id is outside the frozen allow-list."""
    allowed = allow_ids if allow_ids is not None else load_allowlist()['ids']
    bad = [str(i) for i in requested_ids if str(i) not in allowed]
    if bad:
        raise SystemExit(
            'HARD FAIL: collect asked for id(s) outside frozen 28 allow-list: %s (allowlist=%s)'
            % (bad, ALLOWLIST_PATH)
        )

def _parse_requested_ids(argv) -> list[str]:
    """Parse --id / --ids / --dataset-id flags from argv (collect path)."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('--id', '--ids', '--dataset-id', '--dataset-ids'):
            if i + 1 >= len(argv):
                break
            chunk = argv[i + 1]
            out.extend([x.strip() for x in chunk.split(',') if x.strip()])
            i += 2
            continue
        if a.startswith('--id=') or a.startswith('--ids=') or a.startswith('--dataset-id='):
            chunk = a.split('=', 1)[1]
            out.extend([x.strip() for x in chunk.split(',') if x.strip()])
        i += 1
    return out

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
    al = assert_allowlist_wired()
    # Outside-list must hard-fail
    try:
        assert_ids_allowed(['not-an-allowed-id-000'], al['ids'])
        raise AssertionError('expected hard-fail for outside id')
    except SystemExit as e:
        assert 'HARD FAIL' in str(e)
    # Inside-list OK
    sample = list(al['ids'])[:2]
    assert_ids_allowed(sample, al['ids'])
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
        'allowlist', len(al['ids']), 'licences', al['licence_counts'], 'path', str(ALLOWLIST_PATH))
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
    try:
        al = assert_allowlist_wired()
    except Exception as e:
        log('REFUSE: allow-list not wired', e)
        return 5
    requested = _parse_requested_ids(argv)
    if requested:
        # Hard-fail outside list (SystemExit)
        assert_ids_allowed(requested, al['ids'])
        targets = requested
    else:
        # Default collect scope = entire frozen 28
        targets = sorted(al['ids'])
    log('allowlist loaded', len(al['ids']), 'from', ALLOWLIST_PATH,
        'licences', al['licence_counts'], 'targets', len(targets),
        '— ONLY these ids may be collected')
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
        al = assert_allowlist_wired()
        log('guard_dryrun allowlist OK', len(al['ids']), 'licences', al['licence_counts'],
            'path', str(ALLOWLIST_PATH))
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
