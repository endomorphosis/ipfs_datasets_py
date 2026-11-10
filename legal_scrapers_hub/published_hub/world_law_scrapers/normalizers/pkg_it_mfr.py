import gzip, json, glob, re, html, collections, hashlib, os, sys
import pyarrow as pa, pyarrow.parquet as pq
OUT = '/workspace/packaging/out/it_normattiva_mfr_review_20261023'; os.makedirs(f'{OUT}/data', exist_ok=True)
BLK = re.compile(r'<div class="singolo_risultato_collapse.*?(?=<div class="singolo_risultato_collapse|<footer|$)', re.S)
MON = dict(gennaio=1, febbraio=2, marzo=3, aprile=4, maggio=5, giugno=6, luglio=7, agosto=8, settembre=9, ottobre=10, novembre=11, dicembre=12)
raw = pages = 0; rows = []; trunc = []; cnt = collections.Counter()
for f in sorted(glob.glob('/workspace/legal-corpora/it_normattiva_mfr/chunks/*.jsonl.gz')):
    for l in gzip.open(f):
        r = json.loads(l)
        if r.get('type') != 'file' or r.get('s') != 'ok': cnt['page_' + str(r.get('s'))] += 1; continue
        pages += 1; h = r['text']; form = r['provenance'].get('form', {})
        m = re.search(r'Risultato Ricerca semplice:\s*([\d.]+)\s*atti', h); declared = int(m.group(1).replace('.', '')) if m else 0
        got = 0
        for b in BLK.findall(h):
            a = re.search(r'<a href="([^"]*)"[^>]*>(.*?)</a>', b, re.S)
            if not a: continue
            got += 1; raw += 1
            hdr = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', a.group(2))).split())
            t = re.search(r'<span class="atto">(.*?)</span>', b, re.S); title = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', t.group(1))).split()) if t else ''
            hm = re.match(r'(.+?) - (.+?) n\.\s*(\S+) del (\d+) (\w+) (\d{4})(?: - (.*?))?(?:\(Data pubblicazione: ([\d/]+)\))?$', hdr)
            reg, typ, num, dd, mm, yy, status, pub = (hm.groups() if hm else (None,) * 8)
            date = f'{int(yy):04d}-{MON.get((mm or "").lower(), 0):02d}-{int(dd):02d}' if hm else None
            rows.append(dict(region=reg or form.get('regioneList'), regione_code=form.get('regioneList'), act_type=typ, number=num, date=date, year_query=form.get('annoProvvedimento'),
                             status=(status or '').strip() or None, publication_date=pub, title=title, header=hdr, source_link=html.unescape(a.group(1)),
                             source_link_scheme=html.unescape(a.group(1)).split(':')[0], index_url=r['final_url'], retrieved_at=r['provenance']['retrieved_at'], robots_disallowed=True,
                             route='MFR_SEARCH_POST', licence='Normattiva terms not recorded; public legal texts (metadata/index only)'))
        if declared != got: trunc.append(dict(regione=form.get('regioneList'), anno=form.get('annoProvvedimento'), declared=declared, parsed=got))
norm = [x for x in rows if x['header']]
seen = set(); final = []; within = 0
for x in norm:
    k = (x['regione_code'], (x['act_type'] or '').upper(), x['number'], x['date'])
    if k in seen: within += 1; continue
    seen.add(k); x['id'] = 'it-mfr-' + hashlib.sha1('|'.join(map(str, k)).encode()).hexdigest()[:16]; final.append(x)
# vs Benjamin's national IT set (normattiva national) and municipal set: regional acts are a different level; check title+date collisions anyway
ref = pq.read_table('/workspace/packaging/ref/ipfs_italy_laws/data/laws.parquet', columns=['title', 'date']).to_pylist()
refk = {(' '.join((r['title'] or '').lower().split()), r['date']) for r in ref}
ext = [x for x in final if (' '.join(x['header'].lower().split()), x['date']) in refk]
final = [x for x in final if x not in ext] if ext else final
pq.write_table(pa.Table.from_pylist(final), f'{OUT}/data/mfr_index.parquet', compression='zstd')
s = dict(raw_result_rows=raw, pages_ok=pages, page_status=dict(cnt), after_normalize=len(norm), dup_within=within, dup_vs_endomorphosis_ipfs_italy_laws=len(ext),
         dup_vs_italy_municipal='0 by construction (regional acts; municipal set is comuni statutes/regs)', final=len(final),
         pages_declared_ne_parsed=len(trunc), rows_missing_vs_declared=sum(t['declared'] - t['parsed'] for t in trunc), by_region=collections.Counter(x['region'] for x in final),
         link_schemes=collections.Counter(x['source_link_scheme'] for x in final), status=collections.Counter(x['status'] for x in final).most_common(8))
json.dump(dict(summary=s, truncated_pages=trunc), open(f'{OUT}/summary.json', 'w'), indent=1, ensure_ascii=False, default=str); print(json.dumps(s, ensure_ascii=False, default=str)[:2500])
