#!/usr/bin/env python3
"""ES seu-e (AOC Catalunya municipal e-seus) normativa collector. Third-slot (dep_*) collector; CoS GO 2026-10-20 13:54 PT.
Scope: 144 munis (seeds_es_seue.json from ipfs_datasets_py ES code_hosts seeds, vendor=seu-e), NORMATIVA sections only:
  estatuts, ordenances-reguladores-i-reglaments, ordenances-fiscals, plecs-de-clausules-generals.
Terms: avís legal (seu-e.cat/.../avis-legal; verified lescabanyes, altafulla, bellvis) = reuse under Llei 37/2007 (LRISP), commercial or not;
  IP-protected content (corporate identity / images) needs express authorisation -> excluded; no framing (we never frame; local staging only).
Guards: StrictGuard (pause<3584, resume>=4200 x30s, TERM<1500 sustained 10s, instant TERM<1000, max pause 900s, RSS cap 300MB) checked before
  every request + 2s watcher thread. 3 consecutive 403/429/503/timeout (503 counts as 403) -> exit 4 (supervisor: 10-min cool-off; 2nd stop in 2h -> HOLD).
  Polite: >= delay_s (default 2.0s, floor 1.0) between requests, one host (seu-e.cat) at a time, robots.txt checked for EVERY exact path+query.
  STOP_ES_SEUE / HOLD_ES_SEUE honoured between requests. Chunks: chunks/NNN_<slug>.jsonl.gz, one per municipality, atomic; existing = done (resume).
Exit codes: 0 done, 2 stopfile, 3 MEMTERM, 4 strike stop, 5 error.
Usage: es_seue_collect.py full | dryrun   (dryrun = offline: guard sims + robots matcher + filter/parse on saved probe pages; no network)
"""
import os, sys, re, json, time, gzip, html, hashlib, signal, subprocess, datetime, urllib.parse
sys.path.insert(0, '/workspace/scripts')
from strict_mem_guard import StrictGuard, MemShed, Stopped, memavail, rss_mb, DEFAULTS
B = '/workspace/legal-corpora/es_seue'; CH = f'{B}/chunks'; RAW = f'{B}/raw'
SEEDS = f'{B}/seeds_es_seue.json'; CFGF = f'{B}/es_seue_config.json'
STOPS = [f'{B}/STOP_ES_SEUE', '/workspace/logs/STOP_ES_SEUE', f'{B}/HOLD_ES_SEUE', '/workspace/logs/HOLD_ES_SEUE']
HOST = 'https://seu-e.cat'; UA = 'justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'
SECTIONS = ['estatuts', 'ordenances-reguladores-i-reglaments', 'ordenances-fiscals', 'plecs-de-clausules-generals', 'tipus-impositius']  # tipus-impositius added CoS 2026-10-20 14:04
SCHEMA = 2
OUTBOUND = f'{B}/outbound_links_for_verifier.json'
SECBASE = '/ca/web/{slug}/govern-obert-i-transparencia/accio-de-govern-i-normativa/normativa-plans-i-programes/{sec}'
MAX_DOC = 30 * 1024 * 1024; MAX_TEXT = 1_500_000
LICENCE = ('Reuse permitted under Llei 37/2007 (LRISP, as amended by Llei 18/2015) per the seu-e avís legal, commercial or non-commercial, '
           'with attribution; IP-protected content excluded (needs express authorisation); no framing.')
# ---- filters (terms carve-outs) ----
PERSONAL = re.compile(r'padr[oó]|\bcens\b|notificaci|edicte|\bedictes?\b|\bdni\b|\bnie\b|\bnif\b|sanci[oó]|sancionador|multa|nomenament|oposici|'
                      r'borsa de treball|admesos|exclosos|llista provisional|llista definitiva|aspirants|dades personals|persones? interessad|'
                      r'convocat[oò]ria de personal|tribunal qualificador|retribuci|plantilla|rlt\b|empleat', re.I)
# CoS 2026-10-20 14:04: NO title-keyword IP skipping. Skip only docs whose CONTENT carries an explicit IP/copyright reservation (or personal data).
IPRES = re.compile(r'tots els drets reservats|todos los derechos reservados|all rights reserved|\bcopyright\b|©\s*\d{4}|reserva(?:t|da|do)s? (?:de )?(?:tots )?(?:els |los )?drets|propietat intel·lectual[^.]{0,80}(?:prohibi|reserva)|propiedad intelectual[^.]{0,80}(?:prohibi|reserva)', re.I)
DRAFT = re.compile(r'aprovaci[oó] inicial|aprobaci[oó]n inicial', re.I)
FINAL = re.compile(r'aprovaci[oó] definitiva|aprobaci[oó]n definitiva|text consolidat|texto consolidado', re.I)
def classify(text, url):
    s = urllib.parse.unquote(f'{text} {url}')
    if PERSONAL.search(s): return 'skip_personal_data:' + PERSONAL.search(s).group(0).lower()
    return None
def ip_reserved(txt):
    m = IPRES.search(txt[:20000] + ' ' + txt[-20000:]) if txt else None
    return m.group(0) if m else None
def norm_title(t):
    t = urllib.parse.unquote_plus(t).lower()
    t = re.sub(r"aprovaci[oó] (inicial|definitiva|provisional)( de( la| l'| les| el)?)?|aprobaci[oó]n (inicial|definitiva)( de( la| el)?)?|modificaci[oó]|\.pdf|[^a-zà-ü0-9]+", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()
def mark_versions(recs):
    docs = [r for r in recs if r.get('type') == 'doc']
    for r in docs: r['status'] = 'draft' if DRAFT.search(r.get('title', '')) else 'final'
    groups = {}
    for r in docs: groups.setdefault((r['section'], norm_title(r.get('title', ''))), []).append(r)
    for g in groups.values():
        has_final = any(r['status'] == 'final' and r.get('s') == 'ok' for r in g); has_draft = any(r['status'] == 'draft' for r in g)
        for r in g:
            r['preferred'] = (r['status'] == 'final') if (has_final and has_draft) else True
            r['has_draft_and_final'] = bool(has_final and has_draft)
    return recs
# ---- robots (Google-style * and $ wildcards; longest match wins; Allow wins ties) ----
def parse_robots(txt, agent='justicedao-legal-corpus'):
    groups, cur, last_ua = [], None, False
    for raw in txt.splitlines():
        l = raw.split('#', 1)[0].strip()
        if ':' not in l: continue
        k, v = [x.strip() for x in l.split(':', 1)]; k = k.lower()
        if k == 'user-agent':
            if not last_ua: cur = {'ua': [], 'rules': []}; groups.append(cur)
            cur['ua'].append(v.lower()); last_ua = True
        elif k in ('allow', 'disallow') and cur is not None:
            last_ua = False
            if v: cur['rules'].append((k == 'allow', v))
        else: last_ua = False
    mine = [g for g in groups if any(u != '*' and u in agent.lower() for u in g['ua'])]
    rules = [r for g in (mine or [g for g in groups if '*' in g['ua']]) for r in g['rules']]
    return rules
def _rx(p):
    end = p.endswith('$'); p = p[:-1] if end else p
    return re.compile('^' + '.*'.join(re.escape(x) for x in p.split('*')) + ('$' if end else ''))
def robots_ok(rules, pathq):
    best = (-1, True)
    for allow, pat in rules:
        if _rx(pat).match(pathq):
            L = len(pat)
            if L > best[0] or (L == best[0] and allow): best = (L, allow)
    return best[1]
# ---- parsing ----
def doc_links(page, slug):
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        h = html.unescape(m.group(1)).strip(); t = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', m.group(2)))).strip()
        u = urllib.parse.urljoin(HOST + '/', h).replace('://www.seu-e.cat', '://seu-e.cat').replace('seu-e.cat:443', 'seu-e.cat')
        p = urllib.parse.urlsplit(u)
        if p.netloc == 'seu-e.cat' and p.path.startswith('/documents/'):
            if u in seen: continue
            if not t or t.startswith('http'):
                seg = [x for x in p.path.split('/') if x]; t = urllib.parse.unquote_plus(seg[3]) if len(seg) > 4 else urllib.parse.unquote_plus(seg[-1])
            seen.add(u); out.append(('doc', u, t))
    return out
def ext_links(page, slug):
    """outbound links inside main content to municipality's own site (recorded, never fetched)."""
    return sorted({html.unescape(h) for h in re.findall(r'href="(https?://(?!(?:www\.)?seu-e\.cat)[^"]+)"', page)
                   if re.search(r'ordenan|reglament|normativ|estatut', h, re.I)})
def sha(b): return hashlib.sha256(b).hexdigest()
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def now_pt(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
class Strike(Exception): pass
class Fetcher:
    def __init__(s, guard, cfg):
        import requests
        s.r = requests.Session(); s.r.headers.update({'User-Agent': UA, 'Accept-Language': 'ca,es;q=0.8'})
        s.g = guard; s.cfg = cfg; s.last = 0.0; s.cbad = 0; s.rules = None; s.robots_t = 0
        s.st = dict(req=0, http200=0, http404=0, other=0, strikes_total=0, robots_blocked=0, bytes=0, timeouts=0)
    def robots(s):
        if s.rules is None or time.time() - s.robots_t > 6 * 3600:
            r = s._get('/robots.txt', robots_check=False)
            if r is None or r.status_code != 200: raise Strike(f'robots.txt unavailable ({getattr(r, "status_code", None)}) -> refuse to crawl')
            s.rules = parse_robots(r.text); s.robots_t = time.time()
            open(f'{B}/robots_seen.txt', 'w').write(r.text)
            log('ROBOTS loaded rules', len(s.rules))
        return s.rules
    def allowed(s, url):
        p = urllib.parse.urlsplit(url); pq = p.path + ('?' + p.query if p.query else '')
        return robots_ok(s.robots(), pq)
    def _get(s, path_or_url, robots_check=True, stream=False):
        url = path_or_url if path_or_url.startswith('http') else HOST + path_or_url
        if robots_check and not s.allowed(url): s.st['robots_blocked'] += 1; return 'ROBOTS'
        s.g.check()
        for st in STOPS:
            if os.path.exists(st): raise Stopped(st)
        d = max(1.0, float(s.cfg.get('delay_s', 2.0))); w = s.last + d - time.time()
        if w > 0: time.sleep(w)
        s.st['req'] += 1
        try:
            r = s.r.get(url, timeout=(20, 90), stream=stream, allow_redirects=True)
        except Exception as e:
            s.last = time.time(); s.st['timeouts'] += 1; s.cbad += 1; s.st['strikes_total'] += 1
            log(f'NETERR strike consecutive={s.cbad}', url, repr(e)[:160])
            if s.cbad >= 3: raise Strike(f'3 consecutive strikes (neterr/timeout) at {url}')
            return None
        s.last = time.time()
        if r.status_code in (403, 429, 503):
            s.cbad += 1; s.st['strikes_total'] += 1
            log(f'HTTP {r.status_code} strike consecutive={s.cbad}', url)
            r.close()
            if s.cbad >= 3: raise Strike(f'3 consecutive 403/429/503 at {url}')
            time.sleep(min(300, 30 * s.cbad)); return None
        s.cbad = 0
        k = 'http200' if r.status_code == 200 else 'http404' if r.status_code == 404 else 'other'; s.st[k] += 1
        return r
def attribution(m, url, sec):
    return dict(source=f"Seu electrònica de {m['name']} (plataforma seu-e.cat, Consorci Administració Oberta de Catalunya - AOC)",
                publisher=f"Ajuntament / ens local: {m['name']}", platform='seu-e.cat (AOC)', source_url=url, section=sec,
                avis_legal_url=f"{HOST}/ca/web/{m['slug']}/avis-legal", licence=LICENCE, retrieved_at=now_pt())
def pdf_text(path):
    try:
        p = subprocess.run(['pdftotext', '-layout', '-q', path, '-'], capture_output=True, timeout=180)
        return p.stdout.decode('utf-8', 'replace')[:MAX_TEXT]
    except Exception as e: return ''
def fetch_doc(F, url):
    r = F._get(url, stream=True)
    if r == 'ROBOTS': return dict(s='skip_robots')
    if r is None: return dict(s='fetch_fail')
    if r.status_code != 200: r.close(); return dict(s=f'http_{r.status_code}')
    ct = r.headers.get('Content-Type', '').split(';')[0].strip().lower()
    if ct.startswith('image/') or ct.startswith('video/') or ct.startswith('audio/'): r.close(); return dict(s='skip_media_not_text', content_type=ct)
    h = hashlib.sha256(); n = 0; tmp = f'{RAW}/.dl_{os.getpid()}.tmp'
    with open(tmp, 'wb') as f:
        for b in r.iter_content(65536):
            n += len(b)
            if n > MAX_DOC: r.close(); f.close(); os.remove(tmp); return dict(s='skip_too_large', content_type=ct)
            h.update(b); f.write(b)
    r.close(); dg = h.hexdigest()
    ext = {'application/pdf': 'pdf'}.get(ct) or (os.path.splitext(urllib.parse.urlsplit(r.url).path)[1].lstrip('.').lower()[:5] or 'bin')
    dst = f'{RAW}/{dg}.{ext}'
    if os.path.exists(dst): os.remove(tmp)
    else: os.replace(tmp, dst)
    F.st['bytes'] += n
    txt = pdf_text(dst) if (ct == 'application/pdf' or ext == 'pdf') else ''
    if ct.startswith('text/html'):
        txt = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style).*?</\1>', '', open(dst, errors='replace').read(), flags=re.S))))[:MAX_TEXT]
    res = ip_reserved(txt)
    if res: return dict(s='skip_ip_reserved', ip_reservation_match=res, content_type=ct, bytes=n, sha256=dg, raw_path=dst, final_url=r.url, text='', text_chars=0)
    return dict(s='ok', content_type=ct, bytes=n, sha256=dg, raw_path=dst, final_url=r.url, text=txt, text_chars=len(txt))
def write_chunk(name, recs):
    p = f'{CH}/{name}.jsonl.gz'; tmp = p + '.tmp'
    with open(tmp, 'wb') as fb:
        with gzip.GzipFile(fileobj=fb, mode='wb') as g:
            for r in recs: g.write((json.dumps(r, ensure_ascii=False) + '\n').encode())
        fb.flush(); os.fsync(fb.fileno())
    os.replace(tmp, p); fd = os.open(CH, os.O_RDONLY); os.fsync(fd); os.close(fd); return p
def read_chunk(name):
    p = f'{CH}/{name}.jsonl.gz'
    return [json.loads(l) for l in gzip.open(p)] if os.path.exists(p) else None
def chunk_schema(recs): return max([r.get('schema', 1) for r in recs if r.get('type') == 'meta'] or [1])
def write_outbound():
    out = []
    for f in sorted(os.listdir(CH)):
        if not f.endswith('.jsonl.gz'): continue
        for r in (json.loads(l) for l in gzip.open(f'{CH}/{f}')):
            if r.get('type') == 'section':
                for u in r.get('external_links', []): out.append(dict(muni=r['muni'], qid=r['qid'], slug=r['slug'], section=r['section'], url=u, host=urllib.parse.urlsplit(u).netloc, chunk=f))
    tmp = OUTBOUND + '.tmp'; json.dump(dict(generated_at=now_pt(), note='Outbound links from seu-e normativa sections to towns\' own sites: RECORDED ONLY, never fetched; for verifier terms review', n=len(out), n_hosts=len({x['host'] for x in out}), links=out), open(tmp, 'w'), ensure_ascii=False, indent=1); os.replace(tmp, OUTBOUND)
def do_muni(F, i, m, old=None):
    """old = v1 chunk records -> UPGRADE: keep all old section/doc records, fetch only new sections + docs previously skipped by the removed title-IP filter."""
    if old is not None:
        recs = [r for r in old if r.get('type') != 'meta']; have = {r['section'] for r in recs if r['type'] == 'section'}
        for r in recs:
            if r['type'] == 'doc' and str(r.get('s', '')).startswith('skip_ip_protected') and not classify(r.get('title', ''), r['url']):
                prev = r['s']; r.update({k: None for k in ('ip_reservation_match',)}); r.update(fetch_doc(F, r['url'])); r['unskipped_from'] = prev
        todo = [s for s in SECTIONS if s not in have]
    else:
        recs = []; todo = SECTIONS
    for sec in todo:
        path = SECBASE.format(slug=m['slug'], sec=sec); url = HOST + path
        r = F._get(path)
        if r == 'ROBOTS': recs.append(dict(type='section', muni=m['name'], qid=m['qid'], slug=m['slug'], section=sec, url=url, s='skip_robots')); continue
        if r is None or r.status_code != 200:
            recs.append(dict(type='section', muni=m['name'], qid=m['qid'], slug=m['slug'], section=sec, url=url, s=f'http_{getattr(r, "status_code", "fail")}')); continue
        page = r.text; links = doc_links(page, m['slug']); ext = ext_links(page, m['slug'])
        recs.append(dict(type='section', muni=m['name'], qid=m['qid'], slug=m['slug'], section=sec, url=url, s='ok', n_doc_links=len(links), external_links=ext[:50],
                         attribution=attribution(m, url, sec)))
        for _, du, title in links:
            base = dict(type='doc', muni=m['name'], qid=m['qid'], slug=m['slug'], section=sec, title=title, url=du,
                        doc_uuid=(re.search(r'/([0-9a-f]{8}-[0-9a-f-]{27,})', du) or [None, None])[1], attribution=attribution(m, du, sec))
            why = classify(title, du)
            if why: recs.append({**base, 's': why}); continue
            recs.append({**base, **fetch_doc(F, du)})
    mark_versions(recs)
    recs.insert(0, dict(type='meta', schema=SCHEMA, upgraded_from_v1=old is not None, sections=SECTIONS, written_at=now_pt()))
    name = f"{i:03d}_{m['slug']}"; p = write_chunk(name, recs); write_outbound()
    c = {}; [c.__setitem__(x['s'].split(':')[0], c.get(x['s'].split(':')[0], 0) + 1) for x in recs if x['type'] == 'doc']
    log('CHUNK', os.path.basename(p), 'muni', m['name'], 'sections_ok', sum(1 for x in recs if x['type'] == 'section' and x['s'] == 'ok'), 'docs', c,
        'stats', F.st, f'mem={memavail()}MB rss={rss_mb()}MB strikes_consecutive={F.cbad}')
def main_full():
    cfg = dict(DEFAULTS); cfg.update(delay_s=2.0)
    if os.path.exists(CFGF): cfg.update(json.load(open(CFGF)))
    cfg['rss_limit_mb'] = min(300, cfg['rss_limit_mb']); cfg['delay_s'] = max(1.0, float(cfg['delay_s']))
    seeds = json.load(open(SEEDS)); done = {f.split('.')[0] for f in os.listdir(CH) if f.endswith('.jsonl.gz')}
    G = StrictGuard(cfg, stop_file=STOPS[0], pause_file=f'{B}/PAUSE_ES_SEUE', log=log); G.start_watcher()
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(Stopped('SIGTERM')))
    F = Fetcher(G, cfg)
    log('START full pid', os.getpid(), 'seeds', len(seeds), 'done', len(done), 'cfg', cfg, f'mem={memavail()}MB')
    try:
        F.robots()
        for i, m in enumerate(seeds):
            name = f"{i:03d}_{m['slug']}"
            if name in done:
                old = read_chunk(name)
                if chunk_schema(old) >= SCHEMA: continue
                log('UPGRADE v1->v2', name); do_muni(F, i, m, old=old); continue
            do_muni(F, i, m)
    except MemShed as e: log('MEMTERM', e, F.st); return 3
    except Stopped as e: log('STOPPED', e, F.st); return 2
    except Strike as e: log('STRIKE_STOP', e, F.st); return 4
    except Exception as e: log('ERROR', repr(e)[:300], F.st); return 5
    finally: G.stop_watcher()
    open(f'{B}/ES_SEUE_DONE', 'w').write(now_pt() + ' ' + json.dumps(F.st) + '\n'); log('DONE', F.st); return 0
def main_dryrun():
    import strict_mem_guard as S
    ok = True; cfg = dict(DEFAULTS)
    G = StrictGuard(cfg, stop_file='/nonexistent', pause_file='/nonexistent', log=lambda *a: None)
    class Sim:
        def __init__(s, f): s.f = f; s.t = 0.0; s.nw = 2.0
        def mem(s): return s.f(s.t)
        def clock(s): return s.t
        def sleep(s, d):
            e = s.t + d
            while s.nw <= e: s.t = s.nw; G.watch_tick(s.f(s.t), s.t, rss_fn=lambda: RSS[0]); s.nw += 2.0
            s.t = e
    RSS = [80]
    def run(name, f, exp):
        nonlocal ok
        G.G.update(min_mem=10**9, n_pause=0, n_resume=0, low_t0=None, low_n=0, n_streaks=0, hard=None, hard_t=None, termlogged=False); s = Sim(f)
        try: out = f'returned {G.check(_sleep=s.sleep, _mem=s.mem, _clock=s.clock, _rss=lambda: RSS[0])}'
        except MemShed as e: out = f'TERM {e}'
        good = out.startswith(exp); ok &= good; print(f"[{'OK' if good else 'FAIL'}] {name}: {out} t={s.t:.0f}s")
    print('guard cfg', {k: cfg[k] for k in ('pause_memavail', 'resume_memavail', 'resume_hold_s', 'hard_term_memavail', 'hard_term_sustain_s', 'instant_term_memavail', 'max_pause_s', 'rss_limit_mb')})
    run('normal 5000', lambda t: 5000, 'returned')
    run('pause 3400 -> 4300 held 30s resumes', lambda t: 3400 if t < 20 else 4300, 'returned')
    run('flap 4100 resets hold', lambda t: 3400 if t < 5 else (4100 if 10 <= t < 12 else 4300), 'returned')
    run('stuck 4000 -> TERM after 900s', lambda t: 3400 if t < 1 else 4000, 'TERM paused>900')
    run('1400 for 6s -> no TERM', lambda t: 3400 if t < 4 else (1400 if t < 10 else 4400), 'returned')
    run('1400 sustained >=10s -> TERM', lambda t: 3400 if t < 4 else (1400 if t < 40 else 4400), 'TERM sustained_lt1500')
    run('single 900 -> instant TERM', lambda t: 900, 'TERM lt1000')
    RSS[0] = 320; run('rss 320MB -> TERM', lambda t: 5000, 'TERM rss=320MB'); RSS[0] = 80
    rules = parse_robots(open('/workspace/country-law-triage/municipal_linklayer_evidence_20261020/terms/seu-e_robots_20261020.txt').read())
    cases = [(SECBASE.format(slug='dosrius', sec=s), True) for s in SECTIONS] + [
        ('/documents/1218885/7727663/Ordenan%C3%A7a+municipal/ab42c6c9-9652-4eed-9f3c-a36dc71035fd', True),
        ('/ca/web/x/govern-obert-i-transparencia/accio-de-govern-i-normativa/accio-de-govern-i-partits-politics/actes-de-ple', False),
        ('/ca/web/x/govern-obert-i-transparencia/accio-de-govern-i-normativa/normativa-plans-i-programes?p_p_auth=5Q&p_p_id=49', False),
        ('/csv/x', False), ('/ca/web/esparreguera/govern-obert-i-transparencia/serveis-i-tramits/a', False)]
    for p, exp in cases:
        g = robots_ok(rules, p) == exp; ok &= g; print(f"[{'OK' if g else 'FAIL'}] robots {'allow' if exp else 'deny '} {p[:110]}")
    for t, u, exp in [('Ordenança municipal gestió de recollida residus', '/documents/1/2/x/u', None), ('Padró d\'habitants', '/documents/x', 'skip_personal_data'),
                      ('Edicte notificació', '/documents/x', 'skip_personal_data'), ("Taxa per la utilització de l'escut muncipal.", '/documents/x', None),
                      ('Logotip ajuntament', '/documents/x', None), ('Ordenança fiscal núm. 5 taxa escombraries', '/documents/x', None)]:
        c = classify(t, u); g = (c or None) if exp is None else (c or '').startswith(exp); g = (c is None) if exp is None else g
        ok &= g; print(f"[{'OK' if g else 'FAIL'}] filter {t!r} -> {c}")
    pg = open(f'{B}/probes/sec2.html', errors='ignore').read(); L = doc_links(pg, 'dosrius')
    print('parse probe dosrius/ordenances-reguladores: doc links', len(L), 'kept', sum(1 for _, u, t in L if not classify(t, u)), [t for _, u, t in L][:4])
    ok &= len(L) > 0
    for t, exp in [('Text de l\'ordenança. Tots els drets reservats.', True), ('© 2021 Editorial X', True), ('Ordenança fiscal reguladora de la taxa', False)]:
        g = bool(ip_reserved(t)) == exp; ok &= g; print(f"[{'OK' if g else 'FAIL'}] ip_reserved {t!r} -> {ip_reserved(t)}")
    R = mark_versions([dict(type='doc', section='o', title='Aprovació inicial Ordenança residus', s='ok'), dict(type='doc', section='o', title='Aprovació definitiva Ordenança residus', s='ok'), dict(type='doc', section='o', title='Ordenança civisme', s='ok')])
    g = [(r['status'], r['preferred']) for r in R] == [('draft', False), ('final', True), ('final', True)]; ok &= g; print(f"[{'OK' if g else 'FAIL'}] versions", [(r['status'], r['preferred']) for r in R])
    seeds = json.load(open(SEEDS)); print('seeds', len(seeds), 'unique slugs', len({m['slug'] for m in seeds})); ok &= len(seeds) == 144
    print('DRYRUN', 'ALL OK' if ok else 'FAILURES'); return 0 if ok else 1
if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'dryrun'
    sys.exit(main_full() if mode == 'full' else main_dryrun())
