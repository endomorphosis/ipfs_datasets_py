# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, random, re, sys, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.'); import phnet
P = [json.loads(l) for l in open(__import__('os').environ.get('PH_PLACES','/workspace/world_law/staging/ph/_state/places.jsonl'))]
P = [p for p in P if p['urls']]
n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
sample = random.Random(20261014).sample(P, n) if n < len(P) else P

def classify(html, hdr, final):
    h = html.lower(); g = []
    if 'wp-content' in h or 'wp-includes' in h or 'wp-json' in h: g.append('wordpress')
    if '/media/jui/' in h or 'joomla' in h or 'com_content' in h or '/templates/' in h and 'option=com_' in h: g.append('joomla')
    if 'drupal' in h or '/sites/default/files' in h: g.append('drupal')
    if 'gwt' in h or 'govph' in h or 'gwhs' in h or 'gov.ph/gwt' in h or 'gwt-' in h or 'id="gwt' in h: g.append('govph_gwt')
    if 'wix.com' in h or 'wixstatic' in h: g.append('wix')
    if 'blogger' in h or 'blogspot' in h: g.append('blogger')
    if 'facebook.com' in final: g.append('facebook')
    if '__next' in h or '_next/static' in h: g.append('nextjs')
    if 'laravel' in h or 'xsrf-token' in str(hdr).lower(): g.append('laravel')
    m = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', html, re.I)
    gen = m.group(1)[:40] if m else ''
    prim = next((x for x in ['wordpress','joomla','drupal','wix','blogger','nextjs','laravel','facebook'] if x in g), None)
    if not prim: prim = 'govph_gwt' if 'govph_gwt' in g else ('custom_static' if len(h) < 30000 else 'custom')
    return prim, g, gen

def one(p):
    url = p['urls'][0]
    r, pol = phnet.resolve_base(url)
    if r is None: return dict(place_id=p['place_id'], name=p['place_name'], url=url, cls='robots_disallowed' if pol=='robots_disallowed' else 'dead_unreachable', why=pol)
    if r.status_code >= 400: return dict(place_id=p['place_id'], name=p['place_name'], url=url, cls='dead_unreachable', why=f'http{r.status_code}')
    txt = r.text[:400000]
    if len(txt) < 500 or 'domain for sale' in txt.lower() or 'parked' in txt.lower()[:3000]:
        return dict(place_id=p['place_id'], name=p['place_name'], url=url, cls='parked_empty', why=len(txt))
    prim, g, gen = classify(txt, r.headers, r.url)
    return dict(place_id=p['place_id'], name=p['place_name'], url=url, final=r.url, cls=prim, sig=g, gen=gen, server=r.headers.get('server',''), policy=pol)

with ThreadPoolExecutor(16) as ex: res = list(ex.map(one, sample))
out = __import__('os').environ.get('PH_FP_OUT', '/workspace/world_law/staging/ph/_state/fingerprint_%d.jsonl' % n)
with open(out, 'w') as f:
    for x in res: f.write(json.dumps(x, ensure_ascii=False) + '\n')
c = collections.Counter(x['cls'] for x in res)
for k, v in c.most_common(): print(f"{k:20s} {v:4d} {100*v/len(res):5.1f}%")
print(collections.Counter(x.get('gen','') for x in res).most_common(10))
