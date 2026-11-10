#!/usr/bin/env python3
"""Stage ipfs_germany_laws + DE-<Land> append (NO upload) and never-thin pre-check vs hub tip. Read-only Hub metadata call only."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib, json, os, shutil, sys, time, collections
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
from huggingface_hub import HfApi
sys.path.insert(0, '/workspace/scripts')
REPO = 'endomorphosis/ipfs_germany_laws'; TIP = '62477e216917df268f186972ef49581b02144156'
B = Path('{_CORPORA}/de_subnational'); SNAP = B / 'de_tip'; BUILD = B / 'build'
TS = time.strftime('%Y%m%dT%H%M%S'); STAGE = Path(f'{_CORPORA}/hf-staging/ipfs_germany_laws_subnational_{TS}')
ORDER = ['DE-BW', 'DE-BY', 'DE-BE', 'DE-BB', 'DE-HB', 'DE-HH', 'DE-HE', 'DE-MV', 'DE-NI', 'DE-NW', 'DE-RP', 'DE-SL', 'DE-SN', 'DE-ST', 'DE-SH', 'DE-TH']
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def mem_ok():
    m = memavail()
    while m < 4600:
        if m <= 3584: print(f'MEMGUARD TERM {m}', flush=True); os._exit(3)
        print('MEM PAUSE', m, flush=True); time.sleep(20); m = memavail()
        globals()['_pauses'] = globals().get('_pauses', 0) + 1
        if globals()['_pauses'] > 15: print('MEM PAUSE limit reached; continuing above the 3584 MB hard stop', m, flush=True); return
def compare_prefix(old_path, new_path):
    old = pq.ParquetFile(old_path); new = pq.ParquetFile(new_path)
    it = new.iter_batches(batch_size=2000); buf = None; mism = 0; rows = 0; ids = set(); mc = collections.Counter()
    for ob in old.iter_batches(batch_size=2000):
        need = ob.num_rows; parts = []
        while need > 0:
            if buf is None or buf.num_rows == 0: buf = next(it)
            t = min(need, buf.num_rows); parts.append(buf.slice(0, t)); buf = buf.slice(t); need -= t
        for col in ob.schema.names:
            a = ob.column(col).to_pylist(); b = [x for p in parts for x in p.column(col).to_pylist()]
            m = sum(1 for x, y in zip(a, b) if x != y); mism += m
            if m: mc[col] += m
        ids.update(ob.column('id').to_pylist()); rows += ob.num_rows; mem_ok()
    allnew = set()
    for nb in new.iter_batches(batch_size=50000, columns=['id']): allnew.update(nb.column('id').to_pylist())
    return {'old_rows': old.metadata.num_rows, 'new_rows': new.metadata.num_rows, 'old_rows_compared': rows, 'old_row_field_mismatches': mism, 'mismatch_columns': dict(mc),
            'old_ids_missing': len(ids - allnew), 'unique_ids_before': len(ids), 'unique_ids_after': len(allnew),
            'duplicate_ids_before': old.metadata.num_rows - len(ids), 'duplicate_ids_after': new.metadata.num_rows - len(allnew),
            'new_duplicate_ids': (new.metadata.num_rows - len(allnew)) - (old.metadata.num_rows - len(ids)), 'schema_equal': old.schema_arrow.equals(new.schema_arrow),
            'schema_metadata_equal': (old.schema_arrow.metadata == new.schema_arrow.metadata)}
def main():
    mem_ok()
    api = HfApi(token=os.environ.get('HF_TOKEN')); info = api.dataset_info(REPO, files_metadata=True)
    live = {s.rfilename: s for s in info.siblings}
    if info.sha != TIP: print('ABORT tip moved', info.sha); sys.exit(2)
    shutil.copytree(SNAP, STAGE, ignore=shutil.ignore_patterns('.cache'))
    for q in STAGE.rglob('*'): q.chmod(0o755 if q.is_dir() else 0o644)
    oldL = pq.ParquetFile(SNAP / 'data/laws.parquet'); oldA = pq.ParquetFile(SNAP / 'data/articles.parquet')
    old_law_ids = set(pq.read_table(SNAP / 'data/laws.parquet', columns=['id']).column('id').to_pylist())
    old_art_ids = set(pq.read_table(SNAP / 'data/articles.parquet', columns=['id']).column('id').to_pylist())
    newL = pq.read_table(BUILD / 'laws.parquet').to_pylist(); newA = pq.read_table(BUILD / 'articles.parquet').to_pylist()
    newL.sort(key=lambda r: (ORDER.index(r['jurisdiction']), r['date_issued'] or '', r['id'])); rank = {r['id']: i for i, r in enumerate(newL)}
    newA = [r for _, r in sorted(enumerate(newA), key=lambda x: (rank.get(x[1]['law_id'], 10**9), x[0]))]
    coll = {'laws': 0, 'articles': 0}; added = {'laws': collections.Counter(), 'articles': collections.Counter()}
    for kind, oldf, rowsN, oldids in (('laws', oldL, newL, old_law_ids), ('articles', oldA, newA, old_art_ids)):
        schema = oldf.schema_arrow; out = STAGE / f'data/{kind}.parquet'
        w = pq.ParquetWriter(out, schema, compression='zstd')
        for i in range(oldf.metadata.num_row_groups): w.write_table(oldf.read_row_group(i))
        keep = []; seen = set()
        for r in rowsN:
            if r['id'] in oldids or r['id'] in seen: coll[kind] += 1; continue
            seen.add(r['id']); keep.append({c: r.get(c) for c in schema.names})
            added[kind][r['jurisdiction'] if kind == 'laws' else 'DE-' + r['law_id'][3:5].upper()] += 1
        for i in range(0, len(keep), 50000): w.write_table(pa.Table.from_pylist(keep[i:i + 50000], schema=schema)); mem_ok()
        w.close(); del keep
    del newL, newA, rank; import gc; gc.collect(); print('written; MemAvail', memavail(), flush=True)
    for f in ['de_collect.py', 'de_build.py', 'de_finalize.py', 'de_checks.py', 'de_stage_and_check.py']: shutil.copy2(f'/workspace/scripts/{f}', STAGE / 'scrapers' / f)
    chk = {'live_tip': info.sha, 'tip_unchanged': info.sha == TIP}
    for nm, key in (('laws', 'data/laws.parquet'), ('articles', 'data/articles.parquet')):
        lf = live.get(key); chk[f'{nm}_sha256_live'] = lf.lfs.sha256 if lf and lf.lfs else None
        chk[f'{nm}_sha256_snapshot'] = sha(SNAP / key); chk[f'{nm}_snapshot_matches_live'] = chk[f'{nm}_sha256_snapshot'] == chk[f'{nm}_sha256_live']
        chk[f'{nm}_sha256_staged'] = sha(STAGE / key)
    staged = {str(p.relative_to(STAGE)) for p in STAGE.rglob('*') if p.is_file()}
    chk['files_removed'] = sorted(set(live) - staged); chk['files_added'] = sorted(staged - set(live))
    chk['laws'] = compare_prefix(SNAP / 'data/laws.parquet', STAGE / 'data/laws.parquet')
    chk['articles'] = compare_prefix(SNAP / 'data/articles.parquet', STAGE / 'data/articles.parquet')
    chk['id_collisions_skipped'] = coll
    # federal before/after
    fed = collections.Counter(); per = collections.defaultdict(collections.Counter); acnt = {}; jur = {}
    for b in pq.ParquetFile(STAGE / 'data/laws.parquet').iter_batches(batch_size=5000, columns=['id', 'jurisdiction', 'article_count', 'metadata_json']):
        for i, j, c, m in zip(*[b.column(k).to_pylist() for k in ['id', 'jurisdiction', 'article_count', 'metadata_json']]):
            jur[i] = j; acnt[i] = c; per[j]['laws'] += 1; per[j]['laws_' + json.loads(m)['document_type']] += 1
    rows = collections.Counter(); orphan = 0
    for b in pq.ParquetFile(STAGE / 'data/articles.parquet').iter_batches(batch_size=100000, columns=['law_id']):
        for lid in b.column('law_id').to_pylist():
            if lid not in jur: orphan += 1
            rows[lid] += 1
    for i, j in jur.items(): per[j]['articles'] += rows.get(i, 0)
    mism = [i for i in acnt if acnt[i] != rows.get(i, 0)]
    chk['post'] = {'per_jurisdiction': {j: dict(v) for j, v in sorted(per.items())}, 'article_count_mismatch_laws': len(mism), 'article_count_mismatch_sample': mism[:10], 'orphan_articles': orphan}
    chk['federal_before'] = {'laws': oldL.metadata.num_rows, 'articles': oldA.metadata.num_rows}
    chk['federal_after'] = {'laws': per['DE']['laws'], 'articles': per['DE']['articles']}
    ok = lambda d: d['old_rows_compared'] == d['old_rows'] and d['old_row_field_mismatches'] == 0 and d['old_ids_missing'] == 0 and d['schema_equal'] and d['new_duplicate_ids'] == 0
    chk['PASS'] = bool(chk['tip_unchanged'] and chk['laws_snapshot_matches_live'] and chk['articles_snapshot_matches_live'] and not chk['files_removed']
                       and ok(chk['laws']) and ok(chk['articles']) and coll['laws'] == 0 and coll['articles'] == 0 and not mism and orphan == 0
                       and chk['federal_before'] == chk['federal_after'])
    meta = {'repo': REPO, 'base_tip': TIP, 'staged_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'uploaded': False,
            'method': 'append-only: federal (gesetze-im-internet) rows first and byte-identical row values; DE-<Land> Landesrecht rows appended in Land order (BW..TH), then date_issued, then id',
            'subnational_laws_added': dict(added['laws']), 'subnational_articles_added': dict(added['articles']), 'never_thin': chk}
    (STAGE / 'PACK_META.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False)); open(B / 'last_stage_path.txt', 'w').write(str(STAGE))
    json.dump(chk, open(B / 'stage_check.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({'stage': str(STAGE), 'PASS': chk['PASS'], 'laws': chk['laws'], 'articles': chk['articles'], 'post': chk['post'], 'fed': [chk['federal_before'], chk['federal_after']]}, indent=1, ensure_ascii=False)[:5000])
if __name__ == '__main__': main()
