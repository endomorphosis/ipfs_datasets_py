#!/usr/bin/env python3
"""LU legilux RC re-collect via SPARQL + filestore (CoS 18:57 PT Oct 22). Keyless. delay 2s (no Crawl-delay on data.legilux; robots Disallow /filestore/* -> robots_disallowed=true,
advisory on gov host). Format pref html > xml-akomantoso > xml > pdf > pdfa. Memorial PDFs kept WHOLE, fetched once per file (shared by many acts), split at normalization.
3-strike 403/429/503 (503=403) -> rc4. Memory guard StrictGuard. Chunks of 500 works; existing chunk = done. Exit 0 done/2 stop/3 MEMTERM/4 strike/5 error. Stage only."""
import os, sys, re, json, time, gzip, hashlib, subprocess, requests
sys.path.insert(0, '/workspace/scripts'); from strict_mem_guard import StrictGuard, MemShed, Stopped, DEFAULTS, memavail, rss_mb
B = '/workspace/legal-corpora/lu_legilux/rc2'; CH = f'{B}/chunks'; RAW = f'{B}/raw'; IDX = f'{B}/index.jsonl'
STOPS = [f'{B}/STOP_LU_RC2', '/workspace/logs/STOP_LU_RC2', f'{B}/HOLD_LU_RC2', '/workspace/logs/HOLD_LU_RC2']
EP = 'https://data.legilux.public.lu/sparqlendpoint'; UA = 'justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite legal-text archiver)'
PREF = ['html', 'xml-akomantoso', 'xml', 'pdf', 'pdfa']; DELAY = 2.0; N = 500; MAXB = 60 * 1024 * 1024
def log(*a): print(time.strftime('%F %T'), *a, flush=True)
def now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
class Strike(Exception): pass
S = requests.Session(); S.headers['User-Agent'] = UA; last = [0.0]; strikes = [0]; G = None
def get(url, **kw):
    G.check()
    for m in STOPS:
        if os.path.exists(m): raise Stopped(m)
    w = last[0] + DELAY - time.time()
    if w > 0: time.sleep(w)
    try: r = S.get(url, timeout=(15, 120), verify=True, **kw)
    finally: last[0] = time.time()
    if r.status_code in (403, 429, 503):
        strikes[0] += 1; log('STRIKE', r.status_code, strikes[0], url)
        if strikes[0] >= 3: raise Strike(f'{r.status_code} x3')
        time.sleep(min(300, 30 * strikes[0])); return None
    strikes[0] = 0; return r
def build_index():
    if os.path.exists(IDX): return
    Q = ('PREFIX j:<http://data.legilux.public.lu/resource/ontology/jolux#> SELECT ?w ?fmt ?f WHERE {{ ?w j:typeDocument <http://data.legilux.public.lu/resource/authority/resource-type/RC> ; '
         'j:isRealizedBy ?e . ?e j:isEmbodiedBy ?m . ?m j:userFormat ?fmt ; j:isExemplifiedBy ?f . FILTER(STRSTARTS(STR(?w), "http://data.legilux.public.lu/eli/etat/leg/rc/{y}/")) }} LIMIT 10000')
    works = {}  # Virtuoso caps sorted OFFSET at 10000 -> partition by year instead
    for y in range(1795, int(time.strftime('%Y')) + 1):
        r = None
        while r is None: r = get(EP, params={'query': Q.format(y=y)}, headers={'Accept': 'application/sparql-results+json'})
        if r.status_code != 200: raise RuntimeError(f'SPARQL {r.status_code} year {y}: {r.text[:200]}')
        b = r.json()['results']['bindings']
        if len(b) >= 10000: raise RuntimeError(f'year {y} hit 10000-row limit')
        if b: log('SPARQL year', y, 'rows', len(b))
        for x in b: works.setdefault(x['w']['value'], {}).setdefault(x['fmt']['value'].rsplit('/', 1)[-1], x['f']['value'])
    with open(IDX + '.tmp', 'w') as f:
        for w in sorted(works):
            fm = works[w]; pk = next((k for k in PREF if k in fm), None)
            f.write(json.dumps(dict(work=w, formats=fm, picked=pk, file_url=fm.get(pk)), ensure_ascii=False) + '\n')
    os.replace(IDX + '.tmp', IDX); log('INDEX works', len(works))
def text_of(path, kind):
    if kind in ('pdf', 'pdfa'):
        try: return subprocess.run(['pdftotext', '-layout', '-q', path, '-'], capture_output=True, timeout=300).stdout.decode('utf-8', 'replace')
        except Exception: return ''
    t = open(path, 'rb').read().decode('utf-8', 'replace'); t = re.sub(r'(?is)<(style|script)[^>]*>.*?</\1>', ' ', t)
    return re.sub(r'[ \t]+', ' ', re.sub(r'<[^>]+>', ' ', t)).strip()
def main():
    global G
    cfg = dict(DEFAULTS); G = StrictGuard(cfg, stop_file=STOPS[0], pause_file=f'{B}/PAUSE_LU_RC2', log=log); G.start_watcher()
    st = dict(req=0, ok=0, fail=0, shared_reuse=0, bytes=0)
    try:
        build_index(); W = [json.loads(l) for l in open(IDX)]
        seen = {}  # file_url -> sha (dedupe shared Memorial PDFs within this run; across runs via raw/ existence)
        nb = (len(W) + N - 1) // N; log('START pid', os.getpid(), 'works', len(W), 'chunks', nb)
        for c in range(nb):
            p = f'{CH}/rc_{c:03d}.jsonl.gz'
            if os.path.exists(p): continue
            recs = []
            for w in W[c * N:(c + 1) * N]:
                rec = dict(type='work', work=w['work'], picked=w['picked'], formats=w['formats'], file_url=w['file_url'], provenance=dict(publisher='Legilux / SCL Luxembourg',
                           licence='licenceSCL (per SPARQL jolux:license)', route='LEGILUX_SPARQL_FILESTORE', robots_disallowed=True, retrieved_at=now()))
                if not w['file_url']: rec['s'] = 'no_file'; recs.append(rec); continue
                fu = w['file_url'].replace('http://', 'https://', 1); ext = w['picked'].split('-')[0][:4]
                key = hashlib.sha1(fu.encode()).hexdigest(); dst = f'{RAW}/{key}.{ext}'
                reused = os.path.exists(dst)
                if reused: st['shared_reuse'] += 1
                else:
                    r = None
                    try: r = get(fu, stream=True)
                    except requests.RequestException as e: rec.update(s='neterr', detail=repr(e)[:200]); st['fail'] += 1; recs.append(rec); continue
                    st['req'] += 1
                    if r is None or r.status_code != 200:
                        rec.update(s=f'http_{getattr(r, "status_code", "strike")}'); st['fail'] += 1; recs.append(rec); continue
                    n = 0
                    try:
                        with open(dst + '.tmp', 'wb') as f:
                            for x in r.iter_content(1 << 16):
                                f.write(x); n += len(x)
                                if n > MAXB: break
                    except requests.RequestException as e: rec.update(s='neterr_body', detail=repr(e)[:200]); st['fail'] += 1; recs.append(rec); continue
                    if n > MAXB: os.remove(dst + '.tmp'); rec['s'] = 'skip_too_large'; recs.append(rec); continue
                    os.replace(dst + '.tmp', dst); st['bytes'] += n
                rec['raw_path'] = dst; rec['bytes'] = os.path.getsize(dst); rec['sha256'] = hashlib.sha256(open(dst, 'rb').read()).hexdigest()
                rec['whole_memorial_issue'] = ext == 'pdf' and '/memorial/' in fu
                if reused and rec['whole_memorial_issue']: rec.update(s='ok_shared_file', text_ref_sha256=rec['sha256']); st['ok'] += 1; recs.append(rec); continue
                t = text_of(dst, w['picked']); rec['text'] = t[:3_000_000]; rec['text_chars'] = len(t); rec['s'] = 'ok' if len(t.strip()) > 50 else 'ok_low_text'; st['ok'] += 1
                recs.append(rec)
            with open(p + '.tmp', 'wb') as fb:
                with gzip.GzipFile(fileobj=fb, mode='wb') as g:
                    for x in recs: g.write((json.dumps(x, ensure_ascii=False) + '\n').encode())
            os.replace(p + '.tmp', p); log('CHUNK', c, 'n', len(recs), st, f'mem={memavail()} rss={rss_mb()}')
    except MemShed as e: log('MEMTERM', e); return 3
    except Stopped as e: log('STOPPED', e); return 2
    except Strike as e: log('STRIKE_STOP', e); return 4
    except Exception as e: log('ERROR', repr(e)[:300]); return 5
    finally: G.stop_watcher()
    open(f'{B}/LU_RC2_DONE', 'w').write(now() + ' ' + json.dumps(st) + '\n'); log('DONE', st); return 0
if __name__ == '__main__': sys.exit(main())
