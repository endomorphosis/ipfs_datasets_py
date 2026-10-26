#!/usr/bin/env python3
"""Spot check 30 random staged autonomic articles + 10 laws: no markup, notice present, title/heading consistency, ids/urls well-formed."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, random, re
from pathlib import Path
import pyarrow.parquet as pq
B = Path('{_CORPORA}/es_subnational'); STAGE = Path(open(B / 'last_stage_path.txt').read().strip())
NOTICE = 'Texto consolidado de carácter meramente informativo, sin valor oficial.'
random.seed(20261001)
L = pq.read_table(STAGE / 'data/laws.parquet', columns=['id', 'jurisdiction', 'title', 'text', 'source_url', 'eli', 'law_status', 'article_count'], filters=[('jurisdiction', '!=', 'ES')]).to_pylist()
laws = random.sample(L, 10); ids = [x['id'] for x in random.sample(L, 30)]
A = pq.read_table(STAGE / 'data/articles.parquet', filters=[('law_id', 'in', ids)]).to_pylist()
arts = random.sample(A, 30)
tag = re.compile(r'</?[a-zA-Z][^>]{0,80}>')
lr = [dict(id=x['id'], jurisdiction=x['jurisdiction'], title=x['title'][:100], notice_first=x['text'].startswith(NOTICE), markup=bool(tag.search(x['text'])), chars=len(x['text']),
           source_url_ok=x['source_url'].startswith('https://www.boe.es/buscar/act.php?id='), eli=x['eli'], status=x['law_status'], blocks=x['article_count']) for x in laws]
ar = [dict(id=a['id'], title=a['title'][:90], text_starts_with_title=(a['text'] or '').startswith((a['title'] or '')[:40].rstrip('.')), markup=bool(tag.search(a['text'] or '')),
           url_ok=a['source_url'].endswith('/texto/bloque/' + a['document_number']), id_ok=a['id'] == a['law_id'] + '/' + a['document_number'] or '~' in a['id'], chars=len(a['text'] or ''),
           sample=(a['text'] or '')[:160]) for a in arts]
ok = all(r['notice_first'] and not r['markup'] and r['source_url_ok'] for r in lr) and all(not r['markup'] and r['url_ok'] and r['id_ok'] for r in ar)
res = dict(laws=lr, articles=ar, articles_text_starts_with_title=sum(r['text_starts_with_title'] for r in ar), PASS=ok)
json.dump(res, open(B / 'spot_check.json', 'w'), indent=1, ensure_ascii=False)
for r in lr: print(r['jurisdiction'], r['id'], r['status'], r['blocks'], r['notice_first'], r['markup'], r['title'][:70])
for r in ar[:12]: print(r['id'], r['text_starts_with_title'], r['markup'], repr(r['sample'][:110]))
print('SPOT PASS', ok, 'starts_with_title', res['articles_text_starts_with_title'], '/30')
