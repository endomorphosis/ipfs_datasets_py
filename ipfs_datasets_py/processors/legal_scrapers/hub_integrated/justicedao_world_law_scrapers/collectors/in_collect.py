#!/usr/bin/env python3
"""IN subnational (India Code STATE/UT acts) collector. ONE process, sequential, polite.  ** DRAFT — NOT HAND-CHECKED **
Status 2026-10-03 00:56 PT: the authorized host indiacode.nic.in is migrated (static notice -> indiacode.gov.in) and every
content path returns Akamai 504 (see legal-corpora/in_subnational/probe/probe_log.json). Host is LOCKED to indiacode.nic.in;
indiacode.gov.in may only be used with explicit authorization: env IN_ALLOW_HOST=indiacode.gov.in.
Adapter: DSpace 7 REST (/server/api) as used by the hub's scrapers/collect_indiacode.py (CENTRAL acts, 2026-09-02):
  state communities -> discover/search/objects scope=<community> f.identifier_collection=ACT|SECTION (100/page);
  section HTML in SECTION metadata (dc.identifier.section_page_note); PDF bitstream only for acts without sections.
robots.txt fetched+saved+obeyed per host (Crawl-delay honoured, min 2.0s). 3 consecutive 403/503 -> BLOCKED_SOURCE (stop site).
MemAvail checked every request + 5s thread: <=3584MB -> 'MEMGUARD TERM MemAvailable=<n>MB', exit 3. Raw responses cached gz (resume-safe).
Usage: in_collect.py handcheck [ST,ST,...|ALL]   |   in_collect.py full [ALL|ST,ST,...]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, threading, subprocess, tempfile, hashlib
from pathlib import Path
import requests
B = Path('{_CORPORA}/in_subnational'); RAW = B / 'raw'; PROBE = B / 'probe'; ROB = B / 'robots'; IDX = B / 'index'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
UA = 'legal-corpora-in-subnational/1.0 (research corpus of official state acts; polite; contact via huggingface.co/endomorphosis)'
AUTH_HOST = 'indiacode.nic.in'; HOST = os.environ.get('IN_ALLOW_HOST') or 'www.indiacode.nic.in'
assert HOST in ('www.indiacode.nic.in', 'indiacode.nic.in', 'indiacode.gov.in'), HOST
BASE = f'https://{HOST}'; API = f'{BASE}/server/api'; TERM_MB = 3584; MIN_DELAY = 2.0; PAGE = 100
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 10 ** 9
def set_pin(**u):
    try: kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l)
    except Exception: kv = {}
    kv.update({k: str(v) for k, v in u.items()}); open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
def term(m):
    log(f'MEMGUARD TERM MemAvailable={m}MB')
    try: set_pin(mode='HOLD_0_IN_MEMSHED', collectors=0, pid='', phase=f'IN collector self-TERM at MemAvail={m}MB; not restarted', ts=time.strftime('%Y-%m-%dT%H:%MPT'), MemAvail_MB=m)
    except Exception as e: log('pin update failed', e)
    os._exit(3)
def mem_check():
    m = memavail()
    if m <= TERM_MB: term(m)
    return m
def _mg():
    while True: mem_check(); time.sleep(5)

class Blocked(Exception): pass
class Site:
    def __init__(self):
        self.s = requests.Session(); self.s.headers.update({'User-Agent': UA, 'Accept': 'application/json, application/hal+json, */*'})
        self.rules, cd = self.robots(); self.delay = max(MIN_DELAY, cd); self.last = 0.0; self.c_block = 0; self.blocked = False; self.nreq = 0
        self.stats = dict(ok=0, cached=0, robots_skip=0, fail=0, http403_503=0)
        log('host', HOST, 'robots rules', len(self.rules), 'crawl-delay', cd, 'delay used', self.delay)
    def robots(self):
        p = ROB / f'{HOST}.robots.txt'
        if not p.exists():
            r = self.s.get(f'{BASE}/robots.txt', timeout=(20, 90)); time.sleep(MIN_DELAY)
            if r.status_code != 200: raise Blocked(f'robots.txt HTTP {r.status_code}')
            p.write_bytes(r.content)
        rules = []; delay = 0.0; groups = []; cur = None; last_ua = False
        for line in open(p, encoding='utf-8', errors='replace'):
            line = line.split('#', 1)[0].strip()
            if ':' not in line: continue
            k, v = [x.strip() for x in line.split(':', 1)]; k = k.lower()
            if k == 'user-agent':
                if not last_ua: cur = {'ua': [], 'rules': [], 'delay': None}; groups.append(cur)
                cur['ua'].append(v.lower()); last_ua = True; continue
            last_ua = False
            if cur is None: continue
            if k in ('allow', 'disallow') and v:
                rx = re.escape(v).replace(r'\*', '.*'); rx = rx[:-2] + '$' if rx.endswith(r'\$') else rx
                cur['rules'].append((k == 'allow', len(v), re.compile(rx)))
            elif k == 'crawl-delay':
                try: cur['delay'] = float(v)
                except ValueError: pass
        tok = UA.split('/')[0].lower(); mine = [g for g in groups if any(u != '*' and tok.startswith(u.rstrip('*')) for u in g['ua'])]
        for g in (mine or [g for g in groups if '*' in g['ua']]): rules += g['rules']; delay = max(delay, g['delay'] or 0)
        return rules, delay
    def robots_ok(self, url):
        path = re.sub(r'^https?://[^/]+', '', url) or '/'; best = None
        for allow, n, rx in self.rules:
            if rx.match(path) and (best is None or n > best[1] or (n == best[1] and allow)): best = (allow, n)
        return best is None or best[0]
    def get(self, url, params=None, binary=False, timeout=(20, 120)):
        if self.blocked: raise Blocked(HOST)
        full = requests.Request('GET', url, params=params).prepare().url
        if not self.robots_ok(full): self.stats['robots_skip'] += 1; log('robots_skip', full); return None
        err = ''
        for att in range(4):
            mem_check()
            w = self.delay - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); self.nreq += 1; ts = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            try: r = self.s.get(full, timeout=timeout, allow_redirects=True)
            except Exception as e: err = repr(e)[:200]; time.sleep(10 * (att + 1)); continue
            if r.url.split('/')[2] not in (HOST, 'www.indiacode.nic.in', 'indiacode.nic.in'):
                log('OFFHOST redirect refused', full, '->', r.url); self.stats['fail'] += 1; return None
            if r.status_code in (403, 503):
                self.c_block += 1; self.stats['http403_503'] += 1; PROBE.mkdir(parents=True, exist_ok=True)
                (PROBE / f'http{r.status_code}_{self.c_block}_{int(time.time())}.txt').write_text(f'{ts} GET {full}\nHTTP {r.status_code}\n{dict(r.headers)}\n\n{r.text[:4000]}', encoding='utf-8')
                log(f'HTTP {r.status_code} consecutive={self.c_block}', full)
                if self.c_block >= 3:
                    self.blocked = True; log('BLOCKED_SOURCE: 3 consecutive 403/503', HOST)
                    bj = B / 'blocked.json'; d = json.load(open(bj)) if bj.exists() else {}
                    d.setdefault('runtime_blocks', []).append(dict(host=HOST, ts=ts, url=full, status=r.status_code, reason='3 consecutive 403/503')); json.dump(d, open(bj, 'w'), indent=1)
                    raise Blocked(HOST)
                time.sleep(30); continue
            if r.status_code in (429, 500, 502, 504): err = f'HTTP {r.status_code}'; time.sleep(30 * (att + 1)); continue
            self.c_block = 0
            if r.status_code != 200: self.stats['fail'] += 1; log('fail', r.status_code, full); return None
            self.stats['ok'] += 1; return r.content if binary else r
        self.stats['fail'] += 1; log('fail', err, full); return None

def cache_path(*parts): p = RAW.joinpath(*parts); p.parent.mkdir(parents=True, exist_ok=True); return p
def put(p, b): tmp = p.with_suffix(p.suffix + '.tmp'); tmp.write_bytes(gzip.compress(b, 6)); os.replace(tmp, p)
def getc(site, p, url, params=None):
    """cached JSON GET: raw response gz at p (resume-safe)"""
    if p.exists(): site.stats['cached'] += 1; return json.loads(gzip.decompress(p.read_bytes()))
    r = site.get(url, params)
    if r is None: return None
    put(p, r.content); return r.json()
def md(m, k):
    v = (m.get(k) or [{}])[0]; return (v.get('value') if isinstance(v, dict) else v) or ''

def discover_states(site):
    """top communities -> the State community(ies) -> subcommunities = states/UTs"""
    out = {}
    d = getc(site, cache_path('_meta', 'communities_top.json.gz'), f'{API}/core/communities/search/top', dict(size=100))
    tops = ((d or {}).get('_embedded') or {}).get('communities') or []
    for c in tops:
        if re.search(r'\bstate', c.get('name') or '', re.I):
            sd = getc(site, cache_path('_meta', f'sub_{c["uuid"]}.json.gz'), f'{API}/core/communities/{c["uuid"]}/subcommunities', dict(size=100))
            for s in ((sd or {}).get('_embedded') or {}).get('subcommunities') or []:
                out[s['name'].strip()] = dict(uuid=s['uuid'], handle=s.get('handle'), parent=c['name'])
    IDX.mkdir(parents=True, exist_ok=True); json.dump(out, open(IDX / 'states.json', 'w'), indent=1); return out
def st_code(name): return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')[:40]
def paginate(site, st, scope, coll, max_pages=None):
    items = []; p = 0; total_pages = 1
    while p < total_pages and (max_pages is None or p < max_pages):
        d = getc(site, cache_path(st, 'list', f'{coll}_{p:05d}.json.gz'), f'{API}/discover/search/objects',
                 dict(query='*', scope=scope, dsoType='ITEM', page=p, size=PAGE, **{'f.identifier_collection': f'{coll},equals'}))
        if d is None: break
        sr = (d.get('_embedded') or {}).get('searchResult') or {}; pg = sr.get('page') or {}; total_pages = int(pg.get('totalPages') or 0)
        if p == 0: log(st, coll, 'total', pg.get('totalElements'), 'pages', total_pages)
        for o in (sr.get('_embedded') or {}).get('objects') or []:
            it = ((o.get('_embedded') or {}).get('indexableObject')) or o; items.append(it)
        p += 1
    return items, total_pages
def act_meta(it, state):
    m = it.get('metadata') or {}
    return dict(uuid=it.get('uuid'), handle=it.get('handle'), title=it.get('name') or md(m, 'dc.title'), act_id=md(m, 'dc.identifier.act_id') or it.get('handle'),
                act_number=md(m, 'dc.identifier.act_number'), act_year=md(m, 'dc.date.act_year'), enact_date=md(m, 'dc.date.enact_date') or md(m, 'dc.date.issued'),
                enforcement_date=md(m, 'dc.date.enforcement_date'), state=md(m, 'dc.identifier.state_name') or state, department=md(m, 'dc.identifier.department_name'),
                long_title=md(m, 'dc.title.long_title'), regional_title=md(m, 'dc.title.regional'), repealed=md(m, 'dc.identifier.repealed').lower(),
                no_of_section=md(m, 'dc.identifier.no_of_section'), source_url=f'{BASE}/handle/{it.get("handle")}')
def sec_meta(it):
    m = it.get('metadata') or {}
    return dict(uuid=it.get('uuid'), handle=it.get('handle'), name=it.get('name'), act_id=md(m, 'dc.identifier.act_id'), section_number=md(m, 'dc.identifier.section_number'),
                order_number=md(m, 'dc.identifier.order_number'), html=md(m, 'dc.identifier.section_page_note'))
def pdf_text(site, st, act):
    p = cache_path(st, 'pdf', f'{act["uuid"]}.txt.gz')
    if p.exists(): site.stats['cached'] += 1; return gzip.decompress(p.read_bytes()).decode('utf-8', 'replace')
    d = getc(site, cache_path(st, 'bundles', f'{act["uuid"]}.json.gz'), f'{API}/core/items/{act["uuid"]}/bundles', dict(embed='bitstreams'))
    for bun in ((d or {}).get('_embedded') or {}).get('bundles') or []:
        if bun.get('name') != 'ORIGINAL': continue
        bits = ((bun.get('_embedded') or {}).get('bitstreams') or {}).get('_embedded', {}).get('bitstreams') or []
        for b in bits:
            href = ((b.get('_links') or {}).get('content') or {}).get('href')
            if not href or not (b.get('name') or '').lower().endswith('.pdf'): continue
            raw = site.get(href, binary=True, timeout=(20, 300))
            if not raw or raw[:4] != b'%PDF': continue
            with tempfile.NamedTemporaryFile(suffix='.pdf') as t:
                t.write(raw); t.flush(); txt = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', t.name, '-'], capture_output=True, timeout=300).stdout
            put(p, txt); act['pdf_name'] = b.get('name'); act['pdf_bytes'] = len(raw); return txt.decode('utf-8', 'replace')
    return ''
SEC_RX = re.compile(r'(?m)^\s{0,8}(\d{1,3}[A-Z]{0,3})\.\s+[A-Z(\[]')
def run_state(site, name, info, out, limit=None):
    st = st_code(name); mem = mem_check(); log('=== STATE', name, info.get('handle'), f'mem={mem}MB')
    acts, _ = paginate(site, st, info['uuid'], 'ACT', max_pages=1 if limit else None)
    acts = [act_meta(a, name) for a in acts]
    if limit: acts = acts[:limit]
    secs, _ = paginate(site, st, info['uuid'], 'SECTION', max_pages=3 if limit else None)
    by = {}
    for s in map(sec_meta, secs): by.setdefault(s['act_id'], []).append(s)
    res = dict(state=name, acts=len(acts), sections=len(secs), html=0, pdf=0, empty=0)
    for n, a in enumerate(acts, 1):
        if site.blocked: break
        ss = by.get(a['act_id']) or []
        if ss: a['text_source'] = 'html_sections'; a['n_sections'] = len(ss); res['html'] += 1
        else:
            t = pdf_text(site, st, a); a['text_source'] = 'pdf' if t.strip() else 'none'; a['n_sections'] = len(SEC_RX.findall(t)); a['text_chars'] = len(t)
            res['pdf' if t.strip() else 'empty'] += 1
        a['fetched_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z'); out.write(json.dumps(a, ensure_ascii=False) + '\n'); out.flush()
        if n % 50 == 0: log(name, 'progress', n, '/', len(acts), site.stats, 'nreq', site.nreq, f'mem={memavail()}MB')
    log('=== STATE DONE', name, res, site.stats); return res
def main():
    mode = sys.argv[1]; want = sys.argv[2] if len(sys.argv) > 2 else 'ALL'
    threading.Thread(target=_mg, daemon=True).start()
    log('START', mode, want, 'pid', os.getpid(), 'host', HOST, f'mem={memavail()}MB')
    site = Site(); states = discover_states(site); log('states discovered', len(states))
    if want != 'ALL': states = {k: v for k, v in states.items() if st_code(k) in want.split(',') or k in want.split(',')}
    results = {}; IDX.mkdir(parents=True, exist_ok=True)
    with open(IDX / f'acts_{mode}.jsonl', 'a') as out:
        for i, (name, info) in enumerate(states.items()):
            if site.blocked: break
            if mode == 'handcheck' and i >= 5: break
            try: results[name] = run_state(site, name, info, out, limit=5 if mode == 'handcheck' else None)
            except Blocked as b: results[name] = dict(blocked=str(b)); break
            json.dump(dict(mode=mode, host=HOST, results=results, stats=site.stats, nreq=site.nreq), open(B / f'collect_result_{mode}.json', 'w'), indent=1)
    log('DONE', results, site.stats)
if __name__ == '__main__': main()
