# repack_vectors_by_cluster.py

Post-build fix for a vector routing defect in the `country_laws_ir` packager (0.5.0).

## The defect

`layout_vectors()` sorts the vector rows by cluster (cluster 0, then 1, …; inside a cluster, by cosine to the
cluster centroid, highest first) and makes one metadata entry per cluster (centroid, min-score). `write_sharded()`
then cuts the rows into files of 4,096 rows and gives file *k* the metadata of cluster *k*. Once clusters have fewer
than 4,096 rows, a file holds parts of two or three clusters, so the `centroid`, `centroid_min_score` and `cluster_id`
in `indexes/vector_chunks.parquet` don't describe the rows of the file they point to. When there are more clusters
than files, the last clusters get no routing row at all.

Detect it, without writing anything:

    python normalizers/repack_vectors_by_cluster.py RELEASE_DIR --check   # exit 1 = defect

## The fix

    python normalizers/repack_vectors_by_cluster.py RELEASE_DIR

This works in place on a built release, using the release's own `country_laws_ir` (`write_parquet`, `file_descriptor`).

- It cuts the existing rows at cluster boundaries into `data/vectors/part-{cluster:06d}.parquet`, one file per cluster
  (each cluster must have ≤ 4,096 rows).
- Rows, row order and vector values are unchanged. Nothing is re-encoded.
- It rebuilds `indexes/vector_chunks.parquet` from the files it wrote: hashes, sizes, keys, document ranges,
  centroid = L2-normalized mean, and min-score = lowest cosine.
- It updates the manifest's `counts.vector_chunks` and `indexes.vector_chunks`.

Proof printed by the script: the ordered sequence of sha256(`entry_cid` + float64 vector bytes) over every row is
identical before and after, and all other columns and the schema are identical.

The builder itself still needs the real fix (one file per cluster, with large clusters split into ≤ 4,096-row
chunks) before the next builds.

First used on `justicedao/greece_municipal_laws_ir`: 12 clusters in 7 files became 12 files, with the same
27,134 rows and sequence sha256 `69e5515402c9fa02afb30a4e187667f2c1e4f6600fe1ecfebbb7e7f483f66327`.
The previous Greece head `342b4fdd98` had the same defect (8 clusters in 7 files).
