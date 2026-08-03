# Processing and retrieval API domain reference

| Field | Value |
| --- | --- |
| Interface | `ProcessingRetrievalAPIReference@1` |
| Task | `IPFSDOC-080` |
| Status | `canonical` |
| Owner | api-reference / processing-retrieval |
| Source of truth | `ipfs_datasets_py/core_operations/{data_processor,logic_processor}.py`; `ipfs_datasets_py/processors/__init__.py` and `protocol.py`; `processors/universal_processor.py` / `processors/core/universal_processor.py`; `ipfs_datasets_py/embeddings/`; `ipfs_datasets_py/vector_stores/`; `ipfs_datasets_py/search/`; architecture leaves under `docs/architecture/{processing,retrieval}/` |
| Last verified | 2026-08-03 |
| Audience | developer, agent, operator |
| Related | [CORE_AND_DATA.md](CORE_AND_DATA.md), [PROCESSOR_PIPELINE.md](../../architecture/processing/PROCESSOR_PIPELINE.md), [FILE_AND_MULTIMEDIA.md](../../architecture/processing/FILE_AND_MULTIMEDIA.md), [EMBEDDINGS_AND_INDEXING.md](../../architecture/retrieval/EMBEDDINGS_AND_INDEXING.md), [VECTOR_STORES.md](../../architecture/retrieval/VECTOR_STORES.md), [SEARCH_AND_QUERY.md](../../architecture/retrieval/SEARCH_AND_QUERY.md), [DOMAIN_MAP.md](../../architecture/DOMAIN_MAP.md) |
| Review cadence | after processor protocol, embedding, vector store, or search export changes |

## 1. Purpose

This page maps **callable** processing and retrieval surfaces with provenance:

1. Core-operations **DataProcessor** and **LogicProcessor** (two of the eight
   reviewed exports; the other six are specified in
   [CORE_AND_DATA.md](CORE_AND_DATA.md)).
2. Intended **processor**, **embedding**, **vector**, and **search** APIs.
3. **Stability**, **sync/async**, **side effects**, **optional** requirements,
   and **canonical imports**.

Importability is not public stability. Simulated search helpers and mock
backends must not be presented as production success.

## 2. Authority legend

| Tag | Meaning |
| --- | --- |
| **Stability: public** | Preferred external contract |
| **Stability: reviewed** | Exported / protocol-backed; AST is authority |
| **Stability: compatibility** | Dual path, alias, or migration shim |
| **Stability: internal** | Implementation detail; no stability promise |
| **Optional** | Models, ANN libraries, GPU, API keys, extras |
| **Side effects** | Filesystem, network, model downloads, index mutation |

---

## 3. Core-operations processing exports

Both remain imported from the **canonical** core package:

```python
from ipfs_datasets_py.core_operations import DataProcessor, LogicProcessor
```

### 3.1 DataProcessor

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import DataProcessor` |
| **Source** | `ipfs_datasets_py/core_operations/data_processor.py` |
| **Stability** | reviewed |
| **Optional** | Strategy-specific libs for transforms |
| **Side effects** | CPU-bound transforms; may allocate large intermediates |

#### Signatures (AST) — all primary methods **async**

```python
class DataProcessor:
    def __init__(self) -> None
    async def chunk_text(
        text: str,
        strategy: str = "fixed_size",
        chunk_size: int = 1000,
        overlap: int = 100,
        max_chunks: int = 100,
    ) -> Dict[str, Any]
    async def transform_data(
        data: Any,
        transformation: str,
        **parameters,
    ) -> Dict[str, Any]
    async def convert_format(
        data: Any,
        source_format: str,
        target_format: str,
    ) -> Dict[str, Any]
```

| Method | Sync/async | Notes |
| --- | --- | --- |
| `chunk_text` | **async** | Strategies include fixed-size and related variants; cap via `max_chunks` |
| `transform_data` | **async** | Named `transformation` + kwargs |
| `convert_format` | **async** | In-memory format conversion (distinct from `DatasetConverter` path I/O) |

Result authority: dict envelopes with `status` where implemented. Prefer
`DatasetConverter` for file-oriented dataset format conversion
([CORE_AND_DATA.md](CORE_AND_DATA.md)).

```python
processor = DataProcessor()
chunks = await processor.chunk_text("...", strategy="fixed_size", chunk_size=512)
```

### 3.2 LogicProcessor

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import LogicProcessor` |
| **Source** | `ipfs_datasets_py/core_operations/logic_processor.py` |
| **Stability** | reviewed (core export); deep IR/prover ownership remains `logic` domain |
| **Optional** | CEC assets, theorem provers, language models for parse paths |
| **Side effects** | Optional engine invocation; KB ops may mutate in-memory/configured KB |

#### Signatures (AST) — all methods below are **async**

| Method | Parameters (summary) | Role |
| --- | --- | --- |
| `list_cec_rules` | `category=""`, `include_description=True` | List CEC rules |
| `apply_cec_rule` | `rule_name`, `formulas: List[str]` | Apply rule |
| `check_cec_rule` | `rule_name`, `formulas` | Dry-run applicability |
| `get_cec_rule_info` | `rule_name` | Rule metadata |
| `prove_dcec` | `goal`, `axioms=None`, `strategy="auto"`, `timeout=30` | DCEC prove |
| `check_dcec_theorem` | `formula`, `axioms=None` | Tautology check |
| `parse_dcec` | `text`, `language="en"` | NL → DCEC |
| `validate_formula` | `formula_str`, `logic_system="dcec"` | Syntax validate |
| `analyze_formula` | `formula_str` | Structure |
| `get_formula_complexity` | `formula_str` | low/medium/high |
| `prove_tdfol` | `formula`, `axioms=None`, `strategy="auto"`, `timeout_ms=5000`, `max_depth=10`, `include_proof_steps=True` | TDFOL prove |
| `batch_prove_tdfol` | `formulas`, `shared_axioms=None`, … | Batch prove |
| `parse_tdfol` | `text`, `format="symbolic"`, `language="en"` | Parse TDFOL |
| `convert_formula` | `formula`, `source_format="tdfol"`, `target_format="fol"` | Convert reps |
| `manage_kb` | `operation`, `formula=None`, `axioms=None`, `export_format="json"` | KB add/query/export |
| `visualize_proof` | `proof_data=None`, `output_format="ascii"`, `visualization_type="proof_tree"` | Visualize |
| `get_capabilities` | — | Capability report |
| `check_health` | — | Sub-module health |
| `build_knowledge_graph` | `text_corpus`, `include_temporal=True`, `include_deontic=True`, `max_entities=100` | Extract annotated KG |
| `verify_rag_output` | `answer`, `constraints=None`, `logic_system="tdfol"`, `strict_mode=False` | Constraint check on RAG text |

Formal IR identity and submodule registry authority: `ipfs_datasets_py.logic`
(see future knowledge/logic API domain page). This class is the **MCP/CLI-facing
core_operations** façade.

---

## 4. Processor surfaces

### 4.1 Dual-surface migration (read first)

The processors package is in an **active dual-surface migration** (architecture
IPFSDOC-020). Root-level and `core/` types **coexist**:

| Concern | Root / package | Core path |
| --- | --- | --- |
| Protocol | `processors.protocol` | `processors.core.protocol` (sibling tree) |
| Registry | `ProcessorRegistry` / `get_global_registry` | `processors.core.registry` / related |
| Universal entry | `processors.universal_processor.UniversalProcessor` | `processors.core.universal_processor.UniversalProcessor` |

**Stability: compatibility** for the dual period. Prefer the symbols exported
from `ipfs_datasets_py.processors` `__all__` unless you intentionally target
`core/`. Do not assume the two registries share a singleton.

Architecture: [PROCESSOR_PIPELINE.md](../../architecture/processing/PROCESSOR_PIPELINE.md).

### 4.2 Reviewed protocol types

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.processors import ProcessorProtocol, ProcessingResult, ProcessingMetadata, ProcessingStatus, InputType, KnowledgeGraph, Entity, Relationship, VectorStore` |
| **Source** | `ipfs_datasets_py/processors/protocol.py` |
| **Stability** | public / reviewed for root protocol family |

#### `ProcessorProtocol` (AST)

```python
class ProcessorProtocol(Protocol):
    async def can_process(input_source: Union[str, Path]) -> bool
    async def process(input_source: Union[str, Path], **options) -> ProcessingResult
    def get_supported_types() -> list[str]
    def get_priority() -> int
    def get_name() -> str
```

| Method | Sync/async | Side effects |
| --- | --- | --- |
| `can_process` | **async** | May inspect filesystem metadata |
| `process` | **async** | Domain-specific I/O, network, heavy CPU |
| `get_*` | **sync** | Pure metadata |

Supporting types: `ProcessingResult.is_successful()`, `has_errors()`,
`to_dict()`; `ProcessingMetadata.add_error` / `add_warning`; graph helpers on
`KnowledgeGraph`; lightweight `VectorStore` protocol methods
`add_embedding` / `get_embedding` / `search` (in-protocol helper — **not** the
production `vector_stores.BaseVectorStore`).

### 4.3 Registry and input detection

| Symbol | Canonical import | Source | Stability |
| --- | --- | --- | --- |
| `ProcessorRegistry` | `from ipfs_datasets_py.processors import ProcessorRegistry` | `processors/core/registry.py` (re-exported) | reviewed |
| `get_global_registry` | same package | same | reviewed (global singleton — careful in tests) |
| `InputDetector` | `from ipfs_datasets_py.processors import InputDetector` | `processors/input_detection.py` | reviewed |
| `detect_input_type`, `classify_input` | package | same | reviewed |

### 4.4 UniversalProcessor

| Field | Value |
| --- | --- |
| **Canonical import (package)** | `from ipfs_datasets_py.processors import UniversalProcessor, ProcessorConfig` |
| **Source (root)** | `processors/universal_processor.py` |
| **Source (core sibling)** | `processors/core/universal_processor.py` — **compatibility** dual |
| **Stability** | reviewed entry point; dual class coexistence |
| **Optional** | Registered specialized processors and their extras |

#### Root `UniversalProcessor` (AST summary)

```python
class UniversalProcessor:
    def __init__(self, config: Optional[ProcessorConfig] = None) -> None
    async def process(self, input_source: Union[str, Path, list], **options) -> ...
    async def process_batch(self, inputs: list[Union[str, Path]], **options) -> ...
    def get_statistics(self) -> ...
    def reset_statistics(self) -> None
    def clear_cache(self) -> None
    def list_processors(self) -> ...
    def get_health_report(self) -> ...
    def check_health(self) -> ...
    def get_cache_statistics(self) -> ...
```

Core sibling adds explicit `register_processor` / `unregister_processor` /
`get_registered_processors` / `get_capabilities` depending on tree path.

| Concern | Value |
| --- | --- |
| **Sync/async** | `process` / `process_batch` are **async** |
| **Side effects** | Delegates to selected processors (file I/O, OCR, scrapers, …) |

### 4.5 Processor package exports (navigation, not exhaustive)

`processors/__init__.py` exports a **large** reviewed surface (PDF, OCR,
GraphRAG website processors, docket packaging, legal helpers, BM25 helpers,
…). Listing every symbol would invent stability for internals.

**Navigation rules:**

| Need | Prefer |
| --- | --- |
| Protocol / registry / universal entry | Symbols in §4.2–4.4 |
| BM25 / embed helpers on package | `bm25_search_documents`, `build_bm25_index`, `embed_texts_with_router_or_local`, … from `processors.retrieval` re-exports |
| PDF / OCR | `PDFProcessor`, OCR engine classes on package `__all__` |
| File conversion | `FileConverter` under `processors.file_converter` (also package-root lazy) |
| Web archive | `processors.web_archiving` (see [CORE_AND_DATA.md](CORE_AND_DATA.md) archive section) |
| Legal / docket pipelines | Package exports with `docket` / `CourtListener` names — many require **network + credentials** |

**Stability:** symbols on package `__all__` are **reviewed for importability**;
operational readiness remains **optional** per dependency. Deep domain CLIs and
scraper internals stay **internal** unless a guide marks them public.

### 4.6 In-processor retrieval helpers

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.processors import build_bm25_index, search_bm25_index, bm25_search_documents, embed_texts_with_router_or_local, embed_query_for_backend, ...` |
| **Source** | `processors/retrieval.py` (re-exported) |
| **Stability** | reviewed helpers |
| **Optional** | Embedding routers / local models |
| **Async** | Check call site; embedding helpers often **sync or async** depending on function — follow AST |

These are **not** a replacement for `vector_stores.BaseVectorStore` ANN search.

---

## 5. Embedding surfaces

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.embeddings import (...)` |
| **Source** | `ipfs_datasets_py/embeddings/__init__.py` `__all__` |
| **Stability** | reviewed package exports |
| **Optional** | `sentence-transformers`, GPU, TEI/OpenVINO endpoints, accelerate routers |
| **Compat routers** | `ipfs_datasets_py.embeddings_router` / `embedding_router` → accelerator router (**compatibility** aliases) |

### 5.1 Reviewed exports

| Symbol | Role | Sync/async |
| --- | --- | --- |
| `generate_embedding` | Single/batch-capable generation helper | **async** |
| `generate_batch_embeddings` | Multi-text generation | **async** |
| `generate_embeddings_from_file` | File → embeddings artifact | **async** (may **write** `output_path`) |
| `AdvancedIPFSEmbeddings` | Higher-level engine | mixed (see below) |
| `EmbeddingConfig`, `ChunkingConfig` | Config objects | n/a |
| `semantic_search`, `multi_modal_search`, `hybrid_search`, `search_with_filters` | Engine-side search helpers | **async** (see §7 for simulation notes) |
| Sparse / shard helpers | `SparseModel`, `shard_embeddings_by_*`, `merge_embedding_shards`, … | follow AST |

### 5.2 Generation signatures (AST)

```python
async def generate_embedding(
    text: Union[str, Dict[str, Any]],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 32,
    use_gpu: bool = False,
    **kwargs,
) -> Dict[str, Any]

async def generate_batch_embeddings(
    texts: List[str],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 32,
    use_gpu: bool = False,
    max_texts: int = 100,
    **kwargs,
) -> Dict[str, Any]

async def generate_embeddings_from_file(
    file_path: str,
    output_path: Optional[str] = None,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 32,
    chunk_size: Optional[int] = None,
    max_length: Optional[int] = None,
    output_format: str = "json",
    **kwargs,
) -> Dict[str, Any]
```

**Side effects:** may **download models**; file helper may write outputs.

### 5.3 `AdvancedIPFSEmbeddings` (AST summary)

```python
class AdvancedIPFSEmbeddings:
    def __init__(resources=None, metadata=None, config: Optional[EmbeddingConfig] = None) -> None
    async def generate_embeddings(texts, model="sentence-transformers/all-MiniLM-L6-v2") -> Any
    async def index_dataset(dataset_name, split=None, column="text", dst_path="./embeddings_cache", models=None) -> Dict
    async def search_similar(query, model=..., top_k=10, index_path=None) -> List[Dict]
    def chunk_text(text, config: Optional[ChunkingConfig] = None) -> List[tuple]
    # endpoint registration (sync): add_tei_endpoint, add_openvino_endpoint, add_libp2p_endpoint, add_local_endpoint
    async def test_endpoint(endpoint, model) -> bool
    def get_endpoints(...); def get_status() -> Dict
```

| Method | Side effects |
| --- | --- |
| `index_dataset` | Writes under `dst_path`; network for datasets/models |
| `search_similar` | Reads indexes; model inference |
| endpoint adders | Mutate in-process endpoint registry |

Architecture: [EMBEDDINGS_AND_INDEXING.md](../../architecture/retrieval/EMBEDDINGS_AND_INDEXING.md).

---

## 6. Vector store surfaces

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.vector_stores import BaseVectorStore, create_vector_store, FAISSVectorStore, QdrantVectorStore, IPLDVectorStore, ...` |
| **Source** | `vector_stores/__init__.py` (guarded by try/except for optional deps) |
| **Stability** | reviewed when dependencies import; entire package may soft-fail import |
| **Optional** | `faiss`, `qdrant-client`, Elasticsearch client, IPFS for IPLD store |

### 6.1 `BaseVectorStore` protocol (AST) — methods are **async**

```python
class BaseVectorStore(ABC):
    def __init__(self, config: VectorStoreConfig) -> None
    async def create_collection(collection_name=None, dimension=None, **kwargs) -> bool
    async def delete_collection(collection_name=None) -> bool
    async def collection_exists(collection_name=None) -> bool
    async def add_embeddings(embeddings: List[EmbeddingResult], collection_name=None) -> List[str]
    async def search(query_vector: List[float], top_k=10, collection_name=None, filter_dict=None) -> List[SearchResult]
    async def get_by_id(embedding_id, collection_name=None) -> Optional[EmbeddingResult]
    async def delete_by_id(embedding_id, collection_name=None) -> bool
    async def update_embedding(embedding_id, embedding: EmbeddingResult, collection_name=None) -> bool
    async def get_collection_info(collection_name=None) -> Dict
    async def list_collections() -> List[str]
    async def batch_add_embeddings(embeddings, batch_size=100, collection_name=None) -> List[str]
    async def similarity_search(query_vector, top_k=10, collection_name=None, score_threshold=None, filter_dict=None) -> List[SearchResult]
    async def close()
    async def export_to_ipld(collection_name=None) -> Optional[str]
    async def import_from_ipld(root_cid, collection_name=None) -> bool
    async def export_to_car(output_path, collection_name=None) -> bool
    async def import_from_car(car_path, collection_name=None) -> bool
    async def get_store_info() -> Dict
```

Supports async context manager (`__aenter__` / `__aexit__`).

| Concern | Value |
| --- | --- |
| **Side effects** | Index mutation, network to remote stores, CAR/IPLD export **writes** |
| **Filter DSL** | Backend-specific — do not assume universal filters |

### 6.2 Implementations and config

| Symbol | Notes | Optional |
| --- | --- | --- |
| `FAISSVectorStore` | Local ANN | `faiss` |
| `QdrantVectorStore` | Remote/local Qdrant | `qdrant-client` |
| `IPLDVectorStore` | FAISS + content addressing | IPFS/IPLD stack |
| `ElasticsearchVectorStore` | May be `None` if import fails | ES client |
| `UnifiedVectorStoreConfig`, `create_*_config` | Config factories | — |
| `VectorStoreManager`, `create_manager` | Multi-store management | — |
| `create_bridge`, `VectorStoreBridge` | Migration bridges | — |
| Schema types | `EmbeddingResult`, `SearchResult`, `IPLD*`, `CollectionMetadata`, `VectorBlock`, `VectorStoreType` | — |

### 6.3 High-level API (`vector_stores.api`)

```python
async def create_vector_store(
    store_type: Union[str, VectorStoreType],
    collection_name: str,
    dimension: int = 768,
    distance_metric: str = "cosine",
    **kwargs,
) -> BaseVectorStore

async def add_texts_to_store(store, texts, metadata=None, collection_name=None, batch_size=100) -> List[str]
async def search_texts(store, query, top_k=10, collection_name=None, filter_dict=None) -> List[SearchResult]
async def migrate_collection(source_store, target_store, collection_name, target_collection_name=None, batch_size=1000, verify=True) -> int
async def export_collection_to_ipfs(store, collection_name=None) -> Optional[str]
async def import_collection_from_ipfs(store, root_cid, collection_name=None) -> bool
def create_manager() -> VectorStoreManager  # sync factory
```

**Canonical import:** `from ipfs_datasets_py.vector_stores import create_vector_store, add_texts_to_store, search_texts, ...`

Architecture: [VECTOR_STORES.md](../../architecture/retrieval/VECTOR_STORES.md).

---

## 7. Search surfaces

| Field | Value |
| --- | --- |
| **Canonical package** | `ipfs_datasets_py.search` |
| **Source** | `search/__init__.py` (conditional exports) |
| **Stability** | reviewed when deps present; **mock fallback** when not |

### 7.1 `search_embeddings`

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.search import search_embeddings` |
| **Source** | `search/search_embeddings.py` or **mock** `search/search_embeddings_mock.py` on ImportError |
| **Stability** | reviewed orchestration class; mock path is **degraded** |
| **Optional** | Qdrant, FAISS, datasets, models |

Class `search_embeddings` (AST highlights) — mixed sync/async:

| Method | Async | Role |
| --- | --- | --- |
| `generate_embeddings(query, model=None)` | **async** | Encode query |
| `search(collection, query, n=5)` | **async** | Primary search |
| `start_faiss` / `load_faiss` / `ingest_faiss` / `search_faiss` | **async** | FAISS path |
| `load_qdrant_iter` / `ingest_qdrant_iter` | **async** | Qdrant path |
| `rm_cache` | **sync** | Clear cache |

**Side effects:** index load/ingest, model download, network to vector DBs.
When mock is active, results are **not** production retrieval evidence.

### 7.2 Engine helpers on embeddings package

From `embeddings/semantic_search_engine.py` (also re-exported on
`ipfs_datasets_py.embeddings`):

```python
async def semantic_search(query, vector_store_id, model_name=..., top_k=10, similarity_threshold=0.7, include_metadata=True, **kwargs) -> Dict
async def multi_modal_search(query=None, image_query=None, vector_store_id=None, model_name="clip-ViT-B-32", top_k=10, modality_weights=None, **kwargs) -> Dict
async def hybrid_search(query, vector_store_id, lexical_weight=0.3, semantic_weight=0.7, top_k=10, rerank_results=True, **kwargs) -> Dict
async def search_with_filters(query, vector_store_id, filters, top_k=10, search_method="semantic", **kwargs) -> Dict
```

Architecture notes that some helpers may return **simulated** results with
explicit `note` fields — inspect payloads; do not equate to
`BaseVectorStore.search` over real data.

### 7.3 Logic-enhanced and GraphRAG search attachments

When importable, `search/__init__.py` extends `__all__` with:

| Group | Symbols (reviewed export names) |
| --- | --- |
| Logic integration | `LogicEnhancedRAG`, `RAGQueryResult`, `LogicAwareEntityExtractor`, `LogicalEntity`, `LogicalRelationship`, `LogicalEntityType`, `LogicAwareKnowledgeGraph`, `LogicNode`, `LogicEdge`, `TheoremAugmentedRAG` |
| GraphRAG integration | `GraphRAGIntegration`, `HybridVectorGraphSearch`, `CrossDocumentReasoner`, `GraphRAGQueryEngine`, `GraphRAGFactory` |

| Field | Value |
| --- | --- |
| **Stability** | reviewed export names; soft-optional import |
| **Optional** | logic / GraphRAG stacks |
| **Authority** | Boundary attachment points — knowledge/optimizer domains own planner semantics |

### 7.4 Prefer store-backed search when correctness matters

| Path | Production readiness (current tree) |
| --- | --- |
| `BaseVectorStore.search` / `similarity_search` | Real when backend + data present |
| `vector_stores.search_texts` | Real via store + embedding path |
| `search.search_embeddings` | Orchestration; optional-heavy |
| Mock `search_embeddings` | Empty/mock — **not** success |
| `embeddings.semantic_search` helpers | May be simulated — check `note` |
| Processor BM25 helpers | Lexical, not ANN |

Architecture: [SEARCH_AND_QUERY.md](../../architecture/retrieval/SEARCH_AND_QUERY.md).

---

## 8. Core-operations inventory cross-link

All eight reviewed `core_operations` exports:

| Export | Domain page for full signature tables |
| --- | --- |
| `DatasetLoader`, `DatasetSaver`, `DatasetConverter` | [CORE_AND_DATA.md](CORE_AND_DATA.md) |
| `IPFSPinner`, `IPFSGetter` | [CORE_AND_DATA.md](CORE_AND_DATA.md) |
| `KnowledgeGraphManager` | [CORE_AND_DATA.md](CORE_AND_DATA.md) (incl. legacy name corrections) |
| `DataProcessor`, `LogicProcessor` | **this page** §3 |

---

## 9. Canonical import cheat sheet

| Intent | Canonical import | Stability | Async |
| --- | --- | --- | --- |
| Chunk/transform | `core_operations.DataProcessor` | reviewed | methods async |
| Logic façade | `core_operations.LogicProcessor` | reviewed | methods async |
| Protocol types | `processors.ProcessorProtocol`, `ProcessingResult`, … | public/reviewed | process async |
| Universal entry | `processors.UniversalProcessor` | reviewed / dual-compat | process async |
| Generate embeddings | `embeddings.generate_embedding` | reviewed | async |
| Vector store CRUD/search | `vector_stores.BaseVectorStore` / `create_vector_store` | reviewed / optional | async |
| Orchestrated search | `search.search_embeddings` | reviewed / optional mock | async |
| Hybrid engine helper | `embeddings.hybrid_search` | reviewed; may simulate | async |
| Accelerator embed router | `embeddings_router` (compat) | compatibility | follows router |

---

## 10. Side-effect and optional summary

| Surface | Common side effects | Typical optional deps |
| --- | --- | --- |
| `DataProcessor` | CPU / memory | format libs |
| `LogicProcessor` | prover/engine calls | CEC, theorem-provers extras |
| `UniversalProcessor` | full processor I/O | per registered processor |
| Embedding generation | model download, GPU | sentence-transformers, CUDA |
| Vector stores | index mutate, remote I/O | faiss, qdrant, ES, IPFS |
| Search orchestration | index + model + network | same as embeddings/stores |
| GraphRAG/logic search | graph + LLM paths | knowledge/logic extras |

---

## 11. Discrepancies and deferred items

| Item | Disposition |
| --- | --- |
| Dual UniversalProcessor / registries | Documented as compatibility period; architecture owns migration |
| Exhaustive processors `__all__` listing | Intentionally navigational — avoid false stability for every legal/PDF helper |
| Simulated semantic search | Flagged; prefer `BaseVectorStore` for production retrieval claims |
| Query optimizers / streaming loaders under `search/` | Architecture SEARCH_AND_QUERY; not all re-exported on package `__all__` |
| Deep IR / prover APIs | Deferred to knowledge/logic API domain (IPFSDOC-081) |

---

## 12. Validation evidence for this page

- `DataProcessor` / `LogicProcessor` signatures from module AST (2026-08-03).
- Processor protocol and UniversalProcessor methods from AST + package exports.
- Embeddings, vector_stores, and search `__all__` / guarded imports reviewed.
- Cross-linked to architecture guides from IPFSDOC-020 and IPFSDOC-030.
- All eight core-operations exports accounted for across this page and
  [CORE_AND_DATA.md](CORE_AND_DATA.md).
