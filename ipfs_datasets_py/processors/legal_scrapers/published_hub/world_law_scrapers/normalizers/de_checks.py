#!/usr/bin/env python3
"""Build-level checks for DE Landesrecht rows: numbering (incl. § 5a inserts), article_count vs rows, dedupe, empty/short rates.
Usage: de_checks.py <build dir> <out json>"""
import sys, json, re, collections
import pyarrow.parquet as pq
D = sys.argv[1]; OUT = sys.argv[2]
L = pq.read_table(f'{D}/laws.parquet').to_pylist(); A = pq.read_table(f'{D}/articles.parquet').to_pylist()
rows = collections.defaultdict(list)
for a in A: rows[a['law_id']].append(a)
NUM = re.compile(r'^(§|Art\.?|Artikel)\s*(\d+)\s?([a-z]?)\b')
per = collections.defaultdict(collections.Counter); out = {'laws': len(L), 'articles': len(A)}
gaps_s, back_s, dup_s, ins_s = [], [], [], []
title_seen = collections.defaultdict(list)
for l in L:
    j = l['jurisdiction']; md = json.loads(l['metadata_json']); dt = md['document_type']; R = rows[l['id']]
    p = per[j]; p['laws'] += 1; p[f'laws_{dt}'] += 1; p['articles'] += len(R); p[f'articles_{dt}'] += len(R)
    if l['article_count'] != len(R): p['article_count_mismatch'] += 1
    if len(R) == 0: p['zero_article_laws'] += 1
    body = l['text'][len(l['title']):].strip()
    if len(body) < 200: p['law_text_body_under_200_chars'] += 1
    if not body: p['law_text_body_empty'] += 1
    for a in R:
        k = a['id'].split(':', 1)[1]
        if not a['text']:
            p['article_rows_empty_text'] += 1
            if not k.startswith('gl:'): p['article_rows_empty_text_non_structural'] += 1
        elif len(a['text']) < 20: p['article_rows_text_under_20_chars'] += 1
        if k.startswith('gl:'): p['article_rows_structural_gl'] += 1
    seq = []
    for a in R:
        m = NUM.match(json.loads(a['metadata_json'])['enbez'] or '')
        if m: seq.append((m.group(1)[0], int(m.group(2)), m.group(3), a['id']))
    p['numbered_rows'] += len(seq)
    for kind in ('§', 'A'):
        s = [x for x in seq if x[0] == kind]
        seen = set()
        for prev, cur in zip(s, s[1:]):
            if (cur[1], cur[2]) < (prev[1], prev[2]):
                p['numbering_backsteps'] += 1
                if len(back_s) < 30: back_s.append([l['id'], prev[3].split(':', 1)[1], cur[3].split(':', 1)[1]])
            elif cur[1] > prev[1] + 1 and not cur[2]:
                p['numbering_gaps'] += 1
                if len(gaps_s) < 30: gaps_s.append([l['id'], prev[3].split(':', 1)[1], cur[3].split(':', 1)[1]])
        for x in s:
            if x[2]: p['letter_inserts_eg_5a'] += 1; (len(ins_s) < 15 and ins_s.append(x[3]))
            if (x[1], x[2]) in seen:
                p['duplicate_numbers_within_law'] += 1
                if len(dup_s) < 30: dup_s.append(x[3])
            seen.add((x[1], x[2]))
    title_seen[(j, l['title'])].append(l['id'])
ids = collections.Counter(a['id'] for a in A); lids = collections.Counter(l['id'] for l in L)
out.update(per_jurisdiction={j: dict(v) for j, v in sorted(per.items())},
           duplicate_article_ids=sum(c - 1 for c in ids.values() if c > 1), duplicate_law_ids=sum(c - 1 for c in lids.values() if c > 1),
           orphan_articles=sum(1 for a in A if a['law_id'] not in lids),
           duplicate_titles_same_land=[v for v in title_seen.values() if len(v) > 1][:50],
           duplicate_titles_same_land_count=sum(len(v) - 1 for v in title_seen.values() if len(v) > 1),
           samples=dict(numbering_gaps=gaps_s, numbering_backsteps=back_s, duplicate_numbers_within_law=dup_s, letter_inserts=ins_s),
           notes=['numbering_gaps: a jump of >1 between consecutive numbered §§/Artikel (often repealed/aufgehoben norms omitted by the portal, or Anlagen numbering); reported, not altered',
                  'duplicate_numbers_within_law: same § number appears twice (e.g. Mantel/Artikel structure, Anlagen or transitional versions); IDs are disambiguated with #2 suffix',
                  'article_rows_structural_gl: Gliederung heading rows (empty text by design, mirroring federal :gl: rows)'])
json.dump(out, open(OUT, 'w'), indent=1, ensure_ascii=False)
print(json.dumps({k: v for k, v in out.items() if k != 'samples'}, ensure_ascii=False)[:3000])
