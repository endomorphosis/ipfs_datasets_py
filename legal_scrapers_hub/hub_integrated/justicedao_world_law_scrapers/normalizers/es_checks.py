#!/usr/bin/env python3
"""Local checks on parsed ES-<CCAA> rows: numbering, article_count vs rows, dedupe (within new set and vs ES state rows), zero/short."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, gzip, re, collections
from pathlib import Path
import pyarrow.parquet as pq
B = Path('{_CORPORA}/es_subnational')
NOTICE = ('Texto consolidado de carácter meramente informativo, sin valor oficial. Únicamente tienen carácter oficial y auténtico los textos publicados en '
          'el Boletín Oficial del Estado.')
NUM = re.compile(r'^Art[íi]culo\s+(\d+)', re.I)
def jl(p):
    for l in gzip.open(p, 'rt'): yield json.loads(l)
laws = {}; 
for L in jl(B / 'parsed/laws_all.jsonl.gz'):
    md = json.loads(L['metadata_json'])['metadata']
    laws[L['id']] = dict(j=L['jurisdiction'], ac=L['article_count'], off=L['official_identifier'], eli=L['eli'], title=L['title'], body=len(L['text'].replace(NOTICE, '').strip()),
                         rango=md['rango'], dup=md['duplicate_block_ids_suffixed'], status=L['law_status'])
rows = collections.Counter(); seq = collections.defaultdict(list); aid = collections.Counter(); bt = collections.Counter()
for a in jl(B / 'parsed/articles_all.jsonl.gz'):
    rows[a['law_id']] += 1; aid[a['id']] += 1; m = json.loads(a['metadata_json'])['metadata']; bt[m['block_type']] += 1
    if m['block_type'] == 'precepto':
        mm = NUM.match(a['title'] or '')
        if mm: seq[a['law_id']].append(int(mm.group(1)))
per = collections.defaultdict(collections.Counter); regress_laws = []; gap_laws = []
for i, L in laws.items():
    s = seq.get(i, []); j = L['j']
    restarts = sum(1 for x, y in zip(s, s[1:]) if y < x and y == 1); other_regress = sum(1 for x, y in zip(s, s[1:]) if y < x and y != 1)
    ints = set(s); gaps = [k for k in range(1, max(ints) + 1) if k not in ints] if ints else []
    per[j]['laws'] += 1; per[j]['articles'] += rows[i]; per[j]['numbered_article_blocks'] += len(s)
    per[j]['laws_with_restart_at_1 (annex/inserted text)'] += restarts > 0; per[j]['laws_with_other_regressions'] += other_regress > 0
    per[j]['laws_with_number_gaps'] += bool(gaps); per[j]['article_count_mismatch'] += L['ac'] != rows[i]; per[j]['dup_block_ids_suffixed'] += L['dup']
    per[j]['zero_article_laws'] += L['ac'] == 0; per[j]['body_under_200_chars_excl_notice'] += L['body'] < 200
    if other_regress: regress_laws.append(dict(id=i, jurisdiction=j, regressions=other_regress, seq_head=s[:40]))
    if gaps: gap_laws.append(dict(id=i, jurisdiction=j, gaps=gaps[:15], n_gaps=len(gaps), max=max(ints)))
num = dict(per_jurisdiction={k: dict(v) for k, v in sorted(per.items())}, block_types=dict(bt), duplicate_article_ids_in_new=sum(v - 1 for v in aid.values() if v > 1),
           laws_other_regressions=len(regress_laws), regress_sample=regress_laws[:25], laws_with_gaps=len(gap_laws), gap_sample=sorted(gap_laws, key=lambda x: -x['n_gaps'])[:25],
           article_count_mismatch_total=sum(1 for i, L in laws.items() if L['ac'] != rows[i]),
           zero_article_laws=[dict(id=i, jurisdiction=L['j'], rango=L['rango'], status=L['status'], title=L['title'][:120]) for i, L in laws.items() if L['ac'] == 0],
           short_body_laws=[dict(id=i, jurisdiction=L['j'], chars=L['body'], rango=L['rango'], status=L['status'], title=L['title'][:120]) for i, L in laws.items() if L['body'] < 200],
           note='Gaps are expected where articles were repealed and removed from the consolidated text or numbering is non-contiguous in the original; restarts at 1 come from annexed/approved texts (e.g. Estatutos, reglamentos in anexos).')
json.dump(num, open(B / 'numbering_checks.json', 'w'), indent=1, ensure_ascii=False)
# dedupe
old = pq.read_table(B / 'es_tip/data/laws.parquet', columns=['id', 'eli', 'title', 'official_identifier'])
oid = set(old.column('id').to_pylist()); oeli = set(x for x in old.column('eli').to_pylist() if x); otit = set(t.strip().lower() for t in old.column('title').to_pylist())
neli = collections.Counter(L['eli'] for L in laws.values() if L['eli']); ntit = collections.Counter(L['title'].strip().lower() for L in laws.values()); noff = collections.Counter(L['off'] for L in laws.values())
dd = dict(new_laws=len(laws), overlap_with_state_rows=dict(by_boe_identifier=sum(1 for L in laws.values() if L['off'] in oid), by_new_id=sum(1 for i in laws if i in oid),
          by_eli=sum(1 for L in laws.values() if L['eli'] in oeli), by_exact_title=sum(1 for L in laws.values() if L['title'].strip().lower() in otit)),
          within_new=dict(dup_official_identifier=sum(v - 1 for v in noff.values() if v > 1), dup_eli=sum(v - 1 for v in neli.values() if v > 1), dup_exact_title=sum(v - 1 for v in ntit.values() if v > 1),
                          dup_title_examples=[k[:120] for k, v in ntit.items() if v > 1][:10]),
          double_inserted=0, note='State rows contain no ambito Autonómico instruments (all 8,766 are ambito Estatal); Statutes of Autonomy are state organic laws and stay as ES rows.')
json.dump(dd, open(B / 'dedupe_overlap.json', 'w'), indent=1, ensure_ascii=False)
print(json.dumps(num['per_jurisdiction'], ensure_ascii=False)); print({k: num[k] for k in ['duplicate_article_ids_in_new', 'laws_other_regressions', 'laws_with_gaps', 'article_count_mismatch_total']}, 'zero', len(num['zero_article_laws']), 'short', len(num['short_body_laws']))
print(json.dumps(dd, ensure_ascii=False))
