#!/usr/bin/env python3
"""DE subnational (Landesrecht) collector, THIRD-collector edition (CoS order 2026-10-18 15:28 PT). Collect+stage only; NO publish, NO PIN writes.
Derived from de_collect.py (run_* functions unchanged). Sites: NW recht.nrw.de, SN revosax.sachsen.de, HB transparenz.bremen.de, BB bravors.brandenburg.de.
- robots.txt re-fetched live per host at start (falls back to cached copy under robots/ if the fetch fails); every URL robots-checked.
- polite delay >= 1.0s per host (max(site delay, robots Crawl-delay); BB Crawl-delay 20).
- resume: every page is cached under raw/<LAND>/<kind>/<key>.html.gz; cached pages are never refetched.
- 3-strike rule: 403, 429 and 503 are strikes; 3 consecutive strikes on a host -> log 'STOP 3 consecutive 403/429/503 strikes' and exit rc=4 (supervisor: 10-min backoff, HOLD_DE on 2nd stop within 2h).
- memory guard (same as NL-M/NLM2): pause when MemAvail<3584MB, resume when >=4200MB held 30s; hard TERM when <1500MB for 10s (2s poll); instant TERM <1000MB; RSS cap 300MB -> TERM. TERM logs 'MEMTERM' and exits rc=3.
- markers: STOP_DE / HOLD_DE (de_subnational/ or /workspace/logs/) -> clean exit rc=2 before the next request.
Usage: de_sub_collect.py full [LAND,LAND,...]   (default NW,NWSUP,SN,HB,BB)"""
import os, sys, re, json, gzip, time, hashlib, threading, html as H
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
B = Path('/workspace/legal-corpora/de_subnational'); RAW = B / 'raw'; PROBE = B / 'probe'; ROB = B / 'robots'
UA = 'legal-corpora-de-subnational/1.0 (research corpus of official Landesrecht; polite; contact via huggingface.co/endomorphosis)'
SITES = {'NW': ('https://recht.nrw.de', 'recht.nrw.de', 1.0), 'SN': ('https://www.revosax.sachsen.de', 'www.revosax.sachsen.de', 1.0),
         'HB': ('https://www.transparenz.bremen.de', 'www.transparenz.bremen.de', 1.0), 'BB': ('https://bravors.brandenburg.de', 'bravors.brandenburg.de', 20.0)}
MARKERS = [B / 'STOP_DE', B / 'HOLD_DE', Path('/workspace/logs/STOP_DE'), Path('/workspace/logs/HOLD_DE')]
G = dict(pause=3584, resume=4200, resume_hold_s=30, hard=1500, hard_s=10.0, poll_s=2.0, instant=1000, rss_mb=300)
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def rss():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS'): return int(l.split()[1]) // 1024
PAUSED = threading.Event(); MS = dict(min=10**9, pauses=0, resumes=0)
def term(why):
    log(f'MEMTERM {why} rss={rss()}MB'); os._exit(3)
def _guard():
    low = None; ok_since = None; last_stat = time.time()
    while True:
        m = memavail(); n = time.time(); MS['min'] = min(MS['min'], m)
        if m < G['instant']: term(f'instant MemAvailable={m}MB<{G["instant"]}')
        if m < G['hard']:
            low = low or n
            if n - low >= G['hard_s']: term(f'hard MemAvailable={m}MB<{G["hard"]} for {G["hard_s"]:.0f}s')
        else: low = None
        r = rss()
        if r > G['rss_mb']: term(f'RSS {r}MB>{G["rss_mb"]}')
        if not PAUSED.is_set() and m < G['pause']:
            PAUSED.set(); MS['pauses'] += 1; ok_since = None; log(f'MEMPAUSE MemAvailable={m}MB<{G["pause"]}')
        elif PAUSED.is_set():
            if m >= G['resume']:
                ok_since = ok_since or n
                if n - ok_since >= G['resume_hold_s']: PAUSED.clear(); MS['resumes'] += 1; log(f'MEMRESUME MemAvailable={m}MB held {G["resume_hold_s"]}s')
            else: ok_since = None
        if n - last_stat >= 300:
            last_stat = n; log(f'MEMSTAT memavail={m} min_memavail={MS["min"]} rss={r} pauses={MS["pauses"]} resumes={MS["resumes"]} cfg=pause{G["pause"]}/resume{G["resume"]}x{G["resume_hold_s"]}s hard<{G["hard"]}x{G["hard_s"]:.0f}s instant<{G["instant"]} rss<{G["rss_mb"]}')
        time.sleep(G['poll_s'])
threading.Thread(target=_guard, daemon=True).start()
def markers():
    for m in MARKERS:
        if m.exists(): log('MARKER', m, 'present -> clean exit'); sys.exit(2)
def mem_gate():
    while PAUSED.is_set(): time.sleep(2)
class StrikeStop(Exception): pass
def refresh_robots(host, delay):
    p = ROB / f'{host}.robots.txt'
    try:
        r = requests.get(f'https://{host}/robots.txt', headers={'User-Agent': UA}, timeout=(20, 60))
        log(host, 'robots.txt live HTTP', r.status_code, len(r.content), 'bytes')
        if r.status_code == 200:
            if p.exists() and p.read_bytes() != r.content: p.rename(p.with_name(p.name + '.bak_' + time.strftime('%Y%m%dT%H%M%S')))
            p.write_bytes(r.content)
        elif r.status_code in (403, 429, 503): log(host, 'robots.txt strike-status', r.status_code, '(cached copy used)')
        elif r.status_code == 404:
            log(host, 'robots.txt 404 -> no rules (cached copy kept if present)')
    except Exception as e: log(host, 'robots.txt fetch error', repr(e)[:160], '(cached copy used)')
    time.sleep(max(2.0, delay))

def load_robots(host):
    p = ROB / f'{host}.robots.txt'; rules = []; delay = 0.0
    if not p.exists(): return rules, delay
    groups = []; cur = None; last_ua = False
    for line in open(p, encoding='utf-8', errors='replace'):
        line = line.split('#', 1)[0].strip()
        if not line or ':' not in line: continue
        k, v = [x.strip() for x in line.split(':', 1)]; k = k.lower()
        if k == 'user-agent':
            if not last_ua: cur = {'ua': [], 'rules': [], 'delay': None}; groups.append(cur)
            cur['ua'].append(v); last_ua = True; continue
        last_ua = False
        if cur is None: continue
        if k in ('allow', 'disallow') and v:
            rx = re.escape(v).replace(r'\*', '.*'); rx = rx[:-2] + '$' if rx.endswith(r'\$') else rx
            cur['rules'].append((k == 'allow', len(v), re.compile(rx)))
        elif k == 'crawl-delay':
            try: cur['delay'] = float(v)
            except ValueError: pass
    for g in groups:
        if '*' in g['ua']: rules += g['rules']; delay = max(delay, g['delay'] or 0)
    return rules, delay
class Site:
    def __init__(self, land):
        self.land = land; self.base, self.host, d = SITES[land]
        refresh_robots(self.host, d)
        self.rules, cd = load_robots(self.host); self.delay = max(2.0, d, cd); self.c_block = 0; self.blocked = False; self.last = time.time()
        self.s = requests.Session(); self.s.headers.update({'User-Agent': UA, 'Accept-Language': 'de'})
        self.stats = dict(ok=0, cached=0, robots_skip=0, fail=0, http403_429_503=0, http404=0, timeouts=0)
        (RAW / land).mkdir(parents=True, exist_ok=True); self.idx = open(RAW / land / 'index.jsonl', 'a')
        log(land, 'host', self.host, 'robots rules', len(self.rules), 'delay', self.delay)
    def robots_ok(self, url):
        path = re.sub(r'^https?://[^/]+', '', url) or '/'; best = None
        for allow, n, rx in self.rules:
            if rx.match(path) and (best is None or n > best[1] or (n == best[1] and allow)): best = (allow, n)
        return best is None or best[0]
    def get(self, url, key, kind):
        """returns html text or None. Cached under raw/<LAND>/<kind>/<key>.html.gz (resume: cached pages never refetched)"""
        dest = RAW / self.land / kind / f'{key}.html.gz'
        if dest.exists(): self.stats['cached'] += 1; return gzip.decompress(dest.read_bytes()).decode('utf-8', 'replace')
        if not self.robots_ok(url): self.stats['robots_skip'] += 1; log(self.land, 'robots_skip', url); return None
        err = ''
        for att in range(4):
            markers(); mem_gate()
            w = self.delay - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); ts = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            try: r = self.s.get(url, timeout=(20, 90), allow_redirects=True)
            except Exception as e:
                err = repr(e)[:200]; self.stats['timeouts'] += 1; log(self.land, f'NETERR att={att + 1}', url, err[:120]); time.sleep(5 * (att + 1)); continue
            if r.status_code in (403, 429, 503):
                self.c_block += 1; self.stats['http403_429_503'] += 1
                (PROBE / f'{self.land}_http{r.status_code}_{self.c_block}_{int(time.time())}.txt').write_text(
                    f'{ts} GET {url}\nHTTP {r.status_code}\n{dict(r.headers)}\n\n{r.text[:4000]}', encoding='utf-8')
                log(self.land, f'STRIKE HTTP {r.status_code} consecutive={self.c_block}', url)
                if self.c_block >= 3:
                    self.blocked = True; log(self.land, f'STOP 3 consecutive 403/429/503 strikes on {self.host}'); raise StrikeStop(self.land)
                time.sleep(30 * self.c_block); continue
            if r.status_code in (500, 502, 504): err = f'HTTP {r.status_code}'; log(self.land, 'backoff', err, url); time.sleep(30 * (att + 1)); continue
            self.c_block = 0
            if r.status_code == 404: self.stats['http404'] += 1
            if r.status_code != 200: self.stats['fail'] += 1; log(self.land, 'fail', r.status_code, url); return None
            r.encoding = r.encoding if r.encoding and r.encoding.lower() != 'iso-8859-1' else (r.apparent_encoding or 'utf-8')
            txt = r.text; dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix('.tmp'); tmp.write_bytes(gzip.compress(txt.encode('utf-8'))); os.replace(tmp, dest)
            self.idx.write(json.dumps({'key': key, 'kind': kind, 'url': url, 'final_url': r.url, 'status': r.status_code, 'ts': ts}) + '\n'); self.idx.flush()
            self.stats['ok'] += 1; log(self.land, 'OK', r.status_code, len(txt), url) if self.stats['ok'] <= 5 or self.stats['ok'] % 25 == 0 else None
            return txt
        self.stats['fail'] += 1; log(self.land, 'fail', err, url); return None
def k(url): return hashlib.sha1(url.encode()).hexdigest()[:16]

# ---------------- NW
def nw_groups():
    groups = {}
    for u in open(PROBE / 'nw_urls.txt'):
        u = u.strip(); m = re.match(r'https://recht\.nrw\.de/lrgv/(gesetz|rechtsverordnung)/(\d{8})-(.+?)/?$', u)
        if not m: continue
        d = m.group(2); groups.setdefault((m.group(1), m.group(3)), []).append((d[4:] + d[2:4] + d[:2], u.rstrip('/')))
    return groups
def nw_versions(t):
    return {urljoin('https://recht.nrw.de/', h).rstrip('/') for h in re.findall(r"<li class=\"version-item[^\"]*\"><a href='([^']+)'", t)}
def nw_top_link(t):
    m = re.search(r'<li class="version-item[^"]*">(<span>|<a href=\'([^\']+)\')', t); return (m.group(2) if m and m.group(2) else None)
def run_nw(site, limit=None, only=None):
    G = nw_groups(); items = sorted(G.items(), key=lambda kv: max(kv[1])[0], reverse=True)  # newest groups first
    if only: items = [(g, v) for g, v in items if g[1] in only]
    if limit: items = items[:limit]
    log('NW groups', len(items)); covered = set(); fetched = set(); n = 0
    for (typ, slug), vers in items:
        if site.blocked: break
        vers = sorted(vers, reverse=True)
        for _ in range(8):
            cand = [u for d, u in vers if u not in covered]
            if not cand: break
            u = cand[0]; t = site.get(u, k(u), 'law'); covered.add(u); fetched.add(u)
            if t is None: continue
            covered |= nw_versions(t)
            top = nw_top_link(t)
            if top:  # a newer Fassung than this page exists -> fetch it (the law's current Fassung)
                tu = urljoin('https://recht.nrw.de/', top).rstrip('/')
                if tu not in fetched:
                    tt = site.get(tu, k(tu), 'law'); covered.add(tu); fetched.add(tu)
                    if tt: covered |= nw_versions(tt)
        n += 1
        if n % 100 == 0: log('NW progress', n, len(items), site.stats, 'mem', memavail())

def run_nwsup(site, limit=None, only=None):
    """supplement: fetch every NW gesetz/VO sitemap URL not yet fetched and not listed in any fetched page's Fassungen list (slug-collision groups)"""
    covered = set(); fetched = set()
    for l in open(RAW / 'NW' / 'index.jsonl'):
        r = json.loads(l); fetched.add(r['url'].rstrip('/')); fetched.add(r['final_url'].rstrip('/'))
        f = RAW / 'NW' / r['kind'] / f"{r['key']}.html.gz"
        if f.exists(): covered |= nw_versions(gzip.decompress(f.read_bytes()).decode('utf-8', 'replace'))
    covered |= fetched
    allu = sorted([(d, u) for vers in nw_groups().values() for d, u in vers], reverse=True)
    todo = [u for d, u in allu if u not in covered]; log('NWSUP uncovered', len(todo))
    n = 0
    for u in todo:
        if site.blocked: break
        if u in covered: continue
        t = site.get(u, k(u), 'law'); covered.add(u); fetched.add(u); n += 1
        if t is None: continue
        covered |= nw_versions(t); top = nw_top_link(t)
        if top:
            tu = urljoin('https://recht.nrw.de/', top).rstrip('/')
            if tu not in fetched:
                tt = site.get(tu, k(tu), 'law'); covered.add(tu); fetched.add(tu)
                if tt: covered |= nw_versions(tt)
        if n % 100 == 0: log('NWSUP progress', n, site.stats, 'mem', memavail())

# ---------------- SN
def run_sn(site, limit=None, only=None):
    urls = [u.strip() for u in open(PROBE / 'sn_keep.txt') if u.strip()]
    if only: urls = [u for u in urls if re.search(r'/vorschrift/(\d+)', u).group(1) in only]
    if limit: urls = urls[:limit]
    log('SN urls', len(urls))
    for n, u in enumerate(urls, 1):
        if site.blocked: break
        site.get(u, re.search(r'/vorschrift/(\d+)', u).group(1), 'law')
        if n % 100 == 0: log('SN progress', n, len(urls), site.stats, 'mem', memavail())

# ---------------- HB
HB_LIST = ('https://www.transparenz.bremen.de/vorschriften-72741?id=72743&gsid=kogis_tp_berlin01.c.60176.de&_article_id=72741&fulltext='
           '&vorschriften%5B0%5D=Gesetze+und+Rechtsverordnungen&gltigkeit%5B0%5D=In+Kraft&sort=titel&order=asc&max=50&skip=')
def hb_list(site, pages=None):
    out = []; skip = 0; total = None
    while True:
        t = site.get(HB_LIST + str(skip), f'list_{skip:05d}', 'list')
        if t is None: break
        if total is None:
            m = re.search(r'Ergebnisse\s+\d+\s*-\s*\d+\s+von\s+\(([\d.]+)\)', t); total = int(m.group(1).replace('.', '')) if m else 0; log('HB total', total)
        for did, body in re.findall(r'<li class="search-result-item" data-id="(\d+)">(.*?)</li>', t, re.S):
            m = re.search(r'href="(https://www\.transparenz\.bremen\.de/metainformationen/[^"]+template=20_gp_ifg_meta_detail_d)"', body)
            if m: out.append((did, H.unescape(m.group(1))))
        skip += 50
        if skip >= total or (pages and skip >= 50 * pages): break
    json.dump(out, open(RAW / 'HB' / 'hb_list.json', 'w')); return out
def run_hb(site, limit=None, only=None):
    L = hb_list(site, pages=1 if limit else None)
    if only: L = [x for x in L if x[0] in only]
    if limit: L = L[:limit]
    log('HB docs', len(L))
    for n, (did, u) in enumerate(L, 1):
        if site.blocked: break
        site.get(u, did, 'law')
        if n % 100 == 0: log('HB progress', n, len(L), site.stats, 'mem', memavail())

# ---------------- BB
def run_bb(site, limit=None, only=None):
    years = re.findall(r'href="(/de/vorschriften_fundstellennachweis_gesetzte_und_verordnungen_chronologisch/year/\d+)"', open(PROBE / 'bb_chrono.html', encoding='utf-8').read())
    years = sorted(set(years)); links = []
    if only: links = list(only)
    else:
        for y in years:
            t = site.get('https://bravors.brandenburg.de' + y, 'year_' + y.rsplit('/', 1)[1], 'list')
            if t is None: continue
            for h in re.findall(r'href="(/(?:gesetze|verordnungen)/[^"#?]+)"', t):
                if h not in links: links.append(h)
            if limit and len(links) >= limit: break
        json.dump(links, open(RAW / 'BB' / 'bb_links.json', 'w'))
    if limit: links = links[:limit]
    log('BB docs', len(links))
    for n, h in enumerate(links, 1):
        if site.blocked: break
        site.get('https://bravors.brandenburg.de' + h, h.strip('/').replace('/', '__'), 'law')
        if n % 50 == 0: log('BB progress', n, len(links), site.stats, 'mem', memavail())

RUN = {'NWSUP': run_nwsup, 'NW': run_nw, 'SN': run_sn, 'HB': run_hb, 'BB': run_bb}
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    if mode != 'full': log('only mode full is supported'); sys.exit(1)
    lands = sys.argv[2].split(',') if len(sys.argv) > 2 else ['NW', 'NWSUP', 'SN', 'HB', 'BB']
    assert all(l in RUN for l in lands), lands
    ts0 = time.strftime('%Y%m%dT%H%M%S'); out = B / f'collect_result_third_{ts0}.json'
    log('START full', lands, 'pid', os.getpid(), 'mem', memavail(), 'guard', G, 'no_pin True no_publish True result', out); markers(); res = {}
    for land in lands:
        s = Site('NW' if land == 'NWSUP' else land); t0 = time.time()
        try: RUN[land](s)
        except StrikeStop:
            res[land] = dict(stats=s.stats, blocked_source=True, seconds=round(time.time() - t0), delay=s.delay, finished=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
            json.dump(dict(mode='third', result=res), open(out, 'w'), indent=1); log('EXIT strike-stop', res); sys.exit(4)
        res[land] = dict(stats=s.stats, blocked_source=s.blocked, seconds=round(time.time() - t0), delay=s.delay, finished=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
        log('LAND DONE', land, res[land])
        json.dump(dict(mode='third', result=res), open(out, 'w'), indent=1)
    log('DONE', res); log('DE range complete (collect+stage only; no publish)')
if __name__ == '__main__': main()
