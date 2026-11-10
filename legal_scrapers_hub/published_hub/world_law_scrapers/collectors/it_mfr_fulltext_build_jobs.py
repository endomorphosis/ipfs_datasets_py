#!/usr/bin/env python3
"""Build IT_MFR_FULLTEXT jobs.json from MFR index + PAGE2 chunks. HTTPS links only; http:// links -> HTTP_ONLY_PENDING list (not fetched)."""
import gzip, json, re, html, os, glob, urllib.parse, collections
W = '/workspace/legal-corpora'; OUT = f'{W}/it_normattiva_mfr_fulltext'
RX = re.compile(r'<div class="singolo_risultato_collapse[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
seen = {}; pend = {}
for f in sorted(glob.glob(f'{W}/it_normattiva_mfr/chunks/idx_r*.jsonl.gz') + glob.glob(f'{W}/it_normattiva_mfr_page2/chunks/p2_r*.jsonl.gz')):
    src = 'page2' if 'page2' in f else 'index'
    for ln in gzip.open(f, 'rt'):
        o = json.loads(ln); t = o.get('text') or ''
        if not t: continue
        reg = (o.get('provenance') or {}).get('regione')
        for u, ti in RX.findall(t):
            u = html.unescape(u).strip(); ti = ' '.join(re.sub(r'<[^>]+>', ' ', html.unescape(ti)).split())
            d = dict(url=u, title=ti, regione=reg, index_src=src)
            if u.startswith('https://'): seen.setdefault(u, d)
            elif u.startswith('http://'): pend.setdefault(u, d)
by = collections.defaultdict(list)
for u, d in seen.items(): by[urllib.parse.urlsplit(u).netloc].append(d)
att = dict(publisher='Regional council legal databases, indexed via Normattiva Regioni (MFR)', licence_id='terms_unrecorded', licence='public legal texts; per-host terms not recorded')
jobs = []
for h in sorted(by):
    L = by[h]
    for i in range(0, len(L), 200):
        part = L[i:i + 200]
        jobs.append(dict(job=f"ft_{re.sub(r'[^a-z0-9]+', '_', h)}_{i // 200:03d}", kind='files', route='MFR_ACT_FULLTEXT', attribution=dict(att, host=h),
                         urls=[d['url'] for d in part], meta=[dict(title=d['title'], regione=d['regione'], index_src=d['index_src']) for d in part]))
J = dict(name='IT_MFR_FULLTEXT', base=OUT, licence=att['licence'], min_delay_s=2.0, note='HTTPS-only act full text (CoS GO 2026-10-24 16:04 PT); HTTP_ONLY_PENDING excluded', jobs=jobs)
json.dump(J, open(f'{OUT}/jobs.json', 'w'), ensure_ascii=False)
json.dump(sorted(pend.values(), key=lambda d: d['url']), open(f'{OUT}/HTTP_ONLY_PENDING.json', 'w'), ensure_ascii=False)
print('https urls', len(seen), 'hosts', {h: len(v) for h, v in by.items()}, 'jobs', len(jobs), 'http_only_pending', len(pend))
print('index/page2 https', collections.Counter(d['index_src'] for d in seen.values()))
