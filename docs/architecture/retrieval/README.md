# Retrieval architecture index

| Field | Value |
| --- | --- |
| Interface | `RetrievalArchitectureIndex@1` |
| Task | `IPFSDOC-033` |
| Status | `canonical` |
| Owner | architecture / retrieval domain |
| Source of truth | Canonical leaves under `docs/architecture/retrieval/`; `ipfs_datasets_py/{embeddings,vector_stores,search,ml}/`; root `embeddings_router.py` / `embedding_router.py`; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.6 and retrieval cluster; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md); [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md), [knowledge/README.md](../knowledge/README.md) |
| Review cadence | after embedding engine, vector backend, search orchestration, or router changes |
| Goal | `IPFSDOC-G050` (shared with knowledge index) |

> **Lifecycle:** This page is the **canonical routing hub** for retrieval
> (embeddings, vector stores, search/query). It does **not** replace leaf
> architecture guides. Prefer the leaves for contracts, backend matrices,
> failure modes, and extension detail. Root `IPLD_VECTOR_*` session reports,
> stub dumps, and undated marketing inventory claims are **not** architecture
> authority.

## 1. Purpose

Route developers, agents, and operators to the right retrieval documentation
without conflating **embeddings**, **ANN indexes**, **search scores**,
**graph facts**, **optimizer proposals**, or **proof**:

| Need | Go to |
| --- | --- |
| Dense/sparse embedding generation, chunking, schemas, sharding | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) |
| Vector-store protocol, FAISS/Qdrant/ES/IPLD backends, index lifecycle | [VECTOR_STORES.md](VECTOR_STORES.md) |
| Semantic / hybrid / filtered / streaming query orchestration | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) |
| Knowledge-graph facts, GraphRAG orchestration, optimizer loops | [knowledge/README.md](../knowledge/README.md) |
| Domain ownership of embeddings / vector_stores / search / ml | [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.6 + retrieval cluster |
| Cross-domain hops (Flow B artifact→index, Flow C query→result) | [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) |
| Content identity (CID/IPLD) vs index location | [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md), [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Optional ML/backends and fail-closed degradation | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Live package / MCP / API / tutorial anchors | §5 Component families + §7 Documentation routes |
| Backend-specific, optional, or historical material only | §5 status legend + §7.4–§7.5 (labeled; not sole architecture) |

**Effects of this index:** one entry point for retrieval without rewriting the
leaf guides. New code and docs should link here for orientation, then drop into
the owning leaf.

**Core inequalities (all leaves agree):**

- embedding vector **≠** vector-store index **≠** content **CID**
- collection / backend location **≠** content identity
- search **score** **≠** graph fact **≠** proof or authorization
- mock / simulated / stub embedding results **≠** production similarity
- one backend’s filters or hybrid features **do not** generalize to all backends

## 2. Audience

- **Primary:** developers and agents choosing where to implement or document
  embedding generation, vector backends, or query paths.
- **Secondary:** operators provisioning FAISS/Qdrant/Elasticsearch/IPLD paths;
  architects placing retrieval relative to processing, storage, knowledge, and
  logic.

## 3. Scope and non-goals

### In scope

- Index of **canonical** retrieval architecture leaves.
- **Ownership** and **current / optional / backend-specific / compatibility /
  historical** status per retrieval family.
- Routes to retained component paths, API and MCP surfaces, tutorials,
  extension seams, and labeled non-authoritative material.
- Explicit honesty: optional torch/transformers stacks, simulated semantic
  engine results, mock `search_embeddings`, and fallback constant vectors are
  **not** production ranking or identity.

### Non-goals

- Full embedding/chunk/shard algorithms → [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md).
- Full backend capability matrices and consistency models → [VECTOR_STORES.md](VECTOR_STORES.md).
- Full hybrid fusion, streaming, and query-optimizer contracts → [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md).
- Knowledge-graph engine, GraphRAG product orchestration, optimizer control
  loops → [knowledge/README.md](../knowledge/README.md).
- Formal IR / proof / admissibility → [logic/README.md](../logic/README.md).
- Content-addressed storage backends and pins → [storage/README.md](../storage/README.md).
- MCP transport and tool lifecycle framing → [architecture/mcp/](../mcp/).
- Using undated root inventory counts or “production ready” slogans as
  current capability authority.

## 4. Canonical retrieval guides

These three pages are the **architecture authority** for retrieval under
`docs/architecture/retrieval/`. All three have status `canonical` as of last
verification (task `IPFSDOC-030`).

| Guide | Interface | Owns | Status |
| --- | --- | --- | --- |
| [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | `RetrievalArchitecture@1` (embeddings leaf) | Dense/sparse generation, routers, chunk/schema identity, shard layouts, mock/fallback labeling | **canonical** — generation and index layout, not ANN engines |
| [VECTOR_STORES.md](VECTOR_STORES.md) | `RetrievalArchitecture@1` (stores leaf) | `BaseVectorStore` protocol, FAISS/Qdrant/Elasticsearch/IPLD backends, index CRUD/export/migrate, **backend-specific** filters and metrics | **canonical** — store lifecycle; do not generalize one backend to all |
| [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | `RetrievalArchitecture@1` (query leaf) | Semantic/hybrid/filtered/streaming orchestration, query optimizers and caches, simulated vs store-backed paths | **canonical** — composition layer; scores are not proof |

```text
                    ┌──────────────────────────────────────┐
                    │  docs/architecture/retrieval/        │
                    │  README.md  (this index)             │
                    └──────────────────┬───────────────────┘
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   EMBEDDINGS_AND_INDEXING.md   VECTOR_STORES.md        SEARCH_AND_QUERY.md
   (encode / chunk / shard)     (ANN backends /         (query composition /
                                 lifecycle)              optimizers / stream)
```

Cross-links among leaves: embeddings produce vectors and schemas; vector
stores persist and ANN-search them with **backend-local** semantics; search
composes encode → retrieve → optional re-rank/cache without inventing
cross-store transactions or formal authority.

**Reading order for a new retrieval feature:** embeddings → vector stores →
search. For hybrid graph+vector product paths, continue into
[knowledge/GRAPHRAG.md](../knowledge/GRAPHRAG.md) after the retrieval leaves.

**Kinds of truth (do not collapse):** chunk **id**, embedding **vector**,
model **id**, collection **name**, backend **location**, vector **id**,
optional content **CID** (IPLD store), search **score**, cache **key**,
query-optimizer **plan**. See
[ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md).

## 5. Component families: ownership and status

**Product cluster (DOMAIN_MAP):** `embeddings`, `vector_stores`, `search`,
`ml` → this directory ([DOMAIN_MAP.md](../DOMAIN_MAP.md) retrieval cluster /
§4.6). Related routers live at package root (`embeddings_router.py`,
`embedding_router.py`).

MCP tools under
`mcp_server/tools/{embedding_tools,sparse_embedding_tools,vector_store_tools,vector_tools,index_management_tools,search_tools}/`
and CLI surfaces (`ipfs-datasets vector …`, `python -m ipfs_datasets_py.search.cli`)
are **thin wrappers**; algorithms stay in domain packages.

Status legend:

| Status | Meaning |
| --- | --- |
| **canonical** | Preferred import / design for new work |
| **compat** | Supported transitional surface; prefer canonical when writing new code |
| **optional** | Requires extras, host binaries, secrets, daemons, or model stacks |
| **backend-specific** | Behavior or capability depends on which vector-store provider is selected |
| **deprecated** | Still importable with warnings or re-exports; do not extend |
| **historical** | Docs or paths describing past plans/migrations/stubs; not live architecture |
| **mock / simulation** | Explicit non-production path; unit green ≠ production similarity |

### 5.1 Family matrix

| Family | Canonical path(s) | Optional / backend-specific / compat / mock | Architecture leaf | Notes |
| --- | --- | --- | --- | --- |
| **Dense embedding generation** | `embeddings/generation_engine.py`, `embeddings/embeddings_engine.py` | torch / sentence-transformers / accelerate **optional**; fallback vectors **mock/non-production** | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Label stub/fallback explicitly |
| **Sparse embeddings** | `embeddings/sparse_embedding_engine.py` | Sparse service deps **optional**; mock sparse service for hermetic paths | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Not interchangeable with dense ANN alone |
| **Embedding schemas** | `embeddings/schema.py`; `ml/embeddings/schema.py` | ML schema path may parallel package embeddings | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Chunk id + model metadata; not content CID by default |
| **Embedding / endpoint routers** | `embeddings_router.py`, `embedding_router.py` | Remote/endpoint stacks **optional** | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Prefer documented router for multi-provider wiring |
| **Sharding / index layout** | `embeddings/shard_embeddings_engine.py`; `vector_stores/sharding/` | Multi-node coordinators **optional** | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md), [VECTOR_STORES.md](VECTOR_STORES.md) | Shard identity ≠ content identity |
| **ML embeddings helpers** | `ml/embeddings/` | Heavy ML extras **optional** | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Complements package `embeddings/`; not a second product domain |
| **Vector-store protocol** | `vector_stores/base.py` (`BaseVectorStore`) | Shared ABC; optional IPLD/CAR hooks | [VECTOR_STORES.md](VECTOR_STORES.md) | Contract for all backends |
| **Store config / factory / manager** | `vector_stores/config.py`, `api.py`, `manager.py`, `vector_store_engine.py`, `management_engine.py` | Backend selection **backend-specific** | [VECTOR_STORES.md](VECTOR_STORES.md) | Prefer `api` / factory for new callers |
| **FAISS backend** | `vector_stores/faiss_store.py` | FAISS **optional** (slow fallback without it) | [VECTOR_STORES.md](VECTOR_STORES.md) | **backend-specific** metrics and index types |
| **Qdrant backend** | `vector_stores/qdrant_store.py` | Live Qdrant + client **optional** | [VECTOR_STORES.md](VECTOR_STORES.md) | **backend-specific** filters/payloads |
| **Elasticsearch backend** | `vector_stores/elasticsearch_store.py` | ES cluster + async client **optional** | [VECTOR_STORES.md](VECTOR_STORES.md) | Hybrid lexical+vector is **ES-specific** |
| **IPLD vector store** | `vector_stores/ipld_vector_store.py` | Router / `IPLDStorage` / CAR **optional** | [VECTOR_STORES.md](VECTOR_STORES.md) | Content-addressed path; index_cid ≠ sole content identity |
| **Legacy IPLD vector** | `vector_stores/ipld.py` | **compat** older implementation | [VECTOR_STORES.md](VECTOR_STORES.md) | Prefer `ipld_vector_store` for new work |
| **Bridges** | `vector_stores/bridges/` | Integration adapters **optional** by stack | [VECTOR_STORES.md](VECTOR_STORES.md) | Adapters only—not a second business-logic home (ADR-005) |
| **Search orchestration** | `search/search_embeddings.py` | Qdrant preferred / FAISS fallback; heavy deps **optional** | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Backend-oriented; not universal ranking |
| **Mock search** | `search/search_embeddings_mock.py` | **mock** when real import fails | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Empty/mock results; not production similarity |
| **Semantic search engine** | `embeddings/semantic_search_engine.py` | Many helpers return **simulated** results with explicit notes | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Do not treat simulation notes as store hits |
| **Query optimizers (retrieval)** | `search/query_optimizer.py` | Planning/cache/metrics around executors | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Distinct from GraphRAG product optimizers (`optimizers/`) |
| **Streaming loaders** | `search/streaming_data_loader.py` | Filesystem/IPFS streaming **optional** | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Large I/O; not ANN by itself |
| **Content discovery / recommendations** | `search/content_discovery.py`, `search/recommendations/` | Feature availability **optional** | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Discovery helpers; verify against live modules |
| **Graph query attachment** | `search/graph_query/` | Sharded CAR graph backends **optional** | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md); graph authority → knowledge leaves | Retrieval maps attachment only |
| **GraphRAG search integration** | `search/graphrag_integration/` | Hybrid path; LLM **optional** | [knowledge/GRAPHRAG.md](../knowledge/GRAPHRAG.md), [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Orchestration owned by knowledge track |
| **Logic-enhanced search attachment** | `search/logic_integration/` | Theorem/logic extras **optional** | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md); formal authority → logic | Attachment boundary only |
| **MCP / CLI thin surfaces** | embedding / vector / index / search tool packages; `search/cli.py` | Tool availability **optional** by install | §7.3 | No business logic only in tool modules |

### 5.2 Ownership boundaries (summary)

| Owns (retrieval) | Does not own |
| --- | --- |
| Embedding generation, chunk schemas, shard layouts | Graph fact CRUD and Neo4j-compat engine (`knowledge_graphs`) |
| Vector-store protocol and ANN backend implementations | Content CID profiles and pin lifecycle (`storage`) |
| Semantic/hybrid/streaming query composition and retrieval query optimizers | GraphRAG ontology generate/critique product loops (`optimizers`) |
| Labeling mock, simulated, and fallback similarity | Formal proof, attestation, or authorization (`logic`) |
| Backend-specific filter/metric honesty | Hosting FAISS/Qdrant/Elasticsearch as a product deliverable |

**Inbound:** Python API (`embeddings`, `vector_stores.api`, `search`), MCP
embedding/vector/search tools, CLI (`vector create/search`, search module CLI),
processors and PDF/GraphRAG pipelines that emit chunks, optimizers that inject
search executors.

**Outbound:** optional ML stacks (torch, transformers, sentence-transformers,
accelerate); FAISS / Qdrant / Elasticsearch clients; optional IPFS kit and
IPLD/CAR; knowledge-graph hybrid consumers; storage routers for IPLD-backed
vectors.

## 6. Extension recipes (where to implement)

Do **not** put new retrieval business logic only in MCP tool modules. Prefer
domain packages, then thin wrappers.

| Extension | Recipe summary | Detail |
| --- | --- | --- |
| New dense/sparse embedder | Engine + schema fields + optional-dep guards; label fallback vectors | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) |
| New chunk or document schema field | Versioned schema; stable chunk ids; do not invent CIDs from encode success | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) |
| New shard strategy | Manifest + coordinator under sharding paths; document identity vs layout | [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) |
| New vector backend | Implement `BaseVectorStore`; register in factory/manager; document capability gaps | [VECTOR_STORES.md](VECTOR_STORES.md) |
| New filter or hybrid feature | Implement only on capable backends; never claim portability in shared API docs | [VECTOR_STORES.md](VECTOR_STORES.md) |
| New query path (semantic/hybrid/stream) | Compose encode + store search + optional re-rank; separate mock vs live | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) |
| New retrieval query optimizer | Extend `search/query_optimizer` family; metrics/cache around real executors | [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) |
| Hybrid graph+vector product feature | Retrieval leaves for ANN; knowledge [GRAPHRAG.md](../knowledge/GRAPHRAG.md) for orchestration | Both tracks; do not put graph facts only in search |
| Optional dependency lifecycle | Lazy import; feature degrade OK; inventing similarity not OK | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

**Anti-patterns (all leaves agree):** generalizing Elasticsearch hybrid or
Qdrant filters to FAISS; treating fallback embeddings as production ranking;
collapsing chunk id / vector id / collection name / content CID; treating
search scores as graph facts or proofs; business logic only in MCP files;
using undated “N backends / N tests” marketing counts as inventory authority;
assuming missing extras mean undocumented architecture rather than
unprovisioned capability.

## 7. Documentation routes by authority class

### 7.1 Canonical architecture (preferred)

| Document | Role |
| --- | --- |
| **This index** | Routing, family status, extension map |
| [EMBEDDINGS_AND_INDEXING.md](EMBEDDINGS_AND_INDEXING.md) | Encode, chunk, schema, shard |
| [VECTOR_STORES.md](VECTOR_STORES.md) | Protocol and backends |
| [SEARCH_AND_QUERY.md](SEARCH_AND_QUERY.md) | Query composition |
| [knowledge/README.md](../knowledge/README.md) | Sibling hub for KG / GraphRAG / optimizers |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Product domain map |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flows B–C (index and query) |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Kinds of truth |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional capability lifecycle |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Feature degrade vs trust fail-closed |
| [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registries and adapters |

### 7.2 Retained component references (implementation anchors)

Use these live package paths as **component references**. Prefer architecture
leaves when contracts conflict with comments or older READMEs.

| Area | Paths |
| --- | --- |
| Embeddings | `ipfs_datasets_py/embeddings/` (`generation_engine.py`, `sparse_embedding_engine.py`, `schema.py`, `semantic_search_engine.py`, `shard_embeddings_engine.py`) |
| Routers | `ipfs_datasets_py/embeddings_router.py`, `embedding_router.py` |
| ML helpers | `ipfs_datasets_py/ml/embeddings/` |
| Vector stores | `ipfs_datasets_py/vector_stores/` (`base.py`, `api.py`, `manager.py`, `*_store.py`, `sharding/`, `bridges/`) |
| Search | `ipfs_datasets_py/search/` (`search_embeddings.py`, `query_optimizer.py`, `streaming_data_loader.py`, `graph_query/`, `graphrag_integration/`) |
| Package-local READMEs | `vector_stores/README.md`, `search/README.md`, `search/ARCHITECTURE.md` — **component notes**, subordinate to architecture leaves |
| Core ops facade | `core_operations/` surfaces that call embedding/vector helpers (not backend authority) |

### 7.3 API, MCP, CLI, and tutorials

| Surface | Location | Role | Label |
| --- | --- | --- | --- |
| Processing and retrieval API domain | [docs/api/domains/PROCESSING_AND_RETRIEVAL.md](../../api/domains/PROCESSING_AND_RETRIEVAL.md) | Domain API index with links into retrieval leaves | **API domain** — verify against current modules |
| Search / analysis class notes | [docs/analysis/search_api_classes.md](../../analysis/search_api_classes.md) | Class inventory narrative | **analysis** — not leaf replacement |
| MCP embedding tools | `mcp_server/tools/embedding_tools/`, `sparse_embedding_tools/` | Thin generation/search wrappers | **MCP shim** |
| MCP vector / index tools | `…/vector_store_tools/`, `vector_tools/`, `index_management_tools/` | Thin store/index wrappers | **MCP shim** |
| MCP search tools | `…/search_tools/` | Thin query wrappers | **MCP shim** |
| CLI | `ipfs-datasets vector …`; `python -m ipfs_datasets_py.search.cli` | Operator entrypoints | **CLI** |
| GraphRAG tutorials (consume retrieval) | [docs/tutorials/graphrag_tutorial.md](../../tutorials/graphrag_tutorial.md), [graphrag_website_processing_tutorial.md](../../tutorials/graphrag_website_processing_tutorial.md) | End-to-end product walkthroughs | **tutorial** — hybrid authority in knowledge leaves |
| IPLD vector quickstarts (mixed age) | `docs/IPLD_VECTOR_STORE_QUICKSTART.md`, `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | Historical/operator IPLD vector narrative | **mixed / verify** — prefer [VECTOR_STORES.md](VECTOR_STORES.md) |
| Dependency / init | [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports, extras (`vectors`, ML stacks) | **cross-cutting ops** |
| Integration boundaries | [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Optional engines and submodule ownership | **cross-cutting ops** |

Package-local docstrings and package READMEs under the paths in §7.2 are
implementation-level detail. “PROJECT_COMPLETE” and session completion reports
are **historical session evidence**, not preferred architecture.

### 7.4 Backend-specific and optional material (labeled)

| Material | Label | Use for |
| --- | --- | --- |
| FAISS / Qdrant / Elasticsearch / IPLD capability matrices in [VECTOR_STORES.md](VECTOR_STORES.md) | **backend-specific** | Choosing a provider; filters, metrics, hybrid features |
| Packaging extra `vectors`; torch / transformers / sentence-transformers / accelerate | **optional dependencies** | Install gates; missing extra ≠ missing architecture |
| Live Qdrant/Elasticsearch daemons, GPU, IPFS kit flags | **optional host services** | Live ANN and kit-backed paths; hermetic defaults remain valid for unit tests |
| Simulated semantic engine results; mock `search_embeddings`; fallback constant vectors | **mock / simulation / non-production** | Offline CI only; do not treat as ranking quality |
| ES lexical+vector hybrid bodies | **backend-specific** | Not portable to FAISS alone |
| IPLD export_to_ipld optional hooks | **optional / backend-specific** | Other backends may no-op with warning |

### 7.5 Historical migrations and stubs (do not treat as current architecture)

Use only to understand **how** the tree got here or to interpret old paths.
Always re-verify against the **canonical** leaves and live code. **Do not**
copy undated embedded inventory counts from these files into new docs.

| Document / path | Topic | Label |
| --- | --- | --- |
| `docs/IPLD_VECTOR_STORE_*.md`, `docs/IPLD_VECTOR_DATABASE_*.md` | IPLD vector store sessions, plans, examples, indexes | **historical / mixed age** — [VECTOR_STORES.md](VECTOR_STORES.md) is architecture authority |
| `docs/reports/phase_5_vector_embeddings_complete.md`, `docs/PHASE3C5_GOLDEN_VECTOR_COMPLETION.md` | Phase completion snapshots | **historical evidence** |
| `docs/archive/root_status_reports/*VECTOR*`, related completion reports | Session status | **archive** |
| `vector_stores/*_stubs.md`, `search/search_embeddings_stubs.md` | Stub dumps | **historical / stub** |
| `search/search_embeddings.py.backup`, `vector_stores/README_OLD.md` | Backup / superseded notes | **historical** |
| Root/guide fixed “N backends / N tests / production ready” slogans without date | Inventory marketing | **historical** — do not use as current inventory authority |

## 8. Decision guide (quick chooser)

```text
What are you doing?
│
├─ Generate, chunk, schema-bind, or shard embeddings?
│    → EMBEDDINGS_AND_INDEXING.md
│    → missing torch/transformers?  optional deps + mock/fallback labeling
│
├─ Create, update, delete, export, or migrate a vector index?
│    → VECTOR_STORES.md
│    → which backend?  read backend-specific capability matrix
│    → missing FAISS/Qdrant/ES?  optional + fail closed on selected backend
│
├─ Run semantic, hybrid, filtered, or streaming search?
│    → SEARCH_AND_QUERY.md
│    → simulated semantic engine or mock search?  not production ranking
│
├─ Hybrid graph + vector product / GraphRAG / ontology loops?
│    → knowledge/README.md → GRAPHRAG.md / OPTIMIZATION_LOOPS.md
│    → retrieval leaves still own ANN backends
│
├─ Add a new retrieval capability?
│    → §6 Extension recipes → owning leaf
│
├─ Only reading an old IPLD_VECTOR_* report or stub dump?
│    → §7.5 historical, then re-check canonical leaf
│
└─ Cross-domain “where does the artifact go next?”
     → END_TO_END_DATA_FLOW.md (Flows B–C), then knowledge / storage / logic
```

## 9. Related architecture and governance

| Document | Relationship |
| --- | --- |
| [architecture/README.md](../README.md) | Architecture documentation hub |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Guide contract |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product context |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports and extras |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Optional engines and kit boundaries |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | CLI/module entry points |
| [processing/README.md](../processing/README.md) | Processing index (may emit chunks; does not own ANN) |
| [storage/README.md](../storage/README.md) | Storage index (CIDs/backends; indexes *reference* content) |
| [knowledge/README.md](../knowledge/README.md) | Knowledge / GraphRAG / optimizer hub |
| [logic/README.md](../logic/README.md) | Formal authority (not search scores) |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence precedence |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) | Doc IA |

## 10. Validation

Bounded offline checks for this index:

```bash
# Declared output present and keyword coverage (IPFSDOC-033 gate)
test -s docs/architecture/retrieval/README.md
rg -n 'EMBEDDINGS_AND_INDEXING|VECTOR_STORES|SEARCH_AND_QUERY|backend-specific|optional|canonical' \
  docs/architecture/retrieval/README.md

# Canonical leaves still present
test -s docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md
test -s docs/architecture/retrieval/VECTOR_STORES.md
test -s docs/architecture/retrieval/SEARCH_AND_QUERY.md

# Package anchors for major families
test -d ipfs_datasets_py/embeddings
test -d ipfs_datasets_py/vector_stores
test -d ipfs_datasets_py/search
test -d ipfs_datasets_py/ml
test -s ipfs_datasets_py/vector_stores/base.py
```

Known limits: live FAISS/Qdrant/Elasticsearch clusters, GPU model stacks, and
IPFS kit paths are environment-gated. Optional extras may be absent. This
index only proves **routing, ownership language, and status labeling**, not
full ANN or model runtime proof. A green mock search or fallback embedding is
not production retrieval quality.

## 11. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial **canonical** retrieval architecture index for `IPFSDOC-033` / `RetrievalArchitectureIndex@1` |
