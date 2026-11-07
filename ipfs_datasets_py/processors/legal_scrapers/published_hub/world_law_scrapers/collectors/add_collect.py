#!/usr/bin/env python3
"""Generic ADDITIONS collector (STAGED, NOT launched) for FR_SCDL_ADDITIONS and ES_ADDITIONS. Benjamin direct 2026-10-20 16:12 PT: robots.txt ADVISORY on official
government/public-sector law hosts -> disallowed paths ARE fetched but every record carries robots_disallowed=true; Crawl-delay ALWAYS honoured per host:
delay = max(Crawl-delay, 2.0s), one host at a time. TLS verify on; no captcha/WAF/login bypass (403/challenge pages = strike, never retried around).
Guards: StrictGuard (pause<3584/resume>=4200x30s/TERM<1500 10s/instant<1000/max pause 900s/RSS 300MB); 3 consecutive 403/429/503/neterr -> exit 4.
Usage: add_collect.py <jobs.json> full|dryrun. Chunks <base>/chunks/<job>.jsonl.gz (atomic; existing=done). Exit 0 done/2 stop/3 MEMTERM/4 strike/5 error."""
import os, sys, re, json, time, gzip, hashlib, signal, datetime, urllib.parse, csv
sys.path.insert(0, '/workspace/scripts')
from strict_mem_guard import StrictGuard, MemShed, Stopped, memavail, rss_mb, DEFAULTS
from es_seue_collect import parse_robots, robots_ok
from it_dait_collect import crawl_delay
from fr_scdl_collect import rows_from, unpack, pdf_text
UA = 'justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'; MAX = 300 * 1024 * 1024
J = json.load(open(sys.argv[1])); B = J['base']; NAME = J['name']; CH = f'{B}/chunks'; RAW = f'{B}/raw'
STOPS = [f'{B}/STOP_{NAME}', f'/workspace/logs/STOP_{NAME}', f'{B}/HOLD_{NAME}', f'/workspace/logs/HOLD_{NAME}']
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def now_pt(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def pq(u): p = urllib.parse.urlsplit(u); return p.path + ('?' + p.query if p.query else '')
class Strike(Exception): pass
class F:
    def __init__(s, g):
        import requests
        s.r = requests.Session(); s.r.headers['User-Agent'] = UA; s.g = g; s.cbad = 0; s.rob = {}; s.last = {}; s.last_status = None
        s.st = dict(req=0, http200=0, other=0, strikes_total=0, robots_disallowed=0, bytes=0, neterr=0)
    def _req(s, url, host, data=None):
        s.g.check()
        for m in STOPS:
            if os.path.exists(m): raise Stopped(m)
        d = s.rob.get(host, ([], 2.0))[1]; w = s.last.get(host, 0) + d - time.time()
        if w > 0: time.sleep(w)
        s.st['req'] += 1
        try: r = (s.r.post(url, data=data, timeout=(20, 120), stream=True, allow_redirects=False) if data is not None else s.r.get(url, timeout=(20, 120), stream=True, allow_redirects=False))
        except Exception as e:
            s.last[host] = time.time(); s.st['neterr'] += 1; s.cbad += 1; s.st['strikes_total'] += 1; log(f'NETERR strike consecutive={s.cbad}', url, repr(e)[:150])
            if s.cbad >= 3: raise Strike(url)
            return None
        s.last[host] = time.time(); s.last_status = r.status_code
        if r.status_code in (403, 429, 503):
            s.cbad += 1; s.st['strikes_total'] += 1; log(f'HTTP {r.status_code} strike consecutive={s.cbad}', url); r.close()
            if s.cbad >= 3: raise Strike(url)
            time.sleep(min(300, 30 * s.cbad)); return None
        s.cbad = 0; s.st['http200' if r.status_code == 200 else 'other'] += 1; return r
    def robots(s, host):
        if host not in s.rob:
            s.rob[host] = ([], max(2.0, float(J.get('min_delay_s', 2.0)))); r = s._req(f'https://{host}/robots.txt', host)
            t = r.text if (r is not None and r.status_code == 200 and not r.text.lstrip().startswith('<')) else ''
            if r is not None: r.close()
            cd = crawl_delay(t); s.rob[host] = (parse_robots(t), max(2.0, float(J.get('min_delay_s', 2.0)), cd or 0)); log('ROBOTS', host, getattr(r, 'status_code', None), 'crawl_delay', cd, 'delay', s.rob[host][1])
        return s.rob[host]
    def get(s, url, depth=0, data=None):
        """-> (response|None|'BAD_SCHEME', robots_disallowed:bool, final_url). Every hop robots-checked (advisory) and delay-honoured."""
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' and p.scheme != 'http': return 'BAD_SCHEME', False, url
        rl, _ = s.robots(p.netloc); dis = not robots_ok(rl, pq(url))
        if dis: s.st['robots_disallowed'] += 1
        r = s._req(url, p.netloc, data)
        if r is not None and r.status_code in (301, 302, 303, 307, 308) and depth < 5:
            loc = urllib.parse.urljoin(url, r.headers.get('Location', '')); r.close(); r2, d2, fu = s.get(loc, depth + 1); return r2, dis or d2, fu
        return r, dis, url
def save(f, url, ext_hint, data=None):
    r, dis, fu = f.get(url, data=data)
    if isinstance(r, str) or r is None or r.status_code != 200:
        s = r if isinstance(r, str) else f'http_{getattr(r, "status_code", "fail")}'
        if r is not None and not isinstance(r, str): r.close()
        return None, s, dis
    h = hashlib.sha256(); k = 0; dl = f'{RAW}/.dl_{os.getpid()}'
    with open(dl, 'wb') as o:
        for b in r.iter_content(65536):
            k += len(b)
            if k > MAX: break
            h.update(b); o.write(b)
    ct = r.headers.get('Content-Type', '').split(';')[0].lower(); lm = r.headers.get('Last-Modified'); r.close()
    if k > MAX: os.remove(dl); return None, 'skip_too_large', dis
    ext = 'pdf' if 'pdf' in ct else ('csv' if 'csv' in ct else (os.path.splitext(urllib.parse.urlsplit(fu).path)[1].lstrip('.').lower()[:5] or ext_hint))
    dst = f'{RAW}/{h.hexdigest()}.{ext}'; os.replace(dl, dst); f.st['bytes'] += k
    return dict(sha256=h.hexdigest(), bytes=k, raw_path=dst, content_type=ct, ext=ext, final_url=fu, last_modified=lm), 'ok', dis
def update_date(meta):
    """source last-update date (Calella condition): page 'darrera actualització/última actualización/actualitzat' date, else HTTP Last-Modified."""
    try: t = open(meta['raw_path'], errors='replace').read(3_000_000)
    except Exception: t = ''
    m = re.search(r'(?:darrera actualitzaci[oó]|[uú]ltima actualizaci[oó]n|actualitzat|modificat)[^0-9]{0,40}(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2})', t, re.I)
    return m.group(1) if m else (meta.get('last_modified') or None)
def do_job(f, jb):
    p = f'{CH}/{jb["job"]}.jsonl.gz'; tmp = p + '.tmp'; n = 0; res = []
    with open(tmp, 'wb') as fb:
        with gzip.GzipFile(fileobj=fb, mode='wb') as g:
            w = lambda o: g.write((json.dumps(o, ensure_ascii=False) + '\n').encode())
            for k, u in enumerate(jb['urls']):
                form = u.get('form') if isinstance(u, dict) else None; u = u['url'] if isinstance(u, dict) else u
                prov = dict(jb['attribution'], route=jb['route'], source_url=u, retrieved_at=now_pt(), **(jb.get('meta') or [{}] * len(jb['urls']))[k])
                meta, s, dis = save(f, u, 'bin', form); prov['robots_disallowed'] = dis
                if form: prov['form'] = form; res.append((u[:90], s, dis))
                if not meta and jb.get('hold_on_403') and f.last_status == 403:
                    # CoS 16:24 PT: exactly one attempt at launch; 403 again -> HOLD_UA + flag CoS (no chunk written, no further retry)
                    for hp in jb['hold_on_403']: open(hp, 'a').write(f"{now_pt()} 403 again on {u} -> HOLD; flag CoS\n")
                    log('HOLD_ON_403', u, 'markers', jb['hold_on_403']); raise Stopped('HOLD_ON_403')
                if not meta: w(dict(type='file', s=s, provenance=prov)); continue
                if prov.pop('cite_update_date', False): prov['source_update_date'] = update_date(meta)
                if jb['kind'] == 'csv_rows' and meta['ext'] in ('csv', 'xlsx'):
                    for j, row in enumerate(rows_from(meta['raw_path'], meta['ext'])):
                        if j % 500 == 0: f.g.check()
                        w(dict(type='row', row_n=j, data=row, provenance=prov)); n += 1
                    continue
                if meta['ext'] in ('zip', '7z', 'rar'):
                    mem, why = unpack(meta['raw_path'], meta['ext'], f"{RAW}/x_{meta['sha256'][:16]}")
                    for nm, fp in mem: t = pdf_text(fp) if fp.lower().endswith('.pdf') else ''; w(dict(type='member', member=nm, text=t, provenance=prov))
                    w(dict(type='file', s=why or 'ok_archive', **meta, provenance=prov)); continue
                t = pdf_text(meta['raw_path']) if meta['ext'] == 'pdf' else (open(meta['raw_path'], errors='replace').read()[:2_000_000] if meta['ext'] in ('html', 'htm', 'txt', 'xml', 'bin', 'cat') else '')
                w(dict(type='file', s='ok', **meta, text=t, text_chars=len(t), provenance=prov)); n += 1
            w(dict(type='meta', job=jb['job'], route=jb['route'], tried=res, n=n, written_at=now_pt()))
        fb.flush(); os.fsync(fb.fileno())
    os.replace(tmp, p); log('CHUNK', jb['job'], 'n', n, 'tried', res[:5], 'stats', f.st, f'mem={memavail()} rss={rss_mb()}')
def full():
    cfg = dict(DEFAULTS); cfg['rss_limit_mb'] = min(300, cfg['rss_limit_mb'])
    done = {x[:-9] for x in os.listdir(CH) if x.endswith('.jsonl.gz')}
    G = StrictGuard(cfg, stop_file=STOPS[0], pause_file=f'{B}/PAUSE_{NAME}', log=log); G.start_watcher()
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(Stopped('SIGTERM'))); f = F(G)
    log('START', NAME, 'pid', os.getpid(), 'jobs', len(J['jobs']), 'done', len(done))
    try:
        for jb in J['jobs']:
            if jb['job'] not in done: do_job(f, jb)
    except MemShed as e: log('MEMTERM', e, f.st); return 3
    except Stopped as e: log('STOPPED', e, f.st); return 2
    except Strike as e: log('STRIKE_STOP', e, f.st); return 4
    except Exception as e: log('ERROR', repr(e)[:300], f.st); return 5
    finally: G.stop_watcher()
    open(f'{B}/{NAME}_DONE', 'w').write(now_pt() + ' ' + json.dumps(f.st) + '\n'); log('DONE', f.st); return 0
def dry():
    import subprocess, shutil; ok = True
    def chk(c, m):
        nonlocal ok; ok &= bool(c); print(f"[{'OK' if c else 'FAIL'}]", m)
    chk(subprocess.call([sys.executable, '/workspace/scripts/es_seue_collect.py', 'dryrun'], stdout=subprocess.DEVNULL) == 0, 'shared StrictGuard sims')
    chk(all(os.path.isdir(x) for x in (CH, RAW)), 'dirs'); hosts = {}; est = 0; dis = 0; nurl = 0
    for jb in J['jobs']:
        for u in jb['urls']:
            u = u['url'] if isinstance(u, dict) else u; h = urllib.parse.urlsplit(u).netloc; pf = f'{B}/probes/robots_{h}.txt'
            t = open(pf, errors='replace').read() if os.path.exists(pf) else ''
            if t.lstrip().startswith('<'): t = ''
            rl = parse_robots(t); d = max(2.0, float(J.get('min_delay_s', 2.0)), crawl_delay(t) or 0); hosts.setdefault(h, [d, 0, 0, os.path.exists(pf)])
            hosts[h][1] += 1; x = not robots_ok(rl, pq(u)); hosts[h][2] += x; dis += x; nurl += 1
    for h, (d, n, x, pr) in hosts.items(): est += d * (n + 1)
    print('hosts', len(hosts), 'urls', nurl, 'expected robots_disallowed', dis, 'est min (requests x delay, +1 robots/host)', round(est / 60, 1))
    for h, v in sorted(hosts.items(), key=lambda kv: -kv[1][0] * kv[1][1])[:8]: print('   ', h, 'delay', v[0], 'urls', v[1], 'disallowed', v[2], 'probe' if v[3] else 'NO_PROBE(live check)')
    chk(crawl_delay('User-agent: *\nCrawl-delay: 60\n') == 60 and max(2.0, crawl_delay('User-agent: *\n') or 0) == 2.0, 'Crawl-delay parse + max(cd,2.0)')
    chk(not robots_ok(parse_robots('User-agent: *\nDisallow: /api/\n'), '/api/x'), 'disallow detection -> robots_disallowed=true flag')
    chk(update_date({'raw_path': '/dev/null', 'last_modified': 'Mon, 05 Oct 2026 10:00:00 GMT'}) == 'Mon, 05 Oct 2026 10:00:00 GMT', 'update-date fallback to Last-Modified')
    bad = [u for jb in J['jobs'] for u in [x['url'] if isinstance(x, dict) else x for x in jb['urls']] if re.search(r'(^|\.)(scf|teia)\.cat', urllib.parse.urlsplit(u).netloc)]; chk(not bad, f'no scf.cat/teia.cat URLs ({len(bad)})')
    cal = [jb for jb in J['jobs'] if 'calella' in jb['job']]; chk(all(jb['attribution'].get('source_citation') and jb['attribution'].get('cite_update_date') for jb in cal), f'Calella citation+update-date flag ({len(cal)} job)')
    chk(shutil.which('7z') is not None, '7z available (p7zip-full)')
    import zipfile, tempfile; td = tempfile.mkdtemp(dir=RAW, prefix='.dry_'); zp = f'{td}/a.zip'
    with zipfile.ZipFile(zp, 'w') as z: z.writestr('x.pdf', '%PDF-1.4')
    sp = subprocess.run(['7z', 'a', '-y', f'{td}/b.7z', zp], capture_output=True).returncode == 0; m, why = unpack(f'{td}/b.7z', '7z', f'{td}/o')
    chk(sp and why is None and len(m) == 1, f'7z unpack {why}'); shutil.rmtree(td)
    pend = [jb['job'] for jb in J['jobs'] if jb.get('pending_discovery')]; chk(not pend and J['jobs'], f"job list complete ({len(J['jobs'])} jobs; pending_discovery={pend})")
    print('licence/terms:', J.get('licence'))
    print('DRYRUN', NAME, 'ALL OK' if ok else 'FAILURES'); return 0 if ok else 1
if __name__ == '__main__': sys.exit(full() if sys.argv[2:3] == ['full'] else dry())
