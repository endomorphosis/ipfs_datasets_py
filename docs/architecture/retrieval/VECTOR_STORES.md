# Vector stores

| Field | Value |
| --- | --- |
| Interface | `RetrievalArchitecture@1` |
| Task | `IPFSDOC-030` |
| Status | `canonical` |
| Owner | architecture / retrieval domain |
| Source of truth | `ipfs_datasets_py/vector_stores/`; `ipfs_datasets_py/ml/embeddings/schema.py`; `ipfs_datasets_py/mcp_server/tools/vector_store_tools/`; `ipfs_datasets_py/mcp_server/tools/vector_tools/`; `ipfs_datasets_py/mcp_server/tools/index_management_tools/` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md), [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |
| Review cadence | after store backend, base protocol, or manager changes |

> **Sibling guides:** Embedding generation and sharding are in
> [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md). Query orchestration
> is in [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md). IPLD *codecs and CID
> profiles* are in
> [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md)—an
> index is not a content identifier.

## 1. Purpose

This guide answers: **what the vector-store protocol guarantees, how
IPLD/FAISS/Qdrant/Elasticsearch backends differ, how indexes are created,
updated, deleted, exported, and migrated, and how consistency and provenance
behave per backend**—without generalizing one backend’s features to all.

## 2. Audience

- **Primary:** developers choosing or implementing a vector backend; agents
  wiring MCP vector/index tools.
- **Secondary:** operators deploying Qdrant/Elasticsearch/FAISS disk paths;
  architects reviewing multi-store migration.

## 3. Scope and non-goals

### In scope

- `BaseVectorStore` protocol and shared helpers (`batch_add`,
  `similarity_search`, optional IPLD/CAR hooks).
- Configuration: `VectorStoreConfig`, `UnifiedVectorStoreConfig`, factory
  helpers (`create_ipld_config`, `create_faiss_config`, `create_qdrant_config`).
- Backend implementations: **IPLD**, **FAISS**, **Qdrant**, **Elasticsearch**
  (and enum mention of Chroma where present without claiming a full store).
- Schemas: `EmbeddingResult`, `SearchResult`, IPLD extensions,
  `CollectionMetadata`, `VectorBlock`.
- Managers: multi-store `VectorStoreManager` (`manager.py`), index
  management engine (`management_engine.py`), high-level `api.py`.
- Bridges, router integration, sharding coordinator as store layout.
- Index lifecycle: create, add, get, update, delete, list, export/import,
  migrate.
- Optional dependencies, mocks, and fail paths **per backend**.

### Non-goals

- Dense/sparse *generation* algorithms →
  [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md).
- Hybrid fusion, query optimizer classes, streaming loaders →
  [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md).
- Knowledge-graph storage or GraphRAG planners → knowledge guides.
- Claiming universal filter DSL, HNSW, or dense_vector features across all
  stores.

## 4. Context

Vector storage sits between embedding generation and search:

```text
EmbeddingResult[]  -->  BaseVectorStore.add_embeddings
                              |
              +---------------+----------------+
              |               |                |
           FAISS           Qdrant        Elasticsearch
              |               |                |
              +------- IPLDVectorStore --------+
                       (FAISS index + CIDs)
                              |
                     search(query_vector) --> SearchResult[]
```

Design constraints in this tree:

1. **Protocol uniformity** for create/add/search/get/delete/update/list.
2. **Backend specialization** for filters, durability, networking, and IPLD.
3. **Optional deps**: missing `faiss`, `qdrant-client`, or `elasticsearch`
   must not break unrelated imports; constructors raise or managers return
   structured errors when a backend is selected but unavailable.
4. **Content addressing is IPLD-specific**: other backends may store string
   IDs only; export_to_ipld is optional and no-ops with a warning by default.

There are **two manager concepts** with similar names:

| Manager | Module | Role |
| --- | --- | --- |
| Multi-store manager | `vector_stores/manager.py` | Registers store instances; migrate; `search_all` |
| Index management engine | `vector_stores/management_engine.py` | Create/search/list/delete indexes for faiss/qdrant/elasticsearch with local `./vector_indexes` for FAISS |

Do not conflate them with MCP `vector_store_management` thin wrappers.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Vector collection/index lifecycle per backend | Embedding model weights and generation |
| Distance metric mapping **as implemented per store** | Graph query IR / theorem RAG |
| IPLD export root CID and per-vector CID maps (IPLD store) | General IPFS pin policy / cluster consensus |
| Cross-store migration bridges | Query result fusion weights |
| Store health via list/info APIs | Authorization of who may search |

**Inbound callers:** Python API (`vector_stores.api`, managers), MCP
`vector_store_tools` / `vector_tools` / `index_management_tools`, search
modules that hold a store reference, GraphRAG paths that attach a vector
backend.

**Outbound dependencies:** numpy; faiss (FAISS/IPLD search); qdrant-client;
elasticsearch async client; optional `IPLDStorage` / `ipld_car`;
`RouterIntegration` for auto-embed and IPFS block I/O.

**Authority notes:** Collection name + backend location is **not** a content
CID. `root_cid` on IPLD export is an identifier for serialized collection
state, not a search quality guarantee.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Package init | `vector_stores/__init__.py` | Re-exports; soft ImportError swallow for optional deps |
| Base protocol | `vector_stores/base.py` | `BaseVectorStore` ABC + error types + optional IPLD/CAR methods |
| Schemas | `vector_stores/schema.py` | Re-exports + `IPLDEmbeddingResult`, `IPLDSearchResult`, `CollectionMetadata`, `VectorBlock` |
| Config | `vector_stores/config.py` | `UnifiedVectorStoreConfig` + factory helpers |
| FAISS | `vector_stores/faiss_store.py` | Local disk index + pickle metadata |
| Qdrant | `vector_stores/qdrant_store.py` | Remote/local Qdrant collections |
| Elasticsearch | `vector_stores/elasticsearch_store.py` | ES `dense_vector` index mapping |
| IPLD store | `vector_stores/ipld_vector_store.py` | In-memory/FAISS index + CID maps + export/import |
| Legacy IPLD | `vector_stores/ipld.py` | Older IPLD vector implementation (compat) |
| Router integration | `vector_stores/router_integration.py` | Embeddings + IPFS block helpers |
| Manager | `vector_stores/manager.py` | Multi-store registry and migration |
| Management engine | `vector_stores/management_engine.py` | Backend-routed index create/search/list/delete |
| High-level API | `vector_stores/api.py` | `create_vector_store`, `add_texts_to_store`, `search_texts`, migrate/export helpers |
| Bridges | `vector_stores/bridges/` | Cross-store migration adapters |
| Sharding | `vector_stores/sharding/coordinator.py` | Consistent hashing for distributed layout |
| Vector store engine | `vector_stores/vector_store_engine.py` | Engine facade used by tools |
| MCP tools | `mcp_server/tools/vector_store_tools/`, `vector_tools/` | Thin tool layer |

## 7. End-to-end flow

### 7.1 Happy path (protocol)

1. Build a `VectorStoreConfig` / `UnifiedVectorStoreConfig` with
   `store_type`, `collection_name`, `dimension`, `distance_metric`.
2. Construct store via `create_vector_store` / manager / direct class.
3. `await create_collection()` — backend-specific resource allocation.
4. `await add_embeddings(List[EmbeddingResult])` → list of store IDs.
5. `await search(query_vector, top_k, filter_dict?)` → `List[SearchResult]`.
6. Optional: update/delete by ID; `get_collection_info`; `list_collections`.
7. Optional IPLD path: `export_to_ipld` / `export_to_car` / import counterparts.
8. `await close()` or async context manager exit.

### 7.2 Index lifecycle (all backends)

| Phase | Protocol method | Notes |
| --- | --- | --- |
| Create | `create_collection` | Requires dimension on most backends |
| Exists | `collection_exists` | Backend-specific probe |
| Write | `add_embeddings` / `batch_add_embeddings` | IDs returned |
| Read by ID | `get_by_id` | None if missing |
| Update | `update_embedding` | May be delete+add on some backends |
| Delete vector | `delete_by_id` | FAISS may rebuild/mark tombstones depending on implementation |
| Delete index | `delete_collection` | Drops index resources |
| Inspect | `get_collection_info`, `get_store_info`, `list_collections` | Metadata only |
| Export | `export_to_ipld`, `export_to_car` | **Supported meaningfully on IPLD store**; base class warns/returns None/False |
| Import | `import_from_ipld`, `import_from_car` | Same specialization |
| Migrate | manager `migrate` / `migrate_collection` / bridges | Batch copy between stores |

### 7.3 Sequence (IPLD-centric)

```text
Caller                 IPLDVectorStore              Router/IPFS
  | create_collection        |                          |
  |------------------------->| FAISS index + maps       |
  | add_embeddings          |                          |
  |------------------------->| store vectors            |
  |                          |--- store_to_ipfs ------->| (if router on)
  |                          |<-- cid ------------------|
  | search                   |                          |
  |------------------------->| FAISS/numpy top-k        |
  |<-- SearchResult(+cid) ---|                          |
  | export_to_ipld           |                          |
  |------------------------->| pack metadata+vector cids|
  |                          |--- root block ---------->|
  |<-- root_cid -------------|                          |
```

## 8. Contracts

### 8.1 Shared protocol (`BaseVectorStore`)

Abstract methods (all async unless noted):

- `_create_client`
- `create_collection`, `delete_collection`, `collection_exists`
- `add_embeddings`, `search`, `get_by_id`, `delete_by_id`, `update_embedding`
- `get_collection_info`, `list_collections`

Shared concrete helpers:

- `batch_add_embeddings(batch_size=100)`
- `similarity_search` (search + optional `score_threshold`)
- Context managers (`__aenter__`/`__aexit__`, sync exit runs async close)
- Optional IPLD/CAR methods with **default unsupported** behavior

Errors:

- `VectorStoreError` — base
- `VectorStoreConnectionError` — client connectivity
- `VectorStoreOperationError` — failed ops after connect

### 8.2 Schemas

| Type | Key fields | Backend notes |
| --- | --- | --- |
| `EmbeddingResult` | `embedding`, `chunk_id`, `content`, `metadata`, `model_name` | Universal write unit |
| `SearchResult` | `chunk_id`, `content`, `score`, `metadata`, optional `embedding` | Score semantics depend on metric/backend |
| `IPLDEmbeddingResult` | + `cid`, `vector_cid`, `metadata_cid`, `block_size`, `stored_at` | IPLD store |
| `IPLDSearchResult` | + `cid`, `retrieved_from`, `retrieval_time`, `block_size` | IPLD retrieval |
| `CollectionMetadata` | name, dimension, metric, count, timestamps, `root_cid`, index/vectors/metadata CIDs, schema_version, chunk flags | IPLD collection envelope |
| `VectorBlock` | block_id, index range, count, cid, size, compressed | Large IPLD collections |
| `VectorStoreType` | enum: qdrant, faiss, elasticsearch, chroma (+ IPLD extended in config) | Chroma may appear in enum without a full first-class store module in-tree |
| `UnifiedVectorStoreConfig` | router flags, IPLD paths, batch/parallel, multi-store sync knobs | IPLD + multi-store |

Distance metrics commonly configured as strings: `cosine`, `euclidean`/`l2`,
`dot`/`ip`, and sometimes `manhattan`—**mapping differs by backend** (see §9).

### 8.3 Public surfaces

- **Python:** `from ipfs_datasets_py.vector_stores import ...` (see
  `__all__` in package init).
- **MCP:** vector store tools, vector tools (create/search index, management),
  index management tools.
- **Config keys:** host/port, `connection_params` (index_path, index_type,
  hosts, auth, etc.), router provider/backend names.

### 8.4 Persistence and identity

| Backend | Durable identity | Index location |
| --- | --- | --- |
| FAISS | Application `chunk_id` + files `{collection}.index` and metadata pickle | Local paths (`index_path`, `metadata_path`) |
| Qdrant | Point IDs in Qdrant collection | Server at host:port (default 6333) |
| Elasticsearch | Document IDs in ES index | Cluster hosts (default 9200) |
| IPLD | `chunk_id` + optional per-vector CID + collection `root_cid` | Process maps + optional IPFS blocks / CAR |

**Consistency expectations are backend-specific** (see §11). None of the
stores implement a cross-backend distributed transaction.

## 9. Backend capability matrix (do not generalize)

Features below are **only** claimed where the implementation supports them.

### 9.1 FAISS (`FAISSVectorStore`)

| Capability | Behavior |
| --- | --- |
| Deployment | Local process; no network client (`_create_client` → None) |
| Required deps | `faiss` + `numpy` or constructor raises `VectorStoreError` |
| Mock path | Module may install mock FAISS when auto-install fails; real store still expects FAISS_AVAILABLE for constructor |
| Index types (`connection_params.index_type`) | `Flat` → `IndexFlatIP`; `IVF` → `IndexIVFFlat`; `HNSW` → `IndexHNSWFlat`; unknown → Flat + warning |
| Persistence | `faiss.write_index` / `read_index`; metadata pickle beside index |
| Filters | Limited compared to Qdrant/ES—primarily post-search metadata in implementation paths |
| IPLD export | Base default unless extended—not the primary IPLD path |
| Legacy methods | `search_chunks_legacy`, `autofaiss_*`, shard/centroid helpers retained for compat |

### 9.2 Qdrant (`QdrantVectorStore`)

| Capability | Behavior |
| --- | --- |
| Deployment | `QdrantClient(host, port, **connection_params)` |
| Required deps | `qdrant-client` or constructor raises |
| Distance map | cosine→COSINE, euclidean→EUCLID, dot→DOT, manhattan→MANHATTAN |
| Collection create | `VectorParams(size=dimension, distance=...)` |
| Filters | Qdrant `Filter` / field conditions when filter_dict provided |
| Networking | Connection errors → `VectorStoreConnectionError` |
| IPLD export | Not inherent; use migrate to IPLD store |

### 9.3 Elasticsearch (`ElasticsearchVectorStore`)

| Capability | Behavior |
| --- | --- |
| Deployment | `AsyncElasticsearch` with hosts/SSL/basic_auth/api_key |
| Required deps | `elasticsearch` or constructor raises |
| Mapping | `dense_vector` with dims + similarity; `content` text analyzer; `chunk_id`/`model_name` keyword; dynamic `metadata` object |
| Similarity map | cosine; euclidean→l2_norm; dot→dot_product; manhattan→l1_norm |
| Index settings default | 1 shard, 0 replicas (constructor mapping)—**not** a production HA claim |
| Hybrid lexical | `content` is analyzed text—ES can combine lexical + vector **in ES-specific query bodies**; other backends do not inherit this |
| IPLD export | Not inherent |

### 9.4 IPLD (`IPLDVectorStore`)

| Capability | Behavior |
| --- | --- |
| Deployment | In-process collections; optional IPFS via router / `IPLDStorage` |
| Required deps | **numpy required**; FAISS recommended (else slow/fallback search); IPLD/CAR optional |
| Index | FAISS FlatIP/L2/IP by metric; parallel python lists for vectors, metadata, cids, vector_ids |
| Auto-embed | `use_embeddings_router` via `RouterIntegration` |
| Auto IPFS | `use_ipfs_router` stores vectors and export roots |
| Export | `export_to_ipld` builds metadata + vector CID list + root CID |
| Import | `import_from_ipld(root_cid)` reloads blocks |
| CAR | When `ipld_car` available and methods implemented |
| Chunking large collections | `ipld_chunk_size`, `max_block_size`, `VectorBlock` metadata |
| Provenance | CIDs on results when stored; `CollectionMetadata.root_cid` after export |

### 9.5 Management engine backends

`management_engine.VectorStoreManager.create_index(backend=...)` supports
**only** `faiss`, `qdrant`, `elasticsearch` in its switch; unsupported backend
returns `status=error` with `supported_backends` list. IPLD is not a branch in
that engine—use `IPLDVectorStore` / multi-store manager instead.

### 9.6 Enum-only / incomplete

- `VectorStoreType.CHROMA` may exist on the schema enum without a full
  `ChromaVectorStore` implementation parallel to FAISS/Qdrant/ES/IPLD.
- Package init may set `ElasticsearchVectorStore = None` if import fails.

## 10. Failure modes and fallbacks

| Failure | Detection | Visible behavior | Fallback |
| --- | --- | --- | --- |
| FAISS not installed | import / constructor | `VectorStoreError` | Do not silently search real data |
| Qdrant client missing | constructor | `VectorStoreError` with install hint | — |
| Qdrant server down | client ops | `VectorStoreConnectionError` / operation error | Search path may choose another backend if orchestrated at higher layer |
| ES missing | constructor / manager | Error | — |
| IPLD without numpy | constructor | `VectorStoreError` | — |
| IPLD without FAISS | warning at init | Search degrades / fallback path | Slower numpy-style search if implemented |
| IPLD without IPFS router | flags / import | CIDs may be None; local-only collections | Still searchable in-process |
| Base `export_to_ipld` on non-IPLD | method default | warning log, `None` / `False` | Caller must not treat as success CID |
| Delete/update on FAISS | implementation constraints | May rebuild index or fail operation | Check operation return / errors |
| Multi-store migrate verify fail | `verify=True` | Migration reports issues | Source retained |

Distinguish:

- **Dependency not installed** vs **daemon/cluster unreachable**.
- **Unsupported optional method** (IPLD export on FAISS) vs **failed export**.
- **Mock FAISS module objects** used during import vs **production FAISSVectorStore**.

## 11. Consistency, provenance, and multi-store

### Consistency

| Store | Write visibility | Notes |
| --- | --- | --- |
| FAISS | Process + disk files after save | No multi-writer protocol; external file locks not provided |
| Qdrant | Server-side durability per Qdrant deployment | Client does not implement 2PC with other stores |
| Elasticsearch | Near-real-time index refresh semantics of ES | Replica count defaults to 0 in mapping helper |
| IPLD | Immediate in-process; IPFS pin/export is separate step | `auto_pin_to_ipfs` config exists; pinning is not automatic proof of replication |

Multi-store sync flags on `UnifiedVectorStoreConfig`
(`enable_multi_store_sync`, `sync_stores`, `sync_interval`) are configuration
hooks—do not assume continuous active replication unless a running sync worker
is verified in deployment.

### Provenance

- **Application metadata** on `EmbeddingResult.metadata` is caller-defined
  (source path, document id, etc.).
- **IPLD CIDs** identify stored blocks after successful IPFS/router put.
- **Collection root CID** identifies a snapshot export, not live mutable
  Qdrant/ES state.
- **Shard `root_cid`** on `ShardMetadata` identifies a shard payload when set.
- Lineage/receipt systems elsewhere may *reference* these IDs; vector stores
  do not replace provenance engines.

## 12. Extension points

1. Subclass `BaseVectorStore` and implement all abstract methods.
2. Add enum value / factory branch in `VectorStoreManager._create_store` and
   `api.create_vector_store`.
3. Register bridges in `vector_stores/bridges` for migration.
4. Extend `UnifiedVectorStoreConfig` only with backward-compatible fields.
5. MCP tools remain thin wrappers over engines/API.
6. Tests under `tests/unit/vector_stores/` for protocol and backend mocks.

Anti-patterns:

- Documenting Qdrant payload filters as available on FAISS.
- Using collection name as a content CID.
- Importing heavy backends at package import time without guards.
- Assuming `export_to_ipld` works on every store class.

## 13. Invariants

1. Every durable write path accepts `EmbeddingResult` (or equivalent) with
   consistent dimension for a collection.
2. `search` returns `SearchResult` with scores in the backend’s metric space;
   thresholds are not universal similarities.
3. Optional IPLD methods never pretend success when unsupported.
4. Constructors fail closed when **required** deps for that backend are
   missing (raise), rather than returning plausible fake neighbors—except
   where a higher-level search simulator explicitly labels simulation (search
   guide).
5. Manager migration copies vectors; it does not rewrite embedding spaces.
6. Backend-specific features stay backend-scoped in docs, configs, and APIs.

## 14. Rationale and decisions

| Topic | Summary | Source |
| --- | --- | --- |
| Shared ABC + specialized stores | One call shape, many deployments | `base.py` |
| IPLD = FAISS + CIDs | Fast ANN + content addressing | `ipld_vector_store.py` |
| Soft package import | Optional deps | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| Optional IPLD hooks on base | Avoid forcing CAR on all backends | `base.py` defaults |
| Separate management engine | Tool-friendly create/list/delete without full multi-store manager | `management_engine.py` |

Alternatives rejected:

- Single remote DB only — rejected; offline FAISS/IPLD required.
- Treating index files as CIDs — rejected; see ADR-001.

## 15. Security, privacy, and trust boundaries

- Qdrant/ES credentials in `connection_params` must not be logged at info
  level in production configurations.
- Exporting collections to public IPFS gateways publishes embedding content.
- Filters and ACLs are **not** a uniform authorization layer across backends;
  application policy sits above the store.
- This layer must not assert that retrieval implies authorized disclosure.

## 16. Observability and operations

- Logs: connection failures, create/delete collection, IPLD export CIDs,
  missing FAISS warnings.
- `get_collection_info` / `get_store_info` for counts and config snapshots.
- Operations: monitor Qdrant/ES health externally; FAISS disk usage under
  index paths; IPFS pin set for IPLD roots if used.

## 17. Validation

```bash
test -e ipfs_datasets_py/vector_stores/base.py
test -e ipfs_datasets_py/vector_stores/faiss_store.py
test -e ipfs_datasets_py/vector_stores/qdrant_store.py
test -e ipfs_datasets_py/vector_stores/elasticsearch_store.py
test -e ipfs_datasets_py/vector_stores/ipld_vector_store.py
test -e ipfs_datasets_py/vector_stores/manager.py
test -e ipfs_datasets_py/vector_stores/management_engine.py

# pytest tests/unit/vector_stores -q --collect-only
```

Limits: live Qdrant/ES integration tests need services; offline unit tests
should mock clients.

## 18. Related documentation

| Document | Relationship |
| --- | --- |
| [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Upstream vectors and shards |
| [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Downstream query |
| [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md) | CID/IPLD rules |
| [STORAGE_CACHING_AND_BACKENDS.md](../storage/STORAGE_CACHING_AND_BACKENDS.md) | IPFS backend location |
| `ipfs_datasets_py/vector_stores/README.md` | Package-oriented usage |
| Historical `docs/IPLD_VECTOR_STORE_*.md` | Session/history material; architecture leaf is this file |
