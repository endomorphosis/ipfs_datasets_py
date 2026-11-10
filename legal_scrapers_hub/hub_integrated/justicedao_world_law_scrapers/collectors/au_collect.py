#!/usr/bin/env python3
"""AU subnational collector: ONE process, jurisdictions sequential. Memory guard self-TERM at MemAvail<=3584MB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, time, gzip, threading, subprocess, random, argparse, html as htmlmod
import requests
BASE = '{_CORPORA}/au_subnational'
STATE = f'{BASE}/collector_state.json'
UA = 'python-requests (research collection of official state legislation texts; polite)'
MEM_LIMIT_MB = 3584
PIT = '20260928000000'

def log(*a):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)

def memavail_mb():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 10**9

state = {'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'pid': os.getpid(), 'status': 'running', 'jur': {}, 'blocked': {}, 'mem_term': False}
def save_state():
    tmp = STATE + '.tmp'; json.dump(state, open(tmp, 'w'), indent=1); os.replace(tmp, STATE)

def mem_guard():
    while True:
        m = memavail_mb()
        if m <= MEM_LIMIT_MB:
            log(f'MEMGUARD TERM: MemAvailable={m}MB <= {MEM_LIMIT_MB}MB')
            state['status'] = 'MEM_TERM'; state['mem_term'] = True; state['mem_at_term_mb'] = m
            state['ended'] = time.strftime('%Y-%m-%dT%H:%M:%S'); save_state()
            os._exit(3)
        time.sleep(30)

class Blocked(Exception): pass
class Fetcher:
    def __init__(self):
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA
        self.last = {}; self.c403 = {}; self.blocked = set()
        self.delay = {'legislation.nsw.gov.au': 1.0, 'www.legislation.qld.gov.au': 1.0, 'www.legislation.tas.gov.au': 1.0,
                      'www.legislation.wa.gov.au': 1.0, 'legislation.nt.gov.au': 1.0}
    def get(self, url, params=None, timeout=180):
        host = re.match(r'https?://([^/]+)', url).group(1)
        if host in self.blocked: raise Blocked(host)
        for attempt in range(4):
            w = self.delay.get(host, 2.0) - (time.time() - self.last.get(host, 0))
            if w > 0: time.sleep(w)
            self.last[host] = time.time()
            try:
                r = self.s.get(url, params=params, timeout=timeout)
            except requests.RequestException as e:
                log('ERR', url, e); time.sleep(20 * (attempt + 1)); continue
            if r.status_code == 403:
                self.c403[host] = self.c403.get(host, 0) + 1
                log('403', host, self.c403[host], url)
                if self.c403[host] >= 3:
                    self.blocked.add(host); state['blocked'][host] = {'reason': 'BLOCKED_SOURCE 3 consecutive 403', 'url': url, 'ts': time.strftime('%H:%M:%S')}
                    save_state(); raise Blocked(host)
                return r
            self.c403[host] = 0
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get('Retry-After'); wt = int(ra) if ra and ra.isdigit() else 30 * (2 ** attempt)
                log('BACKOFF', r.status_code, url, wt); time.sleep(min(wt, 300)); continue
            return r
        return None

F = Fetcher()
def v(x, k):
    y = x.get(k); return y.get('__value__') if isinstance(y, dict) else y

# ---------------- listing ----------------
PCO = {'NSW': 'legislation.nsw.gov.au', 'QLD': 'www.legislation.qld.gov.au', 'TAS': 'www.legislation.tas.gov.au'}
def list_pco(st):
    L = json.load(open(f'{BASE}/index/{st}_pit_all.json'))
    out = []
    for x in L:
        if v(x, 'repealed') != 'N': continue
        i = v(x, 'id')
        if not i or not re.match(r'^[A-Za-z]+-\d{4}-[0-9A-Za-z]+$', i): continue
        out.append(dict(src_id=i, title=v(x, 'title'), year=v(x, 'year'), no=v(x, 'no'), type=v(x, 'type'), print_type=v(x, 'print.type'),
                        publication_date=x.get('publication.date'), first_valid_date=x.get('first.valid.date'), assent_date=x.get('assent.date'),
                        url=f'https://{PCO[st]}/view/whole/html/inforce/current/{i}'))
    out.sort(key=lambda d: d['src_id'])
    return out

WA = 'https://www.legislation.wa.gov.au/legislation/statutes.nsf/'
def list_wa():
    out = []; seen = set()
    for kind, pref in [('act', 'actsif'), ('sl', 'subsif')]:
        idx = F.get(WA + pref + '.html')
        letters = sorted(set(re.findall(pref + r"_([a-z0-9]+)\.html", idx.text))) if idx is not None else []
        if pref + '_info' in [pref + '_' + l for l in letters]: letters.remove('info')
        log('WA list', pref, len(letters), 'letter pages')
        for l in letters:
            r = F.get(WA + f'{pref}_{l}.html')
            if r is None or r.status_code != 200: log('WA list fail', pref, l); continue
            for row in re.findall(r'<tr>(.*?)</tr>', r.text, re.S):
                m = re.search(r"href='(law_([a-z]\d+)\.html[^']*)'[^>]*>(.*?)</a>", row, re.S)
                if not m: continue
                cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
                h = re.search(r"query=(mrdoc_\d+)\.htm", row)
                lawid = m.group(2)
                if lawid in seen: continue
                seen.add(lawid)
                out.append(dict(src_id=lawid, title=htmlmod.unescape(re.sub(r'<[^>]+>', '', m.group(3))).strip(), kind=kind,
                                number=cells[1] if len(cells) > 1 else '', mrdoc=h.group(1) if h else None,
                                page_url=WA + htmlmod.unescape(m.group(1)),
                                url=(WA + f'RedirectURL?OpenAgent&query={h.group(1)}.htm') if h else None))
    return out

NT = 'https://legislation.nt.gov.au'
def list_nt():
    out = []; seen = set()
    for kind, path in [('act', '/en/LegislationPortal/Acts/By-Title'), ('sl', '/en/LegislationPortal/Subordinate-Legislation/By-Title')]:
        F.s.cookies.clear()  # NT Sitecore session cookie makes the 2nd listing page render empty
        r = F.get(NT + path)
        if r is None or r.status_code != 200: log('NT list fail', path); continue
        for m in re.finditer(r'href="(/en/Legislation/([^"#?]+))"[^>]*>(.*?)</a>', r.text, re.S):
            slug = m.group(2)
            if slug in seen or slug.upper() == 'ADMINISTRATIVE-ARRANGEMENTS-ORDER' and kind == 'act' and False: continue
            t = htmlmod.unescape(re.sub(r'<[^>]+>', '', m.group(3))).strip()
            if not t: continue
            seen.add(slug)
            out.append(dict(src_id=slug, title=t, kind=kind, page_url=NT + m.group(1)))
        log('NT list', kind, len(out))
    return out

# ---------------- fetch ----------------
def raw_path(st, sid, ext):
    d = f'{BASE}/raw/{st}'; os.makedirs(d, exist_ok=True)
    return f'{d}/{re.sub(r"[^A-Za-z0-9._-]", "_", sid)}.{ext}.gz'

def put(p, data):
    tmp = p + '.tmp'
    with gzip.open(tmp, 'wb', compresslevel=6) as f: f.write(data)
    os.replace(tmp, p)

def fetch_one(st, it):
    """returns status string"""
    if st in PCO or st == 'WA':
        p = raw_path(st, it['src_id'], 'html')
        if os.path.exists(p) or os.path.exists(raw_path(st, it['src_id'], 'txt')): return 'cached'
        if not it.get('url'): return 'no_html_link'
        r = F.get(it['url'])
        if r is None: return 'fail_none'
        if r.status_code != 200: return f'http_{r.status_code}'
        it['final_url'] = r.url
        if r.content[:5] == b'%PDF-':
            return pdf_to_txt(st, it, r.content)
        put(p, r.content); return 'ok'
    if st == 'NT':
        p = raw_path(st, it['src_id'], 'txt')
        if os.path.exists(p): return 'cached'
        r = F.get(it['page_url'])
        if r is None or r.status_code != 200: return f'page_{getattr(r, "status_code", None)}'
        pg = r.text
        m = re.search(r'href="(https://legislation\.nt\.gov\.au/api/sitecore/[A-Za-z]+/PDF\?id=\d+)"', pg)
        it['repealed_marker'] = bool(re.search(r'(?i)\b(repealed|expired|revoked)\b', re.sub(r'<[^>]+>', ' ', pg)[:20000])) and False
        mm = re.search(r'(?i)As in force at\s*([^<]{5,30})', pg); it['in_force_at'] = mm.group(1).strip() if mm else None
        if not m: return 'no_pdf_link'
        it['url'] = htmlmod.unescape(m.group(1))
        r2 = F.get(it['url'], timeout=300)
        if r2 is None or r2.status_code != 200: return f'pdf_{getattr(r2, "status_code", None)}'
        if r2.content[:5] != b'%PDF-': return 'not_pdf'
        return pdf_to_txt(st, it, r2.content)

def pdf_to_txt(st, it, data):
    tmp = f'/tmp/au_{os.getpid()}.pdf'
    open(tmp, 'wb').write(data)
    try:
        t = subprocess.run(['pdftotext', '-layout', tmp, '-'], capture_output=True, timeout=300).stdout
    except Exception as e:
        return 'pdftotext_fail'
    finally:
        os.remove(tmp)
    it['pdf_bytes'] = len(data); it['is_pdf'] = True
    put(raw_path(st, it['src_id'], 'txt'), t); return 'ok_pdf'

def run_jur(st, sample=0):
    log('=== JURISDICTION', st)
    lp = f'{BASE}/index/{st}_list.jsonl'
    if os.path.exists(lp):
        items = [json.loads(l) for l in open(lp)]
    else:
        items = list_pco(st) if st in PCO else (list_wa() if st == 'WA' else list_nt())
        if True:
            with open(lp, 'w') as f:
                for it in items: f.write(json.dumps(it) + '\n')
    log(st, 'listed', len(items))
    if sample:
        random.seed(7); items = random.sample(items, min(sample, len(items)))
    js = state['jur'].setdefault(st, {'listed': len(items), 'done': 0, 'status': {}})
    res_path = f'{BASE}/index/{st}_fetch{"_sample" if sample else ""}.jsonl'
    with open(res_path, 'a') as rf:
        for n, it in enumerate(items, 1):
            try:
                s = fetch_one(st, it)
            except Blocked as b:
                log(st, 'BLOCKED', b); js['blocked'] = True; save_state(); break
            it['fetch_status'] = s; it['fetched_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            rf.write(json.dumps(it) + '\n'); rf.flush()
            js['done'] = n; js['status'][s] = js['status'].get(s, 0) + 1
            if n % 25 == 0 or sample:
                log(st, n, '/', len(items), s, it['src_id'], f'mem={memavail_mb()}MB'); save_state()
    js['finished'] = time.strftime('%H:%M:%S'); save_state()
    log('=== DONE', st, js['status'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--sample', type=int, default=0); ap.add_argument('--jur', default='NSW,QLD,TAS,WA,NT')
    a = ap.parse_args()
    if a.sample: STATE = STATE.replace('.json', '_sample.json')
    threading.Thread(target=mem_guard, daemon=True).start()
    log('START pid', os.getpid(), 'memavail', memavail_mb(), 'sample', a.sample)
    for st in a.jur.split(','):
        run_jur(st, a.sample)
    state['status'] = 'finished'; state['ended'] = time.strftime('%Y-%m-%dT%H:%M:%S'); save_state()
    log('ALL DONE')
