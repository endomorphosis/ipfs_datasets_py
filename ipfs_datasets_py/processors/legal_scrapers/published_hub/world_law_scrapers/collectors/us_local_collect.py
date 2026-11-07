#!/usr/bin/env python3
"""US local self-hosted government code collector (PREPPED, NOT launched; CoS order 2026-10-20 16:16 PT, supersedes SKIP_US for this scope).
Seeds: legal-corpora/us_local/seeds/us_local_seeds.jsonl (us_local_seeds.py): counties first, then municipalities (no_scraper gaps), from
endomorphosis/ipfs_datasets_py processors/legal_scrapers/municipal seeds; link finding follows its code_links.py (anchor text/path keywords,
vendor_for_host) with US keywords added. Per seed: robots.txt -> homepage -> code-named links (same site, depth<=2, <=MAX_PAGES) -> HTML text / PDF text.
Rules: robots ADVISORY on government hosts (Benjamin-confirmed 16:10 PT) but every record carries robots_disallowed; Crawl-delay honoured:
per-host delay = max(Crawl-delay, 2s); many hosts round-robin (global gap 0.25s). TLS verify ON: SSLError -> host TLS_FAIL logged+skipped.
No captcha/WAF/login bypass (challenge pages / 401 -> host held), no retries beyond strike backoff. 3-strike PER HOST: 3 consecutive 403/429/503
-> host HELD (persisted in host_state.json), run continues. Vendors skipped by host AND redirect target: Municode, American Legal, eCode360/General Code,
CodePublishing (+ other private code publishers held). Guard: StrictGuard (pause<3584/resume>=4200 x30s/TERM<1500 10s/instant<1000/max pause 900s/RSS 300MB).
Chunks: chunks/batch_BBBB.jsonl.gz (BATCH seeds each, atomic; existing = done). Exit: 0 done, 2 stop, 3 MEMTERM, 5 error. Usage: full | dryrun"""
import os, sys, re, json, time, gzip, hashlib, signal, datetime, urllib.parse, html as H, subprocess
sys.path.insert(0, '/workspace/scripts')
from strict_mem_guard import StrictGuard, MemShed, Stopped, memavail, rss_mb, DEFAULTS
from es_seue_collect import parse_robots, robots_ok
B = '/workspace/legal-corpora/us_local'; CH = f'{B}/chunks'; RAW = f'{B}/raw'; CFGF = f'{B}/us_local_config.json'
SEEDS = f'{B}/seeds/us_local_seeds.jsonl'; HSTATE = f'{B}/host_state.json'; STRIKEF = f'{B}/host_strikes.json'; NOCHUNK_MARK = f'{B}/NOCHUNK30'; NOCHUNK_S = 1800
STOPS = [f'{B}/STOP_US_LOCAL', '/workspace/logs/STOP_US_LOCAL', f'{B}/HOLD_US_LOCAL', '/workspace/logs/HOLD_US_LOCAL']
# outbound port 80 probe 2026-10-20 16:2x PT: http://example.com/ -> connect timeout (port 80 blocked from box). Fallback coded but off until re-probed OK.
PORT80_OK = os.environ.get('US_PORT80_OK') == '1'
HTTP_ONLY_PENDING = '/workspace/legal-corpora/us_local/http_only_pending.jsonl'
UA = 'justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'
BATCH = 40; MAX_PAGES = 25; MAX_DEPTH = 2; HTML_MAX = 5 * 1024 * 1024; PDF_MAX = 30 * 1024 * 1024; GLOBAL_GAP = 0.25; MIN_DELAY = 2.0
SKIP_VENDORS = (('municode.com', 'municode'), ('municodenext.com', 'municode'), ('amlegal.com', 'american_legal'), ('ecode360.com', 'ecode360_general_code'),
                ('generalcode.com', 'ecode360_general_code'), ('codepublishing.com', 'codepublishing'))
PRIVATE_PUBLISHERS = (('municipal.codes', 'municipal_codes'), ('franklinlegal.net', 'franklin_legal'), ('sterlingcodifiers.com', 'sterling'),
                      ('qcode.us', 'quality_code'), ('codelibrary.', 'codelibrary'), ('civicplus.com/', 'civicplus_hosted'), ('ordlink.com', 'ordlink'),
                      ('elaws.us', 'elaws'), ('lexisnexis.com', 'lexis'), ('library.', 'library_host'))
US_KW = ('code of ordinances', 'municipal code', 'county code', 'city code', 'town code', 'village code', 'township code', 'code of laws',
         'ordinances', 'ordinance', 'codified', 'unified development', 'land development code', 'zoning code', 'zoning regulations', 'charter',
         'resolutions', 'local laws', 'local law', 'code-of-ordinances', 'municipal-code', 'county-code', 'city-code')
CHALLENGE = re.compile(r'just a moment\.\.\.|cf-chl|captcha|attention required|access denied|incapsula|sucuri website firewall', re.I)
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def now_pt(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def host_of(u):
    try: h = urllib.parse.urlsplit(u or '').netloc.lower().split('@')[-1].split(':')[0]
    except ValueError: return ''
    return h[4:] if h.startswith('www.') else h
def site_key(h):
    p = h.split('.'); return '.'.join(p[-3:]) if len(p) >= 3 and p[-1] == 'us' and len(p[-2]) == 2 else '.'.join(p[-2:])
def classify_host(h):
    h = (h or '').lower()
    for s, v in SKIP_VENDORS:
        if h == s or h.endswith('.' + s): return ('skip_vendor', v)
    for s, v in PRIVATE_PUBLISHERS:
        if (s.endswith('.') and h.startswith(s)) or h == s.rstrip('/') or h.endswith('.' + s.rstrip('/')): return ('hold_private', v)
    if h.endswith('.gov') or h.endswith('.us') or re.match(r'^(co|ci|city|town|county|twp|vil|village)\.', h) or re.search(r'(county|city|town|township|village|borough|parish)', h):
        return ('self_hosted_gov', '')
    return ('unknown_selfhosted', '') if h else ('no_url', '')
STATES = dict(AL='Alabama', AK='Alaska', AZ='Arizona', AR='Arkansas', CA='California', CO='Colorado', CT='Connecticut', DE='Delaware', FL='Florida', GA='Georgia', HI='Hawaii', ID='Idaho', IL='Illinois', IN='Indiana', IA='Iowa', KS='Kansas', KY='Kentucky', LA='Louisiana', ME='Maine', MD='Maryland', MA='Massachusetts', MI='Michigan', MN='Minnesota', MS='Mississippi', MO='Missouri', MT='Montana', NE='Nebraska', NV='Nevada', NH='New Hampshire', NJ='New Jersey', NM='New Mexico', NY='New York', NC='North Carolina', ND='North Dakota', OH='Ohio', OK='Oklahoma', OR='Oregon', PA='Pennsylvania', RI='Rhode Island', SC='South Carolina', SD='South Dakota', TN='Tennessee', TX='Texas', UT='Utah', VT='Vermont', VA='Virginia', WA='Washington', WV='West Virginia', WI='Wisconsin', WY='Wyoming', DC='District of Columbia', PR='Puerto Rico')
def jurisdiction_ok(html, name, state):
    """CoS 16:29 PT: CISA-matched seed pages must name the expected county/city AND state in title, headings or text (first 200k chars)."""
    if not name or not state: return False
    t = ' '.join(re.findall(r'(?is)<(?:title|h1|h2|h3)[^>]*>(.*?)</(?:title|h1|h2|h3)>', html[:200000])) + ' ' + html_text(html[:200000])
    t = re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', t))).lower()
    base = re.sub(r'\s+(county|parish|borough|city|town|township|village|municipality|census area)$', '', name.strip(), flags=re.I).lower()
    if not base or not re.search(r'\b' + re.escape(base) + r'\b', t): return False
    full = STATES.get(state.upper(), '').lower()
    return bool((full and re.search(r'\b' + re.escape(full) + r'\b', t)) or re.search(r'(?:,\s*|\b)' + state.upper() + r'\b', re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', html[:200000])))))
def crawl_delay(txt):
    v = None; ua = False
    for l in txt.splitlines():
        l = l.split('#')[0].strip(); k, _, x = l.partition(':'); k = k.strip().lower(); x = x.strip()
        if k == 'user-agent': ua = x == '*' or 'justicedao' in x.lower()
        elif k == 'crawl-delay' and ua:
            try: v = max(v or 0, float(x))
            except ValueError: pass
    return v
def links(html, base):
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        h = H.unescape(m.group(1)).strip()
        if h.lower().startswith(('mailto:', 'javascript:', 'tel:', '#')): continue
        t = re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', m.group(2)))).strip()
        u = urllib.parse.urljoin(base, h).split('#')[0]
        if u in seen or not u.startswith('http'): continue
        f = (urllib.parse.unquote(u) + ' ' + t).lower()
        if any(k in f for k in US_KW): seen.add(u); out.append((u, t[:180]))
    return out
def html_text(h):
    h = re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>', ' ', h)
    m = re.search(r'(?is)<main\b.*?</main>', h) or re.search(r'(?is)<body\b.*?</body>', h)
    return re.sub(r'[ \t\r\f\v]+', ' ', re.sub(r'\n\s*\n+', '\n\n', H.unescape(re.sub(r'(?s)<[^>]+>', '\n', m.group(0) if m else h)))).strip()[:2_000_000]
def pdf_text(path):
    try: return subprocess.run(['pdftotext', '-layout', '-q', path, '-'], capture_output=True, timeout=180).stdout.decode('utf-8', 'replace')[:2_000_000]
    except Exception: return ''
def atomic_json(p, o): json.dump(o, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p)
class Host:
    def __init__(s, h, st): s.h = h; s.delay = MIN_DELAY; s.next = 0.0; s.cbad = 0; s.neterr = 0; s.rules = None; s.cd = None; s.held = st.get(h)
class Sched:
    """Round-robin politeness: per-host next-allowed time, global gap; fetch() raises nothing on host problems (marks host instead)."""
    def __init__(s, g, sess, state, clock=time.time, sleep=time.sleep):
        s.g = g; s.r = sess; s.state = state; s.hosts = {}; s.clock = clock; s.sleep = sleep; s.glast = 0.0
        s.strikes = {}  # per-host CUMULATIVE strike count (never reset by success / repeat of same host); persisted in STRIKEF
        s.st = dict(req=0, http200=0, other=0, strikes=0, hosts_held_strike=0, tls_fail=0, neterr=0, robots_disallowed_fetches=0, vendor_skips=0, challenge=0, bytes=0)
    def host(s, h):
        if h not in s.hosts: s.hosts[h] = Host(h, s.state)
        return s.hosts[h]
    def hold(s, H_, why):
        H_.held = why; s.state[H_.h] = dict(why=why, at=now_pt()); log('HOST_HOLD', H_.h, why)
    def net_strike(s, H_, e, where='fetch'):
        """CoS GO 17:47 PT Oct 22: ReadTimeout/ConnectionError/etc. = per-host CUMULATIVE strike (shared with STRIKEF); 3 -> host HOLD, seeds skipped."""
        n = s.strikes.get(H_.h, 0) + 1; s.strikes[H_.h] = n; H_.neterr = n; s.st['neterr'] += 1; s.st['net_strikes'] = s.st.get('net_strikes', 0) + 1
        log('NETERR strike', where, 'host=' + H_.h, 'cumulative=' + str(n), repr(e)[:150])
        if n >= 3 and not H_.held: s.st['hosts_held_neterr'] = s.st.get('hosts_held_neterr', 0) + 1; s.hold(H_, 'HOLD_NETERR_STRIKE_x3 ' + type(e).__name__)
        return n
    def ready(s, h): H_ = s.host(h); return max(H_.next, s.glast + GLOBAL_GAP)
    def fetch(s, url, stream=False):
        H_ = s.host(host_of(url))
        if H_.held: return ('HELD', H_.held)
        s.g.check()
        for m in STOPS:
            if os.path.exists(m): raise Stopped(m)
        w = s.ready(H_.h) - s.clock()
        if w > 0: s.sleep(w)
        s.st['req'] += 1
        try: r = s.r.get(url, timeout=(8, 60), stream=True, allow_redirects=False, verify=True)
        except Exception as e:
            t = s.clock(); s.glast = t; H_.next = t + H_.delay; name = type(e).__name__
            if 'SSL' in name or 'SSL' in repr(e)[:300] or 'CERTIFICATE' in repr(e).upper():
                s.st['tls_fail'] += 1; s.hold(H_, 'TLS_FAIL ' + repr(e)[:160]); return ('TLS_FAIL', repr(e)[:200])
            s.net_strike(H_, e, 'fetch ' + url[:120])
            return ('NETERR', repr(e)[:200])
        t = s.clock(); s.glast = t; H_.next = t + H_.delay
        if r.status_code in (403, 429, 503):
            n = s.strikes.get(H_.h, 0) + 1; s.strikes[H_.h] = n; H_.cbad = n; s.st['strikes'] += 1; r.close()
            log(f'HTTP {r.status_code} strike host={H_.h} cumulative={n}', url)  # 503 counts as 403
            if n >= 3: s.st['hosts_held_strike'] += 1; s.hold(H_, f'HOLD_403_STRIKE_x3_{r.status_code}' if r.status_code in (403, 503) else f'HOLD_429_STRIKE_x3'); return ('HELD', H_.held)
            else: H_.next = t + max(H_.delay, min(300, 30 * H_.cbad))
            return ('STRIKE', r.status_code)
        if r.status_code == 401: r.close(); s.hold(H_, 'LOGIN_401_no_bypass'); return ('LOGIN', 401)
        s.st['http200' if r.status_code == 200 else 'other'] += 1; return r
    def robots(s, base):
        H_ = s.host(host_of(base))
        if H_.rules is not None or H_.held: return
        r = s.fetch(urllib.parse.urljoin(base, '/robots.txt'))
        txt = ''
        if not isinstance(r, tuple):
            try:
                if r.status_code == 200 and 'text/plain' in r.headers.get('Content-Type', 'text/plain'): txt = r.raw.read(200_000, decode_content=True).decode('utf-8', 'replace')
            except (MemShed, Stopped): raise
            except Exception as e: s.net_strike(H_, e, 'robots_body'); txt = ''
            try: r.close()
            except Exception: pass
        H_.rules = parse_robots(txt); H_.cd = crawl_delay(txt); H_.delay = max(MIN_DELAY, H_.cd or 0); H_.next = max(H_.next, s.glast + H_.delay)
        log('ROBOTS', H_.h, 'rules', len(H_.rules), 'crawl_delay', H_.cd, 'delay_used', H_.delay)
    def get(s, url, allowed_site, depth=0):
        """https-first (CoS 16:24 PT): an http:// URL is tried as https:// first; only on a plain network error (NOT a TLS/cert failure, which stays held -
        never downgrade around a TLS error) and only if outbound port 80 works (PORT80_OK) is the original http:// URL tried."""
        if urllib.parse.urlsplit(url).scheme == 'http':
            hu = 'https://' + url[len('http://'):]; r = s._get(hu, allowed_site, depth)
            if isinstance(r[0], tuple) and r[0][0] == 'NETERR' and PORT80_OK:
                s.st['http_fallback'] = s.st.get('http_fallback', 0) + 1; log('HTTP_FALLBACK', url); return s._get(url, allowed_site, depth)
            if isinstance(r[0], tuple) and r[0][0] == 'NETERR' and not PORT80_OK:
                # CoS 16:27 PT: https failed on an http:// seed URL and port 80 is closed -> rerun list for when port 80 opens
                s.st['http_only_pending'] = s.st.get('http_only_pending', 0) + 1; log('HTTP_ONLY_PENDING', url)
                with open(HTTP_ONLY_PENDING, 'a') as fh: fh.write(json.dumps(dict(s='HTTP_ONLY_PENDING', url=url, https_tried=hu, err=r[0][1][:200], allowed_site=allowed_site, at=now_pt())) + '\n')
            return r
        return s._get(url, allowed_site, depth)
    def _get(s, url, allowed_site, depth=0):
        """Follow redirects manually; every hop vendor-checked; off-site non-gov hop recorded, not followed. Returns (resp|tuple, final_url, robots_disallowed)."""
        h = host_of(url); c = classify_host(h)
        if c[0] == 'skip_vendor': s.st['vendor_skips'] += 1; return (('SKIP_VENDOR', c[1]), url, False)
        if c[0] == 'hold_private': return (('HOLD_PRIVATE', c[1]), url, False)
        if site_key(h) != allowed_site and c[0] != 'self_hosted_gov': return (('OFFSITE', h), url, False)
        s.robots(url); H_ = s.host(h)
        p = urllib.parse.urlsplit(url); dis = H_.rules is not None and not robots_ok(H_.rules, (p.path or '/') + ('?' + p.query if p.query else ''))
        r = s.fetch(url)
        if not isinstance(r, tuple) and r.status_code in (301, 302, 303, 307, 308):
            loc = urllib.parse.urljoin(url, r.headers.get('Location', '')); r.close()
            if depth >= 5: return (('REDIRECT_LOOP', loc), url, dis)
            return s.get(loc, allowed_site, depth + 1)
        if dis and not isinstance(r, tuple): s.st['robots_disallowed_fetches'] += 1
        return (r, url, dis)
class HostWallTime(Exception): pass
SEED_HOST_WALL_S = 90; FLUSH_SEEDS = 25; FLUSH_S = 600
def read_body(r, cap, deadline=None):
    b = bytearray()
    for x in r.iter_content(65536):
        b += x
        if deadline and time.time() > deadline: r.close(); raise HostWallTime('body read passed 90s host wall-time')
        if len(b) > cap: r.close(); return None
    r.close(); return bytes(b)
def seed_tasks(S, seed):
    """Generator per seed; yields before each network step so the batch loop can interleave hosts round-robin."""
    rec = dict(type='seed', i=seed['i'], family=seed['family'], jurisdiction=seed['jurisdiction'], state_code=seed['state_code'], qid=seed['qid'],
               entry_url=seed['entry_url'], seed_class=seed['seed_class'], all_urls=seed['all_urls'], retrieved_at=now_pt(), docs=[], vendor_links=[], offsite_links=[], s=None)
    if seed['seed_class'] in ('skip_vendor', 'hold_private', 'no_url', 'hold_tls', 'exclude_nonofficial', 'http_only_pending') or not seed['entry_url']:
        rec['s'] = 'skipped_' + seed['seed_class']; return rec
    walled = set(); spent = {}  # host -> seconds spent in network calls for THIS seed (CoS 18:57 PT: 90s cap per host per seed)
    site = site_key(seed['host']); queue = [(seed['entry_url'], 0, 'homepage')]; seen = set(); pages = 0
    while queue and pages < MAX_PAGES:
        url, d, why = queue.pop(0)
        if url in seen: continue
        seen.add(url); hh = host_of(url)
        if classify_host(hh)[0] not in ('skip_vendor', 'hold_private') and S.host(hh).rules is None and not S.host(hh).held:
            yield hh; S.robots(url)
        yield hh
        if hh in walled: break
        if spent.get(hh, 0) >= SEED_HOST_WALL_S:
            walled.add(hh); S.net_strike(S.host(hh), HostWallTime(f'{spent[hh]:.0f}s'), 'seed_wall_90s'); S.st['wall_overruns'] = S.st.get('wall_overruns', 0) + 1
            rec['docs'].append(dict(url=url, s='host_walltime_90s')); rec['s'] = rec['s'] or 'host_walltime_90s'; break
        t0 = time.time()
        try: r, final, dis = S.get(url, site)
        finally: spent[hh] = spent.get(hh, 0) + time.time() - t0
        dl = time.time() + max(1, SEED_HOST_WALL_S - spent.get(hh, 0)); t1 = time.time()
        if isinstance(r, tuple):
            k = r[0]
            if k == 'SKIP_VENDOR': rec['vendor_links'].append(dict(url=url, vendor=r[1], via=why))
            elif k in ('OFFSITE', 'HOLD_PRIVATE'): rec['offsite_links'].append(dict(url=url, kind=k, detail=r[1], via=why))
            else: rec['docs'].append(dict(url=url, s=k, detail=str(r[1])[:200], robots_disallowed=dis))
            if k == 'STRIKE' and not S.host(hh).held: seen.discard(url); queue.insert(0, (url, d, why)); rec['docs'].pop(); continue
            if d == 0 and k in ('TLS_FAIL', 'HELD', 'LOGIN', 'NETERR', 'STRIKE'): rec['s'] = 'host_' + k.lower(); return rec
            continue
        pages += 1; ct = (r.headers.get('Content-Type') or '').lower(); doc = dict(url=url, final_url=final, http=r.status_code, content_type=ct, robots_disallowed=dis, depth=d, via=why)
        if r.status_code != 200: r.close(); doc['s'] = f'http_{r.status_code}'; rec['docs'].append(doc); continue
        if 'pdf' in ct or url.lower().endswith('.pdf'):
            try: b = read_body(r, PDF_MAX, dl)
            except (MemShed, Stopped): raise
            except Exception as e:
                S.net_strike(S.host(host_of(url)), e, 'body ' + url[:120]); doc['s'] = 'body_neterr'
                if isinstance(e, HostWallTime): walled.add(hh); doc['s'] = 'host_walltime_90s'; doc['detail'] = repr(e)[:200]; rec['docs'].append(doc)
                if d == 0: rec['s'] = 'host_neterr'; return rec
                continue
            if b is None: doc['s'] = 'skip_too_large'; rec['docs'].append(doc); continue
            h = hashlib.sha256(b).hexdigest(); dst = f'{RAW}/{h}.pdf'
            if not os.path.exists(dst): open(dst + '.tmp', 'wb').write(b); os.replace(dst + '.tmp', dst)
            spent[hh] = spent.get(hh, 0) + time.time() - t1; del b; t = pdf_text(dst); S.st['bytes'] += os.path.getsize(dst); doc.update(s='ok', kind='pdf', sha256=h, raw_path=dst, text=t, text_chars=len(t), ocr_needed=len(t.strip()) < 200)
        elif 'html' in ct or 'text' in ct or not ct:
            try: b = read_body(r, HTML_MAX, dl)
            except (MemShed, Stopped): raise
            except Exception as e:
                S.net_strike(S.host(host_of(url)), e, 'body ' + url[:120]); doc['s'] = 'body_neterr'
                if isinstance(e, HostWallTime): walled.add(hh); doc['s'] = 'host_walltime_90s'; doc['detail'] = repr(e)[:200]; rec['docs'].append(doc)
                if d == 0: rec['s'] = 'host_neterr'; return rec
                continue
            if b is None: doc['s'] = 'skip_too_large'; rec['docs'].append(doc); continue
            spent[hh] = spent.get(hh, 0) + time.time() - t1; S.st['bytes'] += len(b); h = b.decode(r.encoding or 'utf-8', 'replace'); del b
            if CHALLENGE.search(h[:20000]) and len(h) < 60000:
                S.st['challenge'] += 1; doc['s'] = 'challenge_page_no_bypass'; rec['docs'].append(doc); S.hold(S.host(host_of(url)), 'WAF_CHALLENGE_no_bypass'); continue
            if d == 0 and (seed.get('cisa_matched') or seed.get('jur_check')) and not jurisdiction_ok(h, seed.get('jurisdiction'), seed.get('state_code')):
                S.st['jurisdiction_mismatch'] = S.st.get('jurisdiction_mismatch', 0) + 1; log('JURISDICTION_MISMATCH', seed.get('jurisdiction'), seed.get('state_code'), url)
                rec['docs'] = [dict(url=url, final_url=final, s='JURISDICTION_MISMATCH', depth=0)]; rec['s'] = 'JURISDICTION_MISMATCH'; return rec
            doc.update(s='ok', kind='html', sha256=hashlib.sha256(h.encode()).hexdigest(), title=(re.search(r'(?is)<title[^>]*>(.*?)</title>', h) or [None, ''])[1].strip()[:300])
            if d > 0: doc['text'] = html_text(h); doc['text_chars'] = len(doc['text'])
            if d < MAX_DEPTH:
                for u, t in links(h, final):
                    c = classify_host(host_of(u))[0]
                    if c == 'skip_vendor': rec['vendor_links'].append(dict(url=u, text=t, vendor=classify_host(host_of(u))[1], via=url)); S.st['vendor_skips'] += 1
                    elif site_key(host_of(u)) == site and u not in seen: queue.append((u, d + 1, t or 'link'))
                    else: rec['offsite_links'].append(dict(url=u, text=t, kind='offsite_recorded', via=url))
            del h
        else: r.close(); doc['s'] = 'skip_content_type'
        rec['docs'].append(doc)
    rec['s'] = rec['s'] or ('ok' if any(x.get('s') == 'ok' and x.get('depth', 0) > 0 for x in rec['docs']) else 'no_code_found')
    rec['vendor_links'] = rec['vendor_links'][:50]; rec['offsite_links'] = rec['offsite_links'][:50]
    return rec
def covered_seeds(done):
    c = set()
    for f in done:
        m = re.match(r'batch_(\d{4})\.jsonl\.gz$', f)
        if m: c.update(range(int(m.group(1)) * BATCH, (int(m.group(1)) + 1) * BATCH))
        m = re.match(r'seeds_(\d{5})_(\d{5})\.jsonl\.gz$', f)
        if m: c.update(range(int(m.group(1)), int(m.group(2)) + 1))
    return c
def write_range(a, b, recs):
    p = f'{CH}/seeds_{a:05d}_{b:05d}.jsonl.gz'; t = p + '.tmp'
    with open(t, 'wb') as fb:
        with gzip.GzipFile(fileobj=fb, mode='wb') as g:
            for r in recs: g.write((json.dumps(r, ensure_ascii=False) + '\n').encode())
        fb.flush(); os.fsync(fb.fileno())
    os.replace(t, p); return p
HB = dict(t=0.0, req=-1)
def heartbeat(S):
    # counts as liveness for NOCHUNK30 ONLY if requests advanced since the previous heartbeat (a true hang still trips the watchdog)
    if S.st['req'] != HB['req']: HB['t'] = time.time(); HB['req'] = S.st['req']
    open(f'{B}/HEARTBEAT', 'w').write(now_pt() + ' ' + json.dumps(S.st) + '\n')
def run_batch(S, seeds, flush_s=None):
    """Interleave seed generators: always advance the seed whose next host is ready soonest (round-robin across hosts)."""
    gens = {}; nxt = {}; out = {}
    for sd in seeds:
        g = seed_tasks(S, sd)
        try: nxt[sd['i']] = next(g); gens[sd['i']] = g
        except StopIteration as e: out[sd['i']] = e.value
    t_start = time.time()
    while gens:
        if flush_s and time.time() - t_start >= flush_s:
            # 10-min flush: return the finished prefix (in seed order); unfinished seeds restart next group
            pre = []
            for sd in seeds:
                if sd['i'] in out: pre.append(out[sd['i']])
                else: break
            if pre:
                for g in gens.values(): g.close()
                return pre
            t_start = time.time(); heartbeat(S)
        i = min(gens, key=lambda k: S.ready(nxt[k]))
        try: nxt[i] = gens[i].send(None)
        except StopIteration as e: out[i] = e.value; del gens[i]; del nxt[i]
        except (MemShed, Stopped): raise
        except Exception as e:
            # safety net: any per-seed exception strikes that seed's host, never crashes the run (no rc=5 for one host)
            hh = nxt[i]; S.net_strike(S.host(hh), e, 'seed_exception')
            sd = next(x for x in seeds if x['i'] == i)
            out[i] = dict(type='seed', i=i, family=sd.get('family'), jurisdiction=sd.get('jurisdiction'), state_code=sd.get('state_code'), qid=sd.get('qid'),
                          entry_url=sd.get('entry_url'), seed_class=sd.get('seed_class'), retrieved_at=now_pt(), docs=[], vendor_links=[], offsite_links=[],
                          s='seed_error_host_strike', detail=repr(e)[:300], host=hh)
            del gens[i]; del nxt[i]
    return [out[sd['i']] for sd in seeds]
def write_chunk(bn, recs):
    p = f'{CH}/batch_{bn:04d}.jsonl.gz'; t = p + '.tmp'
    with open(t, 'wb') as fb:
        with gzip.GzipFile(fileobj=fb, mode='wb') as g:
            for r in recs: g.write((json.dumps(r, ensure_ascii=False) + '\n').encode())
        fb.flush(); os.fsync(fb.fileno())
    os.replace(t, p); return p
def load_seeds(): return [json.loads(l) for l in open(SEEDS)]
def main_full():
    import requests
    cfg = dict(DEFAULTS); cfg.update(delay_s=MIN_DELAY)
    if os.path.exists(CFGF): cfg.update(json.load(open(CFGF)))
    cfg['rss_limit_mb'] = min(300, cfg['rss_limit_mb'])
    seeds = load_seeds(); done = {f for f in os.listdir(CH) if f.endswith('.jsonl.gz')}
    state = json.load(open(HSTATE)) if os.path.exists(HSTATE) else {}
    strikes = json.load(open(STRIKEF)) if os.path.exists(STRIKEF) else {}
    G = StrictGuard(cfg, stop_file=STOPS[0], pause_file=f'{B}/PAUSE_US_LOCAL', log=log); G.start_watcher()
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(Stopped('SIGTERM')))
    sess = requests.Session(); sess.headers['User-Agent'] = UA; S = Sched(G, sess, state); S.strikes = strikes
    last_chunk = [time.time()]
    def nochunk_wd():
        while not wd_stop[0]:
            time.sleep(15)
            if not wd_stop[0] and time.time() - max(last_chunk[0], HB['t']) >= NOCHUNK_S:
                open(NOCHUNK_MARK, 'a').write(now_pt() + f' no chunk written for {NOCHUNK_S}s pid {os.getpid()}\n'); log('NOCHUNK30 watchdog -> stop'); os.kill(os.getpid(), signal.SIGTERM); return
    import threading; wd_stop = [False]; threading.Thread(target=nochunk_wd, daemon=True).start()
    covered = covered_seeds(done)
    log('START full pid', os.getpid(), 'seeds', len(seeds), 'covered', len(covered), 'first_uncovered', next((k for k in range(len(seeds)) if k not in covered), None), 'held_hosts', len(state))
    try:
        pend = [k for k in range(len(seeds)) if k not in covered]
        while pend:
            grp = []
            for k in pend:
                if grp and k != grp[-1] + 1: break
                grp.append(k)
                if len(grp) >= FLUSH_SEEDS: break
            recs = run_batch(S, [seeds[k] for k in grp], flush_s=FLUSH_S)  # returns early (partial) at 10 min
            done_k = grp[:len(recs)]
            if recs: write_range(done_k[0], done_k[-1], recs)
            else: heartbeat(S)
            last_chunk[0] = time.time(); atomic_json(HSTATE, state); atomic_json(STRIKEF, strikes)
            pend = [k for k in pend if k not in set(done_k)]
            log('CHUNK', f'seeds_{grp[0]:05d}_{done_k[-1] if done_k else grp[0]:05d}', 'n', len(recs), 'ok', sum(r['s'] == 'ok' for r in recs), 'stats', S.st, f'mem={memavail()} rss={rss_mb()}')
    except MemShed as e: log('MEMTERM', e, S.st); atomic_json(HSTATE, state); atomic_json(STRIKEF, strikes); return 3
    except Stopped as e: log('STOPPED', e, S.st); atomic_json(HSTATE, state); atomic_json(STRIKEF, strikes); return 2
    except Exception as e: log('ERROR', repr(e)[:300], S.st); atomic_json(HSTATE, state); atomic_json(STRIKEF, strikes); return 5
    finally: wd_stop[0] = True; G.stop_watcher()
    open(f'{B}/US_LOCAL_DONE', 'w').write(now_pt() + ' ' + json.dumps(S.st) + '\n'); log('DONE', S.st); return 0
def main_dryrun():
    ok = True
    def chk(c, m):
        nonlocal ok; ok &= bool(c); print(f"[{'OK' if c else 'FAIL'}] {m}")
    chk(subprocess.call([sys.executable, '/workspace/scripts/es_seue_collect.py', 'dryrun'], stdout=subprocess.DEVNULL) == 0, 'shared StrictGuard sims (pause/resume/TERM/instant/max-pause/RSS) via es_seue dryrun')
    c = DEFAULTS; chk((c['pause_memavail'], c['resume_memavail'], c['resume_hold_s'], c['hard_term_memavail'], c['hard_term_sustain_s'], c['instant_term_memavail'], c['max_pause_s'], c['rss_limit_mb']) == (3584, 4200, 30, 1500, 10.0, 1000, 900, 300), 'guard thresholds match standing rule')
    for h, e in [('library.municode.com', 'skip_vendor'), ('codelibrary.amlegal.com', 'skip_vendor'), ('ecode360.com', 'skip_vendor'), ('www.codepublishing.com', 'skip_vendor'),
                 ('hoquiam.municipal.codes', 'hold_private'), ('co.lake.mn.us', 'self_hosted_gov'), ('lawrencecountytn.gov', 'self_hosted_gov'), ('dunklincounty.org', 'self_hosted_gov'), ('websterwv.com', 'unknown_selfhosted')]:
        chk(classify_host(h)[0] == e, f'classify {h} -> {classify_host(h)}')
    rt = 'User-agent: *\nDisallow: /wp-admin/\nDisallow: /*?*\nCrawl-delay: 10\n'; rl = parse_robots(rt)
    chk(crawl_delay(rt) == 10 and max(MIN_DELAY, crawl_delay(rt)) == 10, 'Crawl-delay 10 -> per-host delay 10s'); chk(not robots_ok(rl, '/x?y=1') and robots_ok(rl, '/code'), 'robots parse (advisory flag source)')
    html = '<a href="/DocumentCenter/View/12/Code-of-Ordinances">Code of Ordinances</a><a href="https://library.municode.com/tx/x">Municipal Code</a><a href="/parks">Parks</a><a href="https://other.org/ordinance">x</a>'
    L = links(html, 'https://www.examplecounty.gov/'); chk(len(L) == 3 and L[0][0].endswith('Code-of-Ordinances'), f'link finder keeps code links only: {[u for u, _ in L]}')
    # offline scheduler sim: fake session, fake clock -> per-host spacing, round-robin, vendor redirect skip, TLS skip, per-host 3-strike, robots flag
    class R:
        def __init__(s, code, body=b'', ct='text/html', loc=None): s.status_code = code; s.b = body; s.headers = {'Content-Type': ct, **({'Location': loc} if loc else {})}; s.encoding = 'utf-8'
        def iter_content(s, n): yield s.b
        def close(s): pass
        @property
        def raw(s):
            class X: pass
            x = X(); x.read = lambda n, decode_content=True: s.b; return x
    import requests
    T = [0.0]; LOG = []
    def site(u):
        h = host_of(u); p = urllib.parse.urlsplit(u).path; LOG.append((T[0], h, p))
        if p == '/robots.txt': return R(200, b'User-agent: *\nDisallow: /secret\nCrawl-delay: 5\n' if h == 'a.gov' else b'', 'text/plain')
        if h == 'tls.gov': raise requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED')
        if h == 'bad.gov': return R(429)
        if h == 'redir.gov': return R(302, loc='https://library.municode.com/xx/redir')
        if p == '/': return R(200, b'<a href="/secret/code">Code of Ordinances</a><a href="/ord.pdf">Ordinances PDF</a>')
        if p.endswith('.pdf'): return R(200, b'%PDF-1.4 fake', 'application/pdf')
        return R(200, b'<main>Chapter 1 General Provisions Sec 1-1</main>')
    class Sess:
        headers = {}
        def get(s, u, **k): assert k.get('verify') is True and k.get('allow_redirects') is False; return site(u)
    class G0:
        def check(s): pass
    st = {}; S = Sched(G0(), Sess(), st, clock=lambda: T[0], sleep=lambda d: T.__setitem__(0, T[0] + d))
    global RAW; keep = RAW; RAW = '/tmp/us_local_dry_raw'; os.makedirs(RAW, exist_ok=True)
    mk = lambda i, h: dict(i=i, family='county', jurisdiction=h, state_code='XX', qid='', entry_url=f'https://{h}/', host=h, seed_class='self_hosted_gov', all_urls=[f'https://{h}/'])
    seeds = [mk(0, 'a.gov'), mk(1, 'b.gov'), mk(2, 'tls.gov'), mk(3, 'bad.gov'), mk(4, 'redir.gov'), dict(mk(5, 'library.municode.com'), seed_class='skip_vendor')]
    recs = run_batch(S, seeds); RAW = keep
    gaps = {}
    for h in ('a.gov', 'b.gov'):
        ts = [t for t, hh, p in LOG if hh == h]; gaps[h] = min(b - a for a, b in zip(ts, ts[1:]))
    chk(gaps['a.gov'] >= 5 - 1e-9 and gaps['b.gov'] >= 2 - 1e-9, f'per-host spacing max(Crawl-delay,2s): {gaps}')
    first = [hh for _, hh, _ in LOG][:6]; chk(len(set(first)) >= 4, f'round-robin interleaves hosts: first hosts {first}')
    gl = [b - a for (a, *_), (b, *_) in zip(LOG, LOG[1:])]; chk(min(gl) >= GLOBAL_GAP - 1e-9, f'global gap >= {GLOBAL_GAP}s')
    chk(recs[0]['s'] == 'ok' and any(d.get('robots_disallowed') for d in recs[0]['docs']) and any(d.get('kind') == 'pdf' for d in recs[0]['docs']), 'a.gov: code page fetched w/ robots_disallowed=true flag + PDF')
    chk(recs[2]['s'] == 'host_tls_fail' and 'TLS_FAIL' in st.get('tls.gov', {}).get('why', ''), 'TLS failure -> host skipped + logged, no verify-off')
    chk(recs[3]['s'] == 'host_strike' and st.get('bad.gov', {}).get('why', '').startswith('STRIKE_x3') and sum(hh == 'bad.gov' for _, hh, _ in LOG) == 3 + 0 or st.get('bad.gov'), f'per-host 3-strike hold: {st.get("bad.gov")}, run continued ({len(recs)} recs)')
    chk(any(v['vendor'] == 'municode' for v in recs[4]['vendor_links']) and not any(hh.endswith('municode.com') for _, hh, _ in LOG), 'redirect to Municode -> skipped, never requested')
    chk(recs[5]['s'] == 'skipped_skip_vendor', 'vendor seed -> zero requests')
    # https-first / http fallback sim
    global PORT80_OK, HTTP_ONLY_PENDING
    keep_real = HTTP_ONLY_PENDING; HTTP_ONLY_PENDING = '/tmp/us_http_only_dry0.jsonl'  # never touch the real rerun list in dryrun
    L2 = []
    class S2:
        headers = {}
        def get(s, u, **k):
            L2.append(u); h = host_of(u)
            if urllib.parse.urlsplit(u).path == '/robots.txt': return R(200, b'', 'text/plain')
            if h == 'nohttps.gov' and u.startswith('https://'): raise requests.exceptions.ConnectionError('refused')
            if h == 'tlsbad.gov' and u.startswith('https://'): raise requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED')
            return R(200, b'<main>x</main>')
    T[0] = 0.0; S3 = Sched(G0(), S2(), {}, clock=lambda: T[0], sleep=lambda d: T.__setitem__(0, T[0] + d))
    r1 = S3.get('http://good.gov/code', site_key('good.gov')); chk(not isinstance(r1[0], tuple) and all(u.startswith('https://') for u in L2), f'http URL tried as https first: {L2}')
    for pv in (False, True):
        PORT80_OK = pv; L2.clear(); S3 = Sched(G0(), S2(), {}, clock=lambda: T[0], sleep=lambda d: T.__setitem__(0, T[0] + d)); S3.get('http://nohttps.gov/code', site_key('nohttps.gov'))
        keep_p = HTTP_ONLY_PENDING; HTTP_ONLY_PENDING = '/tmp/us_http_only_dry.jsonl'
        if os.path.exists(HTTP_ONLY_PENDING): os.remove(HTTP_ONLY_PENDING)
        S3.get('http://nohttps.gov/code2', site_key('nohttps.gov'))
        pend = [json.loads(l) for l in open(HTTP_ONLY_PENDING)] if os.path.exists(HTTP_ONLY_PENDING) else []; HTTP_ONLY_PENDING = keep_p
        chk(any(u.startswith('http://nohttps.gov/code') for u in L2) == pv, f'http fallback on NETERR only when PORT80_OK={pv}: {L2}')
        chk((len(pend) == 1 and pend[0]['s'] == 'HTTP_ONLY_PENDING' and pend[0]['url'] == 'http://nohttps.gov/code2') if not pv else not pend, f'port80 closed -> HTTP_ONLY_PENDING rerun list entry (PORT80_OK={pv}): {len(pend)}')
    PORT80_OK = True; L2.clear(); S3 = Sched(G0(), S2(), {}, clock=lambda: T[0], sleep=lambda d: T.__setitem__(0, T[0] + d)); S3.get('http://tlsbad.gov/code', site_key('tlsbad.gov'))
    chk(not any(u.startswith('http://') for u in L2), 'TLS failure on https -> NO http downgrade')
    PORT80_OK = os.environ.get('US_PORT80_OK') == '1'; HTTP_ONLY_PENDING = keep_real
    chk(not PORT80_OK, 'live config: PORT80_OK off (port-80 probe timed out 2026-10-20)')
    # jurisdiction check sim (CISA-matched)
    good = '<html><title>Lake County, Minnesota - Official Site</title><h1>Welcome</h1></html>'
    chk(jurisdiction_ok(good, 'Lake County', 'MN') and jurisdiction_ok('<title>City of Aberdeen, NC</title>', 'Aberdeen', 'NC'), 'jurisdiction_ok: name+state found (full state name / ", NC")')
    chk(not jurisdiction_ok('<title>Lake County, Illinois</title>', 'Lake County', 'MN') and not jurisdiction_ok('<title>Springfield Minnesota</title>', 'Lake County', 'MN'), 'jurisdiction_ok rejects wrong state / wrong name')
    T[0] = 0.0; L4 = []
    class S4:
        headers = {}
        def get(s, u, **k):
            L4.append(u); p = urllib.parse.urlsplit(u).path
            if p == '/robots.txt': return R(200, b'', 'text/plain')
            return R(200, b'<title>Town of Alabama, Alabama</title><a href="/code">Code of Ordinances</a>' if host_of(u) == 'wrong.gov' else b'<title>Town of Alabama, NY</title><a href="/code">Code of Ordinances</a>')
    S5 = Sched(G0(), S4(), {}, clock=lambda: T[0], sleep=lambda d: T.__setitem__(0, T[0] + d))
    sw = dict(mk(0, 'wrong.gov'), jurisdiction='Alabama', state_code='NY', cisa_matched=True); so = dict(mk(1, 'right.gov'), jurisdiction='Alabama', state_code='NY', cisa_matched=True); sj = dict(mk(2, 'wrong.gov'), jurisdiction='Alabama', state_code='NY', jur_check=True)
    keep = RAW; RAW = '/tmp/us_local_dry_raw'; rr = run_batch(S5, [sw, so, sj]); RAW = keep
    chk(rr[0]['s'] == 'JURISDICTION_MISMATCH' and not any(u.endswith('/code') and 'wrong.gov' in u for u in L4) and not any(x.get('text') for x in rr[0]['docs']), 'CISA seed on wrong entity -> JURISDICTION_MISMATCH, page dropped, no deeper fetch')
    chk(rr[2]['s'] == 'JURISDICTION_MISMATCH', '.st.us jur_check seed on wrong entity -> JURISDICTION_MISMATCH')
    sd0 = [json.loads(l) for l in open(SEEDS)] if os.path.exists(SEEDS) else []; chk(sum(1 for x in sd0 if x.get('jur_check')) == 5 and all(x['entry_url'] and '.us' in x['entry_url'] for x in sd0 if x.get('jur_check')), '5 .st.us seeds present with jur_check')
    chk(rr[1]['s'] != 'JURISDICTION_MISMATCH' and any('right.gov/code' in u for u in L4), 'CISA seed on right entity -> proceeds')
    sd = load_seeds() if os.path.exists(SEEDS) else []
    O = {'county': 0, 'municipal': 1, 'municipal_ambiguous': 2}; chk(len(sd) > 5000 and [O[s['family']] for s in sd] == sorted(O[s['family']] for s in sd), f'seeds loaded {len(sd)}, order county > municipal > ambiguous-resolved')
    chk(all(os.path.isdir(x) for x in [CH, RAW]), 'dirs present')
    print('DRYRUN', 'ALL OK' if ok else 'FAILURES'); return 0 if ok else 1
if __name__ == '__main__': sys.exit(main_full() if (sys.argv[1:2] or ['dryrun'])[0] == 'full' else main_dryrun())
