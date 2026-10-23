"""Re-match KG pending docs (_kg/pending/<cbd_body_id>.jsonl) using the Normalizer's codes_ext/kg_body_to_place.csv.
Strict: body id must map to exactly one wd:Q place. Stages via StagedWriter (validated); records done bodies in _kg/rematched.jsonl."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, os, sys, glob, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from archive.staging import StagedWriter
CSV = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_body_to_place.csv'); B = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); W = B + '/_kg'; DONE = W + '/rematched.jsonl'
rows = list(csv.DictReader(open(CSV)))
cols = rows[0].keys() if rows else []
bc = next((c for c in cols if c in ('cbd_issuing_body_id', 'body_id', 'cbd_body_id', 'issuing_body_id')), None)
pc = next((c for c in cols if c in ('place_id', 'wikidata_id', 'qid', 'wd')), None)
if not bc or not pc: sys.exit(f'unknown columns {list(cols)}')
m = collections.defaultdict(set)
for r in rows:
    p = (r[pc] or '').strip()
    if not p: continue
    if p.startswith('Q'): p = 'wd:' + p
    if not p.startswith(('wd:Q', 'gnis:', 'iso:', 'KG-kg_cbd:')): continue
    m[r[bc].strip()].add(p)
done = {json.loads(l)['code'] for l in open(DONE)} if os.path.exists(DONE) else set()
# KG-kg_cbd ids accepted by the Normalizer (place_codes kg_cbd_body): bodies without a wd map stage under them
_KD = W + '/kgcbd_staged.jsonl'
if os.path.exists(_KD): done |= {json.loads(l)['code'] for l in open(_KD) if l.strip()}

def _dotted_alias(live):
    # dotted CBD organ ids -> live dashed KG-kg_cbd ids (codes/proposed/KG_aiyl_aimaks_dotted.csv); typo variants are not listed
    import csv as _c
    return {r['cbd_organ_id'].strip(): r['proposed_place_id'].strip() for r in _c.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes/proposed/KG_aiyl_aimaks_dotted.csv')))
            if r['proposed_place_id'].strip() in live}
_live = {r['place_id'] for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/codes/place_codes.csv'))) if r['code_system'] == 'kg_cbd_body'}
for _d, _p in _dotted_alias(_live).items():
    if _d not in m: m[_d].add(_p)
AMB = {r['cbd_issuing_body_id'].strip() for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_body_ambiguous.csv')))}
for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/codes/place_codes.csv'))):
    if r['code_system'] == 'kg_cbd_body' and r['place_id'].startswith('KG-kg_cbd:') and r['code'].strip() not in m and r['code'].strip() not in AMB:
        m[r['code'].strip()].add(r['place_id'])
st = collections.Counter()
for f in sorted(glob.glob(W + '/pending/*.jsonl')):
    fid = os.path.basename(f)[:-6]; code = fid.split('__')[0]
    if fid in done or fid.startswith('_placeholder'): continue
    ps = m.get(code, set())
    if len(ps) != 1: st['no_map' if not ps else 'ambiguous'] += 1; continue
    q = next(iter(ps)); w = StagedWriter(B, 'KG', q, batch_prefix='cbdkgpend', chunk=200); n = rej = 0
    for l in open(f):
        r = json.loads(l); r['place_id'] = q
        if r.get('cbd_placeholder_body'): continue
        r.setdefault('cbd_issuing_body_id', code)
        if q.startswith('wd:'): r['qid'] = q[3:]
        else: r.pop('qid', None)
        r['place_match'] = 'normalizer_kg_body_to_place' if q.startswith('wd:') else 'normalizer_kg_cbd_body'
        if w.add(r): rej += 1
        else: n += 1
    w.flush(); st['staged_bodies'] += 1; st['docs'] += n; st['rejected'] += rej
    with open(DONE, 'a') as o: o.write(json.dumps({'code': fid, 'canonical': code, 'place_id': q, 'staged': n, 'rejected': rej, 'files': w.written}) + '\n')
print(dict(st), flush=True)
