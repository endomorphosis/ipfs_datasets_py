"""Fill wikidata_id in codes/proposed/KG_aiyl_aimaks.csv for bodies the Normalizer listed as unresolved/ambiguous.
Source: SPARQL dump _kg/wd_aimak_all.csv (KG items whose ru/ky/en label or alias names an aiyl aimak / aiyl okmotu).
Strict: name stem equal (Kyrgyz letters folded); district must equal when WD has a district; result unique; if the WD item
has no district, the name stem must also be unique among all proposed bodies. Never overwrites an existing wikidata_id."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, sys, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
from kg_match import stem
W = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_kg'); P = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes/proposed/KG_aiyl_aimaks.csv'); X = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/')
def fold(s): return (s or '').lower().translate(str.maketrans('ңөүё', 'ноуе'))
STRIP = r'(?i)\b(айыл аймагы|айылдык аймагы|айылный аймак|айыльный аймак|аильный округ|айылный округ|айыл окмоту|сельская управа|aiyl aimagy?|ayil aymagy?|rural community)\b'
def nstem(name):
    n = re.sub(STRIP, '', fold(name)).strip(' ,-')
    n = re.sub(r'\s+айыл\s+аймак$', '', n).strip()
    return stem(n.replace(' ', '-')) if n else ''
def dstem(d):
    d = fold(d or '').strip()
    return stem(d.split()[0]) if d and 'район' in d else None
items = collections.defaultdict(lambda: {'n': set(), 'd': set(), 'nd': False})
for r in csv.DictReader(open(W + '/wd_aimak_all.csv')):
    q = r['i'].rsplit('/', 1)[1]; it = items[q]; it['n'].add(nstem(r['l']))
    ds = dstem(r['dl'])
    if ds: it['d'].add(ds)
    elif r['d']: it['nd'] = True
for it in items.values():
    if not it['d']: it['nd'] = True
targets = {r['cbd_issuing_body_id'] for f in ('kg_body_unresolved.csv', 'kg_body_ambiguous.csv') for r in csv.DictReader(open(X + f))}
merge = json.load(open(W + '/body_id_merge.json'))
targets |= {merge.get(t, t) for t in targets}
rows = list(csv.DictReader(open(P))); fn = list(rows[0].keys()) + (['wd_match_method'] if 'wd_match_method' not in rows[0] else [])
stem_count = collections.Counter(nstem(r['aiyl_aimak_ru'] or r['aiyl_aimak_ky']) for r in rows)
st = collections.Counter(); added = []
for r in rows:
    r.setdefault('wd_match_method', r.get('wd_match_method') or ('proposed_unique_name' if r['wikidata_id'] else ''))
    if r['cbd_issuing_body_id'] not in targets: continue
    st['target'] += 1
    if r['wikidata_id']: st['already_had_qid'] += 1; continue
    ns = nstem(r['aiyl_aimak_ru'] or r['aiyl_aimak_ky']); ds = dstem(r['parent_district_ru'])
    if not ns: st['no_name'] += 1; continue
    c = [q for q, it in items.items() if ns in it['n']]
    if ds: c = [q for q in c if ds in items[q]['d'] or (not items[q]['d'])]
    else: c = [q for q in c if True]
    if len(c) != 1: st['none' if not c else 'multi'] += 1; continue
    q = c[0]; it = items[q]
    if not it['d'] or not ds:
        if stem_count[ns] != 1: st['nodistrict_name_not_unique'] += 1; continue
        if ds is None and it['d'] and len([x for x in rows if nstem(x['aiyl_aimak_ru'] or x['aiyl_aimak_ky']) == ns]) != 1: st['multi'] += 1; continue
    r['wikidata_id'] = q; r['wd_candidates'] = '1'; r['wd_match_method'] = 'sparql_label_unique_20261016' + ('' if (ds and ds in it['d']) else '_no_district_check')
    st['added'] += 1; added.append((r['cbd_issuing_body_id'], r['aiyl_aimak_ru'] or r['aiyl_aimak_ky'], r['parent_district_ru'], q))
with open(P, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fn); w.writeheader(); w.writerows(rows)
json.dump(added, open(W + '/wd_fill_added.json', 'w'), ensure_ascii=False, indent=0)
print(dict(st)); print('distinct QIDs added', len({a[3] for a in added}))
for a in added[:25]: print(a)
