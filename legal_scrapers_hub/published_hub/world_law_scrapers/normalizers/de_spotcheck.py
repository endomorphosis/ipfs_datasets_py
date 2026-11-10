#!/usr/bin/env python3
"""Spot check: random staged DE-<Land> article rows vs raw source page text. Usage: de_spotcheck.py <stage dir> <out json> [n]"""
import sys, json, random, gzip, re, html as H, collections
import pyarrow.parquet as pq, pyarrow.compute as pc
S = sys.argv[1]; OUT = sys.argv[2]; N = int(sys.argv[3]) if len(sys.argv) > 3 else 48
L = pq.read_table(f'{S}/data/laws.parquet', columns=['id', 'jurisdiction', 'json_path', 'title', 'article_count'])
L = L.filter(pc.not_equal(L['jurisdiction'], 'DE')).to_pylist(); lmap = {l['id']: l for l in L}
A = pq.read_table(f'{S}/data/articles.parquet', columns=['law_id', 'id', 'title', 'text'])
A = A.filter(pc.starts_with(A['law_id'], 'de-')).to_pylist()
by = collections.defaultdict(list)
for a in A:
    if a['law_id'] in lmap and a['text'] and not a['id'].split(':', 1)[1].startswith('gl:'): by[lmap[a['law_id']]['jurisdiction']].append(a)
rnd = random.Random(20261002); res = []
cache = {}
def src(p):
    if p not in cache:
        t = gzip.decompress(open(p, 'rb').read()).decode('utf-8', 'replace')
        t = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', t, flags=re.S); t = re.sub(r'<sup class="satzzahl">\d+</sup>', '', t)
        t = re.sub(r'</?(?:span|a|em|strong|b|i|u|abbr|sup|sub|font)\b[^>]*>', '', t)
        cache[p] = re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', t)).replace('\u00a0', ' '))
    return cache[p]
for j in sorted(by):
    for a in rnd.sample(by[j], min(N // len(by), len(by[j]))):
        l = lmap[a['law_id']]; s = src(l['json_path']); words = re.sub(r'\s+', ' ', a['text'])
        head, tail = words[:60], words[-60:]
        res.append(dict(jurisdiction=j, id=a['id'], title=a['title'], chars=len(a['text']), head_in_source=head in s, tail_in_source=tail in s))
ok = sum(r['head_in_source'] and r['tail_in_source'] for r in res)
out = dict(n=len(res), pass_both=ok, per_jurisdiction={j: dict(n=sum(1 for r in res if r['jurisdiction'] == j), pass_both=sum(1 for r in res if r['jurisdiction'] == j and r['head_in_source'] and r['tail_in_source'])) for j in sorted(by)}, rows=res)
json.dump(out, open(OUT, 'w'), indent=1, ensure_ascii=False); print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False))
for r in res:
    if not (r['head_in_source'] and r['tail_in_source']): print('MISS', r)
