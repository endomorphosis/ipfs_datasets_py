"""Targeted clean re-scrape of explicit KG CBD organs (prefix-contamination fix, 2026-10-18).
Reuses kg_cbd_full.recs_for (patched: keep doc only if authoritiesId.code == organ code / canon) and writes ONE
.full file per place: staging/sasia_ru/KG/<place_key>.full.<UTC>Zrescrape.jsonl (whole-place replace).
- Sequential with the main run: every API request waits while any other cbd API scraper process
  (kg_cbd_full.py / kg_cbd_local.py / kg_id_cleanup.py) is alive, so the site never sees >1 req/s from us.
  Same 1 req/s spacing as kg_cbd_local.call. Single instance via flock on _kg/rescrape_prefix.lock.
- Failed requests (retries exhausted) abort the organ (no truncated .full is ever staged); retried on a later pass.
- Every record re-checked: GetDocument authoritiesId.code exactly == organ code/canon; source_url not staged under
  another KG place (staging/*/KG, processed/sasia_ru/KG); doc_id unique; validate_file 0 bad rows before rename.
- Resume: _kg/rescrape_prefix_done.jsonl (one line per place). Log: _kg/rescrape_prefix.log
Usage: kg_cbd_rescrape.py --organs 2=wd:Q2556747,8=wd:Q737375,...  [--tag rescrape]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, time, glob, datetime, argparse, fcntl, shutil, resource, csv, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline')); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
import kg_cbd_local, kg_cbd_full
from schema import validate_file, validate_record, place_key
B = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); W = B + '/_kg'; DONE = W + '/rescrape_prefix_done.jsonl'; KGDIR = B + '/KG'; FAILDIR = W
API_SCRAPERS = ('kg_cbd_full.py', 'kg_cbd_local.py', 'kg_id_cleanup.py')
def now(): return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def log(*a): print(now(), *a, flush=True)
def mem_mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

def other_api_procs():
    me = os.getpid(); out = []
    for p in glob.glob('/proc/[0-9]*/cmdline'):
        try:
            pid = int(p.split('/')[2])
            if pid == me: continue
            cmd = open(p, 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace')
        except Exception: continue
        if 'python' in cmd and any(s in cmd for s in API_SCRAPERS): out.append(pid)
    return out
_gate = {'t': 0.0, 'waits': 0}
def gate():
    if time.time() - _gate['t'] < 2: return
    warned = False
    while True:
        o = other_api_procs()
        if not o: break
        if not warned: log('GATE waiting: other cbd API scraper(s) running', o); warned = True; _gate['waits'] += 1
        time.sleep(60)
    if warned: log('GATE open')
    _gate['t'] = time.time()

class ApiFail(Exception): pass
AUTH = {}      # documentCode -> authoritiesId.code from GetDocument
LISTCODE = {}  # documentCode -> authority code exposed by GetDocuments list item (if the API exposes one)
_seen_keys = [False]
def _list_code(x):
    a = x.get('authoritiesId')
    if isinstance(a, dict) and a.get('code') is not None: return str(a['code']).strip()
    for k in ('authorityCode', 'authoritiesCode', 'authoritiesIdCode'):
        if x.get(k) is not None: return str(x[k]).strip()
    return None
def gated_call(method, path, **kw):
    if path.startswith('/GetDocument?DocumentCode='):
        c = path.split('=', 1)[1]
        if c in LISTCODE and LISTCODE[c] not in CUR['codes']: return None   # list item already proves it's another body's doc
    gate()
    last = kg_cbd_local.last
    for a in range(4):
        w = last[0] + 1.0 - time.time()
        if w > 0: time.sleep(w)
        try:
            r = kg_cbd_local.S.request(method, kg_cbd_local.API + path, timeout=60, **kw); last[0] = time.time()
            if r.status_code == 200:
                d = r.json()
                if path.startswith('/GetDocuments') and d and d.get('data'):
                    if not _seen_keys[0]: log('list item keys:', sorted(d['data'][0].keys())); _seen_keys[0] = True
                    for x in d['data']:
                        lc = _list_code(x)
                        if lc is not None: LISTCODE[x['documentCode']] = lc
                if path.startswith('/GetDocument?DocumentCode=') and d:
                    AUTH[path.split('=', 1)[1]] = str(((d.get('authoritiesId') or {}).get('code')) or '').strip()
                return d
            if r.status_code in (400, 404): return None
            log('HTTP', r.status_code, path)
        except Exception as e:
            last[0] = time.time(); log('ERR', type(e).__name__, path)
        time.sleep(5 * (a + 1))
    raise ApiFail(f'{method} {path} failed after 4 tries')
CUR = {'codes': set()}

def organ_mapping(code):
    """Same organ -> (place, place_ru, src) resolution as kg_cbd_full.main()."""
    mapped = {}
    for l in open(W + '/kg_organ_map.jsonl'): x = json.loads(l); mapped[x['code']] = x
    ext = collections.defaultdict(set); EXT = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_body_to_place.csv')
    if os.path.exists(EXT):
        for r in csv.DictReader(open(EXT)):
            if r['place_id'].startswith('wd:Q'): ext[r['cbd_issuing_body_id'].strip()].add(r['place_id'].strip())
    merge = json.load(open(W + '/body_id_merge.json')) if os.path.exists(W + '/body_id_merge.json') else {}
    o = next(o for o in json.load(open(W + '/kg_local_organs.json')) if o['code'] == code)
    o = dict(o); o['canon'] = merge.get(code, code)
    cand = set(ext.get(o['canon'], set()) | ext.get(code, set()))
    for c in (code, o['canon']):
        if c in mapped: cand.add(mapped[c]['qid'])
    base = mapped.get(code) or mapped.get(o['canon']) or {}
    q = next(iter(cand)) if len(cand) == 1 else None
    o['place_ru'] = base.get('place_ru') if base.get('qid') == q else None
    o['src'] = 'organ_map' if base.get('qid') == q else 'normalizer_kg_body_to_place'
    return o, q, cand

def url_index(exclude_keys):
    """source_url -> place_key for every KG record currently staged (any bot) or in processed/sasia_ru/KG."""
    idx = {}
    files = glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/*/KG/*.jsonl')) + glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/processed/sasia_ru/KG/*.jsonl'))
    for f in files:
        k = os.path.basename(f).split('.')[0]
        if k in exclude_keys or os.path.basename(f).startswith(('.', '_')): continue
        try:
            for l in open(f, encoding='utf-8'):
                try: u = json.loads(l).get('source_url')
                except Exception: continue
                if u: idx.setdefault(u, k)
        except FileNotFoundError: pass   # moved by the Normalizer meanwhile
    return idx

def do_place(qid, codes, all_keys, tag):
    """All organs mapped to one place go into ONE .full file (a .full replaces the whole place)."""
    pk = place_key(qid); os.makedirs(KGDIR, exist_ok=True)
    recs, docs, bad_auth, names, per_organ = [], set(), 0, [], {}
    for code in codes:
        o, q, cand = organ_mapping(code)
        if q != qid: raise RuntimeError(f'mapping mismatch for {code}: main-run logic gives {sorted(cand)}, requested {qid}')
        CUR['codes'] = {str(o['code']).strip(), str(o['canon']).strip()}; names.append(o['name']); n0 = len(docs)
        for r in kg_cbd_full.recs_for(o, qid):
            dc = r['doc_id'].split(':')[1]
            if AUTH.get(dc) not in CUR['codes']: bad_auth += 1; continue   # belt and braces (recs_for already filters)
            if validate_record(r): log('INVALID', r['doc_id'], validate_record(r)); continue
            recs.append(r); docs.add(dc)
            if mem_mb() > 450: raise RuntimeError('MEM HIGH')
        per_organ[code] = len(docs) - n0
        log('  organ', code, 'docs', per_organ[code])
    ids = collections.Counter(r['doc_id'] for r in recs)
    if any(v > 1 for v in ids.values()): raise RuntimeError('duplicate doc_id within place')
    idx = url_index(all_keys)
    dups = [(r['source_url'], idx[r['source_url']]) for r in recs if r['source_url'] in idx]
    held = None
    if dups:   # do not stage a record whose source_url is staged under another KG place; keep it aside for review
        held = f'{FAILDIR}/rescrape_prefix_held_dups/{pk}.jsonl'; os.makedirs(os.path.dirname(held), exist_ok=True)
        du = {u for u, _ in dups}
        with open(held, 'w') as f:
            for r in recs:
                if r['source_url'] in du: f.write(json.dumps(dict(r, _dup_of_place=idx[r['source_url']]), ensure_ascii=False) + '\n')
        recs = [r for r in recs if r['source_url'] not in du]
    res = {'codes': codes, 'organs': names, 'place_id': qid, 'docs_by_organ': per_organ, 'docs': len(docs), 'records': len(recs),
           'ru': sum(r['language'] == 'ru' for r in recs), 'ky': sum(r['language'] == 'ky' for r in recs),
           'dropped_bad_auth': bad_auth, 'held_dup_source_url': len(dups), 'dup_places': sorted({p for _, p in dups})}
    if not recs:
        res['status'] = 'empty_not_staged'; return res   # never stage an empty .full (it would wipe the place)
    ts = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')
    final = f'{KGDIR}/{pk}.full.{ts}{tag}.jsonl'; tmp = f'{KGDIR}/.{pk}.full.{ts}{tag}.tmp.jsonl'
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        f.flush(); os.fsync(f.fileno())
    v = validate_file(tmp, expect_place_key=pk)
    if not v['ok'] or v['bad_rows'] or v['rows'] != len(recs) or list(v['place_ids']) != [qid]:
        bad = f'{FAILDIR}/rescrape_prefix_failed_{pk}.{ts}.jsonl'; os.rename(tmp, bad)
        res.update(status='validation_failed', err=str(v['errors'][:3]), kept=bad); return res
    os.rename(tmp, final)
    res.update(status='staged', file=os.path.basename(final), validated_rows=v['rows'], bad_rows=v['bad_rows'])
    return res

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--organs', required=True); ap.add_argument('--tag', default='rescrape')
    ap.add_argument('--passes', type=int, default=3); a = ap.parse_args()
    assert '.' not in a.tag and a.tag.isalnum()
    organs = [tuple(x.split('=', 1)) for x in a.organs.split(',')]
    lk = open(W + '/rescrape_prefix.lock', 'w')
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: log('another rescrape instance holds the lock; exiting'); return
    kg_cbd_full.call = gated_call   # recs_for resolves `call` from its module globals
    places = collections.OrderedDict()
    for c, q in organs: places.setdefault(q, []).append(c)
    all_keys = {place_key(q) for q in places}
    log('start', len(organs), 'organs', len(places), 'places', 'pid', os.getpid())
    for p in range(a.passes):
        done = {json.loads(l)['place_id'] for l in open(DONE)} if os.path.exists(DONE) else set()
        todo = [(q, cs) for q, cs in places.items() if q not in done]
        if not todo: break
        for q, cs in todo:
            if shutil.disk_usage('/workspace').free < 35e9: log('DISK LOW <35GB; stopping'); return
            if mem_mb() > 450: log('MEM HIGH; stopping'); return
            log('place', q, 'organs', cs)
            try: res = do_place(q, cs, all_keys, a.tag)
            except Exception as e:
                log('ERROR', q, cs, f'{type(e).__name__}: {e}'[:300]); continue
            log(json.dumps(res, ensure_ascii=False))
            if res['status'] in ('staged', 'empty_not_staged'):
                with open(DONE, 'a') as f: f.write(json.dumps(dict(res, at=now()), ensure_ascii=False) + '\n')
        if p < a.passes - 1: time.sleep(300)
    done = {json.loads(l)['place_id'] for l in open(DONE)} if os.path.exists(DONE) else set()
    left = [q for q in places if q not in done]
    log('finished' if not left else f'incomplete: {left}', 'gate_waits', _gate['waits'])
if __name__ == '__main__': main()
