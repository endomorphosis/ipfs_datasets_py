# Search and query

| Field | Value |
| --- | --- |
| Interface | `RetrievalArchitecture@1` |
| Task | `IPFSDOC-030` |
| Status | `canonical` |
| Owner | architecture / retrieval domain |
| Source of truth | `ipfs_datasets_py/search/`; `ipfs_datasets_py/embeddings/semantic_search_engine.py`; `ipfs_datasets_py/mcp_server/tools/search_tools/`; `ipfs_datasets_py/mcp_server/tools/embedding_tools/advanced_search.py` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after search engine, optimizer, or streaming loader changes |

> **Sibling guides:** Embedding generation is in
> [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md). Store protocols and
> backend differences are in [VECTOR_STORES.md](VECTOR_STORES.md). Graph query
> IR and sharded CAR graph backends under `search/graph_query/` are adjacent
> but **graph-authority** details belong to knowledge guides; this page maps
> only how they attach to retrieval.

## 1. Purpose

This guide answers: **how semantic, hybrid, multi-modal, filtered, and
streaming searches are invoked; how query optimization and caching work; what
is simulated versus store-backed; and how consistency and provenance appear in
results**—without claiming unavailable models or generalizing backend filters.

## 2. Audience

- **Primary:** developers and agents implementing retrieval queries, MCP
  search tools, or optimizer integration.
- **Secondary:** operators tuning caches and streaming throughput; architects
  separating vector search from GraphRAG/logic RAG.

## 3. Scope and non-goals

### In scope

- `search_embeddings` orchestration (Qdrant preference, FAISS fallback, mocks).
- Engine-side semantic / multi-modal / hybrid / filtered helpers in
  `embeddings/semantic_search_engine.py` (including simulation notes).
- Store-level `search` / `similarity_search` contracts (referenced, not
  re-specified).
- `QueryOptimizer` family: stats, LRU cache, index registry, vector/graph/hybrid
  optimizers.
- Streaming loaders (`StreamingDataLoader`, memory-mapped vectors, stats/cache).
- Content discovery and vector tool helpers under `search/`.
- Logic-enhanced / theorem-augmented RAG **attachment points** (boundary only).
- Optional models, mocks, env flags, unavailable behavior.

### Non-goals

- Embedding training or sparse mock internals → embeddings guide.
- FAISS index type matrix / ES mappings → vector stores guide.
- Full knowledge-graph lifecycle and GraphRAG planner authority → knowledge
  guides (IPFSDOC-031+).
- Proving ranking quality or evaluation harnesses (benchmarks exist separately).

## 4. Context

Search is a **composition layer**:

1. Encode the query (dense embedding, sparse terms, or multi-modal features).
2. Select backend(s) and optional indexes.
3. Retrieve candidates (ANN, lexical, or hybrid fusion).
4. Optionally re-rank, filter, cache, and record metrics.
5. Return ranked hits with scores and metadata—not proofs.

Multiple implementations coexist and **must not be collapsed**:

| Path | Module | Production readiness (current tree) |
| --- | --- | --- |
| Store protocol search | `BaseVectorStore.search` | Real when backend deps and data present |
| `search_embeddings` class | `search/search_embeddings.py` | Backend-oriented orchestration; heavy optional deps |
| Mock `search_embeddings` | `search/search_embeddings_mock.py` | Empty/mock results when import fails |
| Semantic engine helpers | `embeddings/semantic_search_engine.py` | **Simulated** results with explicit `note` fields |
| Management engine search | `vector_stores/management_engine.py` | FAISS/Qdrant/ES index search helpers |
| Query optimizers | `search/query_optimizer.py` | Planning/cache/metrics around executors |
| Streaming loaders | `search/streaming_data_loader.py` | Large dataset I/O, not ANN by itself |
| Graph query package | `search/graph_query/` | Graph IR execution (separate authority) |
| Logic / theorem RAG | `search/logic_integration/` | Augments RAG with logic—not pure vector search |

Historical module notes live in `search/ARCHITECTURE.md`; this guide is the
canonical architecture leaf for documentation refresh IPFSDOC-030.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Query orchestration and result ranking APIs | Embedding weight storage |
| Hybrid fusion parameters at search engines / optimizers | Graph fact persistence schemas |
| Query metrics, caches, index registry for optimizers | Vector collection create/delete (stores) |
| Streaming read paths for large corpora | IPFS pin policy |
| Declaring mock/simulated search behavior | Legal/authorization gates on results |

**Inbound callers:** Python `search` package, MCP `search_tools` and advanced
embedding search tools, GraphRAG adapters, CLIs (`search/cli.py`).

**Outbound dependencies:** vector stores; embedding generation/router;
optional ipfs_kit, qdrant, datasets, pyarrow; optimizers may call injected
executor callables.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Package init | `search/__init__.py` | Imports real or mock `search_embeddings`; optional logic exports |
| Search embeddings | `search/search_embeddings.py` | Core semantic search class over Qdrant/FAISS/IPFS kit |
| Mock search | `search/search_embeddings_mock.py` | Dependency-free stub |
| Semantic engine | `embeddings/semantic_search_engine.py` | `semantic_search`, `multi_modal_search`, `hybrid_search`, `search_with_filters` |
| Query optimizer | `search/query_optimizer.py` | Metrics, cache, index registry, vector/graph/hybrid optimizers |
| Streaming loader | `search/streaming_data_loader.py` | Streaming + mmap vector loading |
| Content discovery | `search/content_discovery.py` | Discovery helpers |
| Vector tools | `search/vector_tools.py` | Vector-oriented search utilities |
| Search tools API | `search/search_tools_api.py` | API surface for tools |
| Graph query | `search/graph_query/` | IR, executor, sharded CAR backends |
| GraphRAG integration | `search/graphrag_integration/` | Adapter into GraphRAG |
| Logic integration | `search/logic_integration/` | Logic-aware RAG variants |
| Recommendations | `search/recommendations/` | Recommendation engine |
| MCP search tools | `mcp_server/tools/search_tools/` | Thin wrappers |
| MCP advanced search | `mcp_server/tools/embedding_tools/advanced_search.py` | Wraps semantic engine |

```text
Query text/image
      |
      +---> generate query embedding (real or fallback)
      |
      +---> path selection
              |
              +-- semantic_search_engine (often simulated)
              +-- search_embeddings (Qdrant if up else FAISS)
              +-- BaseVectorStore.search (store-backed)
              +-- HybridQueryOptimizer (vector + graph plans)
              +-- graph_query executor (graph IR)
      |
      v
 Ranked results + metrics/cache (+ optional logic augmentation)
```

## 7. End-to-end flows

### 7.1 Store-backed vector search (authoritative when wired)

1. Obtain query vector via generation engine or router (same model/dimension as
   the collection).
2. Call `await store.search(query_vector, top_k, collection_name, filter_dict)`.
3. Optionally `similarity_search` with `score_threshold`.
4. Interpret `SearchResult.score` in the store’s metric (cosine IP, L2, etc.).
5. Backend filter support is **not** universal—see VECTOR_STORES matrix.

### 7.2 `search_embeddings` orchestration

From class design and package docs:

1. Configure `resources` (models, stores, IPFS nodes, caches, memory limits)
   and `metadata` (search config, mappings, performance).
2. Detect Qdrant availability (historically port 6333); set `qdrant_found`.
3. Prefer Qdrant ingest/search iterators when available; otherwise FAISS via
   ipfs_kit-related helpers when enabled.
4. `generate_embeddings` for queries; `search(collection, query, n)` returns
   ranked documents.
5. Memory modes: low-memory iterative pairs vs high-memory full load tests.
6. Env controls:
   - `IPFS_KIT_DISABLE` / `IPFS_DATASETS_PY_BENCHMARK` → disable kit load
   - `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` → enable kit
   - `IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER` → adapter path
7. Optional accelerate integration when installed.

If `search_embeddings` import fails, package init substitutes the mock class
and logs a warning.

### 7.3 Semantic engine helpers (simulated by default)

`semantic_search`, `multi_modal_search`, `hybrid_search`, and
`search_with_filters` validate inputs then return **structured simulated
hits** with notes such as:

- “Simulated semantic search - full implementation requires vector store
  integration”
- Multi-modal note requiring CLIP or similar
- Hybrid combines lexical and semantic **synthetic** candidate lists with
  weights (`lexical_weight`, `semantic_weight`), optional rerank flag

These APIs are useful for MCP contract shapes and demos. They are **not**
store-backed ANN unless a later integration replaces the simulation body.

Validation highlights:

| API | Checks |
| --- | --- |
| `semantic_search` | non-empty query; `vector_store_id` required; `top_k` in 1..1000; threshold in [0,1] |
| `multi_modal_search` | text and/or image query; store id; modality weights normalized |
| `hybrid_search` | query + store id; weights renormalized if sum &gt; 0 |

### 7.4 Hybrid search (two meanings)

Do not conflate:

1. **Engine hybrid** (`hybrid_search` in semantic engine): weighted merge of
   simulated lexical and semantic lists; optional rerank flag.
2. **Optimizer hybrid** (`HybridQueryOptimizer`): plans/executes combined
   vector + knowledge-graph query parameters with adaptive weights via
   `QueryOptimizer` infrastructure.
3. **Elasticsearch hybrid**: possible only when using ES text + `dense_vector`
   features on that backend—not portable to FAISS alone.

### 7.5 Streaming search-oriented I/O

`streaming_data_loader.py` provides:

| Class | Role |
| --- | --- |
| `StreamingStats` | Throughput, batch timings |
| `StreamingCache` | Prefetch/cache for stream consumers |
| `StreamingDataLoader` | Format-aware streaming (Parquet/CSV/JSON, etc.) when pyarrow/datasets present |
| `MemoryMappedVectorLoader` | mmap large vector matrices without full RAM load |
| `StreamingDataset` | Dataset-shaped streaming access |

Streaming is for **loading and iterating** large corpora or vector tables. It
does not replace ANN indexes; it feeds indexing or offline scan paths.

Optional deps: `numpy`, `pyarrow`, `datasets`—features degrade when missing.

### 7.6 Query optimization

`query_optimizer.py` components:

| Class | Role |
| --- | --- |
| `QueryMetrics` | Per-query timing, result/scan counts, cache/index flags, errors |
| `QueryStatsCollector` | History, averages, percentiles, recommendations inputs |
| `LRUQueryCache` | Keyed by query type + params hash |
| `IndexRegistry` | Register/find indexes by fields or query type |
| `QueryOptimizer` | `optimize_query`, `execute_query` with cache + metrics |
| `VectorIndexOptimizer` | Vector search param optimization / execution wrapper |
| `KnowledgeGraphQueryOptimizer` | Graph traversal planning, relationship costs, entity priorities; can execute graph IR |
| `HybridQueryOptimizer` | Combines vector + graph optimizers; adaptive weights |
| `create_query_optimizer` | Factory with cache size and collector wiring |

Optimizers **do not** invent store features. They choose plans, caches, and
indexes already registered, and record whether an index or cache was used.

### 7.7 Logic / GraphRAG attachment (boundary)

- `logic_integration`: `LogicEnhancedRAG`, `TheoremAugmentedRAG`, logic-aware
  entity extraction/graphs—results may include logical structure beyond
  vector scores.
- `graphrag_integration`: adapts search into GraphRAG pipelines.
- `graph_query`: separate IR/executor/budgets; sharded CAR routing for graph
  shards.

These must not be described as “just another vector backend.”

## 8. Contracts

### 8.1 Inputs

| Input | Source | Validation |
| --- | --- | --- |
| Query text | caller / MCP | Non-empty where required |
| Query vector | generator | Dimension must match collection |
| `vector_store_id` / collection | caller | Required by semantic engine; store name for store APIs |
| `top_k` / `n` | caller | Engine bounds; store accepts positive k |
| Filters | `filter_dict` / engine filters | Backend-specific effectiveness |
| Hybrid weights | caller | Renormalized in engine/optimizer |
| Streaming paths | filesystem / IPFS | Format + optional dep availability |

### 8.2 Outputs

| Output | Guarantees |
| --- | --- |
| Store `SearchResult` | id/content/score/metadata; score metric is backend-local |
| Semantic engine dict | `status`, `results`, often `note` for simulation |
| Mock search | `{'results': [], 'status': 'mock'}` shape |
| Optimizer execution | metrics recorded; cache hit flag when served from LRU |
| Streaming batches | iterators/generators; stats via `StreamingStats` |

### 8.3 Public surfaces

- **Python:** `ipfs_datasets_py.search` (`search_embeddings`, optimizers,
  streaming, optional logic exports); semantic helpers from
  `ipfs_datasets_py.embeddings`.
- **CLI:** `search/cli.py`.
- **MCP:** `search_tools`, advanced search in embedding tools.
- **Env:** kit and adapter flags listed in §7.2.

### 8.4 Consistency

| Path | Consistency notes |
| --- | --- |
| Store search | Sees data durable in that backend; no cross-store snapshot isolation |
| Hybrid multi-store `search_all` (manager) | Merges results from independent stores—scores may not be calibrated across stores |
| Simulated engine | Deterministic-ish synthetic scores; not tied to index state |
| Cache (`LRUQueryCache`) | Stale if underlying index mutates without `invalidate` |
| Streaming reads | Point-in-time file/object reads; not a transactional snapshot of Qdrant/ES |

### 8.5 Provenance

- Results may include metadata from indexed `EmbeddingResult.metadata`.
- IPLD search results may include `cid` / retrieval timing when using IPLD
  store.
- Logic/theorem RAG may attach reasoning traces—those are **not** vector
  similarity provenance.
- Simulation paths must not be treated as evidence of source documents in an
  audit chain.

## 9. Failure modes and fallbacks

| Failure | Detection | Behavior | Fallback |
| --- | --- | --- | --- |
| `search_embeddings` import error | package init | Mock class loaded + warning | Empty/mock search |
| Qdrant unavailable | probe / connection | Orchestration uses FAISS path when configured | Degraded backend |
| ipfs_kit disabled | env flags | Kit module None | Local-only paths |
| Embedding router missing | import | Query embed may fail or use alternate | Fallback embeddings (non-semantic) if generation falls back |
| Semantic engine validation | ValueError paths | `status=error` | No fabricated success without error field |
| Optional accelerate missing | `HAVE_ACCELERATE` | Distributed inference off | Local path |
| Streaming without pyarrow | `HAVE_ARROW` | Format support reduced | Error or limited loaders |
| Cache key collision / stale | operator concern | Wrong cached answer until invalidate | Call `invalidate_cache` after reindex |
| Graph IR budget exceeded | graph_query budgets | Structured error via optimizer serialization helpers | Fail closed for that plan |

Explicit distinctions:

- **Simulated success** (semantic engine `note`) vs **store-backed success**.
- **Mock module** (import failure) vs **empty collection** (valid search, zero
  hits).
- **Optimizer plan failure** vs **backend search failure**.

## 10. Optional models and unavailable behavior

| Capability | Optional pieces | Unavailable behavior |
| --- | --- | --- |
| Dense query encode | sentence-transformers/torch / router providers | Fallback constant vectors if generation_engine fallback engages |
| Multi-modal | CLIP-class models (`clip-ViT-B-32` string in API) | Simulation only in semantic engine |
| Qdrant | server + qdrant-client | FAISS or error depending on caller |
| FAISS | faiss-cpu/gpu | Store constructor errors; search_embeddings may lose FAISS path |
| ES hybrid text | elasticsearch | N/A on pure FAISS |
| Streaming columnar | pyarrow, datasets | Reduced streaming formats |
| Accelerate | accelerate integration module | Local embedding only |
| Logic RAG | logic_integration imports | Package exports omit logic symbols if import fails |

Default dense model strings appearing in search-related configs/docs include
`sentence-transformers/all-MiniLM-L6-v2`, and historical notes mention
`thenlper/gte-small`, `Alibaba-NLP/gte-*` endpoints—availability is
environment-specific, not guaranteed by the search package.

## 11. Extension points

1. Replace simulation bodies in `semantic_search_engine` with real store
   lookups while keeping the public dict contract and validation.
2. Register new index metadata in `IndexRegistry` for optimizer selection.
3. Add executor callables to `QueryOptimizer.execute_query` for new query
   types.
4. Extend streaming format handlers behind `HAVE_*` guards.
5. Keep MCP tools as re-exports; put fusion logic in engines/optimizers.
6. Tests: `tests/unit/search`, `tests/unit_tests/search` for contracts;
   integration tests only when backends provisioned.

Anti-patterns:

- Calibrating scores across FAISS IP and ES l2 without conversion.
- Treating mock/simulated hits as evaluation gold.
- Putting ANN index files under “streaming search” without an index.
- Using query cache across model version changes without invalidation.

## 12. Invariants

1. Every production retrieval path must document whether it is store-backed,
   simulated, or mock.
2. Query embedding model/dimension must match the target collection’s
   embedding space.
3. Hybrid weights are normalized before fusion when engines/optimizers apply
   them.
4. Optimizer caches are correctness-sensitive to index mutation—invalidate on
   rebuild.
5. Backend filter and hybrid lexical features are never documented as
   universal.
6. Graph/logic augmentations are additive layers; they do not redefine vector
   score meaning.

## 13. Rationale and decisions

| Topic | Summary | Source |
| --- | --- | --- |
| Mock on import failure | Keep package importable | `search/__init__.py`, ADR-002/004 |
| Simulated semantic engine | Stable MCP/tool contracts offline | `semantic_search_engine.py` |
| Optimizer separate from stores | Planning/metrics without owning storage | `query_optimizer.py` |
| Streaming separate from ANN | I/O scale vs index algorithms | `streaming_data_loader.py` |
| Qdrant preferred, FAISS fallback | Historical orchestration | `search/ARCHITECTURE.md`, `search_embeddings.py` |

Alternatives rejected:

- Single search API hiding simulation vs real—rejected; agents would misread
  evidence.
- Global score threshold semantics—rejected; metrics differ by backend.

## 14. Security, privacy, and trust boundaries

- Queries may contain sensitive text; logs should avoid raw query bodies at
  info level in shared deployments.
- Cached query results can leak prior user queries if cache keys are shared
  across tenants—scope caches per tenant in multi-tenant deployments.
- Logic/theorem layers may appear authoritative; they are not substitutes for
  policy or proof kernels unless those systems explicitly run.
- Search must not claim that a hit is authorized for disclosure.

## 15. Observability and operations

- `QueryStatsCollector.get_stats_summary`: totals, cache hit rate, error rate,
  percentiles, slowest queries, index usage.
- `get_optimization_recommendations` for adaptive hints.
- Streaming throughput via `StreamingStats.get_throughput`.
- Search path logs for backend selection and dependency warnings.
- Invalidate LRU caches after reindex or model swap.

## 16. Validation

```bash
test -e ipfs_datasets_py/search/search_embeddings.py
test -e ipfs_datasets_py/search/search_embeddings_mock.py
test -e ipfs_datasets_py/search/query_optimizer.py
test -e ipfs_datasets_py/search/streaming_data_loader.py
test -e ipfs_datasets_py/embeddings/semantic_search_engine.py

# pytest tests/unit/search -q --collect-only
# pytest tests/unit_tests/search -q --collect-only
```

Limits: full Qdrant/FAISS/IPFS kit paths need optional services and deps;
offline validation covers mock, optimizer unit behavior, and simulated engine
validation errors.

## 17. Related documentation

| Document | Relationship |
| --- | --- |
| [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Query encoding and shards |
| [VECTOR_STORES.md](VECTOR_STORES.md) | ANN backends and filters |
| `ipfs_datasets_py/search/ARCHITECTURE.md` | Historical module-oriented notes |
| `ipfs_datasets_py/search/README.md` | Package README |
| Knowledge / GraphRAG guides (planned leaves) | Graph authority and planners |
| [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md) | CID fields on IPLD hits |
