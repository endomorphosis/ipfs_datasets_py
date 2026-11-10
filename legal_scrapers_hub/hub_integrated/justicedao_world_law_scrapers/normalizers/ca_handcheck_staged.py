#!/usr/bin/env python3
"""20-law hand check read from the STAGED parquet rows (ON/NS/NB/NT/NU, 4 each)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, sys, re
from pathlib import Path
import pyarrow.parquet as pq
sys.path.insert(0, '/workspace/scripts'); import ca_parse as P
B = Path('{_CORPORA}/ca_subnational'); STAGE = Path((B / 'last_stage_path.txt').read_text().strip())
IDS = ['ca-on-statute-90h08', 'ca-on-statute-18o08', 'ca-on-regulation-900194', 'ca-on-regulation-140132',
       'ca-ns-stat-water', 'ca-ns-stat-community-colleges', 'ca-ns-reg-mvacadianplates', 'ca-ns-reg-ppkbayswater',
       'ca-nb-cs-c-6.1', 'ca-nb-cs-2018-c.12', 'ca-nb-cr-2012-103', 'ca-nb-cr-2024-48',
       'ca-nt-limitation-of-actions.a', 'ca-nt-financial-administration.a', 'ca-nt-public-service.r4', 'ca-nt-financial-administration.r13',
       'ca-nu-labour-standards-act-official-consolidation', 'ca-nu-traffic-safety-act-consolidation', 'ca-nu-liquor-regulations-consolidation', 'ca-nu-access-information-and-protection-privacy-regulations-consolidation']
want = set(IDS); laws = {}
for b in pq.ParquetFile(STAGE / 'data/laws.parquet').iter_batches(batch_size=500):
    for r in b.to_pylist():
        if r['id'] in want: laws[r['id']] = r
arts = {i: [] for i in IDS}
for b in pq.ParquetFile(STAGE / 'data/articles.parquet').iter_batches(batch_size=20000, columns=['law_id', 'id', 'title', 'document_number', 'article_number', 'text']):
    for r in b.to_pylist():
        if r['law_id'] in want: arts[r['law_id']].append(r)
out = []
for i in IDS:
    L = laws.get(i)
    if L is None: out.append(dict(law_id=i, verdict='FAIL', issues=['not found in staged laws'])); continue
    m = json.loads(L['metadata_json']); om = m['metadata']['official_metadata']; pm = om.get('page_meta', {}) or {}
    A = arts[i]
    units = [dict(kind='section' if a['article_number'] == a['document_number'] else 'schedule', num=a['document_number']) for a in A]
    nc = P.numbering_check(units)
    ids_unique = len({a['id'] for a in A}) == len(A)
    issues = []
    if not A: issues.append('0 articles: no numbered sections in source (order/designation); full text on law row')
    if nc['nonmonotonic']: issues.append(f"{nc['nonmonotonic']} non-monotonic steps (source decimal numbering)")
    if nc['int_gaps']: issues.append(f"{nc['int_gaps']} integer gaps {nc['gap_sample']} (repealed/omitted sections)")
    if L['identifier'] == L['official_identifier']: issues.append('identifier fell back to source id')
    if L['article_count'] != len(A): issues.append(f"article_count {L['article_count']} != rows {len(A)}")
    if not ids_unique: issues.append('duplicate article ids')
    ok = L['article_count'] == len(A) and ids_unique and L['identifier'] != L['official_identifier'] and len(L['text']) > 200
    out.append(dict(jurisdiction=L['jurisdiction'], kind=m['document_type'], law_id=i, title=L['title'], identifier=L['identifier'], date=L['date'],
                    currency_or_note=pm.get('consolidation_period') if L['jurisdiction'] == 'CA-ON' else om.get('note'),
                    source_url=L['source_url'], license_head=L['license'][:60], article_count=L['article_count'], article_rows=len(A),
                    first=nc['first'], last=nc['last'], first_article=A[0]['title'][:80] if A else None, last_article=A[-1]['title'][:80] if A else None,
                    text_chars=len(L['text']), issues=issues, verdict=('PASS' if A else 'PASS_WITH_NOTE') if ok else 'FAIL'))
res = dict(generated_from='staged rows', stage=str(STAGE), n=len(out), summary={v: sum(1 for x in out if x['verdict'] == v) for v in ('PASS', 'PASS_WITH_NOTE', 'FAIL')}, laws=out,
           parser_fixes_from_first_pass=json.load(open(B / 'handcheck_20.json')).get('fixes_applied_after_first_pass'))
json.dump(res, open(B / 'handcheck_20_staged.json', 'w'), indent=1, ensure_ascii=False)
for x in out: print(x.get('verdict'), x.get('jurisdiction'), x.get('kind'), '|', (x.get('title') or '')[:40], '|', x.get('identifier'), '|', x.get('date'), '|', x.get('article_count'), x.get('first'), x.get('last'))
print(res['summary'])
