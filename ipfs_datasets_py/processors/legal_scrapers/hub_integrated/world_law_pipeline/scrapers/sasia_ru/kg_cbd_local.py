"""Kyrgyzstan local acts (local keneshes / mayoralties) from cbd.minjust.gov.kg (Ministry of Justice central
database; robots: allow all). Uses the site's own public API (same host). 1 req/s. No proxies."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, re, json, time, html as H, datetime, argparse, collections, shutil, requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from schema import validate_record, validate_file, place_key
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
API = 'https://cbd.minjust.gov.kg/api/v1'; B = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); OUT = B + '/KG'; W = B + '/_kg'
S = requests.Session(); S.trust_env = False; S.headers['User-Agent'] = 'world-law-research-bot/1.0 (municipal law archive research)'
last = [0]
def call(method, path, **kw):
    w = last[0] + 1.0 - time.time()
    if w > 0: time.sleep(w)
    for a in range(4):
        try:
            r = S.request(method, API + path, timeout=60, **kw); last[0] = time.time()
            if r.status_code == 200: return r.json()
            if r.status_code in (400, 404): return None
        except Exception: last[0] = time.time()
        time.sleep(5 * (a + 1))
    return None
def strip(h):
    h = re.sub(r'(?is)<(style|script)[^>]*>.*?</\1>', ' ', h or '')
    h = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>', '\n', h)
    t = H.unescape(re.sub(r'<[^>]+>', ' ', h)); t = re.sub(r'[ \t\xa0]+', ' ', t)
    return re.sub(r'\n\s*\n+', '\n\n', t).strip()
def d10(s): return s[:10] if s and not s.startswith('0001') else None
def dtype(v):
    v = (v or '').lower()
    return 'ordinance' if re.search(r'постановлен|решени|токтом|чечим', v) else 'decision' if re.search(r'распоряж|буйрук', v) else 'regulation'
def run_place(qid, organs, cap):
    pk = place_key(qid); recs = []; seen = set(); listed = 0; nolang = 0
    for o in organs:
        pg = 1
        while len(seen) < cap:
            d = call('POST', f'/GetDocuments?pageNumber={pg}&pageSize=100', json={'authoritiesId': o['code'], 'includeInvalid': True})
            if not d or not d.get('data'): break
            listed = max(listed, 0) + len(d['data'])
            for x in d['data']:
                if x['documentCode'] in seen or len(seen) >= cap: continue
                seen.add(x['documentCode'])
                doc = call('GET', f'/GetDocument?DocumentCode={x["documentCode"]}')
                if not doc or not doc.get('editions'): continue
                ed = doc['editions'][-1]
                rec = None
                for lang, fld, nm in (('ru', 'contentRu', 'nameRus'), ('ky', 'contentKg', 'nameKyr')):
                    e = call('GET', f'/GetEdition?editionId={ed["id"]}&lang={"ru" if lang == "ru" else "kg"}')
                    html = (e or {}).get('contentRu') or (e or {}).get(fld) or ''  # API returns requested-language text in contentRu
                    text = strip(html)
                    if len(text) < 200: continue
                    title = re.sub(r'\s+', ' ', doc.get(nm) or x.get('nameRu' if lang == 'ru' else 'nameKg') or '').strip()
                    r = {'place_id': qid, 'country_code': 'KG', 'doc_id': f'cbdkg:{x["documentCode"]}' + ('' if lang == 'ru' else ':ky'),
                         'source_platform': 'cbd_minjust_kg', 'source_url': f'https://cbd.minjust.gov.kg/{x["documentCode"]}/edition/{ed["id"]}/{"ru" if lang == "ru" else "kg"}',
                         'doc_type': dtype((doc.get('refTypeId') or {}).get('nameRus')), 'language': lang, 'content_format': 'html', 'html': html, 'text': text,
                         'title_native': title[:1000], 'number': doc.get('number'), 'adopted_date': d10(doc.get('dateAdopted')), 'published_date': d10(doc.get('datePublication')),
                         'in_force': {'Действует': True, 'Утратил силу': False}.get((doc.get('status') or {}).get('nameRus')), 'consolidated': len(doc['editions']) > 1,
                         'retrieved_at': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'), 'source_official': True,
                         'source_org': 'Министерство юстиции Кыргызской Республики (ЦБД НПА)', 'source_policy': 'robots_allowed_rfc9309',
                         'issuing_body': (doc.get('authoritiesId') or {}).get('nameRus'), 'registration_number': doc.get('numberRegistration'),
                         'edition_id': ed['id'], 'place_name': o.get('place_ru'), 'qid': qid[3:]}
                    if validate_record(r): print('INVALID', r['doc_id'], validate_record(r), flush=True); continue
                    recs.append(r)
                if not any(r['doc_id'].split(':')[1] == x['documentCode'] for r in recs): nolang += 1
            if pg * 100 >= d.get('totalResultsCount', 0): break
            pg += 1
    out = None
    if recs:
        ts = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ'); os.makedirs(OUT, exist_ok=True)
        fin = f'{OUT}/{pk}.cbdkg{ts}.jsonl'; tmp = f'{OUT}/.tmp.{pk}.cbdkg{ts}.jsonl'
        with open(tmp, 'w') as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
            f.flush(); os.fsync(f.fileno())
        v = validate_file(tmp, expect_place_key=pk)
        if not v['ok'] or v['bad_rows']: os.remove(tmp); return {'place_key': pk, 'status': 'validation_failed', 'err': str(v['errors'][:2])}
        os.rename(tmp, fin); out = fin
    return {'place_key': pk, 'status': 'ok', 'organs': len(organs), 'listed': listed, 'docs': len(seen), 'records': len(recs), 'ru': sum(r['language'] == 'ru' for r in recs), 'ky': sum(r['language'] == 'ky' for r in recs), 'no_text': nolang, 'file': out}
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--map', default=W + '/kg_organ_map.jsonl'); ap.add_argument('--places', type=int, default=20); ap.add_argument('--cap', type=int, default=60)
    ap.add_argument('--done', default=W + '/kg_done.jsonl'); a = ap.parse_args()
    by = collections.defaultdict(list)
    for l in open(a.map): x = json.loads(l); by[x['qid']].append(x)
    done = {json.loads(l)['place_key'] for l in open(a.done)} if os.path.exists(a.done) else set()
    for qid in sorted(by)[:a.places]:
        if place_key(qid) in done: continue
        if shutil.disk_usage('/workspace').free < 35e9: print('DISK LOW', flush=True); break
        try: res = run_place(qid, by[qid], a.cap)
        except Exception as e: res = {'place_key': place_key(qid), 'status': 'error', 'error': f'{type(e).__name__}: {e}'[:200]}
        print(datetime.datetime.now().strftime('%H:%M:%S'), json.dumps(res, ensure_ascii=False), flush=True)
        with open(a.done, 'a') as f: f.write(json.dumps(res, ensure_ascii=False) + '\n')
    print('finished', flush=True)
