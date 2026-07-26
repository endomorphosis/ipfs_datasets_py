# Intent IR scaffold

Intent IR is the source-grounded semantic boundary between skill corpora,
GraphRAG, and formal-logic training. It represents goals, modalities,
conditions, actions, effects, verification steps, and control flow. It never
authorizes or executes commands found in a source skill.

The current scaffold contains:

- an immutable canonical schema and cross-reference validator;
- deterministic JSON and SHA-256 content identity;
- backend-neutral normalizer, GraphRAG, formalizer, and artifact-store ports;
- a bounded read-only adapter and source-use policy for pinned SkillCenter
  SQLite bundles;
- resumable, policy-gated embedding checkpoints routed through
  `ipfs_accelerate_py`; and
- a versioned corpus-evidence ontology, deterministic projector,
  partition-isolated retriever, persisted BM25 bag-of-words index, and
  integrity-bound FAISS GraphRAG index.

It deliberately does not execute source skills or treat retrieved context as
proof. The LLM normalizer and trained autoencoder head still belong behind the
bounded protocols and evaluation gates.

## Intended artifact chain

```text
pinned HF bundle
  -> raw bundle CID + manifest
  -> bounded SkillCenter record/content CID
  -> validated IntentIRDocument CID
  -> GraphRAG projection CID
  -> formal-logic projection CID
  -> proof/evaluation receipt CID
```

Each arrow must retain the parent identity, producer version, configuration
digest, diagnostics, and review state. Training and proof artifacts must refer
to bodies by CID rather than recursively embedding the corpus.

## SkillCenter pilot operations

Generate or resume the pinned pilot embeddings:

```bash
python scripts/ops/intent_ir/build_skillcenter_embeddings.py \
  --profile security-lite
python scripts/ops/intent_ir/build_skillcenter_embeddings.py \
  --profile github-lite
```

Build the policy-gated BM25 bag-of-words index:

```bash
python scripts/ops/intent_ir/build_skillcenter_bm25.py \
  --smoke-query "credential rotation verification"
```

Regenerate the combined graph/vector snapshot with BM25-scored lexical
neighborhoods, then optionally exercise both lexical and dense retrieval:

```bash
python scripts/ops/intent_ir/build_skillcenter_graphrag.py \
  --neighbor-backend bm25 \
  --smoke-query "How do I verify a credential rotation?"
```

The BM25 output contains deterministic document metadata, vocabulary, postings,
and policy-decision tables without storing source bodies. The GraphRAG output
contains a FAISS cosine index, metadata and split tables, the immutable corpus
graph, a scored neighbor table, and separately content-addressed source blocks.
With `--neighbor-backend bm25`, every graph `NEIGHBOR_OF` edge records its BM25
score and matched terms while FAISS remains available as a complementary dense
retriever. Loading either index rehashes every declared artifact and fails
closed on graph, lexical index, vector, checkpoint, policy, or configuration
drift.

## Complete SkillCenter corpus

The full-corpus path is separate from the bounded pilot path above. It treats
every physical record in every SQLite bundle as internal retrieval material,
while retaining each record's policy decision and never executing skill
instructions.

The pinned Hub revision
`f9dd4fec3c86d85ebf116c7408ac5ce602c418a1` contains 24 SQLite bundles and
216,972 physical records. This audited count is authoritative for the build:
it is 34 greater than the dataset-card total of 216,938. One bundle,
`clawskills-bundle-lite-other-v20260227.sqlite`, declares 14,983 records in its
metadata but physically contains 750; the content table, search index, and join
table all agree on the physical count.

Each row is keyed by `entry_cid`, a CIDv1/base32/raw/sha2-256 identifier over a
versioned, canonical, container-independent representation of the intrinsic
skill record. CID creation uses the package CID utilities and artifact loading
uses the shared CID validator. The corpus also retains the CID bytes,
multihash bytes, raw SHA-256 digest, exact body CID, and source-bundle CID.
Unchanged content therefore keeps its primary key if a bundle is repackaged.

Download the pinned snapshot if necessary and build or fully verify the
canonical Parquet corpus:

```bash
python scripts/ops/intent_ir/build_skillcenter_corpus.py --download
python scripts/ops/intent_ir/build_skillcenter_corpus.py --verify-only
```

Build the complete CID-keyed BM25 index and the resumable BM25-derived property
graph:

```bash
python scripts/ops/intent_ir/build_skillcenter_corpus_bm25.py \
  --smoke-query "credential rotation verification"
python scripts/ops/intent_ir/build_skillcenter_cid_graph.py \
  --query-workers 16 \
  --neighbor-k 8 \
  --smoke-query "credential rotation verification"
```

Generate exactly one `thenlper/gte-small` vector per `entry_cid` through
`ipfs_accelerate_py.embeddings_router`, then build the CID-keyed FAISS index.
For CUDA, first use an interpreter whose PyTorch build reports
`torch.cuda.is_available() == True`. Keep CUDA checkpoints in a device-specific
directory so they cannot be confused with CPU checkpoints. The operational
batch sizes below are powers of two:

```bash
CUDA_EMBEDDING_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}/ipfs_datasets_py/intent-ir/skillcenter-embeddings/f9dd4fec3c86d85ebf116c7408ac5ce602c418a1/full-cid/thenlper-gte-small-cuda"
CUDA_VECTOR_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}/ipfs_datasets_py/intent-ir/skillcenter-vectors/f9dd4fec3c86d85ebf116c7408ac5ce602c418a1/full-cid/thenlper-gte-small-cuda"

python scripts/ops/intent_ir/build_skillcenter_full_embeddings.py \
  --model thenlper/gte-small \
  --provider huggingface \
  --device cuda \
  --source-batch-size 512 \
  --router-batch-size 256 \
  --router-workers 1 \
  --output-dir "${CUDA_EMBEDDING_ROOT}"
python scripts/ops/intent_ir/build_skillcenter_cid_vectors.py \
  --model thenlper/gte-small \
  --embedding-dir "${CUDA_EMBEDDING_ROOT}" \
  --output-dir "${CUDA_VECTOR_ROOT}" \
  --query-device cuda \
  --smoke-query "credential rotation verification"
python scripts/ops/intent_ir/audit_skillcenter_cid_indexes.py \
  --vector-dir "${CUDA_VECTOR_ROOT}" \
  --verify-corpus-rows
```

The full BM25 database, graph, vector metadata, and Parquet CID sidecar all
join on the same `entry_cid`. File and graph-root CIDs describe local content
identities; they do not by themselves assert that the artifacts have been
published or pinned to an IPFS network.

### Hugging Face thin-client release

Convert the canonical corpus, BM25 FTS5 database, GraphRAG database, and FAISS
index into a Hugging Face dataset card plus uniformly Zstandard-compressed
Parquet. Every data file contains at most 4,096 rows. The BM25 meta-index maps
non-overlapping lexical ranges to posting shards; the vector meta-index maps
normalized semantic centroids to vector shards. Recursive spherical k-means
guarantees that each centroid maps to only one or two physical shards, and
rows are sorted by decreasing cosine similarity to their shard centroid.

```bash
HF_RELEASE_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}/ipfs_datasets_py/intent-ir/skillcenter-huggingface/f9dd4fec3c86d85ebf116c7408ac5ce602c418a1/full-cid-zstd"

python scripts/ops/intent_ir/build_skillcenter_hf_release.py \
  --output-dir "${HF_RELEASE_ROOT}" \
  --dataset-repo-id Tommysha/skillcenter-ir
python scripts/ops/intent_ir/build_skillcenter_hf_release.py \
  --output-dir "${HF_RELEASE_ROOT}" \
  --validate-only
```

Upgrade an existing v1 release without rebuilding or duplicating its corpus,
BM25, and graph Parquet files:

```bash
HF_RELEASE_V2_ROOT="${HF_RELEASE_ROOT}-centroid-v2"
python scripts/ops/intent_ir/build_skillcenter_hf_release.py \
  --rebalance-from "${HF_RELEASE_ROOT}" \
  --output-dir "${HF_RELEASE_V2_ROOT}"
```

Stable files are hard-linked when both release roots use the same filesystem;
the source release is not changed.

Add paged incoming/outgoing graph navigation to the centroid-sorted v2
release without rebuilding its corpus, BM25, graph tables, or vectors:

```bash
HF_RELEASE_V3_ROOT="${HF_RELEASE_ROOT}-graph-v3"
python scripts/ops/intent_ir/build_skillcenter_hf_release.py \
  --graph-navigation-from "${HF_RELEASE_V2_ROOT}" \
  --output-dir "${HF_RELEASE_V3_ROOT}"
```

The generated `README.md`, `manifest.json`, remote query client, reusable
`semantic_traversal.py` engine, and `query-skillcenter-hf` agent skill are
included in the release root. Test bounded retrieval locally before upload:

```bash
python scripts/ops/intent_ir/query_skillcenter_hf.py \
  --local-root "${HF_RELEASE_ROOT}" \
  bm25 "securely rotate API credentials" --top-k 10
python scripts/ops/intent_ir/query_skillcenter_hf.py \
  --local-root "${HF_RELEASE_ROOT}" \
  vector "securely rotate API credentials" \
  --candidate-centroids 4 --device auto --top-k 10
python scripts/ops/intent_ir/query_skillcenter_hf.py \
  --local-root "${HF_RELEASE_V3_ROOT}" \
  graph neighbors "<node-cid>" --direction both --limit 25
python scripts/ops/intent_ir/query_skillcenter_hf.py \
  --local-root "${HF_RELEASE_V3_ROOT}" \
  graph walk "<node-cid>" --max-depth 2 --max-nodes 100 \
  --max-edges 500 --max-shards 32
python scripts/ops/intent_ir/query_skillcenter_hf.py \
  --local-root "${HF_RELEASE_V3_ROOT}" \
  graph walk "<node-cid>" --strategy semantic-beam \
  --query "securely rotate API credentials" --direction adaptive \
  --candidate-centroids 4 --max-vector-shards 8 --beam-width 16 \
  --max-depth 2 --max-nodes 100 --max-edges 500 --max-shards 32
```

After publishing the release folder, omit `--local-root` and pass the Hub
repository and a pinned commit through `--repo-id` and `--revision`. The query
response includes a `fetch_trace` listing every downloaded meta-index, posting
or vector shard, and result-bearing corpus shard.

Embedding-guided traversal is implemented once in
`knowledge_graphs.query.semantic_traversal`. The canonical hybrid query engine,
legacy GraphRAG compatibility surfaces, serialized graph path search, and the
SkillCenter thin client all delegate to it. BFS remains the default. Semantic
walks batch candidate-vector lookups, score proximity/progress/direction and
edge structure, and enforce depth, node, edge, degree, beam, backend-call,
adjacency-shard, and vector-shard ceilings. Missing node vectors fall back to
structural scoring and are reported as approximate.
