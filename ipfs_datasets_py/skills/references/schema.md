# SkillCenter remote release schema

`manifest.json` declares the source revision, content bindings, row counts,
BM25 constants, vector model, and descriptors for each compact meta-index.
Verify descriptor size and SHA-256 before reading a shard.

## Identity and pointers

- `entry_cid`: canonical CIDv1/raw/sha2-256 primary identity.
- `document_index`: compact release pointer equal to the canonical
  `corpus_index`; never use it as content identity.
- `corpus_chunk_id`: `document_index // 4096`.
- `corpus_row_offset`: `document_index % 4096`.

All data files use Zstandard Parquet and contain at most 4,096 rows.

## BM25

`indexes/bm25_keyword_shards.parquet` contains lexical ranges:

- `first_key`, `last_key`: inclusive term bounds.
- `relative_path`: posting shard path.
- `term_count`, `posting_count`, `token_instance_count`: coverage.
- `cid`, `sha256`, `size_bytes`: integrity.

Posting rows contain a term plus aligned arrays of `document_indices`,
`document_lengths`, `title_frequencies`, and `body_frequencies`. A frequent
term may occupy several bounded posting rows in the same shard.

## Vectors

`indexes/vector_chunks.parquet` contains one row per vector shard:

- `centroid`: normalized routing vector.
- `shard_centroid`: normalized centroid used to sort the physical shard.
- `relative_path`: exact vector shard path.
- `row_count`: at most 4,096.
- `cluster_id`: semantic routing-centroid identifier.
- `chunk_in_cluster`: zero or one.
- `centroid_shard_count`: one or two.
- `cid`, `sha256`, `size_bytes`: integrity.

Rows are sorted by decreasing cosine similarity to `shard_centroid`. Group
meta rows by `cluster_id`, score each distinct `centroid`, fetch its one or two
shards, then compute exact cosine scores against normalized `embedding`
values. The default probes four semantic centroids.

Semantic graph traversal uses the same meta-index. It ranks centroids once
against the query, fetches no more than `max_vector_shards`, and exposes
vectors only for candidate graph CIDs present in those shards. This is bounded
and query-directed, but approximate: graph nodes outside the selected
centroids and non-SKILL structural nodes have no available vector.

## Corpus hydration

`indexes/corpus_chunks.parquet` maps inclusive document ranges to corpus
shards. Fetch only shards containing final BM25/vector document pointers.
Return `entry_cid`, source/license metadata, and skill content from those
canonical rows.

## Graph navigation

`indexes/graph_node_chunks.parquet` resolves a node CID to its canonical node
row. `indexes/graph_outgoing_adjacency.parquet` and
`indexes/graph_incoming_adjacency.parquet` map CID ranges to adjacency
artifacts. Ranges can overlap when a high-degree node spans multiple files.

Each adjacency row contains:

- `node_cid`, `direction`, `page_index`, and `page_count`;
- aligned arrays of `edge_cids`, `edge_types`, `neighbor_cids`,
  `neighbor_node_types`, `retrieval_methods`, and `scores`;
- `neighbor_count` capped at 4,096; and
- `total_neighbor_count` for the unfiltered direction.

Each adjacency artifact contains at most 8,192 edge pointers. Rows are ordered
by node CID and then by descending score with null scores last. Fetch matching
range descriptors in `shard_id` order and stop when the query or walk budget
is satisfied. Do not infer graph completeness after a budgeted stop.

`scripts/semantic_traversal.py` is bundled beside the query client and covered
by its manifest descriptor. Semantic walks score query proximity, progress
toward the query, embedding-space direction alignment, relationship weight,
and depth penalty. Missing embeddings fall back to relationship structure and
must be reported as approximate.
