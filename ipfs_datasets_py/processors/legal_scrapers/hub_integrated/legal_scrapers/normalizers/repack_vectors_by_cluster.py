"""repack_vectors_by_cluster.py RELEASE_DIR [--check]

Fix for the country_laws_ir packager's vector routing defect (package.py: write_sharded() re-chunks the vector rows into
files of 4,096 rows, then pairs index row k / file k with the metadata of cluster k; once clusters are smaller than 4,096
rows, a file holds parts of 2-3 clusters and its centroid, min-score and row order do not belong to it).

What it does, in place, on a built release directory:
  1. reads data/vectors/*.parquet in the order of indexes/vector_chunks.parquet and checks that the rows are grouped by
     cluster_id in non-decreasing order (the builder writes cluster 0, then 1, ...; within a cluster rows are sorted by
     cosine to the cluster centroid, descending) and that no cluster has more than MAX_ROWS_PER_FILE rows;
  2. writes one file per cluster, data/vectors/part-{cluster_id:06d}.parquet, with the package's own write_parquet(), keeping
     every row, every column value and the global row order unchanged (the files are simply cut at cluster boundaries);
  3. rebuilds indexes/vector_chunks.parquet from the files written: cid / sha256 / size_bytes (cidutil.file_descriptor),
     row_count, first/last entry_cid, start/end document_index, and, as layout_vectors() defines them, centroid =
     shard_centroid = L2-normalized float32 mean of the cluster's vectors and centroid_min_score = min cosine of its rows;
  4. updates manifest.json: counts.vector_chunks and the indexes.vector_chunks descriptor (format kept: indent 2);
  5. proves the repack: sha256 of (entry_cid + float64 little-endian bytes of the embedding) for every row, in order,
     before and after must be identical; prints both sequence digests.
Vector values are never recomputed. --check only reports whether the release has the defect (no writes).
Needs the release's own country_laws_ir package (shipped in RELEASE_DIR/country_laws_ir) and pyarrow, pandas, numpy.
"""
from __future__ import annotations
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq

R = os.path.abspath(sys.argv[1]); CHECK = '--check' in sys.argv
sys.path.insert(0, R)
from country_laws_ir import MAX_ROWS_PER_FILE
from country_laws_ir.cidutil import file_descriptor
from country_laws_ir.parquet_io import write_parquet

IDX = f'{R}/indexes/vector_chunks.parquet'
idx = pd.read_parquet(IDX)
files = list(idx.relative_path)
assert sorted(files) == sorted(os.path.relpath(p, R) for p in glob.glob(f'{R}/data/vectors/*.parquet')), 'index and files differ'


def row_hashes(tables):
    out = []
    for t in tables:
        cids = t['entry_cid'].to_pylist()
        E = t['embedding'].combine_chunks().flatten().to_numpy().astype('<f8', copy=False).reshape(len(cids), -1)
        out += [hashlib.sha256(c.encode() + E[i].tobytes()).hexdigest() for i, c in enumerate(cids)]
    return out


def file_report(rel):
    t = pq.read_table(f'{R}/{rel}', columns=['entry_cid', 'cluster_id', 'embedding'])
    return t


# 1. read and check
before_tabs = [pq.read_table(f'{R}/{rel}') for rel in files]
T = pa.concat_tables(before_tabs)
cl = np.asarray(T['cluster_id'].to_pylist())
defect = []
for r, t in zip(idx.itertuples(), before_tabs):
    x = t['embedding'].combine_chunks().flatten().to_numpy().reshape(t.num_rows, -1).astype(np.float32)
    c = x.mean(0); c = c / max(float(np.linalg.norm(c)), 1e-12)
    ok = (set(t['cluster_id'].to_pylist()) == {int(r.cluster_id)} and np.abs(c - np.asarray(r.centroid, np.float32)).max() < 1e-5
          and abs(float((x @ np.asarray(r.shard_centroid, np.float32)).min()) - r.centroid_min_score) < 1e-5)
    if not ok: defect.append(r.relative_path)
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
before = row_hashes(before_tabs)

# 2. write one file per cluster (old files removed first; names are reused part-000000 .. part-{k-1})
df = T.to_pandas()
del before_tabs
for rel in files: os.remove(f'{R}/{rel}')
rows = []; start = 0
for k, n in enumerate(sizes):
    part = df.iloc[start:start + int(n)].reset_index(drop=True); start += int(n)
    rel = f'data/vectors/part-{k:06d}.parquet'; path = f'{R}/{rel}'
    write_parquet(__import__('pathlib').Path(path), part)
    x = np.asarray(np.stack(part.embedding.map(lambda e: np.asarray(e, dtype=np.float64)).values), np.float32)
    c = x.mean(0); c = c / max(float(np.linalg.norm(c)), 1e-12)
    sims = x @ c
    d = file_descriptor(__import__('pathlib').Path(path), rel, extra={
        'shard_id': k, 'kind': 'vectors', 'row_count': int(len(part)),
        'first_key': str(part.entry_cid.iloc[0]), 'last_key': str(part.entry_cid.iloc[-1]),
        'start_document_index': int(part.document_index.iloc[0]), 'end_document_index': int(part.document_index.iloc[-1]),
        'schema_version': str(idx.schema_version.iloc[0])})
    d.update({'centroid': c.tolist(), 'shard_centroid': c.tolist(), 'centroid_min_score': float(sims.min()),
              'centroid_shard_count': 1, 'chunk_in_cluster': 0, 'cluster_id': k, 'dimension': int(x.shape[1]),
              'model_name': str(idx.model_name.iloc[0])})
    rows.append(d)
assert start == len(df)
# 3. index, same column order as before
new_idx = pd.DataFrame(rows)[list(idx.columns)]
write_parquet(__import__('pathlib').Path(IDX), new_idx)

# 5. proof
after_tabs = [pq.read_table(f'{R}/{r["relative_path"]}') for r in rows]
after = row_hashes(after_tabs)
A = pa.concat_tables(after_tabs)
assert after == before, 'row hash sequence changed'
other_cols_equal = all(A[c].to_pylist() == T[c].to_pylist() for c in T.column_names if c != 'embedding')
assert other_cols_equal and A.schema.equals(T.schema), 'columns or schema changed'

# 4. manifest
mp = f'{R}/manifest.json'; raw = open(mp).read(); m = json.loads(raw)
nl = '\n' if raw.endswith('\n') else ''
assert json.dumps(m, indent=2, ensure_ascii=False) + nl == raw, 'manifest format differs'
m['counts']['vector_chunks'] = len(rows)
m['indexes']['vector_chunks'] = file_descriptor(__import__('pathlib').Path(IDX), 'indexes/vector_chunks.parquet')
open(mp, 'w').write(json.dumps(m, indent=2, ensure_ascii=False) + nl)
seq = lambda h: hashlib.sha256(''.join(h).encode()).hexdigest()
print(json.dumps({'rows': len(after), 'files_before': len(files), 'files_after': len(rows), 'cluster_sizes': sizes.tolist(),
                  'row_hash_sequence_before': seq(before), 'row_hash_sequence_after': seq(after), 'identical': after == before,
                  'other_columns_and_schema_identical': bool(other_cols_equal), 'manifest_vector_chunks': len(rows)}))
