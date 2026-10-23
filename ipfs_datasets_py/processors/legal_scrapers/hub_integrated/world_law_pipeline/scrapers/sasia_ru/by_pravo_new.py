"""Belarus local acts (decisions of local Councils of Deputies = p0 D9…, executive committees = p0 R9…) from pravo.by.
Only server-rendered listing found: rolling 'Новые поступления' pages (official publication + National Register),
covering ~3-4 days. => forward harvester: run daily; resumable via _by/by_seen.jsonl. No backfill path (archive pages are
JS/form-driven; Wayback breaker open). robots.txt honoured via rfc9309 (only /bitrix/ & debug params disallowed).
Doc: card page /document/?guid=12551&p0=<id> -> born-digital PDF /upload/docs/op/<id>_<ts>.pdf -> pdftotext.
Mapping: strict unique Wikidata match: raion (national-unique raion names), selsovet (unique nationally, or unique within
the raion named in the act), city (oblast-subordinated cities only). Oblast-level and Minsk-city acts are adm1 -> skipped."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, re, json, time, html as H, datetime, argparse, csv, collections, shutil, subprocess, tempfile, resource
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline')); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/web'))
from archive.staging import StagedWriter
from schema import place_key
from rfc9309 import Robots
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
import requests
BASE = 'https://pravo.by'; ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); W = ST + '/_by'
UA = 'world-law-research-bot/1.0 (municipal law archive research)'
S = requests.Session(); S.trust_env = False; S.headers['User-Agent'] = UA
LISTS = ['/ofitsialnoe-opublikovanie/novye-postupleniya/', '/natsionalnyy-reestr/novye-postupleniya/']
last = [0.0]; RB = [None]
def get(path, binary=False):
    url = path if path.startswith('http') else BASE + path
    if not RB[0].can_fetch(UA, url): return None
    for a in range(4):
        w = last[0] + 2.0 - time.time()
        if w > 0: time.sleep(w)
        try:
            r = S.get(url, timeout=90, allow_redirects=False); last[0] = time.time()
            if r.status_code == 200: return r.content if binary else r.text
            if r.status_code in (301, 302, 403, 404): return None
        except Exception: last[0] = time.time()
        time.sleep(5 * (a + 1))
    return None
def norm(s): return re.sub(r'\s+', ' ', s.replace('ё', 'е')).strip()
def root(adj):
    a = adj.lower().replace('ё', 'е')
    for suf in ('ского', 'цкого', 'ский', 'цкий', 'ской', 'ского'):
        if a.endswith(suf): return a[:-len(suf)] + ('ц' if suf.startswith('ц') else '')
    return None
def load_places():
    rai, sel, city = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(set)
    name = {}
    for r in csv.DictReader(open(W + '/by_wd.csv')):
        q = 'wd:' + r['i'].rsplit('/', 1)[1]; t = r['t'].rsplit('/', 1)[1]; ru = norm(r['ru'])
        if ru.endswith(' район'): k = root(ru.split()[0]); k and rai[k].add(q); name[q] = ru
        elif t in ('Q515', 'Q1549591', 'Q3957', 'Q2514025', 'Q20009975') and r['iso'] != 'BY-HM': city[ru.lower()].add(q); name[q] = ru
    for r in csv.DictReader(open(W + '/by_wd2.csv')):
        q = 'wd:' + r['i'].rsplit('/', 1)[1]; ru = norm(r['ru'])
        if ru.endswith('сельсовет'):
            k = root(ru.split()[0]); dk = root(norm(r['dru']).split()[0])
            if k: sel[k].add((q, dk)); name[q] = ru
    return rai, sel, city, name
def match(body, P):
    rai, sel, city, name = P; b = norm(body)
    if re.search(r'(?i)областн|Минского городского', b): return None, 'adm1'
    m = re.search(r'([А-ЯЁ][\w\-]+)\s+сельского\s+(?:Совета|исполнительного)', b)
    if m:
        k = root(m.group(1)); md = re.search(r'([А-ЯЁ][\w\-]+)\s+района', b); dk = root(md.group(1)) if md else None
        c = {q for q, d in sel.get(k, ()) if not dk or d == dk}
        return (next(iter(c)), 'selsovet') if len(c) == 1 else (None, f'selsovet_{len(c)}')
    m = re.search(r'([А-ЯЁ][\w\-]+)\s+районного\s+(?:Совета|исполнительного)', b)
    if m:
        c = rai.get(root(m.group(1)) or '', set())
        return (next(iter(c)), 'raion') if len(c) == 1 else (None, f'raion_{len(c)}')
    m = re.search(r'([А-ЯЁ][\w\-]+)\s+городского\s+(?:Совета|исполнительного)', b)
    if m:
        k = root(m.group(1)) or ''
        c = set().union(*[v for nm, v in city.items() if k and nm.startswith(k) and len(nm) - len(k) <= 2] or [set()])
        return (next(iter(c)), 'city') if len(c) == 1 else (None, f'city_{len(c)}')
    return None, 'unparsed'
def listing():
    out = {}
    for L in LISTS:
        s = get(L) or ''
        for m in re.finditer(r'p0=([RD]9\d{2}[a-z]\d{7})', s):
            pid = m.group(1)
            if pid in out: continue
            seg = s[m.start() - 200:m.start() + 1500]
            t = norm(H.unescape(re.sub(r'<[^>]+>', ' ', seg[200:])))
            t = t.split('Дополнительная информация')[0]
            t = re.sub(r'^[^>]*>\s*', '', t)
            mm = re.match(r'(?:(\d+-\d+/\d+) \((\d\d\.\d\d\.\d{4})\) )?(.*?) (Решение .+)$', t)
            if not mm: continue
            out[pid] = {'p0': pid, 'reg': mm.group(1), 'pub': mm.group(2), 'title': mm.group(3).strip(), 'act': mm.group(4).strip()}
    return list(out.values())
def doc_text(pid):
    s = get(f'/document/?guid=12551&p0={pid}')
    if not s: return None, None
    pdfs = sorted(set(re.findall(r'href="(/upload/docs/op/[^"]+\.pdf)"', s)))
    txt = []
    for p in pdfs[:3]:
        b = get(p, binary=True)
        if not b or len(b) > 60e6: continue
        with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
            f.write(b); f.flush()
            r = subprocess.run(['pdftotext', '-layout', f.name, '-'], capture_output=True, timeout=120); txt.append(r.stdout.decode('utf-8', 'replace'))
    return '\n'.join(txt).strip(), (BASE + pdfs[0]) if pdfs else None
def iso_date(d): return f'{d[6:]}-{d[3:5]}-{d[:2]}' if d else None
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--places', type=int, default=20); ap.add_argument('--log-tag', default='run'); ap.add_argument('--collect-only', action='store_true'); a = ap.parse_args()
    rr = requests.get(BASE + '/robots.txt', timeout=30, headers={'User-Agent': UA})
    RB[0] = Robots(rr.text) if rr.status_code == 200 else Robots(allow_all=True) if 400 <= rr.status_code < 500 else Robots(disallow_all=True)
    P = load_places(); seenf = W + '/by_seen.jsonl'
    seen = {json.loads(l)['p0'] for l in open(seenf)} if os.path.exists(seenf) else set()
    if a.collect_only:
        idf = W + '/by_ids.jsonl'; have = {json.loads(l)['p0'] for l in open(idf)} if os.path.exists(idf) else set()
        new = [r for r in listing() if r['p0'] not in have]; st = collections.Counter()
        with open(idf, 'a') as f:
            for r in new:
                mb = re.search(r'Решение (.+?) от \d', r['act']); r['body'] = mb.group(1) if mb else r['act']
                q, why = match(r['body'], P); r.update(place_id=q, match=why, collected_at=datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    card_url=f'{BASE}/document/?guid=12551&p0={r["p0"]}'); st['mapped' if q else why] += 1
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(datetime.datetime.now().strftime('%F %T'), 'collected', len(new), dict(st), 'total', len(have) + len(new), flush=True); return
    rows = [r for r in listing() if r['p0'] not in seen]; st = collections.Counter(); by = collections.defaultdict(list)
    for r in rows:
        mb = re.search(r'Решение (.+?) от \d', r['act']); body = mb.group(1) if mb else r['act']
        q, why = match(body, P); st[why if not q else 'mapped_' + why] += 1
        r['body'] = body; r['match'] = why
        if q: by[q].append(r)
        else:
            with open(W + '/by_unmapped.jsonl', 'a') as f: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('listing', len(rows), dict(st), 'places', len(by), flush=True)
    for q in list(by)[:a.places]:
        if shutil.disk_usage('/workspace').free < 35e9: print('DISK LOW', flush=True); break
        w = StagedWriter(ST, 'BY', q, batch_prefix='pravobynew', chunk=200); c = collections.Counter()
        for r in by[q]:
            text, pdf = doc_text(r['p0'])
            if not text or len(text) < 200: c['no_text'] += 1; continue
            num = re.search(r'№\s*(\S+)', r['act']); ad = re.search(r'от (\d{1,2}) (\w+) (\d{4})', r['act'])
            rec = {'place_id': q, 'country_code': 'BY', 'doc_id': f'pravoby:{r["p0"]}', 'source_platform': 'pravo_by',
                   'source_url': f'{BASE}/document/?guid=12551&p0={r["p0"]}', 'doc_type': 'decision', 'language': 'ru',
                   'content_format': 'pdf_text', 'text': text, 'title_native': r['title'][:1000], 'number': num.group(1) if num else None,
                   'published_date': iso_date(r['pub']), 'consolidated': False, 'in_force': None,
                   'retrieved_at': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'), 'source_official': True,
                   'source_org': 'Национальный правовой Интернет-портал Республики Беларусь (НЦПИ)', 'source_policy': 'robots_allowed_rfc9309',
                   'issuing_body': r['body'], 'act_line': r['act'], 'national_register_number': r['reg'], 'pdf_url': pdf,
                   'body_kind': r['match'], 'qid': q[3:], 'place_name': P[3].get(q)}
            if re.search(r'[іўІЎ]', text[:3000]) and not re.search(r'[ыъЫЪ]', text[:3000]): rec['language'] = 'be'
            err = w.add(rec)
            if err: c['invalid'] += 1; print('INVALID', rec['doc_id'], err, flush=True)
            else: c['staged'] += 1
        w.flush()
        res = {'place_key': place_key(q), 'place': P[3].get(q), 'listed': len(by[q]), **c, 'files': w.written}
        print(datetime.datetime.now().strftime('%H:%M:%S'), json.dumps(res, ensure_ascii=False), flush=True)
        with open(seenf, 'a') as f:
            for r in by[q]: f.write(json.dumps({'p0': r['p0'], 'place': q}) + '\n')
        with open(W + '/by_done.jsonl', 'a') as f: f.write(json.dumps(res, ensure_ascii=False) + '\n')
    print('finished', flush=True)
if __name__ == '__main__': main()
