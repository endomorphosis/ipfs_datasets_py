"""Uzbekistan local acts (district/city khokims + Kengashes of people's deputies) from lex.uz.
Listing: server-rendered /ru/search/loc?lang=1&body_id=<organ>[&from=dd.mm.yyyy&to=dd.mm.yyyy] (20 rows/page, no paging ->
date windows are bisected until <=20). Organ tree: the site's own /ru/ajax_methods_url?action=GetOrganTree (same host).
robots.txt: 404 -> allow all (RFC 9309). 1 req/s, no proxies. Oblast-level / Tashkent-city-level bodies are adm1 -> skipped.
Mapping: strict unique Wikidata match (district/city root + same ISO 3166-2 region); unmatched -> _uz/unmatched.jsonl."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, re, json, time, html as H, datetime, argparse, csv, collections, shutil, subprocess, tempfile, zipfile, io, resource
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from archive.staging import StagedWriter
from schema import place_key
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
import requests
BASE = 'https://lex.uz'; ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); W = ST + '/_uz'
S = requests.Session(); S.trust_env = False; S.headers['User-Agent'] = 'world-law-research-bot/1.0 (municipal law archive research)'
last = [0.0]
def get(url, binary=False):
    for a in range(4):
        w = last[0] + 1.0 - time.time()
        if w > 0: time.sleep(w)
        try:
            r = S.get(url, timeout=90); last[0] = time.time()
            if r.status_code == 200 and '/Pages/404' not in r.url: return r.content if binary else r.text
            if r.status_code in (404, 403) or '/Pages/404' in r.url: return None
        except Exception: last[0] = time.time()
        time.sleep(5 * (a + 1))
    return None
REG = {'Г. ТАШКЕНТ': 'UZ-TK', 'ТАШКЕНТСКАЯ': 'UZ-TO', 'КАШКАДАРЬИН': 'UZ-QA', 'САМАРКАНД': 'UZ-SA', 'СУРХАНДАРЬИН': 'UZ-SU', 'ДЖИЗАК': 'UZ-JI',
       'ХОРЕЗМ': 'UZ-XO', 'АНДИЖАН': 'UZ-AN', 'ФЕРГАН': 'UZ-FA', 'СЫРДАРЬИН': 'UZ-SI', 'НАВОИ': 'UZ-NW', 'БУХАР': 'UZ-BU', 'НАМАНГАН': 'UZ-NG', 'КАРАКАЛПАК': 'UZ-QR'}
def region(path):
    for p in path:
        for k, v in REG.items():
            if k in p.upper(): return v
    return None
def roots(w):
    w = w.replace('ё', 'е'); out = set()
    for suf, rep in (('ского', ''), ('цкого', 'ц'), ('ский', ''), ('цкий', 'ц'), ('инского', 'и'), ('инский', 'и'), ('нского', ''), ('нский', ''), ('ской', ''), ('ий', ''), ('ого', '')):
        if w.endswith(suf) and len(w) - len(suf) >= 3: out.add((w[:-len(suf)] + rep).lower())
    return out
def city_forms(w):
    w = w.replace('ё', 'е').lower(); f = {w}
    if w.endswith(('а', 'я', 'ы', 'и')): f.add(w[:-1])
    if w.endswith('я'): f.add(w[:-1] + 'ь')
    return f | roots(w)
def fold(w):
    w = w.lower().replace('ё', 'е').replace('ъ', '').replace('ь', '').replace('-', '').replace(' ', '')
    for a, b in (('дж', 'ж'), ('ы', 'и'), ('э', 'е'), ('ю', 'у'), ('й', 'и'), ('х', 'к'), ('ҳ', 'к'), ('қ', 'к'), ('ғ', 'г'), ('ў', 'у'), ('о', 'а')): w = w.replace(a, b)
    return re.sub(r'(.)\1+', r'\1', w)
def classify(name):
    n = re.sub(r'\s+', ' ', name.replace('\u200e', '')).strip()
    if re.search(r'(?i)област|Жокаргы|Республики Каракалпакстан$', n): return None, None
    if re.search(r'(?i)город\w*\s+Ташкент|Ташкентский городской', n): return None, None
    m = re.search(r'([А-ЯЁ][\w\-]+)\s+район', n) or re.search(r'район\w*\s+([А-ЯЁ][\w\-]+)', n)
    if m: return 'district', m.group(1)
    m = re.search(r'(?i)(?:город[а]?\.?|г\.)\s+([А-ЯЁ][\w\-]+)', n) or re.search(r'([А-ЯЁ][\w\-]+)\s+городск', n)
    if m: return 'city', m.group(1)
    return None, None
def build_map():
    O = json.load(open(W + '/uz_organs.json'))
    WD = collections.defaultdict(lambda: {'types': set()})
    for r in csv.DictReader(open(W + '/uz_wd.csv')):
        q = 'wd:' + r['i'].rsplit('/', 1)[1]; x = WD[q]; x.update(q=q, ru=r['ru'], uz=r['uz'], iso=r['iso']); x['types'].add(r['t'].rsplit('/', 1)[1])
    dist = [x for x in WD.values() if x['ru'].endswith(' район')]; city = [x for x in WD.values() if x['types'] & {'Q515', 'Q1549591'}]
    out, un, st = [], [], collections.Counter()
    for o in O:
        if o['lvl'] < 3 or not re.search(r'(?i)хоким|кенгаш', o['name']): continue
        kind, w = classify(o['name']); iso = region(o['path'])
        if not kind: st['skip_adm1_or_unparsed'] += 1; continue
        if kind == 'district':
            R = roots(w) or {w.lower()}
            c = [x for x in dist if x['iso'] == iso and roots(x['ru'].split()[0]) & R]
        else:
            F = city_forms(w); c = [x for x in city if x['iso'] == iso and (x['ru'].lower() in F or roots(x['ru']) & F)]
        if not c and kind == 'district':
            FR = {fold(x) for x in R}
            c = [x for x in dist if x['iso'] == iso and {fold(y) for y in roots(x['ru'].split()[0])} & FR]
            if not c:
                m2 = re.search(r'(?<!Хоким )\b([А-ЯЁ][\w]+)[\s\-]' + re.escape(w) + r'\s+район', re.sub(r'\s+', ' ', o['name']))
                if m2: FR = {fold(m2.group(1) + x) for x in R}; c = [x for x in dist if x['iso'] == iso and {fold(y) for y in roots(x['ru'].split()[0])} & FR]
            if len(c) == 1: kind = 'district_fold'
        if len(c) == 1: out.append(dict(organ=o['name'], body_id=o['id'], qid=c[0]['q'], place_ru=c[0]['ru'], kind=kind, iso=iso)); st[kind + '_ok'] += 1
        else: un.append(dict(organ=o['name'], body_id=o['id'], kind=kind, iso=iso, n_candidates=len(c))); st[kind + ('_multi' if c else '_none')] += 1
    with open(W + '/uz_organ_map.jsonl', 'w') as f:
        for x in out: f.write(json.dumps(x, ensure_ascii=False) + '\n')
    with open(W + '/unmatched.jsonl', 'w') as f:
        for x in un: f.write(json.dumps(x, ensure_ascii=False) + '\n')
    print(dict(st), 'places', len({x['qid'] for x in out}), flush=True)
def fmt(d): return d.strftime('%d.%m.%Y')
def listing(body, a=None, b=None, depth=0):
    q = f'{BASE}/ru/search/loc?lang=1&body_id={body}' + (f'&from={fmt(a)}&to={fmt(b)}' if a else '')
    s = get(q) or ''
    m = re.search(r'найдено (\d+)', s); n = int(m.group(1)) if m else 0
    if n > 20 and depth < 16:
        a = a or datetime.date(1991, 1, 1); b = b or datetime.date.today()
        if a < b:
            mid = a + (b - a) // 2
            return listing(body, a, mid, depth + 1) + listing(body, mid + datetime.timedelta(days=1), b, depth + 1)
    rows = []
    for mm in re.finditer(r'href="/ru/docs/(\d+)"[^>]*>(.*?)</a>(.*?)(?=href="/ru/docs/\d+"[^>]*>[^<]{5}|$)', s, re.S):
        title = re.sub(r'\s+', ' ', H.unescape(re.sub('<[^>]+>', ' ', mm.group(2)))).strip()
        if not title: continue
        info = re.sub(r'\s+', ' ', H.unescape(re.sub('<[^>]+>', ' ', mm.group(3)[:3000]))).strip()
        rows.append({'id': mm.group(1), 'title': title, 'info': info[:400]})
    if n > 20 and len(rows) >= 20: print('WARN window still >20', body, a, b, n, flush=True)
    return rows
UI = re.compile(r'(?s)<span onclick="lx_[^"]*"[^>]*>.*?</span>|<img[^>]*>')
def body_html(s):
    i = s.find('id="divCont"')
    if i < 0: return '', ''
    seg = s[s.rfind('<div', 0, i):]
    j = seg.find('<div class="docBody__content') if False else -1
    end = re.search(r'(?s)<footer|class="footer|id="modal', seg); seg = seg[:end.start()] if end else seg
    seg = UI.sub('', seg)
    t = re.sub(r'[ \t\xa0]+', ' ', H.unescape(re.sub(r'(?s)<script.*?</script>|<style.*?</style>', '', re.sub(r'(?i)</div>|<br\s*/?>|</p>', '\n', seg))))
    t = re.sub(r'<[^>]+>', ' ', t); t = re.sub(r'\n\s*\n+', '\n', re.sub(r'[ ]+', ' ', t)).strip()
    t = re.sub(r'^id="divCont"[^>]*>\s*', '', t)
    return seg, t
def lang_of(t):
    lat = len(re.findall(r'[A-Za-z]', t)); cyr = len(re.findall(r'[А-Яа-яЁёЎўҚқҒғҲҳ]', t)); uzc = len(re.findall(r'[ЎўҚқҒғҲҳ]', t))
    if lat > cyr: return 'uz-Latn'
    return 'uz-Cyrl' if uzc >= 3 else 'ru'
def pdf_text(zid):
    b = get(f'{BASE}/ru/files/{zid}.zip', binary=True)
    if not b or len(b) > 60e6: return ''
    out = []
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        for nm in z.namelist():
            if not nm.lower().endswith('.pdf'): continue
            with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
                f.write(z.read(nm)); f.flush()
                r = subprocess.run(['pdftotext', '-layout', f.name, '-'], capture_output=True, timeout=120)
                out.append(r.stdout.decode('utf-8', 'replace'))
    except Exception: return ''
    return '\n'.join(out).strip()
def fetch_doc(row, m):
    s = get(f'{BASE}/ru/docs/{row["id"]}')
    if not s: return None, 'fetch_fail'
    i = s.find('оригинального текста'); oid = row['id']
    if i > 0:
        mm = re.search(r'href="/ru/docs/(\d+)"', s[i - 600:i + 600])
        if mm and mm.group(1) != row['id']:
            s2 = get(f'{BASE}/ru/docs/{mm.group(1)}')
            if s2: s, oid = s2, mm.group(1)
    seg, t = body_html(s)
    zips = re.findall(r'href="/ru/files/(\d+)\.zip"', seg)
    fmt_ = 'html'; text = t; html = seg
    body_len = len(re.sub(r'\[ (ОКОЗ|ТСЗ|OKOZ|TSZ)[^\]]*\]', '', t))
    if zips and body_len < 1500:
        pt = '\n'.join(filter(None, (pdf_text(z) for z in zips[:3])))
        if len(pt) < 200: return None, 'pdf_no_text'
        text, html, fmt_ = pt, None, 'pdf_text'
    elif body_len < 300: return None, 'no_text'
    num = re.search(r'№\s*([\w\-/\.]+)', row['info']); dt = re.search(r'от (\d\d)\.(\d\d)\.(\d{4})', row['info'])
    r = {'place_id': m['qid'], 'country_code': 'UZ', 'doc_id': f'lexuz:{oid}', 'source_platform': 'lex_uz', 'source_url': f'{BASE}/ru/docs/{oid}',
         'doc_type': 'decision', 'language': lang_of(text), 'content_format': fmt_, 'text': text, 'title_native': row['title'][:1000],
         'number': num.group(1) if num else None, 'adopted_date': f'{dt.group(3)}-{dt.group(2)}-{dt.group(1)}' if dt else None,
         'consolidated': False, 'in_force': None, 'retrieved_at': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
         'source_official': True, 'source_org': 'Национальная база данных законодательства Lex.uz (Адолат, Минюст РУз)', 'source_policy': 'robots_404_allow_rfc9309',
         'issuing_body': m['organ'], 'lexuz_body_id': m['body_id'], 'lexuz_ru_listing_id': row['id'], 'listing_info': row['info'], 'qid': m['qid'][3:], 'place_name': m['place_ru']}
    if html: r['html'] = html
    return r, 'ok'
def run(a):
    by = collections.defaultdict(list)
    for l in open(W + '/uz_organ_map.jsonl'): x = json.loads(l); by[x['qid']].append(x)
    done = {json.loads(l)['place_key'] for l in open(a.done)} if os.path.exists(a.done) else set()
    qids = sorted(by)[:a.places] if a.places else sorted(by)
    for q in qids:
        pk = place_key(q)
        if pk in done: continue
        if shutil.disk_usage('/workspace').free < 35e9: print('DISK LOW', flush=True); return
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 450 * 1024: print('MEM HIGH', flush=True); return
        w = StagedWriter(ST, 'UZ', q, batch_prefix='lexuzloc', chunk=200); st = collections.Counter(); seen = set(); listed = 0
        try:
            for m in by[q]:
                rows = listing(m['body_id']); listed += len(rows)
                for row in rows:
                    if row['id'] in seen or len(seen) >= a.cap: continue
                    seen.add(row['id'])
                    r, why = fetch_doc(row, m); st[why] += 1
                    if r:
                        if any(x['doc_id'] == r['doc_id'] for x in w.buf): st['dup_orig'] += 1; continue
                        err = w.add(r)
                        if err: st['invalid'] += 1; print('INVALID', r['doc_id'], err, flush=True)
                        else: st[r['content_format']] += 1; st[r['language']] += 1
            w.flush(); res = {'place_key': pk, 'status': 'ok', 'organs': len(by[q]), 'listed': listed, 'staged': sum(1 for _ in w.written) and st['ok'] - st['dup_orig'] - st['invalid'], **st, 'files': w.written}
        except Exception as e:
            res = {'place_key': pk, 'status': 'error', 'error': f'{type(e).__name__}: {e}'[:200]}
        print(datetime.datetime.now().strftime('%H:%M:%S'), json.dumps(res, ensure_ascii=False), flush=True)
        with open(a.done, 'a') as f: f.write(json.dumps(res, ensure_ascii=False) + '\n')
    print('finished', flush=True)
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--map-only', action='store_true'); ap.add_argument('--places', type=int, default=20)
    ap.add_argument('--cap', type=int, default=60); ap.add_argument('--done', default=W + '/uz_done.jsonl'); a = ap.parse_args()
    if a.map_only: build_map()
    else: run(a)
