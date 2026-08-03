# Embeddings and indexing

| Field | Value |
| --- | --- |
| Interface | `RetrievalArchitecture@1` |
| Task | `IPFSDOC-030` |
| Status | `canonical` |
| Owner | architecture / retrieval domain |
| Source of truth | `ipfs_datasets_py/embeddings/`; `ipfs_datasets_py/ml/embeddings/`; `ipfs_datasets_py/embeddings_router.py`; `ipfs_datasets_py/embedding_router.py`; `ipfs_datasets_py/vector_stores/sharding/`; packaging extras and env flags |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after embedding engine, schema, shard, or router changes |

> **Sibling guides:** Persistence and backend protocol differences live in
> [VECTOR_STORES.md](VECTOR_STORES.md). Query paths (semantic, hybrid,
> streaming, optimizers) live in [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md).
> Content identity (CID profiles, IPLD codecs) lives in
> [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md).

## 1. Purpose

This guide answers: **how dense and sparse embeddings are generated, routed,
chunked, schema-bound, and sharded for index construction**—including which
paths are real model inference, which are mocks/fallbacks, and how shard
identity relates to vector identity and content CIDs.

It is the embedding and indexing leaf of the retrieval domain. Vector *store*
lifecycle and backend-specific ANN features are not generalized here.

## 2. Audience

- **Primary:** developers and agents implementing embedding generation,
  chunking, sharding, or wiring MCP embedding tools.
- **Secondary:** architects placing retrieval paths; operators diagnosing
  optional ML dependency failures.

## 3. Scope and non-goals

### In scope

- Dense embedding generation (`generation_engine`, `AdvancedIPFSEmbeddings`,
  optional `ml.embeddings` / router paths).
- Sparse embedding models and the mock sparse service.
- Chunking configuration and document/chunk schemas.
- Embedding result schemas and identity fields.
- Shard strategies (by count/dimension, by cluster) and shard manifests.
- Distributed shard coordination (`vector_stores/sharding`) as index layout.
- Optional model stacks, endpoint routing, and unavailable/mock behavior.
- MCP tool surfaces that thin-wrap these engines.

### Non-goals

- ANN index types, Qdrant/Elasticsearch/FAISS feature matrices →
  [VECTOR_STORES.md](VECTOR_STORES.md).
- Semantic/hybrid query fusion, streaming loaders, query optimizers →
  [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md).
- GraphRAG orchestration and knowledge-graph authority → knowledge guides
  (IPFSDOC-031+).
- Changing production embedding code as part of this documentation task.

## 4. Context

Retrieval in `ipfs_datasets_py` is layered so that **embedding generation** is
separate from **vector storage** and from **query execution**:

1. Text (or multimodal payload) is chunked and encoded into dense or sparse
   vectors.
2. Vectors are packaged as schema objects (`EmbeddingResult` / sparse
   records) with stable chunk IDs and optional model metadata.
3. Large corpora may be **sharded** by count, dimension slice, cluster, or
   consistent-hash ring before index materialization.
4. Stores persist and index vectors; search engines consume them.

Heavy ML dependencies (torch, transformers, sentence-transformers, accelerate)
are **optional**. Callers must treat fallback constant vectors and simulated
search as **not** production similarity results
([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md),
[ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

Two package surfaces coexist:

| Surface | Path | Role |
| --- | --- | --- |
| Lightweight embeddings | `ipfs_datasets_py/embeddings/` | Dependency-light engines, MCP re-exports, sparse/mock services |
| ML embeddings | `ipfs_datasets_py/ml/embeddings/` | Schema source of truth, chunker, core models, multi-model helpers |

`embeddings/schema.py` loads `ml/embeddings/schema.py` by file path to avoid
pulling heavy `ml.embeddings` package side effects during vector-store-only
imports.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Dense/sparse vector generation contracts | ANN index create/search semantics per backend |
| Chunking configs and `DocumentChunk` / `EmbeddingResult` shapes | Pin lifecycle / IPFS backend selection |
| Shard file layouts and shard ring assignment | Graph facts, proof, or critic scores |
| Optional model / endpoint routing for embeddings | Knowledge-graph entity identity |
| Mock/fallback embedding services when deps missing | Query optimizer statistics |

**Inbound callers:** Python API (`embeddings`, `ml.embeddings`), MCP tool
families (`embedding_tools`, `sparse_embedding_tools`, shard tools),
`vector_stores.RouterIntegration` when auto-embedding is enabled, search
paths that encode queries.

**Outbound dependencies:** optional `IPFSEmbeddings` / router modules;
numpy (sparse mock and array wrappers); sentence-transformers / torch when
installed; filesystem for shard manifests and file-based generation.

**Authority notes:** An embedding vector is a **derived representation**, not
content identity. A CID on an IPLD-stored vector is a content identifier for
the serialized block; it is not proof of semantic correctness
([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Package exports | `embeddings/__init__.py` | Public re-exports: sparse, shard, semantic search, generation, advanced engine |
| Generation engine | `embeddings/generation_engine.py` | `generate_embedding`, `generate_batch_embeddings`, `generate_embeddings_from_file` |
| Advanced engine | `embeddings/embeddings_engine.py` | `AdvancedIPFSEmbeddings`, `EmbeddingConfig`, `ChunkingConfig` |
| Sparse engine | `embeddings/sparse_embedding_engine.py` | `SparseModel`, `SparseEmbedding`, `MockSparseEmbeddingService` |
| Shard engine | `embeddings/shard_embeddings_engine.py` | Dimension/count sharding, cluster sharding, merge |
| Semantic search (engine-side) | `embeddings/semantic_search_engine.py` | Simulated semantic/multi-modal/hybrid helpers (see SEARCH guide) |
| Schema shim | `embeddings/schema.py` | Loads `ml/embeddings/schema.py` without package side effects |
| ML schema | `ml/embeddings/schema.py` | `EmbeddingResult`, `SearchResult`, `EmbeddingConfig`, `VectorStoreConfig`, `VectorStoreType` |
| ML core / multi-model | `ml/embeddings/core.py`, `multi_model_embedding.py`, `create_embeddings.py` | Heavier embedding implementations when installed |
| Chunker | `ml/embeddings/chunker.py` | Chunking utilities for document pipelines |
| Embeddings router (compat) | `embeddings_router.py` | Alias into accelerator embeddings router |
| Embedding adapter/router | `embedding_router.py`, `utils/embedding_adapter.py` | Optional adapter paths for search |
| Router integration | `vector_stores/router_integration.py` | Auto-embed + IPFS block put/get for stores |
| Shard coordinator | `vector_stores/sharding/coordinator.py` | Consistent-hash ring, `ShardMetadata`, node assignment |
| MCP dense tools | `mcp_server/tools/embedding_tools/` | Thin wrappers over generation/shard/search engines |
| MCP sparse tools | `mcp_server/tools/sparse_embedding_tools/` | Sparse generate/index/search tools |

```text
  text / file / multimodal dict
            |
            v
  ChunkingConfig / DocumentChunk
            |
            v
  +------------------+     optional      +--------------------+
  | generation_engine| ----deps miss---> | constant fallback  |
  | / AdvancedIPFS   |                   | vectors (dim 4)    |
  | / embeddings_rtr |                   +--------------------+
  +--------+---------+
           | EmbeddingResult / list[float]
           v
  +------------------+     sparse path    +---------------------------+
  | dense index path |                   | MockSparseEmbeddingService |
  +--------+---------+                   +-------------+-------------+
           |                                           |
           v                                           v
  shard engines / ring                     SparseEmbedding (indices, values)
           |
           v
  vector store add_embeddings  (see VECTOR_STORES.md)
```

## 7. End-to-end flow

### 7.1 Dense embedding happy path

1. Caller invokes `generate_embedding` / `generate_batch_embeddings` or
   `AdvancedIPFSEmbeddings.generate_embeddings`.
2. Input is validated (non-empty text; single-text max 10_000 chars; batch
   `max_texts` default 100).
3. If `IPFSEmbeddings` (or equivalent) is importable (`HAVE_EMBEDDINGS`), the
   model named in `model_name` runs and returns float vectors with `dimension`,
   optional timing/memory fields.
4. Results are returned as dicts (`status`, `embedding`/`embeddings`, `model`,
   `dimension`, `normalized`) or as numpy arrays from the advanced engine.
5. Callers map vectors into `EmbeddingResult(embedding, chunk_id, content,
   metadata, model_name)` before store ingestion.

### 7.2 Sparse embedding path

1. Choose `SparseModel` enum value: `splade`, `bm25`, `tfidf`, `bow`,
   `colbert` (declared model types).
2. `MockSparseEmbeddingService.generate_sparse_embedding` produces a
   **deterministic mock** sparse vector (seeded from text hash): indices,
   values, dimension, sparsity, model, metadata.
3. `index_sparse_embeddings` stores per-collection documents with sparse
   embeddings in process memory.
4. `sparse_search` scores by index-set overlap (Jaccard-style), not by a
   trained SPLADE network unless a future real backend replaces the mock.

**Important:** The sparse engine in-tree is a **mock service** suitable for
tests and tool contracts. Do not document it as a trained SPLADE/ColBERT
runtime.

### 7.3 Chunking

`ChunkingConfig` / `ChunkingStrategy` support:

| Method / strategy | Behavior (current) |
| --- | --- |
| `fixed` | Fixed character windows with overlap |
| `sliding_window` | Step via `step_size` |
| `semantic` / sentences | Sentence split fallback (regex); not a neural segmenter unless ML chunker is used |
| ML `ChunkingStrategy` | `SEMANTIC`, `FIXED`, `SENTENCES`, `SLIDING_WINDOW` on schema configs |

`AdvancedIPFSEmbeddings.chunk_text` returns `(start, end)` spans. Full
document pipelines may use `ml/embeddings/chunker.py` and
`DocumentChunk` with `chunk_id`, `document_id`, offsets, and metadata.

### 7.4 Sharding for index construction

#### Count / dimension shards (`shard_embeddings_engine`)

- Input: path to JSON embeddings file or list of `{ "embedding": [...] }` dicts.
- **By count:** slices into `shard_{NNNN}.json` with `shard_size` (default 1000).
- **Dimension chunks:** optional `dimension_chunks` writes
  `shard_{NNNN}_dim_{MMMM}.json` with `dimension_range` per slice.
- **Cluster shards:** `shard_embeddings_by_cluster` groups similar vectors
  (k-means when available; otherwise documented clustering method string).
- **Manifest:** `sharding_manifest.json` records totals, strategy, shard list,
  timestamps.
- **Merge:** `merge_embedding_shards` reassembles shards for downstream index
  builds.

#### Distributed ring shards (`vector_stores/sharding/coordinator.py`)

| Type | Fields / role |
| --- | --- |
| `ShardMetadata` | `shard_id`, `node_id`, `vector_count`, `size_bytes`, timestamps, optional `root_cid`, `healthy`, `replicas` |
| `ConsistentHashRing` | Virtual nodes (default 150), MD5-based placement, multi-node replica selection |
| `ShardRegistry` | `shards`, `vector_to_shard`, `node_to_shards` maps |

Shard identity (`shard_id`) and content identity (`root_cid` on a shard or
collection) are **different kinds of truth**. The ring assigns *location*;
CIDs identify *payload bytes*.

### 7.5 Routing

| Mechanism | When used | Behavior |
| --- | --- | --- |
| Direct `generation_engine` | Default MCP/Python path | Local or fallback generation |
| `AdvancedIPFSEmbeddings` endpoint registries | TEI / OpenVINO / libp2p / local maps | Config stored until generation; no network until request |
| `embeddings_router` / accelerator router | When import succeeds | Provider-routed embedding (`embed_texts`) |
| `RouterIntegration.generate_embeddings` | Vector store auto-embed | Lazy-loads embeddings module; returns vectors or raises/logs if unavailable |
| Env flags (search path) | e.g. `IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER` | Optional adapter enablement |

Default dense model string used across engines:
`sentence-transformers/all-MiniLM-L6-v2` (typically 384-dim when real models
run). Callers must record `model_name` on `EmbeddingResult` so indexes are not
mixed across dimensions or spaces without an explicit rebuild.

### 7.6 Initialization and lifecycle

1. Import lightweight `embeddings` package (safe without torch).
2. First real generation attempts optional heavy import; on failure sets
   `HAVE_EMBEDDINGS = False` and uses fallback vectors.
3. Sparse service is process-local (`get_default_sparse_service`); no durable
   sparse index unless a vector store backend is used.
4. Shard writers create output directories and manifests on disk.
5. Index *materialization* (FAISS files, Qdrant collections, ES indices, IPLD
   export) is owned by vector stores after embeddings exist.

## 8. Contracts

### 8.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| Text | `str` or dict with `text` / modality | Non-empty string; length caps in generation engine |
| Batch texts | `List[str]` | Non-empty; `max_texts` (default 100) |
| File path | path for `generate_embeddings_from_file` | Exists, is file, non-empty content |
| `model_name` | string | Passed through; no offline model registry enforcement |
| Sparse model | `SparseModel` or string | Known keys in mock service dict, else SPLADE defaults |
| Shard embeddings data | path or list of dicts with `embedding` | Format checks; empty rejected |

### 8.2 Outputs

| Output | Type / sink | Guarantees |
| --- | --- | --- |
| Dense result dict | `status`, vectors, `model`, `dimension` | `status=success` may still be **fallback** (see `message`) |
| `EmbeddingResult` | schema dataclass | `chunk_id` + `embedding` + `content`; metadata optional |
| `SparseEmbedding` | indices, values, dimension, sparsity | Mock-deterministic for same text+model seed path |
| Shard manifest | JSON on disk | Lists shards; not a CID |
| Shard `root_cid` | optional on `ShardMetadata` | Set only when IPLD export attaches a CID |

### 8.3 Public surfaces

- **Python API:** `ipfs_datasets_py.embeddings` (`generate_*`,
  `AdvancedIPFSEmbeddings`, sparse/shard helpers);
  `ipfs_datasets_py.ml.embeddings` for heavy/schema paths.
- **CLI:** domain CLIs may wrap engines; primary automation is MCP/Python.
- **MCP tools:** `embedding_tools` (generation, advanced, shard, cluster,
  advanced search registration); `sparse_embedding_tools`.
- **Config / env:** model names and endpoint maps on configs; search/adapter
  flags such as `IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER`,
  `IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `IPFS_KIT_DISABLE`.

### 8.4 Persistence and identity

| Kind | What it is | What it is not |
| --- | --- | --- |
| `chunk_id` | Stable application ID for a chunk | Content CID |
| `model_name` + dimension | Embedding space identity | Guarantee of model weights availability |
| Shard filename / `shard_id` | Partition identity | Global uniqueness across clusters without registry |
| Vector CID / collection `root_cid` | IPLD content id after store export | Semantic provenance of the source document |
| Sparse collection name | In-memory mock index key | Durable store name unless mirrored to a backend |

Provenance of **source documents** (lineage, receipts) is owned by analytics /
provenance modules and storage guides—not by the embedding engine. Embeddings
may *carry* metadata fields pointing at sources; they do not mint authority.

## 9. Failure modes and fallbacks

| Failure | Detection | Caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| Heavy embeddings not installed | `ImportError` → `HAVE_EMBEDDINGS=False` | `status=success` with fixed 4-d vectors and `message` about fallback | Constant placeholder vectors—**not** semantic |
| Generation exception | try/except in engine | `status=error`, `error` string | No silent success |
| Empty/invalid text | validation | `status=error` | Reject |
| Batch too large | `max_texts` | `status=error` | Reject |
| Sparse collection missing | lookup | Empty result list from `sparse_search` | No fabricated hits with success masquerading as indexed data |
| Cluster shard without sklearn/numpy | method path | Error status or reduced clustering | Depends on implementation path—treat cluster shards as optional-dep |
| `index_dataset` / `search_similar` on advanced engine | stub bodies | Success-shaped stub or synthetic results | Explicit stub notes in code (`indexed_count: 0`, sample results) |
| Router module missing | import in `RouterIntegration` | Embeddings router unavailable flags | Store may require precomputed vectors |

Explicit distinctions:

- **Not installed** (`HAVE_EMBEDDINGS=False`) vs **installed but failed**
  (`status=error` after exception).
- **Mock sparse service** vs **real SPLADE/BM25 library** (only mock is
  default in-tree).
- **Stub index_dataset / simulated search** vs **store-backed ANN search**.

## 10. Extension points

1. Add a real sparse backend behind `SparseModel` without changing the
   `SparseEmbedding` wire shape; keep mock for tests.
2. Register new dense models via `model_name` and optional multi-model helpers
   under `ml/embeddings/`; record dimension in results and store config.
3. Extend shard strategies in `shard_embeddings_engine` or ring policies in
   `sharding/coordinator.py`; update manifests/metadata fields.
4. Wire MCP tools as thin re-exports only—business logic stays in engines.
5. Tests: unit tests under `tests/unit` / embedding tool tests; do not require
   GPU for contract tests.

Anti-patterns:

- Treating fallback 4-d vectors as production embeddings.
- Mixing models/dimensions in one collection without rebuild.
- Putting model download or torch imports in MCP tool modules.
- Claiming sparse `SPLADE`/`COLBERT` enum values imply trained weights.

## 11. Invariants

1. Dense generation either uses a real embedding engine or clearly labels
   fallback output; callers must check `message` / dependency probes for
   production gates.
2. `EmbeddingResult.chunk_id` and vector bytes are the unit of store upsert;
   schema aliases (`id`/`vector`/`text`) must remain compatible.
3. Shard manifests describe partitions; they are not substitutes for content
   CIDs or search indexes.
4. Sparse mock collections are process-local unless exported to a durable
   store.
5. Optional ML dependencies must not make lightweight import of
   `embeddings` or vector-store schema fail hard when schema is loaded via
   the file-path shim.
6. Backend-specific index features (HNSW params, ES analyzers, Qdrant
   filters) are not part of the embedding contract.

## 12. Rationale and decisions

| Topic | Summary | ADR / source |
| --- | --- | --- |
| Split lightweight vs ML packages | Keep MCP and vector-store imports usable without torch | `embeddings/__init__.py`, schema shim |
| Fallback vectors on missing deps | Preserve tool/demo shape offline | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Mock sparse service | Contract stability before real sparse runtimes | `sparse_embedding_engine.py` |
| Schema ownership in `ml/embeddings` | Single EmbeddingResult/SearchResult definition | `ml/embeddings/schema.py` |
| Shard vs CID | Partitioning vs content addressing | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |

Alternatives rejected (brief):

- Always requiring torch at import — rejected; breaks minimal installs.
- Presenting simulated semantic search as full store integration — rejected;
  results carry explicit simulation notes (see SEARCH guide).

## 13. Security, privacy, and trust boundaries

- Trust boundaries: remote TEI/OpenVINO/libp2p endpoints are untrusted network
  surfaces; validate endpoint config before production use.
- Secrets: API keys for hosted embedding providers belong in env/secret
  stores, not in shard JSON or collection metadata committed to git.
- Embeddings of private text are still sensitive data when stored or pinned.
- This layer must not claim authorization, proof, or policy approval over
  retrieved content.

## 14. Observability and operations

- Logs: `logging` on generation failures, fallback warnings, shard errors.
- Stats: sparse service counters (`embeddings_generated`, `searches_performed`,
  collections/docs); generation optional `processing_time` / `memory_usage`.
- Diagnostics: probe `HAVE_EMBEDDINGS`, sparse model dict, shard manifest
  presence; compare `dimension` across batch members before indexing.

## 15. Validation

```bash
# Paths exist
test -e ipfs_datasets_py/embeddings/generation_engine.py
test -e ipfs_datasets_py/embeddings/sparse_embedding_engine.py
test -e ipfs_datasets_py/embeddings/shard_embeddings_engine.py
test -e ipfs_datasets_py/ml/embeddings/schema.py
test -e ipfs_datasets_py/vector_stores/sharding/coordinator.py

# Focused collection (optional; may skip if deps missing)
# pytest tests/unit_tests/embedding_tools -q --collect-only
# pytest tests/unit/vector_stores -q --collect-only
```

Known validation limits: full model inference and real SPLADE require optional
extras and often network model downloads; offline CI should rely on mock and
fallback paths.

## 16. Related documentation

| Document | Relationship |
| --- | --- |
| [VECTOR_STORES.md](VECTOR_STORES.md) | Store protocol, backends, index lifecycle |
| [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Query paths, hybrid fusion, optimizers, streaming |
| [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md) | CID / IPLD identity model |
| [STORAGE_CACHING_AND_BACKENDS.md](../storage/STORAGE_CACHING_AND_BACKENDS.md) | IPFS backend location, not embedding space |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Identifier vs location vs receipt |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional capabilities |
| Package READMEs under `vector_stores/`, historical `docs/IPLD_VECTOR_STORE_*` | Historical / usage detail; this guide is the architecture leaf |
