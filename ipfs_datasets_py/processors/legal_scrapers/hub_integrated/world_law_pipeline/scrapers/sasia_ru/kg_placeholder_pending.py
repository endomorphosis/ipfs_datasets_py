"""Scrape acts filed under cbd placeholder body ids (_kg/body_id_drop.json) into _kg/pending/_placeholder__<safe>.jsonl,
tagged cbd_placeholder_body=true, for later attribution from each act's header. Never staged. Runs alongside
kg_cbd_full.py, so it adds 1 s extra per request (~0.5 req/s from this job). Resume: _kg/placeholder_done.jsonl."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, re, time, hashlib, datetime
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
import kg_cbd_local as L
from kg_cbd_full import recs_for
_call = L.call
def slow(*a, **k): time.sleep(1.0); return _call(*a, **k)
L.call = slow
import kg_cbd_full; kg_cbd_full.call = slow
W = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_kg'); PEND = W + '/pending'; DONE = W + '/placeholder_done.jsonl'
drop = json.load(open(W + '/body_id_drop.json'))
done = {json.loads(l)['code'] for l in open(DONE)} if os.path.exists(DONE) else set()
os.makedirs(PEND, exist_ok=True)
for code, info in drop.items():
    if not code or code in done: continue
    safe = re.sub(r'[^A-Za-z0-9_-]', '', code)[:40] + '_' + hashlib.sha1(code.encode()).hexdigest()[:8]
    fin = f'{PEND}/_placeholder__{safe}.jsonl'; tmp = fin + '.tmp'; n = 0
    with open(tmp, 'w') as f:
        for r in recs_for({'code': code, 'name': info['name']}, None):
            r['cbd_placeholder_body'] = True; r['issuing_body'] = None; r['cbd_body_name_in_classifier'] = info['name']
            f.write(json.dumps(r, ensure_ascii=False) + '\n'); n += 1
    os.rename(tmp, fin) if n else os.remove(tmp)
    res = {'code': code, 'file': fin if n else None, 'records': n, 'cbd_docs': info.get('cbd_docs')}
    print(datetime.datetime.now().strftime('%H:%M:%S'), json.dumps(res, ensure_ascii=False), flush=True)
    with open(DONE, 'a') as f: f.write(json.dumps(res, ensure_ascii=False) + '\n')
print('finished', flush=True)
