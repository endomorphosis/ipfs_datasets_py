"""Write staging/ph/_state/wayback_deferred.jsonl: dead PH sites (munis/provinces + cities) as deferred Wayback items.
Fields follow asia_latam _archive_queue (country, source, host, place_id, block_reason, archive_queue, note)
plus national deferred_wayback.tsv (deferred_at, place_id) and url/place_name for the archive worker. Idempotent."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, datetime
from urllib.parse import urlparse
ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/ph/_state')
now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
rows, seen = [], set()
for places, done, src in (('places.jsonl', 'done.jsonl', 'ph_lgu'), ('cities.jsonl', 'done_cities.jsonl', 'ph_lgu_city')):
    if not os.path.exists(f'{ST}/{done}'): continue
    P = {json.loads(l)['place_id']: json.loads(l) for l in open(f'{ST}/{places}')}
    for l in open(f'{ST}/{done}'):
        d = json.loads(l)
        if d['status'] != 'unreachable' or d['place_id'] in seen: continue
        seen.add(d['place_id']); p = P[d['place_id']]
        for u in p['urls'][:1]:
            rows.append(dict(deferred_at=now, country='PH', source=src, host=urlparse(u).netloc.lower(), place_id=d['place_id'],
                             place_name=p.get('place_name'), admin_level=p.get('admin_level'), url=u,
                             block_reason=d.get('why'), archive_queue='wayback_deferred', status='deferred',
                             note='live site unreachable from box; try Wayback/CC captures of homepage + ordinance/resolution/EO PDFs'))
with open(ST + '/wayback_deferred.jsonl.tmp', 'w') as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
os.rename(ST + '/wayback_deferred.jsonl.tmp', ST + '/wayback_deferred.jsonl')
import collections; print(len(rows), collections.Counter(r['source'] for r in rows), collections.Counter(r['block_reason'] for r in rows))
