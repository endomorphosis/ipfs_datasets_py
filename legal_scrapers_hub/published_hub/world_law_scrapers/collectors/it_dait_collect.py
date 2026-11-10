#!/usr/bin/env python3
"""IT DAIT Raccolta Ufficiale degli Statuti collector (PREPPED, NOT launched; CoS GO 2026-10-20 16:08 PT per Benjamin 'collect the rest').
Host dait.interno.gov.it. Listing /territorio-e-autonomie-locali/statuti?page=N (0..~414, 20/page, 8284 enti: 7908 Comuni, 95 Province, 15 Città metropolitane, 193 Unioni),
detail /territorio-e-autonomie-locali/statuti/<slug>, attachment /documenti/statuti/*.pdf. robots.txt fetched live and checked for every exact path+query (refuse if disallowed);
Crawl-delay honoured: delay = max(Crawl-delay, cfg delay_s>=2.0). TLS verify on. Guards: StrictGuard (pause<3584/resume>=4200x30s/TERM<1500 10s/instant<1000/max pause 900s/RSS 300MB);
3 consecutive 403/429/503/neterr -> exit 4. Every record: licence=unstated_public_sector + attribution. Dedupe: overlap flags vs Benjamin hub endomorphosis/ipfs_italy_municipal_laws
(benjamin_hub_statuti_ref.json) by normalized comune name (+ISTAT where known) and pdf sha256; flagged rows kept in chunks (never deleted), excluded at build only on sha/title-year match.
Chunks: chunks/list_PPPP.jsonl.gz (one listing page + its details/pdfs; atomic; existing=done). Exit: 0 done, 2 stop, 3 MEMTERM, 4 strike, 5 error. Usage: full | dryrun"""
import os, sys, re, json, time, gzip, hashlib, signal, datetime, urllib.parse, html as H, unicodedata
sys.path.insert(0, '/workspace/scripts')
from strict_mem_guard import StrictGuard, MemShed, Stopped, memavail, rss_mb, DEFAULTS
from es_seue_collect import parse_robots, robots_ok
B = '/workspace/legal-corpora/it_dait'; CH = f'{B}/chunks'; RAW = f'{B}/raw'; CFGF = f'{B}/it_dait_config.json'; REF = f'{B}/benjamin_hub_statuti_ref.json'
STOPS = [f'{B}/STOP_IT_DAIT', '/workspace/logs/STOP_IT_DAIT', f'{B}/HOLD_IT_DAIT', '/workspace/logs/HOLD_IT_DAIT']
HOST = 'dait.interno.gov.it'; BASE = f'https://{HOST}'; LIST = '/territorio-e-autonomie-locali/statuti'
UA = 'justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'
PDF_MAX = 60 * 1024 * 1024; LIC = 'unstated_public_sector'
# CoS 16:35 PT fold-in: the IT municipal world-gap comuni (verifier exact_gap_v2: 296; our recompute 301 incl. unnamed qids) and the province statuti
# (Provincia + Città metropolitana) are in this same DAIT listing; their rows carry CC BY 4.0 (Ministero dell'Interno note legali, www.interno.gov.it) + source citation.
# All other dait rows keep licence=unstated_public_sector.
GAPF = f'{B}/it_world_gap_296.json'; CCBY = 'CC-BY-4.0'
CCBY_NOTE = "Ministero dell'Interno note legali (www.interno.gov.it): contenuti testuali e documentali disponibili con licenza CC BY 4.0, a condizione che sia citata la fonte"
def load_gap():
    try: return {r['norm'] for r in json.load(open(GAPF))['rows'] if r['norm']}
    except Exception: return set()
def licence_for(rec, gap):
    tipo = (rec.get('tipo') or '').lower(); nm = norm(rec.get('title') or rec['slug'].replace('-', ' '))
    tier = 'province' if tipo.startswith(('provincia', 'città metropolitana', 'citta metropolitana')) else ('municipal_world_gap' if tipo.startswith('comune') and nm in gap else None)
    if not tier: return dict(licence=LIC)
    return dict(licence=CCBY, licence_note=CCBY_NOTE, fold_in_tier=tier,
                source_citation=f"Ministero dell'Interno - DAIT, Raccolta Ufficiale degli Statuti: {rec.get('title') or rec['slug']} ({rec.get('tipo') or ''}{', ' + rec['provincia'] if rec.get('provincia') else ''}), {rec['detail_url']}")
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def now_pt(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def norm(s): return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower())
def crawl_delay(txt):
    v = None; ua = False
    for l in txt.splitlines():
        l = l.split('#')[0].strip(); k, _, x = l.partition(':'); k = k.strip().lower(); x = x.strip()
        if k == 'user-agent': ua = x == '*'
        elif k == 'crawl-delay' and ua:
            try: v = float(x)
            except ValueError: pass
    return v
def parse_list(h):
    return sorted(set(re.findall(r'href="(?:https://dait\.interno\.gov\.it)?(/territorio-e-autonomie-locali/statuti/[a-z0-9\-]+)"', h)))
def last_page(h):
    p = [int(x) for x in re.findall(r'[?&]page=(\d+)', h)]; return max(p) if p else 0
def parse_detail(h):
    m = re.search(r'<main.*?</main>', h, re.S); s = m.group(0) if m else h
    t = re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', s)))
    g = lambda rx: (re.search(rx, t) or [None, None])[1]
    return dict(tipo=g(r'Tipo ente territoriale:\s*([A-Za-zàèéìòù ]+?)\s*\('), provincia=g(r'Tipo ente territoriale:[^()]*\(([^)]+)\)'),
                anno_delibera=g(r'Anno delibera\s*(\d{4})'), title=(re.search(r'<h1[^>]*>(.*?)</h1>', s, re.S) and re.sub(r'\s+', ' ', H.unescape(re.sub('<[^>]+>', '', re.search(r'<h1[^>]*>(.*?)</h1>', s, re.S).group(1)))).strip()),
                files=sorted(set(re.findall(r'href="((?:https://dait\.interno\.gov\.it)?/documenti/statuti/[^"]+)"', s))))
class Strike(Exception): pass
class Fetcher:
    def __init__(s, g, cfg):
        import requests
        s.r = requests.Session(); s.r.headers['User-Agent'] = UA; s.g = g; s.delay = max(2.0, float(cfg.get('delay_s', 2.0))); s.last = 0; s.cbad = 0; s.rules = None
        s.st = dict(req=0, http200=0, other=0, strikes_total=0, robots_blocked=0, bytes=0, neterr=0)
    def _req(s, url):
        s.g.check()
        for m in STOPS:
            if os.path.exists(m): raise Stopped(m)
        w = s.last + s.delay - time.time()
        if w > 0: time.sleep(w)
        s.st['req'] += 1
        try: r = s.r.get(url, timeout=(20, 120), stream=True, allow_redirects=False)
        except Exception as e:
            s.last = time.time(); s.st['neterr'] += 1; s.cbad += 1; s.st['strikes_total'] += 1; log(f'NETERR strike consecutive={s.cbad}', url, repr(e)[:150])
            if s.cbad >= 3: raise Strike(url)
            return None
        s.last = time.time()
        if r.status_code in (403, 429, 503):
            s.cbad += 1; s.st['strikes_total'] += 1; log(f'HTTP {r.status_code} strike consecutive={s.cbad}', url); r.close()
            if s.cbad >= 3: raise Strike(url)
            time.sleep(min(300, 30 * s.cbad)); return None
        s.cbad = 0; s.st['http200' if r.status_code == 200 else 'other'] += 1; return r
    def init_robots(s):
        r = s._req(BASE + '/robots.txt')
        if r is None or r.status_code not in (200, 404): raise RuntimeError('robots unreachable -> refuse')
        txt = r.text if r.status_code == 200 else ''; s.rules = parse_robots(txt); cd = crawl_delay(txt)
        if cd: s.delay = max(s.delay, cd)
        log('ROBOTS', HOST, r.status_code, 'rules', len(s.rules), 'crawl_delay', cd, 'delay_used', s.delay)
    def get(s, url, depth=0):
        p = urllib.parse.urlsplit(url)
        if p.netloc != HOST: return 'OFFHOST'
        if not robots_ok(s.rules, p.path + ('?' + p.query if p.query else '')): s.st['robots_blocked'] += 1; log('ROBOTS_BLOCK', url); return 'ROBOTS'
        r = s._req(url)
        if r is not None and r.status_code in (301, 302, 303, 307, 308) and depth < 5:
            loc = urllib.parse.urljoin(url, r.headers.get('Location', '')); r.close(); return s.get(loc, depth + 1)
        return r
def load_ref():
    if not os.path.exists(REF): return {}, set()
    R = json.load(open(REF)); return {norm(n): c for c, n in R['comuni']}, {norm(x['title']) for x in R['statuti']}
def pdf_text(path):
    import subprocess
    try: return subprocess.run(['pdftotext', '-layout', '-q', path, '-'], capture_output=True, timeout=180).stdout.decode('utf-8', 'replace')[:2_000_000]
    except Exception: return ''
GAP = load_gap()
def do_page(F, pg, refc):
    p = f'{CH}/list_{pg:04d}.jsonl.gz'; tmp = p + '.tmp'; n = 0
    r = F.get(f'{BASE}{LIST}?page={pg}')
    if isinstance(r, str) or r is None or r.status_code != 200: raise RuntimeError(f'listing page {pg} failed: {getattr(r, "status_code", r)}')
    slugs = parse_list(r.text); r.close()
    with open(tmp, 'wb') as fb:
        with gzip.GzipFile(fileobj=fb, mode='wb') as g:
            for sl in slugs:
                url = BASE + sl; d = F.get(url)
                rec = dict(type='statuto', slug=sl.rsplit('/', 1)[1], detail_url=url, licence=LIC, robots_disallowed=False,
                           attribution=dict(publisher="Ministero dell'Interno - DAIT, Raccolta Ufficiale degli Statuti", listing=BASE + LIST, retrieved_at=now_pt()))
                if isinstance(d, str) or d is None or d.status_code != 200:
                    rec['s'] = d if isinstance(d, str) else f'http_{getattr(d, "status_code", "fail")}'
                    if d == 'ROBOTS': rec['robots_disallowed'] = True
                    g.write((json.dumps(rec, ensure_ascii=False) + '\n').encode()); continue
                meta = parse_detail(d.text); d.close(); rec.update(meta, s='ok', files_meta=[])
                for fu in meta['files']:
                    fu = urllib.parse.urljoin(BASE, fu); fr = F.get(fu)
                    if isinstance(fr, str) or fr is None or fr.status_code != 200:
                        rec['files_meta'].append(dict(url=fu, s=fr if isinstance(fr, str) else f'http_{getattr(fr, "status_code", "fail")}')); continue
                    h = hashlib.sha256(); k = 0; dl = f'{RAW}/.dl_{os.getpid()}'
                    with open(dl, 'wb') as f:
                        for b in fr.iter_content(65536):
                            k += len(b)
                            if k > PDF_MAX: break
                            h.update(b); f.write(b)
                    fr.close()
                    if k > PDF_MAX: os.remove(dl); rec['files_meta'].append(dict(url=fu, s='skip_too_large')); continue
                    dst = f'{RAW}/{h.hexdigest()}.pdf'; os.replace(dl, dst); F.st['bytes'] += k; txt = pdf_text(dst)
                    rec['files_meta'].append(dict(url=fu, s='ok', sha256=h.hexdigest(), bytes=k, raw_path=dst, text=txt, text_chars=len(txt), ocr_needed=len(txt.strip()) < 200))
                c = refc.get(norm(rec.get('title') or rec['slug'].replace('-', ' '))) if (rec.get('tipo') or '').lower().startswith('comune') else None
                rec['overlap'] = dict(benjamin_hub_istat=c, candidate=bool(c)); rec.update(licence_for(rec, GAP))
                g.write((json.dumps(rec, ensure_ascii=False) + '\n').encode()); n += 1
                if n % 5 == 0: F.g.check()
        fb.flush(); os.fsync(fb.fileno())
    os.replace(tmp, p); log('CHUNK', os.path.basename(p), 'enti', len(slugs), 'ok', n, 'stats', F.st, f'mem={memavail()} rss={rss_mb()}')
def main_full():
    cfg = dict(DEFAULTS); cfg.update(delay_s=2.0)
    if os.path.exists(CFGF): cfg.update(json.load(open(CFGF)))
    cfg['rss_limit_mb'] = min(300, cfg['rss_limit_mb'])
    done = {f for f in os.listdir(CH) if f.endswith('.jsonl.gz')}
    G = StrictGuard(cfg, stop_file=STOPS[0], pause_file=f'{B}/PAUSE_IT_DAIT', log=log); G.start_watcher()
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(Stopped('SIGTERM'))); F = Fetcher(G, cfg); refc, _ = load_ref()
    log('START full pid', os.getpid(), 'done chunks', len(done), 'cfg', cfg)
    try:
        F.init_robots()
        r = F.get(f'{BASE}{LIST}'); lp = last_page(r.text); r.close(); log('LISTING last_page', lp)
        for pg in range(lp + 1):
            if f'list_{pg:04d}.jsonl.gz' in done: continue
            do_page(F, pg, refc)
    except MemShed as e: log('MEMTERM', e, F.st); return 3
    except Stopped as e: log('STOPPED', e, F.st); return 2
    except Strike as e: log('STRIKE_STOP', e, F.st); return 4
    except Exception as e: log('ERROR', repr(e)[:300], F.st); return 5
    finally: G.stop_watcher()
    open(f'{B}/IT_DAIT_DONE', 'w').write(now_pt() + ' ' + json.dumps(F.st) + '\n'); log('DONE', F.st); return 0
def main_dryrun():
    import subprocess; ok = True
    def chk(c, m):
        nonlocal ok; ok &= bool(c); print(f"[{'OK' if c else 'FAIL'}]", m)
    chk(subprocess.call([sys.executable, '/workspace/scripts/es_seue_collect.py', 'dryrun'], stdout=subprocess.DEVNULL) == 0, 'shared StrictGuard sims (es_seue dryrun)')
    rt = open(f'{B}/probes/robots_dait.interno.gov.it.txt').read(); rl = parse_robots(rt)
    for pth in [LIST, LIST + '?page=413', LIST + '/abano-terme', '/documenti/statuti/statuto-comune-pd-abano-terme.pdf']: chk(robots_ok(rl, pth), f'robots allows {pth}')
    chk(not robots_ok(rl, '/search/x'), 'robots blocks /search/ (parser sanity)'); chk(crawl_delay(rt) is None, f'no Crawl-delay -> delay 2.0s')
    lh = open(f'{B}/probes/dait_statuti.html').read(); sl = parse_list(lh); lp = last_page(lh)
    chk(len(sl) == 20 and lp == 414, f'listing parse: {len(sl)} enti/page, last_page {lp} -> ~{20*(lp+1)} (site says 8284)')
    d = parse_detail(open(f'{B}/probes/dait_abano.html').read())
    chk(d['tipo'] == 'Comune' and d['provincia'] == 'PADOVA' and d['anno_delibera'] == '2012' and len(d['files']) == 1, f'detail parse {d}')
    refc, _ = load_ref(); chk(len(refc) == 34 and refc.get(norm('Bolzano')) == '021008', f'overlap ref loaded: {len(refc)} hub comuni')
    chk(all(os.path.exists(x) for x in [CH, RAW]) and LIC == 'unstated_public_sector', 'dirs + licence flag')
    gp = load_gap(); chk(len(gp) >= 250, f'world-gap comuni list loaded: {len(gp)} named')
    nm = next(iter(gp)); b = dict(slug='x', detail_url='https://dait.interno.gov.it/territorio-e-autonomie-locali/statuti/x')
    r1 = licence_for(dict(b, tipo='Provincia', title='PADOVA', provincia='PADOVA'), gp); r2 = licence_for(dict(b, tipo='Comune', title=nm), gp); r3 = licence_for(dict(b, tipo='Comune', title='zzznotacomune'), gp)
    chk(r1['licence'] == 'CC-BY-4.0' and r1['source_citation'].startswith("Ministero dell'Interno") and r2['licence'] == 'CC-BY-4.0' and r2['fold_in_tier'] == 'municipal_world_gap' and r3 == {'licence': 'unstated_public_sector'}, 'licence split: province + world-gap comuni -> CC BY 4.0 + citation; other dait rows unstated_public_sector')
    print('DRYRUN', 'ALL OK' if ok else 'FAILURES'); return 0 if ok else 1
if __name__ == '__main__': sys.exit(main_full() if (sys.argv[1:2] or ['dryrun'])[0] == 'full' else main_dryrun())
