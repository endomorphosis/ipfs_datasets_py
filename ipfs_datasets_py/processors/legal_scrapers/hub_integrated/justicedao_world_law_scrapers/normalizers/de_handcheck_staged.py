#!/usr/bin/env python3
"""Hand check on STAGED rows (reads only the selected ids from <stage>/data via parquet filters): built rows vs independent regex scan of the raw cache page.
Usage: de_handcheck_staged.py <stage dir> <out.json> <ids-file>"""
import sys, json, gzip, re, html as H, collections
import pyarrow.parquet as pq
D = sys.argv[1]; OUT = sys.argv[2]
ids = set(open(sys.argv[3]).read().split())
laws = pq.read_table(f'{D}/data/laws.parquet', filters=[('id', 'in', sorted(ids))]).to_pylist(); arts = pq.read_table(f'{D}/data/articles.parquet', filters=[('law_id', 'in', sorted(ids))]).to_pylist()
assert len(laws) == len(ids), (len(laws), len(ids))
by = collections.defaultdict(list)
for a in arts: by[a['law_id']].append(a)
def rawtext(p):
    t = gzip.decompress(open(p, 'rb').read()).decode('utf-8', 'replace')
    t = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', t, flags=re.S).replace('&amp;nbsp;', ' ')
    t = re.sub(r'<sup class="satzzahl">\d+</sup>', '', t)
    t = re.sub(r'<a href="#FNID[^"]*"[^>]*>.*?</a>', '', t, flags=re.S)
    t2 = re.sub(r'</?(?:span|a|em|strong|b|i|u|abbr|sup|sub|font)\b[^>]*>', '', t)
    return t, re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', t2)).replace('\u00a0', ' '))
def src_paras(land, t):
    if land == 'NW': return re.findall(r'<span class="field field--field_num">\s*(§§?\s*[0-9]+(?: ?[a-z](?![a-zäöüß]))?|Art(?:ikel|\.)?\s*[0-9IVXLC]+(?: ?[a-z](?![a-zäöüß]))?)', t)
    if land == 'SN': return re.findall(r'<section[^>]*title="((?:§|Artikel|Art\.)[\s\u00a0]*[0-9IVXLC]+[a-z]?)', t)
    if land == 'HB': return re.findall(r'<div class="jgwsAiZDoc".{0,600}?<h[2-6][^>]*>\s*((?:§|Artikel|Art\.)\s*[0-9IVXLC]+[a-z]?)\b', t, re.S)
    if land == 'BB':
        t = t[t.find('reiterbox_innen_text'):]
        return re.findall(r'<h[2-6][^>]*>\s*(?:<a (?:name|id)="[^"]*"></a>)?\s*(?:<span class="paragraph_bez">)?\s*((?:&sect;|§|Artikel|Art\.)(?:\s|&nbsp;)*[0-9IVXLC]+[a-z]?)\b', t)
res = []
for L in laws:
    if ids and L['id'] not in ids: continue
    land = L['jurisdiction'][3:]; t, txt = rawtext(L['json_path']); A = by[L['id']]
    sp = [re.sub(r'(\d) ([a-z])$', r'\1\2', re.sub(r'\s+', ' ', H.unescape(x).replace('\u00a0', ' ')).strip()) for x in src_paras(land, t.replace('&amp;nbsp;', ' ').replace('&nbsp;', ' '))]
    bp = [json.loads(a['metadata_json'])['enbez'] for a in A if (json.loads(a['metadata_json'])['enbez'] or '').startswith(('§', 'Art'))]
    key = lambda x: (lambda m: (m.group(1)[0], m.group(2)) if m else x)(re.match(r'^(§|Art)\S*\s*(\d+\s?[a-z]?(?![a-zäöüß]))', re.sub(r'\s+', ' ', x)))
    keyn = lambda x: (key(x)[0], key(x)[1].replace(' ', '')) if isinstance(key(x), tuple) else x
    sset, bset = collections.Counter(keyn(x) for x in sp), collections.Counter(keyn(x) for x in bp)
    nonempty = [a for a in A if a['text']]
    def present(a):
        s = re.sub(r'\s+', ' ', a['text'])[:80]
        return s in txt
    samp = [a for a in nonempty if (json.loads(a['metadata_json'])['enbez'] or '').startswith(('§', 'Art'))]
    first, last = (samp[0], samp[-1]) if samp else (None, None)
    r = dict(id=L['id'], land=land, doc_type=json.loads(L['metadata_json'])['document_type'], title=L['title'][:90], title_in_source=(L['title'][:60] in txt) or (L['title'][:60] in re.sub(r'\s+', ' ', H.unescape(t))),
             date=L['date'], article_count=L['article_count'], article_rows=len(A), src_para_headings=len(sp), built_para_rows=len(bp),
             para_multiset_equal=sset == bset, missing_in_build=list((sset - bset).elements())[:5], extra_in_build=list((bset - sset).elements())[:5],
             first_para=(first['id'].split(':', 1)[1] if first else None), first_text_in_source=present(first) if first else None,
             last_para=(last['id'].split(':', 1)[1] if last else None), last_text_in_source=present(last) if last else None,
             empty_rows=len(A) - len(nonempty), text_chars=len(L['text']))
    r['PASS'] = bool(r['title_in_source'] and r['article_count'] == r['article_rows'] and r['para_multiset_equal'] and (first is None or (r['first_text_in_source'] and r['last_text_in_source'])) and r['article_rows'] > 0)
    res.append(r)
json.dump(res, open(OUT, 'w'), indent=1, ensure_ascii=False)
for r in res: print(('PASS' if r['PASS'] else 'FAIL'), r['id'][:40], r['doc_type'][:4], r['date'], r['article_rows'], r['src_para_headings'], r['built_para_rows'], r['first_para'], r['last_para'], r['first_text_in_source'], r['last_text_in_source'], r['empty_rows'], r['missing_in_build'], r['extra_in_build'], r['title'][:50])
print('PASS', sum(r['PASS'] for r in res), '/', len(res))
