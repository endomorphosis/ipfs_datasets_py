#!/usr/bin/env python3
"""CA subnational collector: ONE process, jurisdictions sequential (ON, MB, SK, NS, NB, NL, NT, NU).
Official provincial/territorial sites only. robots.txt checked/saved beforehand (robots/). 3 consecutive 403 (or bot-challenge)
on a host -> BLOCKED_SOURCE. Memory: pause while MemAvail < 4600 MB; self-TERM at <= 3584 MB (sets state HOLD_0_CA_MEMSHED)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, time, gzip, threading, subprocess, random, argparse, html as H
import requests
BASE = '{_CORPORA}/ca_subnational'
STATE = f'{BASE}/collector_state.json'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
UA = 'python-requests (research collection of official provincial legislation texts; polite)'
TERM_MB = 3584; PAUSE_MB = 4600
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 10 ** 9
state = {'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'pid': os.getpid(), 'status': 'running', 'jur': {}, 'blocked': {}, 'mem_term': False, 'pauses': 0}
def save_state():
    tmp = STATE + '.tmp'; json.dump(state, open(tmp, 'w'), indent=1); os.replace(tmp, STATE)
def set_pin(mode, collectors, phase):
    try:
        kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l)
    except Exception: kv = {}
    kv.update(mode=mode, collectors=str(collectors), phase=phase, ts=time.strftime('%Y-%m-%dT%H:%MPT'), MemAvail_MB=str(memavail()))
    open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
def mem_term(m):
    log(f'MEMGUARD TERM: MemAvailable={m}MB <= {TERM_MB}MB')
    state.update(status='MEM_TERM', mem_term=True, mem_at_term_mb=m, ended=time.strftime('%Y-%m-%dT%H:%M:%S')); save_state()
    set_pin('HOLD_0_CA_MEMSHED', 0, f'CA collector self-TERM at MemAvail={m}MB; not restarted')
    os._exit(3)
def mem_guard():
    while True:
        m = memavail()
        if m <= TERM_MB: mem_term(m)
        time.sleep(5)
def mem_pause():
    m = memavail()
    while m < PAUSE_MB:
        if m <= TERM_MB: mem_term(m)
        state['pauses'] += 1; log(f'MEM PAUSE MemAvailable={m}MB < {PAUSE_MB}MB; sleeping 30s'); save_state(); time.sleep(30); m = memavail()

class Blocked(Exception): pass
CHALLENGE = re.compile(rb'Radware Page|sgcaptcha|/cdn-cgi/challenge-platform|Just a moment\.\.\.|Request blocked\.')
class Fetcher:
    def __init__(self):
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA
        self.last = {}; self.c403 = {}; self.blocked = set()
        self.delay = {'www.ontario.ca': 1.0, 'nslegislature.ca': 10.0, 'novascotia.ca': 1.0, 'web2.gov.mb.ca': 1.0, 'publications.saskatchewan.ca': 1.0,
                      'laws.gnb.ca': 1.0, 'www.assembly.nl.ca': 1.0, 'www.justice.gov.nt.ca': 1.0, 'www.nunavutlegislation.ca': 1.0}
    def get(self, url, timeout=180, **kw):
        host = re.match(r'https?://([^/]+)', url).group(1)
        if host in self.blocked: raise Blocked(host)
        for attempt in range(4):
            mem_pause()
            w = self.delay.get(host, 2.0) - (time.time() - self.last.get(host, 0))
            if w > 0: time.sleep(w)
            self.last[host] = time.time()
            try: r = self.s.get(url, timeout=timeout, **kw)
            except requests.RequestException as e:
                log('ERR', url, e); time.sleep(20 * (attempt + 1)); continue
            bad = r.status_code == 403 or (r.status_code in (200, 202) and CHALLENGE.search(r.content[:20000] or b''))
            if bad:
                self.c403[host] = self.c403.get(host, 0) + 1
                log('BLOCKLIKE', r.status_code, host, self.c403[host], url)
                os.makedirs(f'{BASE}/probe', exist_ok=True)
                open(f'{BASE}/probe/block_{host}_{self.c403[host]}.html', 'wb').write(r.content[:200000])
                if self.c403[host] >= 3:
                    self.blocked.add(host); state['blocked'][host] = {'reason': 'BLOCKED_SOURCE 3 consecutive 403/challenge', 'status': r.status_code, 'url': url, 'ts': time.strftime('%H:%M:%S')}
                    save_state(); raise Blocked(host)
                return None
            self.c403[host] = 0
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get('Retry-After'); wt = int(ra) if ra and ra.isdigit() else 30 * (2 ** attempt)
                log('BACKOFF', r.status_code, url, wt); time.sleep(min(wt, 300)); continue
            return r
        return None
F = Fetcher()
def clean_t(s): return re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()

# ---------------- listings ----------------
ON = 'https://www.ontario.ca/laws/api/v2/legislation/en'
def list_on():
    out = []
    for kind in ('statute', 'regulation'):
        r = F.get(f'{ON}/browse-search', params=dict(text='', selection='current', result=kind, sort='AZ', page=1, pageSize=50))
        d = r.json(); seen = set()
        log('ON list', kind, 'hits.total', d['hits']['total']['value'])
        state.setdefault('listing_totals', {})[f'ON_{kind}'] = d['hits']['total']['value']
        for b in d['aggregations']['act']['buckets']:
            for h in b[kind][kind + '_hits']['hits']['hits']:
                s = h['_source']; a = s['alias']['en']
                if a in seen or s['state']['en'] != 'current': continue
                seen.add(a)
                out.append(dict(src_id=a, kind=kind, title=s['title']['en'], act=(s.get('act') or {}).get('en'), volume=(s.get('volume') or {}).get('en'),
                                date_from=(s.get('dateFrom') or {}).get('en'), url=f'{ON}/doc-search/{a}', page_url=f'https://www.ontario.ca/laws/{a}'))
    return out

MB = 'https://web2.gov.mb.ca/laws/'
def list_mb():
    out = []; seen = set()
    r = F.get(MB + 'statutes/index_ccsm.php')
    for row in re.findall(r'(?s)<tr style="vertical-align:top">(.*?)</tr>', r.text):
        m = re.search(r'<td class="left s_9em">([^<]+)</td>\s*<td class="left ?"><a title="Current version \(HTML\)" href="(ccsm/[^"]+)">(.*?)</a>(.*?)</td>', row, re.S)
        if not m: continue
        chap, href, title, rest = m.groups(); sid = 'ccsm-' + chap.strip()
        if sid in seen: continue
        seen.add(sid); en = re.search(r'Original chapter version" href="[^"]*">(.*?)</a>', rest)
        out.append(dict(src_id=sid, kind='statute', title=clean_t(title), citation=f'C.C.S.M. c. {chap.strip()}', enacted=clean_t(en.group(1)) if en else None, url=MB + 'statutes/' + H.unescape(href)))
    for idx in ('regs/index.php', 'regs/index_nonccsm.php'):
        r = F.get(MB + idx); act = None
        for tr in re.findall(r'(?s)<tr[^>]*>(.*?)</tr>', r.text):
            ma = re.search(r'<td class="tline[^"]*" colspan="5"><b>(.*?)</b>', tr)
            if ma: act = clean_t(ma.group(1)); continue
            m = re.search(r'<a title\s*=\s*"([^"]*)" href="(current/[^"?#]+)[^"]*">([^<]+)</a>', tr)
            if not m: continue
            rt, href, no = m.groups(); sid = 'reg-' + no.strip()
            if sid in seen: continue
            seen.add(sid)
            out.append(dict(src_id=sid, kind='regulation', title=clean_t(rt), citation=f'Man. Reg. {no.strip()}', act=act, url=MB + 'regs/' + href + '?lang=en'))
    return out

SK = 'https://publications.saskatchewan.ca/api/v1/'
def list_sk():
    r = F.get(SK + 'freelaw/acts'); out = []; seen = set()
    for x in r.json():
        a = x['act']
        rows = [(a, 'statute', None)] + [(g, 'regulation', a['name']) for g in (x.get('regulations') or [])]
        for p, kind, act in rows:
            if p['productStatusType'] != 'ACTIVE' or p['productId'] in seen: continue
            seen.add(p['productId'])
            out.append(dict(src_id=str(p['productId']), kind=kind, title=p['name'], citation=p.get('customIdentifier'), act=act,
                            url=SK + f"products/{p['productId']}", page_url=f"https://publications.saskatchewan.ca/#/products/{p['productId']}"))
    return out

def list_ns():
    out = []
    r = F.get('https://nslegislature.ca/legislative-business/bills-statutes/consolidated-public-statutes')
    c = re.sub(r'(?s)<!--.*?-->', '', r.text); seen = set()
    for t, href in re.findall(r'<li>([^<]{3,200}?)\s*(?:&nbsp;)*\s*<a href="(/sites/default/files/legc/statutes HTML/[^"]+\.htm)"', c):
        slug = href.rsplit('/', 1)[1][:-4]
        if slug in seen or slug.startswith('xxxxx'): continue
        seen.add(slug)
        out.append(dict(src_id='stat-' + slug, kind='statute', title=clean_t(t), url='https://nslegislature.ca' + href.replace(' ', '%20')))
    r = F.get('https://novascotia.ca/just/regulations/regsbyact.htm'); c = r.content.decode('latin-1')
    for blk in re.split(r'<!--- BEGIN ACT --->', c)[1:]:
        ma = re.search(r'(?s)<h2>(.*?)<span', blk); act = clean_t(ma.group(1)) if ma else None
        for href, t, det in re.findall(r'(?s)<dt class="reglist-name"><a href="(regs/[^"]+\.htm)">(.*?)</a>\s*<dd class="reglist-details">(.*?)(?=<dt|<!---|</dl>)', blk):
            slug = href[5:-4]
            if slug in seen or slug.startswith('____'): continue
            seen.add(slug)
            out.append(dict(src_id='reg-' + slug, kind='regulation', title=clean_t(t), citation=clean_t(det), act=act, url='https://novascotia.ca/just/regulations/' + href))
    return out

def list_nb():
    out = []; seen = set()
    for corpus, kind, pfx in (('statutes', 'statute', 'cs'), ('regs', 'regulation', 'cr')):
        r = F.get(f'https://laws.gnb.ca/en/chapters?corpus={corpus}&selection=all')
        for tr in re.findall(r'(?s)<tr class="clickable"[^>]*>(.*?)</tr>', r.text):
            m = re.search(r'<th class="text-nowrap">([^<]+)</th>\s*<td><a [^>]*title="([^"]*)" href="(/en/document/' + pfx + r'/[^"]+)">', tr)
            if not m or 'Repealed' in tr: continue
            chap, t, href = m.groups()
            if href in seen: continue
            seen.add(href)
            out.append(dict(src_id=f'{pfx}-{H.unescape(chap).strip()}', kind=kind, title=H.unescape(t).strip(), citation=H.unescape(chap).strip(), url='https://laws.gnb.ca' + href))
    return out

def list_nl():
    r = F.get('https://www.assembly.nl.ca/robots.txt')
    if r is None or r.status_code != 200:
        state['jur'].setdefault('NL', {})['unavailable'] = f'robots.txt HTTP {getattr(r, "status_code", None)} at {time.strftime("%H:%M:%S")}'
        log('NL unavailable', getattr(r, 'status_code', None)); return []
    open(f'{BASE}/robots/www.assembly.nl.ca.txt', 'wb').write(r.content)
    log('NL robots now available; adapter not implemented in this run'); state['jur'].setdefault('NL', {})['note'] = 'robots available at collect time but no adapter; see report'
    return []

def list_nt():
    r = F.get('https://www.justice.gov.nt.ca/en/legislation/'); out = []; seen = set()
    for m in re.finditer(r'<a class="gn-filebrowse-node-label" href="(https://www\.justice\.gov\.nt\.ca/en/files/legislation/[^"]+/([^"/]+)\.(a|r\d+)\.pdf)" title="Title">\s*(.*?)\s*</a>\s*<div class="gn-filebrowse-node-meta"><div[^>]*data-attribute-name="date">([^<]*)</div>', r.text, re.S):
        url, slug, k, t, d = m.groups(); sid = f'{slug}.{k}'
        if sid in seen: continue
        seen.add(sid)
        out.append(dict(src_id=sid, kind='statute' if k == 'a' else 'regulation', title=clean_t(t), modified=d.strip(), url=url))
    return out

NU = 'https://www.nunavutlegislation.ca'
def list_nu():
    """Current consolidations; regulations are nested <article> children of their parent act's row."""
    out = []; seen = set()
    for L in [''] + [f'?title={c}' for c in 'BCDEFGHIJKLMNOPQRSTUVWXYZ']:
        r = F.get(NU + '/en/consolidated-law/current' + L)
        if r is None: continue
        t = r.text; depth = 0; stack = []
        for m in re.finditer(r'<article class="media-type--consolidated_law">|</article>', t):
            if m.group(0) == '</article>':
                depth -= 1; stack and stack.pop(); continue
            depth += 1
            seg = t[m.end():]; nxt = re.search(r'<article|</article>', seg); seg = seg[:nxt.start()] if nxt else seg
            mt = re.search(r'<div class="title">\s*<a href="(/en/consolidated-law/([^"]+))">(.*?)</a>', seg, re.S)
            parent = stack[0] if stack else None
            stack.append(mt.group(2) if mt else None)
            if not mt: continue
            href, slug, tt = mt.groups()
            if slug in seen: continue
            seen.add(slug); note = re.search(r'(?s)<b>Note:</b>(.*?)</div>', seg)
            kind = 'statute' if depth == 1 else 'regulation'
            out.append(dict(src_id=slug, kind=kind, title=clean_t(tt), note=clean_t(note.group(1)) if note else None, act_slug=parent, page_url=NU + href))
    return out

# ---------------- fetch ----------------
def raw_path(st, sid, ext):
    d = f'{BASE}/raw/{st}'; os.makedirs(d, exist_ok=True)
    return f'{d}/{re.sub(r"[^A-Za-z0-9._-]", "_", sid)}.{ext}.gz'
def put(p, data):
    tmp = p + '.tmp'
    with gzip.open(tmp, 'wb', compresslevel=6) as f: f.write(data)
    os.replace(tmp, p)
def pdf_to_txt(st, it, data, crop_left=False):
    tmp = f'/tmp/ca_{os.getpid()}.pdf'; open(tmp, 'wb').write(data)
    try:
        args = ['pdftotext', '-layout']
        if crop_left:
            info = subprocess.run(['pdfinfo', tmp], capture_output=True, text=True, timeout=60).stdout
            m = re.search(r'Page size:\s+([\d.]+) x ([\d.]+)', info); w, h = (float(m.group(1)), float(m.group(2))) if m else (612, 792)
            args += ['-x', '0', '-y', '0', '-W', str(int(w / 2)), '-H', str(int(h))]
        t = subprocess.run(args + [tmp, '-'], capture_output=True, timeout=300).stdout
    except Exception: return 'pdftotext_fail'
    finally: os.remove(tmp)
    it['pdf_bytes'] = len(data); it['is_pdf'] = True
    put(raw_path(st, it['src_id'], 'txt'), t); return 'ok_pdf'
def fetch_one(st, it):
    if os.path.exists(raw_path(st, it['src_id'], 'html')) or os.path.exists(raw_path(st, it['src_id'], 'txt')) or os.path.exists(raw_path(st, it['src_id'], 'json')):
        return 'cached'
    if st == 'ON':
        r = F.get(it['url'])
        if r is None: return 'fail_none'
        if r.status_code != 200: return f'http_{r.status_code}'
        try: d = r.json()
        except Exception: return 'bad_json'
        if not d.get('content'): return 'empty_content'
        put(raw_path(st, it['src_id'], 'json'), r.content); return 'ok'
    if st in ('MB', 'NS', 'NB'):
        r = F.get(it['url'])
        if r is None: return 'fail_none'
        if r.status_code != 200: return f'http_{r.status_code}'
        it['final_url'] = r.url; put(raw_path(st, it['src_id'], 'html'), r.content); return 'ok'
    if st == 'SK':
        r = F.get(it['url'])
        if r is None or r.status_code != 200: return f'product_{getattr(r, "status_code", None)}'
        p = r.json(); fm = sorted([f for f in p.get('productFormats', []) if (f.get('productFormatType') or '').strip().upper() == 'PDF' and f.get('productFormatMediumType') == 'DIGITAL'], key=lambda f: (f.get('language') != 'English', not f.get('isPrimary')))
        it['description'] = clean_t(p.get('longDescriptionEnglish'))[:1000]; it['publication_date'] = p.get('productPublicationDate')
        if not fm: return 'no_pdf_format'
        it['pdf_url'] = SK + f"products/{p['productId']}/formats/{fm[0]['productFormatId']}/download"; it['pdf_name'] = (fm[0].get('digitalAttributes') or {}).get('fileName')
        r2 = F.get(it['pdf_url'], timeout=300)
        if r2 is None or r2.status_code != 200: return f'pdf_{getattr(r2, "status_code", None)}'
        if r2.content[:5] != b'%PDF-': return 'not_pdf'
        return pdf_to_txt(st, it, r2.content)
    if st == 'NT':
        r = F.get(it['url'], timeout=300)
        if r is None or r.status_code != 200: return f'pdf_{getattr(r, "status_code", None)}'
        if r.content[:5] != b'%PDF-': return 'not_pdf'
        return pdf_to_txt(st, it, r.content, crop_left=True)   # bilingual 2-column PDFs: English is the left column
    if st == 'NU':
        r = F.get(it['page_url'])
        if r is None or r.status_code != 200: return f'page_{getattr(r, "status_code", None)}'
        m = re.search(r'href="(/en/file-download/download/public/\d+)"', r.text)
        cur = re.search(r'Current to:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', r.text); it['current_to_page'] = cur.group(1) if cur else None
        if not m: return 'no_pdf_link'
        it['url'] = NU + m.group(1)
        r2 = F.get(it['url'], timeout=300)
        if r2 is None or r2.status_code != 200: return f'pdf_{getattr(r2, "status_code", None)}'
        if r2.content[:5] != b'%PDF-': return 'not_pdf'
        return pdf_to_txt(st, it, r2.content)
    return 'no_adapter'

LISTERS = dict(ON=list_on, MB=list_mb, SK=list_sk, NS=list_ns, NB=list_nb, NL=list_nl, NT=list_nt, NU=list_nu)
def run_jur(st, sample=0, ids=None):
    log('=== JURISDICTION', st, f'mem={memavail()}MB')
    lp = f'{BASE}/index/{st}_list.jsonl'
    if os.path.exists(lp): items = [json.loads(l) for l in open(lp)]
    else:
        try: items = LISTERS[st]()
        except Blocked as b:
            log(st, 'BLOCKED at listing', b); state['jur'].setdefault(st, {})['blocked'] = str(b); save_state(); return
        if items:
            with open(lp, 'w') as f:
                for it in items: f.write(json.dumps(it) + '\n')
    log(st, 'listed', len(items))
    if ids: items = [it for it in items if it['src_id'] in ids]
    elif sample:
        random.seed(7); items = random.sample(items, min(sample, len(items)))
    js = state['jur'].setdefault(st, {}); js.update(listed=len(items), done=0, status={})
    res_path = f'{BASE}/index/{st}_fetch{"_sample" if (sample or ids) else ""}.jsonl'
    with open(res_path, 'a') as rf:
        for n, it in enumerate(items, 1):
            try: s = fetch_one(st, it)
            except Blocked as b:
                log(st, 'BLOCKED', b); js['blocked'] = str(b); save_state(); break
            except Exception as e:
                s = f'error_{type(e).__name__}'; log(st, 'ERROR', it['src_id'], repr(e)[:300])
            it['fetch_status'] = s; it['fetched_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            rf.write(json.dumps(it) + '\n'); rf.flush()
            js['done'] = n; js['status'][s] = js['status'].get(s, 0) + 1
            if n % 25 == 0 or sample or ids:
                log(st, n, '/', len(items), s, it['src_id'], f'mem={memavail()}MB'); save_state()
    js['finished'] = time.strftime('%H:%M:%S'); save_state()
    log('=== DONE', st, js['status'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--sample', type=int, default=0); ap.add_argument('--jur', default='ON,MB,SK,NS,NB,NL,NT,NU')
    ap.add_argument('--ids', default=''); ap.add_argument('--list-only', action='store_true')
    a = ap.parse_args()
    if a.sample or a.ids or a.list_only: STATE = STATE.replace('.json', '_sample.json')
    threading.Thread(target=mem_guard, daemon=True).start()
    log('START pid', os.getpid(), 'memavail', memavail(), 'args', vars(a))
    for st in a.jur.split(','):
        if a.list_only:
            lp = f'{BASE}/index/{st}_list.jsonl'
            if not os.path.exists(lp):
                items = LISTERS[st]()
                if items:
                    with open(lp, 'w') as f:
                        for it in items: f.write(json.dumps(it) + '\n')
                log(st, 'listed', len(items))
            continue
        ids = None
        if a.ids:
            ids = {x.split(':', 1)[1] for x in a.ids.split('|') if x.startswith(st + ':')}
            if not ids: continue
        run_jur(st, a.sample, ids)
    state['status'] = 'finished'; state['ended'] = time.strftime('%Y-%m-%dT%H:%M:%S'); save_state()
    log('ALL DONE')
