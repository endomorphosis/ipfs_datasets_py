# Streaming vector repack and release gates

Two bounded-memory tools for re-packing municipal IR releases of any size. They fix the `country_laws_ir` 0.5.0
vector routing defect described in `REPACK_VECTORS_BY_CLUSTER.md`.

## repack_vectors_by_cluster_stream.py

    python normalizers/repack_vectors_by_cluster_stream.py RELEASE_DIR [--check] [--hub REPO@REV] [--scratch DIR]

This is the streaming version of `repack_vectors_by_cluster.py` (@7f9ceba09f). It runs the same checks (defect test,
rows grouped by cluster in non-decreasing order, cluster ids 0..k-1, ≤ 4,096 rows per cluster, schema and column values
unchanged, per-row sha256(`entry_cid` + vector bytes) sequence unchanged) and writes the same files.

- It reads one old vector file at a time and holds one cluster at a time.
- Each new file is read back and checked before the next one is written.
- With `--hub`, the old vector files are fetched from the Hub revision one at a time and deleted after use, so local disk
  only holds the new files.

**Byte identity with 7f9ceba09f.** Both scripts were run on the same input in the same Python environment, and every
output file (`data/vectors/part-*.parquet`, `indexes/vector_chunks.parquet`, `manifest.json`) has the same sha256:

- luxembourg `6bc71ecf40` (3 files) and denmark `833e36249e` (2 files): pandas 3.0.6 / pyarrow 26.
- greece `342b4fdd98` (8 clusters in 7 files, cluster 7 had no index row) and australia `7eb959f363` (7 clusters in 5
  files): pandas 2.2.3 / pyarrow 26.
- On each input, three runs give the same result: `repack_vectors_by_cluster.py`, the streaming script reading local
  files, and the streaming script with `--hub`.

**Environment note.** Older packs store `string` (not `large_string`) columns. Under pandas 3 the shared write path
(`write_parquet` → `pa.Table.from_pandas`) turns them into `large_string`. Both scripts then refuse at their schema check.
Run them under pandas 2.x for those packs.

## gates_stream.py

    python normalizers/gates_stream.py RELEASE_DIR RAW_DIR RAW_REV OUT.json [--hub REPO@REV] [--raw-hub REPO@REV] [--scratch DIR]

It runs the same 34 release gates as the Verifier-derived `gates.py` / `gates_lean.py`, streaming:

- Corpus and raw files are read one at a time, keeping only the id, link, url, revision and hash columns; bodies are kept as sha256.
- Vectors are read one file at a time, with per-cluster float64 sums instead of the full matrix.
- BM25 and graph counts come from parquet metadata.
- With `--hub` / `--raw-hub`, missing files are fetched one at a time and deleted after use.
- `validate_ir_schema` is imported from `normalizers/schema.py` next to the script (override the directory with `LEGAL_SCRAPERS_SCHEMA_DIR`).
- A gate whose inputs can't be read (for example, raw files in another layout) is recorded as failed with `NOT_RUN`;
  the other gates still run.

Checked against `gates_lean.py` on luxembourg `b9cfe13208` (all 34 pass, identical result values, local and `--hub`).
Also checked against its raw-tolerant variant on australia `7eb959f363`: the same 12 failing gates with identical values,
including the `vector_index_consistent` defect list.

### Centroid tolerance (vector_index_consistent)

`vector_index_consistent` compares each index row's stored `centroid` with the centroid recomputed from the rows of its
cluster. The tolerance is **5e-5** (max absolute difference per dimension); it was 1e-5 in `42c31d4016`. The builder and
`repack_vectors_by_cluster.py` (`7f9ceba09f`) compute the stored centroid as a float32 mean, while this gate recomputes it as
a float64 mean. On large, tight clusters the two differ by more than 1e-5 although nothing is wrong: Belgium `8fb0a87e1a`
after the repack (row-hash sequence `4aced8bf5ef6…`, unchanged) has a maximum difference of about 1.2e-5 on clusters 10, 16,
22 and 29 (about 3.7k rows each). A misrouted file, the defect this gate is meant to catch, is off by far more: on Belgium
any two distinct cluster centroids differ by at least 2.2e-2. Only the centroid tolerance changed. The `centroid_min_score` tolerance (1e-5), the order check and every other
gate are unchanged.

### Article rows and text_preservation v3.4.3

From text_preservation v3.4.3 the builder normalizes an article row with its law row's raw text as `parent` (an article
copy keeps every line its law row keeps). When the shipped `country_laws_ir.structure.normalize_legal_text` accepts
`parent`, `body_eq_shipped_normalize_raw` does the same: the laws pass keeps each raw law text (zlib-compressed, by id) and
every raw article whose `law_id` names a law with non-empty text is normalized with that text as `parent`. Releases built
before v3.4.3 ship a normalizer without `parent` and are checked exactly as before.
