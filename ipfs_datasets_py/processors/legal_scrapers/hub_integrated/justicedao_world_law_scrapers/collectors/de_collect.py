#!/usr/bin/env python3
"""DE subnational (Landesrecht) collector. Single process, sequential, polite.
Sites: NW recht.nrw.de, SN revosax.sachsen.de, HB transparenz.bremen.de, BB bravors.brandenburg.de (Crawl-delay 20).
robots.txt-checked per URL; 3 consecutive 403/503 per site -> BLOCKED_SOURCE (evidence under probe/).
MemAvail pause <=4600MB, self-TERM <=3584MB -> state mode=HOLD_0_DE_MEMSHED collectors=0.
Usage: de_collect.py handcheck  |  de_collect.py full [LAND,LAND,...]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, hashlib, threading, html as H
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
B = Path('{_CORPORA}/de_subnational'); RAW = B / 'raw'; PROBE = B / 'probe'; ROB = B / 'robots'
UA = 'legal-corpora-de-subnational/1.0 (research corpus of official Landesrecht; polite; contact via huggingface.co/endomorphosis)'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
SITES = {'NW': ('https://recht.nrw.de', 'recht.nrw.de', 1.0), 'SN': ('https://www.revosax.sachsen.de', 'www.revosax.sachsen.de', 1.0),
         'HB': ('https://www.transparenz.bremen.de', 'www.transparenz.bremen.de', 1.0), 'BB': ('https://bravors.brandenburg.de', 'bravors.brandenburg.de', 20.0)}
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def set_pin(**u):
    kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l); kv.update({k: str(v) for k, v in u.items()})
    open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
def term(m):
    log(f'MEMGUARD TERM MemAvailable={m}MB')
    set_pin(mode='HOLD_0_DE_MEMSHED', collectors=0, pid='', phase=f'DE collector self-TERM at MemAvail={m}MB; not restarted', ts=time.strftime('%Y-%m-%dT%H:%MPT'))
    os._exit(3)
def mem_gate():
    while True:
        m = memavail()
        if m <= 3584: term(m)
        if m <= 4600: log(f'MEM PAUSE MemAvailable={m}MB'); time.sleep(30); continue
        return
def _mg():
    while True:
        m = memavail()
        if m <= 3584: term(m)
        time.sleep(5)
threading.Thread(target=_mg, daemon=True).start()

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
        self.rules, cd = load_robots(self.host); self.delay = max(d, cd); self.c_block = 0; self.blocked = False; self.last = 0.0
        self.s = requests.Session(); self.s.headers.update({'User-Agent': UA, 'Accept-Language': 'de'})
        self.stats = dict(ok=0, cached=0, robots_skip=0, fail=0, http403_503=0)
        (RAW / land).mkdir(parents=True, exist_ok=True); self.idx = open(RAW / land / 'index.jsonl', 'a')
        log(land, 'robots rules', len(self.rules), 'delay', self.delay)
    def robots_ok(self, url):
        path = re.sub(r'^https?://[^/]+', '', url) or '/'; best = None
        for allow, n, rx in self.rules:
            if rx.match(path) and (best is None or n > best[1] or (n == best[1] and allow)): best = (allow, n)
        return best is None or best[0]
    def get(self, url, key, kind):
        """returns html text or None. Cached under raw/<LAND>/<kind>/<key>.html.gz"""
        dest = RAW / self.land / kind / f'{key}.html.gz'
        if dest.exists(): self.stats['cached'] += 1; return gzip.decompress(dest.read_bytes()).decode('utf-8', 'replace')
        if self.blocked: return None
        if not self.robots_ok(url): self.stats['robots_skip'] += 1; log(self.land, 'robots_skip', url); return None
        mem_gate(); err = ''
        for att in range(4):
            w = self.delay - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); ts = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            try: r = self.s.get(url, timeout=(20, 90), allow_redirects=True)
            except Exception as e: err = repr(e)[:200]; time.sleep(5 * (att + 1)); continue
            if r.status_code in (403, 503):
                self.c_block += 1; self.stats['http403_503'] += 1
                (PROBE / f'{self.land}_http{r.status_code}_{self.c_block}_{int(time.time())}.txt').write_text(
                    f'{ts} GET {url}\nHTTP {r.status_code}\n{dict(r.headers)}\n\n{r.text[:4000]}', encoding='utf-8')
                log(self.land, f'HTTP {r.status_code} consecutive={self.c_block}', url)
                if self.c_block >= 3: self.blocked = True; log(self.land, 'BLOCKED_SOURCE: 3 consecutive 403/503'); return None
                time.sleep(30); continue
            if r.status_code in (429, 500, 502, 504): err = f'HTTP {r.status_code}'; time.sleep(30 * (att + 1)); continue
            self.c_block = 0
            if r.status_code != 200: self.stats['fail'] += 1; log(self.land, 'fail', r.status_code, url); return None
            r.encoding = r.encoding if r.encoding and r.encoding.lower() != 'iso-8859-1' else (r.apparent_encoding or 'utf-8')
            txt = r.text; dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix('.tmp'); tmp.write_bytes(gzip.compress(txt.encode('utf-8'))); os.replace(tmp, dest)
            self.idx.write(json.dumps({'key': key, 'kind': kind, 'url': url, 'final_url': r.url, 'status': r.status_code, 'ts': ts}) + '\n'); self.idx.flush()
            self.stats['ok'] += 1; return txt
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
HAND = {'NW': dict(only={'gesetz-ueber-die-rechtsverhaeltnisse-der-mitglieder-des-landtags-nordrhein',                          'datenschutzgesetz-nordrhein-westfalen-dsg-nrw', 'polizeigesetz-des-landes-nordrhein-westfalen',
                         'gemeindeordnung-fuer-das-land-nordrhein', 'verordnung-ueber-die-ausbildung-und-pruefung-fuer-die-laufbahnen-des',
                         'bauordnung-fuer-das-land-nordrhein-westfalen-landesbauordnung-2018-bauo-nrw', 'gemeindeordnung-fuer-das-land-nordrhein-westfalen-go-nrw-bekanntmachung-der', 'kommunalwahlordnung-kwahlo', 'schulgesetz-fuer-das-land-nordrhein-westfalen-schulgesetz-nrw-schulg', 'ausbildungsordnung-grundschule-ao-gs'}),
        'SN': dict(only={'1779', '4850', '4864', '2782', '4236'}), 'HB': dict(limit=6), 'BB': dict(only=['/gesetze/bbgafoeg', '/gesetze/bbgpolg', '/verordnungen/bbgpolhv_2015', '/verordnungen/bbggav'])}
def main():
    mode = sys.argv[1]; lands = sys.argv[2].split(',') if len(sys.argv) > 2 else ['NW', 'SN', 'HB', 'BB']
    log('START', mode, lands, 'pid', os.getpid(), 'mem', memavail()); res = {}
    for land in lands:
        s = Site('NW' if land == 'NWSUP' else land); t0 = time.time()
        RUN[land](s, **(HAND.get(land, {}) if mode == 'handcheck' else {}))
        res[land] = dict(stats=s.stats, blocked_source=s.blocked, seconds=round(time.time() - t0), delay=s.delay, finished=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
        log('LAND DONE', land, res[land])
        json.dump(dict(mode=mode, result=res), open(B / f'collect_result_{mode}.json', 'w'), indent=1)
    log('DONE', res)
if __name__ == '__main__': main()
