"""ID regencies (Q3191695) + cities (Q3199141) from asia_latam/id/wd_P2588.csv, joined with candidate CSV URLs.
Writes staging/id_jdih/_state/places.jsonl with jdih host candidates."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, collections
import pandas as pd
rows = {}
for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/asia_latam/id/wd_P2588.csv'))):
    q = r['item'].rsplit('/', 1)[1]; inst = r['inst'].rsplit('/', 1)[1]
    if not re.fullmatch(r'\d{2}\.\d{2}', r['code']) or inst not in ('Q3191695', 'Q3199141'): continue
    rows.setdefault(q, dict(place_id='wd:' + q, qid=q, place_name=r['label_id'] or r['label_en'], kemendagri=r['code'],
                            admin_level='regency' if inst == 'Q3191695' else 'city', urls=[]))
c = pd.read_csv((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'), low_memory=False, usecols=['place_id','country_code','source_url','place_name','admin_level'])
c = c[c.country_code == 'ID']
for r in c.itertuples():
    if r.place_id in rows and isinstance(r.source_url, str): rows[r.place_id]['urls'].append(r.source_url)
def slug(n): return re.sub(r'[^a-z0-9]', '', n.lower().replace('kabupaten', '').replace('kota', '').replace('kepulauan', 'kep'))
for d in rows.values():
    s = slug(d['place_name']); sfx = 'kab' if d['admin_level'] == 'regency' else 'kota'
    hosts = []
    for u in d['urls']:
        h = re.sub(r'^(www|web|portal)\.', '', (re.match(r'https?://([^/:]+)', u) or [None, ''])[1].lower())
        if h.endswith('.go.id'): hosts.append('jdih.' + h)
    hosts += [f'jdih.{s}{sfx}.go.id', f'jdih.{s}.go.id', f'jdih.{sfx}{s}.go.id']
    d['jdih_hosts'] = list(dict.fromkeys(hosts))
with open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/id_jdih/_state/places.jsonl'), 'w') as f:
    for d in rows.values(): f.write(json.dumps(d, ensure_ascii=False) + '\n')
print(len(rows), collections.Counter(d['admin_level'] for d in rows.values()), 'with official url', sum(1 for d in rows.values() if d['urls']))
