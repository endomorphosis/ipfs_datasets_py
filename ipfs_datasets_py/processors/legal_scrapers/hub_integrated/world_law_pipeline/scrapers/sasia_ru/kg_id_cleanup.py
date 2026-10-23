"""Clean KG body ids flagged by the Normalizer (codes_ext/kg_aiyl_aimaks_flags.csv).
typo id -> canonical id merged only if cbd's own classifier names for BOTH ids parse to the same aiyl aimak
(same name stem; districts equal when both given). Placeholders (nonstandard ids without a canonical twin) are dropped
from the proposed CSV and from scraping; their cbd doc counts are recorded so nothing is lost silently.
Writes _kg/body_id_merge.json, _kg/body_id_drop.json, _kg/id_cleanup_report.json and rewrites codes/proposed/KG_aiyl_aimaks.csv (backup kept)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, sys, shutil, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
from kg_match import stem
from kg_aimak_propose import parse
from kg_cbd_local import call
W = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_kg'); P = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes/proposed/KG_aiyl_aimaks.csv')
F = list(csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_aiyl_aimaks_flags.csv'))))
names = {o['code']: o['name'] for o in json.load(open(W + '/kg_local_organs.json'))}
STD = re.compile(r'[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9.]+')
def key(n):
    p = parse(n or '')
    return (stem(p[1]), stem(p[2]) if p[2] else None) if p else None
def ndocs(code):
    d = call('POST', '/GetDocuments?pageNumber=1&pageSize=1', json={'authoritiesId': code, 'includeInvalid': True})
    return (d or {}).get('totalResultsCount')
merge, drop, rep = {}, {}, collections.Counter(); notes = []
for r in F:
    bid = r['cbd_issuing_body_id']
    cans = [m for m in re.findall(r'near_duplicate_body_id_of:([^;]*)', r['flags']) if m]
    if cans and bid and re.search(r'^[0-9a-f]{8}-|^[0-9a-f]{32}|^[0-9.]+$', bid):
        rep['typo_candidates'] += 1; ok = None
        for c in cans:
            if c not in names or bid not in names: continue
            a, b = key(names[bid]), key(names[c])
            if a and b and a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1]): ok = c
        if ok: merge[bid] = ok; rep['merged'] += 1; notes.append({'id': bid, 'canonical': ok, 'name': names[bid], 'canonical_name': names[ok]})
        else: rep['typo_not_confirmed'] += 1; notes.append({'id': bid, 'canonical': cans, 'name': names.get(bid), 'canonical_name': [names.get(c) for c in cans], 'result': 'not_same_body_kept'})
    elif not bid or not STD.fullmatch(bid):
        drop[bid] = {'name': r['cbd_issuing_body_name'], 'cbd_docs': ndocs(bid) if bid else None}; rep['placeholders_dropped'] += 1
json.dump(merge, open(W + '/body_id_merge.json', 'w'), ensure_ascii=False, indent=1)
json.dump(drop, open(W + '/body_id_drop.json', 'w'), ensure_ascii=False, indent=1)
json.dump({'counts': rep, 'typo_notes': notes}, open(W + '/id_cleanup_report.json', 'w'), ensure_ascii=False, indent=1)
import os
if not os.path.exists(P + '.bak_20261016_idcleanup'): shutil.copy(P, P + '.bak_20261016_idcleanup')
P_SRC = P + '.bak_20261016_idcleanup'
rows = list(csv.DictReader(open(P_SRC))); out = []; seen = set()
for r in rows:
    b = r['cbd_issuing_body_id']
    if b in drop: continue
    if b in merge:
        r['cbd_issuing_body_id'] = merge[b]; r['merged_from_body_ids'] = b
        if merge[b] in seen: continue
    r.setdefault('merged_from_body_ids', '')
    seen.add(r['cbd_issuing_body_id']); out.append(r)
# fold merged_from into the canonical row
mf = collections.defaultdict(list)
for a, b in merge.items(): mf[b].append(a)
for r in out: r['merged_from_body_ids'] = '|'.join(mf.get(r['cbd_issuing_body_id'], []))
fn = [k for k in rows[0].keys() if k != 'merged_from_body_ids'] + ['merged_from_body_ids']
with open(P, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fn); w.writeheader(); w.writerows(out)
print(dict(rep), 'csv rows', len(rows), '->', len(out), 'placeholder docs', {k: v['cbd_docs'] for k, v in drop.items()})
