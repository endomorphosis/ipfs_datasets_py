"""Regenerate ocr_queue: HEAD-check direct PDFs (drop 404), split gdrive rows, look for direct-PDF alternatives
on the same LGU site (WP media search by number, then known direct links). Checkpoint: _state/_ocrfix_ckpt.jsonl"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, sys, collections
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phnet, ph_crawl as C
ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/ph/_state')
src = ST + '/ocr_queue.orig.jsonl'
if not os.path.exists(src): os.rename(ST + '/ocr_queue.jsonl', src)
Q = [json.loads(l) for l in open(src)]
done = {json.loads(l)['place_id']: json.loads(l) for l in open(ST + '/done.jsonl')}
ck = ST + '/_ocrfix_ckpt.jsonl'
seen = {}
if os.path.exists(ck):
    for l in open(ck): x = json.loads(l); seen[x['key']] = x
ckf = open(ck, 'a'); import threading; lk = threading.Lock()
def save(x):
    with lk: ckf.write(json.dumps(x, ensure_ascii=False) + '\n'); ckf.flush(); seen[x['key']] = x

def head(u):
    r, pol = phnet.get(u, timeout=30, allow_redirects=True) if False else (None, None)
    rb, pol = phnet.robots(u)
    if not rb.can_fetch(phnet.UA, u): return 'robots'
    phnet._wait(urlparse(u).netloc)
    try:
        r = phnet.S.head(u, timeout=30, verify=False, allow_redirects=True)
        if r.status_code in (403, 405, 501):  # some servers reject HEAD
            phnet._wait(urlparse(u).netloc)
            r = phnet.S.get(u, timeout=30, verify=False, stream=True); r.close()
        return r.status_code
    except Exception as e: return 'err:' + type(e).__name__

def numkey(t):
    n = C.parse_num(t or '')
    if not n:
        m = re.match(r'\s*((?:19|20)\d{2}-\d{1,4})\b', t or ''); n = m.group(1) if m else None
    if not n: return None
    m = re.search(r'No\.\s*(\S+)', n); core = (m.group(1) if m else n)
    return core if re.search(r'\d', core) and len(re.sub(r'\D', '', core)) >= 2 else None

def norm(s): return re.sub(r'[^0-9a-z]', '', s.lower())

def check_pdf(x):
    k = 'pdf|' + x['source_url']
    if k in seen: return
    st = head(x['source_url']); hu = None
    if st == 'robots' and x['source_url'].startswith('http://'):
        hu = 'https://' + x['source_url'][7:]; st2 = head(hu)
        if st2 != 'robots': st = st2
        else: hu = None
    save(dict(key=k, status=st, https_url=hu))

direct_by_place = collections.defaultdict(list)
for x in Q:
    if x['source_kind'] == 'pdf': direct_by_place[x['place_key']].append(x)

def alt_gdrive(x):
    k = 'gd|' + x['doc_id']
    if k in seen: return
    core = numkey(x['title']); res = dict(key=k, num=core, alt=None, how=None)
    if core:
        c = norm(core)
        # 1) known direct PDFs of this place
        for y in direct_by_place.get(x['place_key'], []):
            if c in norm(os.path.basename(urlparse(y['source_url']).path) + ' ' + y['title']):
                res.update(alt=y['source_url'], how='known_direct'); break
        d = done.get(x['place_key'], {})
        if not res['alt'] and d.get('template') == 'wordpress':
            r, _ = phnet.get(d['base'] + 'wp-json/wp/v2/media?per_page=20&search=' + quote(core), timeout=30)
            try:
                for m in (r.json() if r is not None and r.status_code == 200 else []):
                    u = m.get('source_url', '')
                    if u.lower().endswith('.pdf') and c in norm(os.path.basename(u) + ' ' + (m.get('title') or {}).get('rendered', '')):
                        res.update(alt=u, how='wp_media_search'); break
            except Exception: pass
    if res['alt'] and res['how'] != 'known_direct':
        st = head(res['alt']); res['alt_status'] = st
        if st != 200: res['alt'] = None
    save(res)

with ThreadPoolExecutor(12) as ex:
    list(ex.map(check_pdf, [x for x in Q if x['source_kind'] == 'pdf']))
    list(ex.map(alt_gdrive, [x for x in Q if x['source_kind'] == 'gdrive']))
main, gd = [], []; st = collections.Counter(); alts = collections.Counter(); urls = set()
for x in Q:
    if x['source_kind'] == 'pdf':
        s = seen['pdf|' + x['source_url']]['status']; st[str(s)] += 1
        if s == 404 or s == 410: continue
        hu = seen['pdf|' + x['source_url']].get('https_url')
        x = dict(x, head_status=s, **({'source_url': hu, 'original_http_url': x['source_url']} if hu else {}))
        if x['source_url'] not in urls: urls.add(x['source_url']); main.append(x)
    else:
        a = seen['gd|' + x['doc_id']]; gd.append(dict(x, num_key=a['num'], alt_url=a['alt'], alt_how=a['how']))
        alts[a['how'] or 'none'] += 1
        if a['alt'] and a['alt'] not in urls:
            urls.add(a['alt']); main.append(dict(x, source_url=a['alt'], source_kind='pdf', alt_for_gdrive=x['source_url'], alt_how=a['how']))
def w(p, rows):
    with open(p + '.tmp', 'w') as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.rename(p + '.tmp', p)
w(ST + '/ocr_queue.jsonl', main); w(ST + '/ocr_queue_gdrive_blocked.jsonl', gd)
print(json.dumps(dict(orig=len(Q), pdf_head=dict(st), gdrive=len(gd), gdrive_alt=dict(alts), main_queue=len(main)), indent=1))
