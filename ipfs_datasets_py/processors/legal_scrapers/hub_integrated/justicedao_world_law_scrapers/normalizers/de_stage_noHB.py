#!/usr/bin/env python3
"""Build the noHB staging (federal + DE-NW/SN/BB; DE-HB HELD) from the HB-inclusive staging. Offline except read-only Hub metadata (tip check).
Federal row groups are copied verbatim from the tip snapshot; Landesrecht rows minus DE-HB appended in the same order."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, time, shutil, hashlib, collections, re
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
from huggingface_hub import HfApi
REPO = 'endomorphosis/ipfs_germany_laws'; TIP = '62477e216917df268f186972ef49581b02144156'
B = Path('{_CORPORA}/de_subnational'); SNAP = B / 'de_tip'
SRC = Path('{_CORPORA}/hf-staging/ipfs_germany_laws_subnational_20261002T171728')
TS = time.strftime('%Y%m%dT%H%M%S'); DST = Path(f'{_CORPORA}/hf-staging/ipfs_germany_laws_subnational_noHB_{TS}')
EXP = {'laws': 9287, 'articles': 194134, 'per': {'DE': (6127, 129983), 'DE-NW': (1264, 26603), 'DE-SN': (934, 17237), 'DE-BB': (962, 20311)}}
HELD = {'DE-HB': (1166, 18581)}
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def guard(tag):
    m = memavail(); print(tag, 'MemAvail', m, flush=True)
    if m <= 3584: print('MEMGUARD STOP', flush=True); os._exit(3)
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
guard('start')
api = HfApi(token=os.environ['HF_TOKEN']); info = api.dataset_info(REPO, files_metadata=True)
if info.sha != TIP: print('ABORT tip moved', info.sha); sys.exit(2)
live = {s.rfilename: s for s in info.siblings}
for f in ('data/laws.parquet', 'data/articles.parquet'): assert live[f].lfs.sha256 == sha(SNAP / f), f
# copy non-data files
DST.mkdir(parents=True)
for p in SRC.rglob('*'):
    if p.is_file() and not str(p.relative_to(SRC)).startswith('data/'):
        q = DST / p.relative_to(SRC); q.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, q)
(DST / 'data').mkdir()
oldL = pq.ParquetFile(SNAP / 'data/laws.parquet'); oldA = pq.ParquetFile(SNAP / 'data/articles.parquet')
nFL, nFA = oldL.metadata.num_rows, oldA.metadata.num_rows
srcL = pq.read_table(SRC / 'data/laws.parquet'); srcA = pq.read_table(SRC / 'data/articles.parquet')
# sanity: staged federal prefix == snapshot
assert srcL.slice(0, nFL).equals(pq.read_table(SNAP / 'data/laws.parquet')), 'laws prefix'
guard('loaded')
appL = srcL.slice(nFL); appA = srcA.slice(nFA); del srcL, srcA
hb_ids = set(appL.filter(pc.equal(appL['jurisdiction'], 'DE-HB')).column('id').to_pylist())
keepL = appL.filter(pc.not_equal(appL['jurisdiction'], 'DE-HB'))
keepA = appA.filter(pc.invert(pc.is_in(appA['law_id'], value_set=pa.array(sorted(hb_ids)))))
drop = {'laws': appL.num_rows - keepL.num_rows, 'articles': appA.num_rows - keepA.num_rows}
assert drop == {'laws': HELD['DE-HB'][0], 'articles': HELD['DE-HB'][1]}, drop
for kind, oldf, keep in (('laws', oldL, keepL), ('articles', oldA, keepA)):
    w = pq.ParquetWriter(DST / f'data/{kind}.parquet', oldf.schema_arrow, compression='zstd')
    for i in range(oldf.metadata.num_row_groups): w.write_table(oldf.read_row_group(i))
    for i in range(0, keep.num_rows, 50000): w.write_table(keep.slice(i, 50000).cast(oldf.schema_arrow))
    w.close()
del appL, appA, keepL, keepA; guard('written')
# ---- checks
def compare_prefix(old_path, new_path):
    old = pq.read_table(old_path); new = pq.read_table(new_path); n = old.num_rows
    pre = new.slice(0, n); colseq = {c: old.column(c).combine_chunks().equals(pre.column(c).combine_chunks()) for c in old.schema.names}
    def rowhash(t):
        h = hashlib.sha256()
        for b in t.to_batches(5000):
            for row in zip(*[b.column(c).to_pylist() for c in t.schema.names]): h.update(json.dumps(row, ensure_ascii=False).encode())
        return h.hexdigest()
    oids = set(old.column('id').to_pylist()); nids = set(new.column('id').to_pylist())
    r = {'old_rows': n, 'new_rows': new.num_rows, 'columns_arrow_equal': all(colseq.values()), 'mismatch_columns': [c for c, v in colseq.items() if not v],
         'federal_rowset_sha256_old': rowhash(old), 'federal_rowset_sha256_new': rowhash(pre), 'old_ids_missing': len(oids - nids),
         'duplicate_ids_before': n - len(oids), 'duplicate_ids_after': new.num_rows - len(nids), 'new_duplicate_ids': (new.num_rows - len(nids)) - (n - len(oids)),
         'schema_equal_incl_metadata': old.schema.equals(new.schema, check_metadata=True), 'column_order_equal': old.schema.names == new.schema.names}
    r['PASS'] = bool(r['columns_arrow_equal'] and r['federal_rowset_sha256_old'] == r['federal_rowset_sha256_new'] and r['old_ids_missing'] == 0 and r['new_duplicate_ids'] == 0 and r['schema_equal_incl_metadata'])
    return r
def post(lp, ap):
    L = pq.read_table(lp, columns=['id', 'jurisdiction', 'article_count']).to_pylist()
    jur = {r['id']: r['jurisdiction'] for r in L}; ac = {r['id']: r['article_count'] for r in L}
    rows = collections.Counter(pq.read_table(ap, columns=['law_id']).column(0).to_pylist())
    per = collections.defaultdict(collections.Counter)
    for i, j in jur.items(): per[j]['laws'] += 1; per[j]['articles'] += rows.get(i, 0)
    return {'per_jurisdiction': {j: dict(v) for j, v in sorted(per.items())}, 'orphan_articles': sum(c for lid, c in rows.items() if lid not in jur),
            'article_count_mismatch_laws': sum(1 for i in ac if ac[i] != rows.get(i, 0)), 'hb_law_rows': sum(1 for j in jur.values() if j == 'DE-HB'),
            'hb_article_rows': sum(c for lid, c in rows.items() if lid.startswith('de-hb-'))}
chk = {'live_tip': info.sha, 'tip_unchanged': info.sha == TIP, 'snapshot_matches_live': True, 'stage': str(DST), 'source_stage': str(SRC), 'hb_dropped': drop}
chk['laws'] = compare_prefix(SNAP / 'data/laws.parquet', DST / 'data/laws.parquet'); guard('laws cmp')
chk['articles'] = compare_prefix(SNAP / 'data/articles.parquet', DST / 'data/articles.parquet'); guard('arts cmp')
chk['post'] = post(DST / 'data/laws.parquet', DST / 'data/articles.parquet')
pj = chk['post']['per_jurisdiction']
chk['expected_counts_match'] = (chk['laws']['new_rows'] == EXP['laws'] and chk['articles']['new_rows'] == EXP['articles'] and set(pj) == set(EXP['per'])
                                and all((pj[j]['laws'], pj[j]['articles']) == v for j, v in EXP['per'].items()))
chk['federal_first'] = True  # federal row groups written first verbatim
chk['laws_sha256_staged'] = sha(DST / 'data/laws.parquet'); chk['articles_sha256_staged'] = sha(DST / 'data/articles.parquet')
chk['PASS'] = bool(chk['tip_unchanged'] and chk['laws']['PASS'] and chk['articles']['PASS'] and chk['expected_counts_match'] and chk['post']['orphan_articles'] == 0
                   and chk['post']['article_count_mismatch_laws'] == 0 and chk['post']['hb_law_rows'] == 0 and chk['post']['hb_article_rows'] == 0)
json.dump(chk, open(B / 'stage_check_noHB.json', 'w'), indent=1, ensure_ascii=False); open(B / 'last_stage_path_noHB.txt', 'w').write(str(DST))
print(json.dumps({k: chk[k] for k in ('stage', 'PASS', 'expected_counts_match', 'post', 'hb_dropped')}, indent=1))
print('laws', {k: v for k, v in chk['laws'].items() if 'sha256' not in k}); print('articles', {k: v for k, v in chk['articles'].items() if 'sha256' not in k})
if not chk['expected_counts_match']: print('STOP: counts mismatch'); sys.exit(4)
