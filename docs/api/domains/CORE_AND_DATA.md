# Core and data API domain reference

| Field | Value |
| --- | --- |
| Interface | `CoreDataAPIReference@1` |
| Task | `IPFSDOC-080` |
| Status | `canonical` |
| Owner | api-reference / core-data |
| Source of truth | `ipfs_datasets_py/core_operations/__init__.py` (`__all__`); module ASTs under `core_operations/`; `ipfs_datasets_py/dataset_manager.py`; `ipfs_datasets_py/ipfs_datasets.py`; package `__getattr__` / `__all__` in `ipfs_datasets_py/__init__.py`; `ipfs_datasets_py/storage/`; `ipfs_datasets_py/ipfs_backend_router.py`; `ipfs_datasets_py/web_archiving/`; `ipfs_datasets_py/huggingface/`; `ipfs_datasets_py/p2p_networking/`; architecture leaves under `docs/architecture/storage/`; unit tests `tests/unit/core_operations/` |
| Last verified | 2026-08-03 |
| Audience | developer, agent, operator |
| Related | [PROCESSING_AND_RETRIEVAL.md](PROCESSING_AND_RETRIEVAL.md), [DOMAIN_MAP.md](../../architecture/DOMAIN_MAP.md), [STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md), [CONTENT_ADDRESSING_AND_IPLD.md](../../architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md), [P2P_AND_PUBLICATION.md](../../architecture/storage/P2P_AND_PUBLICATION.md), legacy [CORE_OPERATIONS_API.md](../CORE_OPERATIONS_API.md) (superseded for method names) |
| Review cadence | after `core_operations` export or dataset/storage/publication surface changes |

## 1. Purpose

This page is the **source-grounded callable map** for core data, IPFS pin/get,
storage engines, web archive, and publication surfaces. It covers:

1. All **eight** reviewed `core_operations` exports (dataset + IPFS subset
   fully specified here; processing-oriented exports are summarized with
   pointers to [PROCESSING_AND_RETRIEVAL.md](PROCESSING_AND_RETRIEVAL.md)).
2. Intended **dataset**, **storage**, **archive**, and **publication** APIs.
3. Stability, sync/async, side effects, optional requirements, and
   **canonical imports**.

Importability alone does **not** imply public stability. Prefer the
**canonical** import paths below.

## 2. Authority legend

| Tag | Meaning |
| --- | --- |
| **Stability: public** | Intended for external callers; breaking changes require review |
| **Stability: reviewed** | Exported and exercised by tests/MCP/CLI; contract is the module AST |
| **Stability: compatibility** | Alias, lazy re-export, or dual-path surface; prefer canonical target |
| **Stability: internal** | Present in tree but not in reviewed `__all__` / not a public promise |
| **Source** | Module path and symbol that authorize the row |
| **Optional** | Needs extras, binaries, submodules, network, or env flags |
| **Side effects** | I/O, network, pin sets, filesystem writes, process state |

Result authority for core operations is almost always a **dict envelope** with
`status` of `"success"` or `"error"` (plus domain keys). Treat `status !=
"success"` as failure; never invent success from partial payloads.

---

## 3. Eight current `core_operations` exports

**Canonical package import:**

```python
from ipfs_datasets_py.core_operations import (
    DatasetLoader,
    DatasetSaver,
    DatasetConverter,
    IPFSPinner,
    IPFSGetter,
    KnowledgeGraphManager,
    DataProcessor,
    LogicProcessor,
)
```

**Source:** `ipfs_datasets_py/core_operations/__init__.py` `__all__` (exactly
these eight names). MCP tools and CLI commands are expected to be thin wrappers
around these classes.

| Export | Module | Role in this domain page | Stability |
| --- | --- | --- | --- |
| `DatasetLoader` | `core_operations/dataset_loader.py` | Dataset load | reviewed |
| `DatasetSaver` | `core_operations/dataset_saver.py` | Dataset save | reviewed |
| `DatasetConverter` | `core_operations/dataset_converter.py` | Format conversion | reviewed |
| `IPFSPinner` | `core_operations/ipfs_pinner.py` | Pin / content add | reviewed |
| `IPFSGetter` | `core_operations/ipfs_getter.py` | Retrieve by CID | reviewed |
| `KnowledgeGraphManager` | `core_operations/knowledge_graph_manager.py` | Graph lifecycle (core export) | reviewed |
| `DataProcessor` | `core_operations/data_processor.py` | Chunk / transform (see processing page) | reviewed |
| `LogicProcessor` | `core_operations/logic_processor.py` | Logic helpers (see processing page) | reviewed |

**Not exported (internal):** `core_operations/index_manager.py`
(`IndexManagerCore`, `MockIndexManager`, …) is **not** in `__all__`.
**Stability: internal** — do not document as a public import.

### 3.1 Shared conventions

| Concern | Contract |
| --- | --- |
| Async | Primary methods are `async def`. Dataset/IPFS classes also expose `*_sync` helpers that run the async path. |
| Construction | Lightweight `__init__`; no network at import of the package. |
| Errors | Prefer returned `{"status": "error", ...}` over raised exceptions for operational failures; validation may still raise in rare paths. |
| Side effects | Load/save touch filesystem and optional HF network; pin/get touch IPFS daemon/backends; graph methods may open drivers. |

---

## 4. DatasetLoader

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import DatasetLoader` |
| **Source** | `ipfs_datasets_py/core_operations/dataset_loader.py` |
| **Stability** | reviewed |
| **Optional** | Hugging Face `datasets` for hub names; local path/URL loaders may need network |

### Signatures (AST)

```python
class DatasetLoader:
    def __init__(self) -> None
    async def load(
        source: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
    def load_sync(
        source: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
```

| Method | Sync/async | Side effects |
| --- | --- | --- |
| `load` | **async** | May download HF datasets, read local files/URLs |
| `load_sync` | **sync** wrapper | Same as `load` |

**`source`:** HF id (`"squad"`), local directory, local file (JSON/CSV/Parquet/…),
or URL. **Python (`.py`) and executable paths are rejected** (error envelope).

**Success keys (typical):** `status`, `dataset_id`, `metadata`, …
**Error keys:** `status="error"`, `message`.

```python
loader = DatasetLoader()
result = await loader.load("squad", options={"split": "train"})
# or: loader.load_sync("path/to/data.json")
```

---

## 5. DatasetSaver

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import DatasetSaver` |
| **Source** | `ipfs_datasets_py/core_operations/dataset_saver.py` |
| **Stability** | reviewed |
| **Optional** | Format writers (parquet/arrow extras as installed) |

### Signatures (AST)

```python
class DatasetSaver:
    def __init__(self) -> None
    async def save(
        dataset: Any,
        destination: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
    def save_sync(
        dataset: Any,
        destination: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
```

| Method | Sync/async | Side effects |
| --- | --- | --- |
| `save` / `save_sync` | async / sync | **Writes** dataset files to `destination` |

---

## 6. DatasetConverter

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import DatasetConverter` |
| **Source** | `ipfs_datasets_py/core_operations/dataset_converter.py` |
| **Stability** | reviewed |
| **Optional** | Source/target format libraries |

### Signatures (AST)

```python
class DatasetConverter:
    def __init__(self) -> None
    async def convert(
        source: str,
        target_format: str,
        source_format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
    def convert_sync(
        source: str,
        target_format: str,
        source_format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
```

| Method | Sync/async | Side effects |
| --- | --- | --- |
| `convert` / `convert_sync` | async / sync | Reads source path; may write converted output depending on options |

---

## 7. IPFSPinner

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import IPFSPinner` |
| **Source** | `ipfs_datasets_py/core_operations/ipfs_pinner.py` |
| **Stability** | reviewed |
| **Optional** | IPFS daemon / `ipfs_kit_py` / MCP client depending on `integration_mode` |

### Signatures (AST)

```python
class IPFSPinner:
    def __init__(self, integration_mode: str = "direct") -> None
    async def pin(
        content_source: Union[str, Dict[str, Any]],
        recursive: bool = True,
        wrap_with_directory: bool = False,
        hash_algo: str = "sha2-256",
    ) -> Dict[str, Any]
    def pin_sync(
        content_source: Union[str, Dict[str, Any]],
        recursive: bool = True,
        wrap_with_directory: bool = False,
        hash_algo: str = "sha2-256",
    ) -> Dict[str, Any]
```

| Method | Sync/async | Side effects |
| --- | --- | --- |
| `pin` / `pin_sync` | async / sync | **Pins** content to IPFS; may start/use kit or MCP; may hash local paths |

**Success keys (typical):** `status`, `cid`, `content_type` (`file` \| `directory` \| `data`), `size`, `hash_algo`.
**Error:** missing paths return `status="error"` with message (tested).

### Legacy correction

Older docs used `pin(content_source, backend_options=None)`. That signature is
**wrong** for the current tree. Use `recursive`, `wrap_with_directory`, and
`hash_algo` as above. For low-level backend selection, use
`ipfs_datasets_py.ipfs_backend_router` (§10), not invented `backend_options` on
`IPFSPinner.pin`.

---

## 8. IPFSGetter

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import IPFSGetter` |
| **Source** | `ipfs_datasets_py/core_operations/ipfs_getter.py` |
| **Stability** | reviewed |
| **Optional** | Reachable IPFS backend / daemon |

### Signatures (AST)

```python
class IPFSGetter:
    def __init__(self, integration_mode: str = "direct") -> None
    async def get(
        cid: str,
        output_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
    def get_sync(
        cid: str,
        output_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]
```

| Method | Sync/async | Side effects |
| --- | --- | --- |
| `get` / `get_sync` | async / sync | Network/backend fetch; may **write** to `output_path` |

---

## 9. KnowledgeGraphManager (core export)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import KnowledgeGraphManager` |
| **Source** | `ipfs_datasets_py/core_operations/knowledge_graph_manager.py` |
| **Stability** | reviewed |
| **Optional** | Graph drivers / Neo4j-style URLs; advanced helpers may need logic/KG extras |

Graph **product** depth (GraphRAG planners, optimizers) lives under knowledge
architecture; this section is the **reviewed core_operations callable surface**.

### Construction

```python
class KnowledgeGraphManager:
    def __init__(self, driver_url: str = "ipfs://localhost:5001") -> None
```

### Lifecycle and CRUD (AST) — all **async**

| Method | Signature (params) | Notes |
| --- | --- | --- |
| `initialize` | `() -> Dict[str, Any]` | Open/init connection — **not** `create()` |
| `close` | `() -> Dict[str, Any]` | Close connection |
| `add_entity` | `(entity_id, entity_type, properties=None)` | Mutates graph |
| `add_relationship` | `(source_id, target_id, relationship_type, properties=None)` | Mutates graph |
| `query_cypher` | `(query, parameters=None)` | Read/write depending on Cypher |
| `hybrid_search` | `(query, search_type="semantic", limit=10)` | **not** `search_hybrid` |
| `transaction_begin` | `()` | Side effect: open tx |
| `transaction_commit` | `(transaction_id=None)` | Param name is `transaction_id` |
| `transaction_rollback` | `(transaction_id=None)` | |
| `index_create` | `(index_name, entity_type, properties: List[str])` | **not** `create_index(label, property)` |
| `constraint_add` | `(constraint_name, constraint_type, entity_type, properties: List[str])` | **not** `add_constraint(...)` |

### Extended methods (AST) — all **async**

| Method | Purpose (docstring first line) |
| --- | --- |
| `extract_srl` | SRL frames from text |
| `ontology_materialize` | OWL/RDFS-style materialization |
| `distributed_execute` | Partitioned Cypher execution |
| `graphql_query` | GraphQL against KG data |
| `visualize` | Export visualization format string |
| `suggest_completions` | Suggest missing relationships |
| `explain_entity` | Structured explanation |
| `verify_provenance` | Provenance chain integrity |

### Legacy corrections (wrong names in older API prose)

| Legacy (incorrect) | Current (AST) |
| --- | --- |
| `create()` | `initialize()` |
| `search_hybrid(...)` | `hybrid_search(...)` |
| `create_index(label, property)` | `index_create(index_name, entity_type, properties)` |
| `add_constraint(label, property, constraint_type=...)` | `constraint_add(constraint_name, constraint_type, entity_type, properties)` |
| `transaction_commit(tx_id)` as sole positional | `transaction_commit(transaction_id=None)` |

```python
kg = KnowledgeGraphManager()
await kg.initialize()
await kg.add_entity("person1", "Person", {"name": "Alice"})
hits = await kg.hybrid_search("Alice", search_type="hybrid", limit=10)
await kg.close()
```

---

## 10. DataProcessor and LogicProcessor (exports; full detail elsewhere)

These two remain first-class **core_operations** exports and must be imported
from the canonical package. Full method tables live in
[PROCESSING_AND_RETRIEVAL.md](PROCESSING_AND_RETRIEVAL.md).

| Export | Canonical import | Role |
| --- | --- | --- |
| `DataProcessor` | `from ipfs_datasets_py.core_operations import DataProcessor` | `chunk_text`, `transform_data`, `convert_format` (all **async**) |
| `LogicProcessor` | `from ipfs_datasets_py.core_operations import LogicProcessor` | CEC/DCEC/TDFOL helpers, formula/KB ops (all **async**) |

| Field | DataProcessor | LogicProcessor |
| --- | --- | --- |
| **Source** | `core_operations/data_processor.py` | `core_operations/logic_processor.py` |
| **Stability** | reviewed | reviewed |
| **Optional** | transform backends | CEC/logic extras, provers for prove paths |
| **Side effects** | CPU transforms; format conversion may allocate large objects | May invoke optional logic engines; usually no durable store unless KB ops configured |

---

## 11. Dataset surfaces (intended public)

### 11.1 `DatasetManager` / `ManagedDataset`

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.dataset_manager import DatasetManager` (also lazy via package `__getattr__` as `DatasetManager`) |
| **Source** | `ipfs_datasets_py/dataset_manager.py` |
| **Stability** | reviewed (lazy optional at package root) |
| **Optional** | accelerate-related path when `use_accelerate=True` |

```python
class DatasetManager:
    def __init__(self, use_accelerate: bool = True) -> None
    def get_dataset(self, dataset_id: str) -> ManagedDataset
    def save_dataset(self, dataset_id: str, dataset: _DatasetLike) -> None

class ManagedDataset:
    def __init__(self, dataset: _DatasetLike, dataset_id: str) -> None
    async def save_async(self, destination: str, format: Optional[str] = None, **options) -> Dict[str, Any]
    def save(self, destination: str, format: Optional[str] = None, **options) -> Dict[str, Any]
```

`save` is **sync**; `save_async` is **async**. Both may write destinations.

### 11.2 Package `IPFSDatasets` / `ipfs_datasets_py`

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py import IPFSDatasets` (alias of class `ipfs_datasets_py` in `ipfs_datasets.py`) |
| **Source** | `ipfs_datasets_py/ipfs_datasets.py`; package `__getattr__` |
| **Stability** | public name / reviewed class; heavy methods are **workflow-oriented** |
| **Optional** | HF datasets, embedding models, IPFS kit; falls back to `_FallbackIPFSDatasets` when core deps missing |

Important **async** methods on class `ipfs_datasets_py` (selected):

| Method | Role |
| --- | --- |
| `load_dataset(dataset, split=None)` | Load into instance state (HF-oriented workflow) |
| `load_original_dataset(dataset, split=None)` | Original dataset path |
| `load_checkpoints` / `load_chunk_checkpoints` / `load_combined_checkpoints` | Checkpoint I/O |
| `load_combined` / `combine_checkpoints` / `generate_clusters` / `load_clusters` | Embedding/cluster workflows |

**Side effects:** filesystem under `dst_path` / cache dirs; optional network downloads.

### 11.3 Package `load_dataset`

| Field | Value |
| --- | --- |
| **Canonical meaning** | Lazy re-export of Hugging Face `datasets.load_dataset` when available |
| **Source** | `ipfs_datasets_py/__init__.py` `__getattr__("load_dataset")` |
| **Stability** | **compatibility** with the external `datasets` package — **not** the same contract as `DatasetLoader.load` |
| **Optional** | Requires `datasets` installed; otherwise resolves to `None` |

Prefer `DatasetLoader` for the ipfs-datasets **status-envelope** API; use
`load_dataset` only when intentionally calling Hugging Face's API.

### 11.4 Dataset serialization (lazy package symbols)

| Symbol | Canonical path | Stability |
| --- | --- | --- |
| `DatasetSerializer`, `GraphDataset`, `GraphNode`, `VectorAugmentedGraphDataset` | `ipfs_datasets_py.data_transformation.serialization.dataset_serialization` via package `__getattr__` | reviewed when available; **Optional** deps |
| `DataInterchangeUtils` / CAR helpers | `data_transformation.serialization.car_conversion` | reviewed / optional |

When unavailable, package attributes become `None` and `HAVE_*` flags clear —
treat as degraded, not success.

### 11.5 `FileConverter` / `ConversionResult` (package root)

| Field | Value |
| --- | --- |
| **Canonical import** | Prefer `from ipfs_datasets_py.processors.file_converter import FileConverter, ConversionResult` |
| **Package root** | Lazy `from ipfs_datasets_py import FileConverter` — **compatibility** convenience |
| **Source** | `ipfs_datasets_py/processors/file_converter/converter.py` |
| **Stability** | reviewed processor surface; listed in package `__all__` |
| **Async** | `convert` (**async**), `convert_sync` (**sync**), `convert_batch` (**async**) |

---

## 12. Storage surfaces

### 12.1 `ipfs_datasets_py.storage`

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.storage import StorageType, CompressionType, StorageItem, Collection, MockStorageManager` |
| **Source** | `storage/__init__.py`, `storage/storage_engine.py` |
| **Stability** | reviewed facade; `MockStorageManager` is for **dev/test** (name is intentional) |
| **Async** | **sync** methods on `MockStorageManager` |

```python
class MockStorageManager:
    def store_item(content, storage_type=StorageType.MEMORY, compression=CompressionType.NONE,
                   metadata=None, tags=None, collection_name="default") -> StorageItem
    def retrieve_item(item_id: str, include_content: bool = False) -> Optional[Dict[str, Any]]
    def list_items(collection_name=None, storage_type=None, tags=None, limit=100, offset=0) -> List[Dict]
    def delete_item(item_id: str) -> bool
    def create_collection(name, description="", metadata=None) -> Dict
    def get_collection(name) -> Optional[Dict]
    def list_collections() -> List[Dict]
    def delete_collection(name, delete_items=False) -> bool
    def get_storage_stats() -> Dict
```

**Side effects:** in-process store mutations (not IPFS by default).

### 12.2 IPFS backend router (location / pin primitives)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend, pin, unpin, cat, add_bytes, add_path, get_to_path, ...` |
| **Source** | `ipfs_datasets_py/ipfs_backend_router.py` |
| **Stability** | reviewed protocol + providers |
| **Optional** | Kubo CLI (`ipfs`); `ipfs_accelerate_py` / `ipfs_kit_py` when env-enabled |
| **Async** | Provider methods are **sync** I/O-style unless a provider documents otherwise |

**Protocol `IPFSBackend`:** `add_bytes`, `cat`, `pin`, `unpin`, `block_put`,
`block_get`, `add_path`, `get_to_path`, `ls`, `dag_export`.

**Env (optional selection):**

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_PY_IPFS_BACKEND` | Force backend name |
| `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE` | Enable accelerate provider |
| `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` | Enable kit provider |
| `IPFS_DATASETS_PY_KUBO_CMD` | Override `ipfs` CLI |

**Side effects:** pin set and content placement changes; not content-identity
math (see content-addressing architecture guide).

### 12.3 Caching (adjacent storage)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.caching import CacheManager` (plus module re-exports in `__all__`) |
| **Source** | `ipfs_datasets_py/caching/` |
| **Stability** | reviewed manager; individual engines vary |
| **Optional** | distributed/remote cache extras |

Caches are **performance**, not identity. Do not treat cache hit as proof of
correctness.

### 12.4 IPLD / content addressing

Deep CID/CAR/IPLD APIs live under processors storage and architecture docs.
Entry architecture: [CONTENT_ADDRESSING_AND_IPLD.md](../../architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md).
Do not use package-root mocks as production identity.

---

## 13. Archive surfaces (web archiving)

| Field | Value |
| --- | --- |
| **Canonical implementation** | `ipfs_datasets_py.processors.web_archiving.unified_api.UnifiedWebArchivingAPI` |
| **Package re-export** | `ipfs_datasets_py.web_archiving` re-exports contracts + unified API (**compatibility** shim for path stability) |
| **Contracts source** | `processors/web_archiving/contracts.py` (also re-exported under `web_archiving.contracts`) |
| **Stability** | reviewed unified API + contracts; individual engines optional |
| **Optional** | Search/fetch engines, API keys, network, Playwright/scraping extras |

### Contracts (reviewed types)

`OperationMode`, `ErrorSeverity`, `UnifiedError`, `UnifiedSearchHit`,
`UnifiedDocument`, `ExecutionTrace`, `UnifiedSearchRequest`,
`UnifiedFetchRequest`, `UnifiedSearchResponse`, `UnifiedFetchResponse`.

### `UnifiedWebArchivingAPI` methods (AST)

```python
class UnifiedWebArchivingAPI:
    def search(request: Union[UnifiedSearchRequest, str], **kwargs) -> UnifiedSearchResponse
    def fetch(request: Union[UnifiedFetchRequest, str], **kwargs) -> UnifiedFetchResponse
    def search_and_fetch(request: Union[UnifiedSearchRequest, str], **kwargs) -> Dict[str, Any]
    def agentic_discover_and_fetch(...) -> Dict[str, Any]
    def health() -> Dict[str, Any]
```

| Concern | Value |
| --- | --- |
| **Sync/async** | Methods are **sync** at the unified API boundary |
| **Side effects** | Network search/fetch; may persist via configured scrapers |
| **Canonical import** | `from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI, UnifiedAPIConfig` |

Inspect response objects / error severity; do not treat empty engine sets as
successful archive completion.

---

## 14. Publication surfaces

### 14.1 Hugging Face publication / snapshot

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.huggingface import (...)` per `__all__` |
| **Source** | `ipfs_datasets_py/huggingface/{repository,snapshot,bucket}.py` |
| **Stability** | reviewed schemas + fetchers |
| **Optional** | Hub credentials/network; offline inventory/revision models still usable |
| **Async** | Primary classes use **sync** methods |

Selected callables:

| Type | Methods / role |
| --- | --- |
| `HuggingFaceRepository` | `resolve_revision(revision)`, `snapshot(**options)` |
| `HuggingFaceRepositoryRevision` | `to_dict` / `canonical_bytes` / `to_json` |
| `HuggingFaceSnapshotFetcher` / cache types | Snapshot fetch + integrity validation |
| `HuggingFaceBucketStore` | `inventory()`, `fetch(item, destination)`, `verify_download(item, path)` |

**Side effects:** network fetch and **filesystem writes** under destinations.
Architecture: [P2P_AND_PUBLICATION.md](../../architecture/storage/P2P_AND_PUBLICATION.md).

### 14.2 P2P distribution

| Field | Value |
| --- | --- |
| **Canonical import** | Lazy modules: `from ipfs_datasets_py.p2p_networking import p2p_connectivity, p2p_peer_registry, p2p_workflow_scheduler, libp2p_kit, ...` |
| **Source** | `p2p_networking/__init__.py` `__all__` + optional engines |
| **Stability** | package import is stable; **libp2p** full kit is **optional** (`libp2p` extra / stubs) |
| **Optional** | real libp2p, multiaddr bootstrap, cluster |

Engines when importable: `PeerEngine`, `TaskQueueEngine`, `WorkflowEngine`.
Treat stubs/simulations as **non-production completion** (architecture guide).

### 14.3 Cluster retention

`ipfs_datasets_py.ipfs_cluster` owns cluster-oriented retention; pin location
policy is distinct from CID identity. See storage architecture leaves.

---

## 15. Cross-surface import map (quick)

| Intent | Canonical import | Stability |
| --- | --- | --- |
| Load dataset (status envelope) | `core_operations.DatasetLoader` | reviewed |
| Save / convert dataset | `DatasetSaver` / `DatasetConverter` | reviewed |
| Pin / get IPFS content | `IPFSPinner` / `IPFSGetter` | reviewed |
| Low-level IPFS backend | `ipfs_backend_router.get_ipfs_backend` | reviewed |
| In-process storage engine | `storage.MockStorageManager` | reviewed (mock) |
| Knowledge graph core ops | `KnowledgeGraphManager` | reviewed |
| Chunk/transform core ops | `DataProcessor` | reviewed → processing page |
| Logic core ops | `LogicProcessor` | reviewed → processing page |
| Web archive unified | `processors.web_archiving.unified_api.UnifiedWebArchivingAPI` | reviewed |
| Hub publication models | `huggingface.*` | reviewed |
| HF hub load (upstream) | package `load_dataset` | compatibility / optional |
| Legacy short API doc | `docs/api/CORE_OPERATIONS_API.md` | **stale method names** — use this page |

---

## 16. Discrepancies and deferred items

| Item | Disposition |
| --- | --- |
| Legacy `CORE_OPERATIONS_API.md` method names | Corrected in §7 and §9; leave legacy file for IPFSDOC-082 index work unless owned elsewhere |
| `index_manager.py` in `core_operations/` | **Internal** — not in `__all__` |
| Dual `web_archiving` package vs `processors.web_archiving` | Prefer processors implementation; top-level package is re-export shim |
| Exhaustive HF snapshot class method table | Partial — follow AST in `huggingface/snapshot.py` for callers |
| Production non-mock storage engines | Thin `storage` facade today; IPLD/backends are separate modules |

---

## 17. Validation evidence for this page

- Export list matches `core_operations/__init__.py` `__all__` (eight symbols).
- Method names/signatures extracted from module ASTs on 2026-08-03.
- Legacy wrong names called out against current AST.
- Dataset, storage, archive, and publication surfaces tied to package
  `__all__` / `__getattr__` / architecture dependency docs (IPFSDOC-010,
  IPFSDOC-023, related storage leaves).
