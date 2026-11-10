#!/usr/bin/env python3
"""Stage NL article extract. No network. Streams per law; pyarrow batches; MemAvail guard 3584MB.
Usage: nl_build_stage.py <stage_dir>"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, shutil, time
import pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
B = '{_CORPORA}/nl_extract'; TIP = f'{B}/nl_tip'; V2 = f'{B}/out/articles_v2'
S = sys.argv[1]; os.makedirs(f'{S}/data', exist_ok=True); os.makedirs(f'{S}/scrapers', exist_ok=True)
def mem():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def guard():
    m = mem()
    if m < 3584: print(f'MEMGUARD ABORT MemAvailable={m}MB', flush=True); sys.exit(3)
lp = pq.ParquetFile(f'{TIP}/data/laws.parquet'); ap = pq.ParquetFile(f'{TIP}/data/articles.parquet')
LS, AS = lp.schema_arrow, ap.schema_arrow
law_ids = pq.read_table(f'{TIP}/data/laws.parquet', columns=['id'])['id'].to_pylist()
# old article rows kept only for laws without split output
need_old = [l for l in law_ids if not os.path.exists(f'{V2}/{l}.jsonl.gz') or os.path.getsize(f'{V2}/{l}.jsonl.gz') == 0]
old = {}
if need_old:
    t = pq.read_table(f'{TIP}/data/articles.parquet', filters=[('law_id', 'in', need_old)])
    for r in t.to_pylist(): old.setdefault(r['law_id'], []).append(r)
counts, source = {}, {}
w = pq.ParquetWriter(f'{S}/data/articles.parquet', AS, compression='zstd')
buf = []; nrows = 0
def flush():
    global buf
    if buf: w.write_table(pa.Table.from_pylist(buf, schema=AS), row_group_size=20000); buf = []
for i, lid in enumerate(law_ids, 1):
    rows = []
    p = f'{V2}/{lid}.jsonl.gz'
    if os.path.exists(p):
        with gzip.open(p, 'rt', encoding='utf-8') as f: rows = [json.loads(x) for x in f]
    if rows: source[lid] = 'split'
    else: rows = old.get(lid, []); source[lid] = 'hub_row_kept'
    counts[lid] = len(rows); buf += rows; nrows += len(rows)
    if len(buf) >= 20000: flush(); guard()
    if i % 2000 == 0: print(time.strftime('%H:%M:%S'), 'articles', i, nrows, f'mem={mem()}MB', flush=True)
flush(); w.close()
# laws: identical columns; only article_count replaced
lw = pq.ParquetWriter(f'{S}/data/laws.parquet', LS, compression='zstd')
for b in lp.iter_batches(batch_size=2000):
    t = pa.Table.from_batches([b], schema=LS)
    ac = pa.array([counts[x] for x in t['id'].to_pylist()], type=LS.field('article_count').type)
    t = t.set_column(LS.get_field_index('article_count'), LS.field('article_count'), ac)
    lw.write_table(t, row_group_size=2000); guard()
lw.close()
shutil.copy(f'{TIP}/.gitattributes', f'{S}/.gitattributes')
shutil.copy(f'{TIP}/scrapers/collect_bwb.py', f'{S}/scrapers/collect_bwb.py')
for s in ('nl_collect.py', 'nl_split.py', 'nl_resplit.py'): shutil.copy(f'/workspace/scripts/{s}', f'{S}/scrapers/{s}')
json.dump(dict(n_laws=len(law_ids), n_articles=nrows, source_counts={k: list(source.values()).count(k) for k in set(source.values())},
               hub_row_kept=[l for l, v in source.items() if v == 'hub_row_kept']), open(f'{S}.build.json', 'w'), indent=1)
print('DONE laws', len(law_ids), 'articles', nrows, {k: list(source.values()).count(k) for k in set(source.values())}, flush=True)
