"""repack_vectors_by_cluster_stream.py RELEASE_DIR [--check] [--hub REPO@REV] [--scratch DIR]

Streaming, bounded-memory version of repack_vectors_by_cluster.py (legal_scrapers@7f9ceba09f). Same checks, same output:
the files it writes (data/vectors/part-*.parquet, indexes/vector_chunks.parquet, manifest.json) are byte-identical to
what repack_vectors_by_cluster.py writes on the same input in the same Python environment. Peak memory holds about one old
vector file plus one cluster (<= 4,096 rows), plus one 64-character row hash per row, whatever the repo size.

The vector routing defect it fixes: country_laws_ir 0.5.0 write_sharded() cuts the cluster-sorted vector rows into 4,096-row
files but gives index row/file k the centroid and min-score of cluster k.

Passes:
  1. read the old vector files one at a time in index order: defect check (same test as repack_vectors_by_cluster.py), cluster ids,
     schema, and the before row hashes sha256(entry_cid + float64 little-endian vector bytes). --check stops here (exit 1 = defect).
     If there is no defect it does nothing. It refuses to repack if rows are not grouped by cluster in non-decreasing order, if
     cluster ids are not 0..k-1, or if a cluster has more than MAX_ROWS_PER_FILE rows.
  2. read the old files again in order, cut the rows at cluster boundaries and write each cluster with the release's own
     write_parquet() to a temporary name. Each old file is removed once it has been read; each new file is read back and checked
     (row hashes, other column values, schema). Then the temporary files are renamed to data/vectors/part-{cluster:06d}.parquet.
  3. rebuild indexes/vector_chunks.parquet (file_descriptor + keys, document range, centroid = shard_centroid = L2-normalized
     float32 mean, centroid_min_score = min cosine) and update manifest.json counts.vector_chunks / indexes.vector_chunks.
  4. re-read the new files and check that the ordered row-hash sequence equals the one from pass 1; print both digests.

--hub REPO@REV: the old vector files are not kept locally. Each one is downloaded from that Hub dataset revision into --scratch
(default RELEASE_DIR/.repack_fetch) right before it is read and deleted right after, so local disk only holds the new files.
In this mode RELEASE_DIR must hold indexes/vector_chunks.parquet, manifest.json and country_laws_ir/, and no old vector files.
"""
from __future__ import annotations
import argparse, glob, hashlib, json, os, sys
from pathlib import Path
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq

ap = argparse.ArgumentParser()
ap.add_argument('release'); ap.add_argument('--check', action='store_true'); ap.add_argument('--hub'); ap.add_argument('--scratch')
args = ap.parse_args()
R = os.path.abspath(args.release); CHECK = args.check
sys.path.insert(0, R)
from country_laws_ir import MAX_ROWS_PER_FILE
from country_laws_ir.cidutil import file_descriptor
from country_laws_ir.parquet_io import write_parquet

IDX = f'{R}/indexes/vector_chunks.parquet'
idx = pd.read_parquet(IDX)
files = list(idx.relative_path)
local_vec = sorted(os.path.relpath(p, R) for p in glob.glob(f'{R}/data/vectors/*.parquet'))
if args.hub:
    os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    from huggingface_hub import HfApi, hf_hub_download
    HREPO, HREV = args.hub.split('@')
    SCR = os.path.abspath(args.scratch or f'{R}/.repack_fetch')
    hub_vec = sorted(f for f in HfApi().list_repo_files(HREPO, repo_type='dataset', revision=HREV)
                     if f.startswith('data/vectors/') and f.endswith('.parquet'))
    assert sorted(files) == hub_vec, 'index and files differ'
    assert not local_vec, '--hub mode: old vector files must not be present locally'
else:
    assert sorted(files) == local_vec, 'index and files differ'


def fetch(rel):
    if not args.hub:
        return f'{R}/{rel}'
    return hf_hub_download(HREPO, rel, repo_type='dataset', revision=HREV, local_dir=SCR)


def release_old(path, remove_local):
    if args.hub or remove_local:
        os.remove(path)


def row_hashes(t):
    cids = t['entry_cid'].to_pylist()
    E = t['embedding'].combine_chunks().flatten().to_numpy().astype('<f8', copy=False).reshape(len(cids), -1)
    return [hashlib.sha256(c.encode() + E[i].tobytes()).hexdigest() for i, c in enumerate(cids)]


# 1. read and check, one file at a time
defect = []; cl_parts = []; before = []; schema = None; counts = []
for r in idx.itertuples():
    p = fetch(r.relative_path); t = pq.read_table(p)
    if schema is None:
        schema = t.schema
    assert t.schema.equals(schema), f'{r.relative_path}: schema differs from the first vector file'
    x = t['embedding'].combine_chunks().flatten().to_numpy().reshape(t.num_rows, -1).astype(np.float32)
    c = x.mean(0); c = c / max(float(np.linalg.norm(c)), 1e-12)
    ok = (set(t['cluster_id'].to_pylist()) == {int(r.cluster_id)} and np.abs(c - np.asarray(r.centroid, np.float32)).max() < 1e-5
          and abs(float((x @ np.asarray(r.shard_centroid, np.float32)).min()) - r.centroid_min_score) < 1e-5)
    if not ok: defect.append(r.relative_path)
    cl_parts.append(np.asarray(t['cluster_id'].to_pylist())); counts.append(t.num_rows)
    before += row_hashes(t)
    del t, x
    release_old(p, False)
cl = np.concatenate(cl_parts) if cl_parts else np.zeros(0, int); del cl_parts
clusters = sorted(set(cl.tolist()))
print(json.dumps({'release': os.path.basename(R), 'files': len(files), 'clusters': len(clusters), 'files_not_matching_their_index_row': defect}))
if CHECK:
    sys.exit(1 if defect else 0)
if not defect:
    print('no defect; nothing to do'); sys.exit(0)
assert (np.diff(cl) >= 0).all(), 'rows are not grouped by cluster in non-decreasing order; refusing to repack'
assert clusters == list(range(len(clusters))), 'cluster ids are not 0..k-1'
sizes = np.bincount(cl)
assert sizes.max() <= MAX_ROWS_PER_FILE, f'a cluster has {sizes.max()} rows > {MAX_ROWS_PER_FILE}'
total = len(cl); del cl

# 2. write one file per cluster under temporary names, reading the old files again in order
tmp = lambda k: f'{R}/data/vectors/.repack-tmp-{k:06d}.parquet'
pending = []; npend = 0; nxt = 0; start = 0; parts = []
for k, n in enumerate(sizes):
    n = int(n)
    while npend < n:
        rel = files[nxt]; nxt += 1
        p = fetch(rel); t = pq.read_table(p); release_old(p, True)
        pending.append(t); npend += t.num_rows
    buf = pa.concat_tables(pending) if len(pending) > 1 else pending[0]
    take = buf.slice(0, n); rest = buf.slice(n)
    pending = [rest] if rest.num_rows else []; npend = rest.num_rows
    part = take.to_pandas()
    write_parquet(Path(tmp(k)), part)
    x = np.asarray(np.stack(part.embedding.map(lambda e: np.asarray(e, dtype=np.float64)).values), np.float32)
    c = x.mean(0); c = c / max(float(np.linalg.norm(c)), 1e-12)
    sims = x @ c
    back = pq.read_table(tmp(k))
    assert row_hashes(back) == before[start:start + n], f'cluster {k}: row hashes changed'
    assert back.schema.equals(schema) and all(back[cn].to_pylist() == take[cn].to_pylist() for cn in schema.names if cn != 'embedding'), \
        f'cluster {k}: columns or schema changed'
    parts.append({'k': k, 'n': n, 'centroid': c.tolist(), 'min': float(sims.min()), 'first_key': str(part.entry_cid.iloc[0]),
                  'last_key': str(part.entry_cid.iloc[-1]), 'start_doc': int(part.document_index.iloc[0]),
                  'end_doc': int(part.document_index.iloc[-1]), 'dim': int(x.shape[1])})
    start += n
    del part, x, take, back, buf
assert start == total and npend == 0 and nxt == len(files), 'not every old row was written exactly once'
for k in range(len(sizes)):
    os.replace(tmp(k), f'{R}/data/vectors/part-{k:06d}.parquet')
if args.hub and os.path.isdir(SCR):
    import shutil; shutil.rmtree(SCR, ignore_errors=True)

# 3. index (same columns, same order as before) and manifest
rows = []
for q in parts:
    k = q['k']; rel = f'data/vectors/part-{k:06d}.parquet'
    d = file_descriptor(Path(f'{R}/{rel}'), rel, extra={
        'shard_id': k, 'kind': 'vectors', 'row_count': q['n'], 'first_key': q['first_key'], 'last_key': q['last_key'],
        'start_document_index': q['start_doc'], 'end_document_index': q['end_doc'], 'schema_version': str(idx.schema_version.iloc[0])})
    d.update({'centroid': q['centroid'], 'shard_centroid': q['centroid'], 'centroid_min_score': q['min'],
              'centroid_shard_count': 1, 'chunk_in_cluster': 0, 'cluster_id': k, 'dimension': q['dim'],
              'model_name': str(idx.model_name.iloc[0])})
    rows.append(d)
new_idx = pd.DataFrame(rows)[list(idx.columns)]
write_parquet(Path(IDX), new_idx)

# 4. proof over the written files
after = []
for d in rows:
    after += row_hashes(pq.read_table(f"{R}/{d['relative_path']}", columns=['entry_cid', 'embedding']))
assert after == before, 'row hash sequence changed'

mp = f'{R}/manifest.json'; raw = open(mp).read(); m = json.loads(raw)
nl = '\n' if raw.endswith('\n') else ''
assert json.dumps(m, indent=2, ensure_ascii=False) + nl == raw, 'manifest format differs'
m['counts']['vector_chunks'] = len(rows)
m['indexes']['vector_chunks'] = file_descriptor(Path(IDX), 'indexes/vector_chunks.parquet')
open(mp, 'w').write(json.dumps(m, indent=2, ensure_ascii=False) + nl)
seq = lambda h: hashlib.sha256(''.join(h).encode()).hexdigest()
print(json.dumps({'rows': len(after), 'files_before': len(files), 'files_after': len(rows), 'cluster_sizes': sizes.tolist(),
                  'row_hash_sequence_before': seq(before), 'row_hash_sequence_after': seq(after), 'identical': after == before,
                  'other_columns_and_schema_identical': True, 'manifest_vector_chunks': len(rows)}))
