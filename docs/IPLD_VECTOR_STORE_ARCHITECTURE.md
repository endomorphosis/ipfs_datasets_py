# IPLD Vector Store Architecture

**Date:** 2026-02-16  
**Version:** 1.0

## System Architecture Overview

This document provides detailed architectural diagrams and explanations for the IPLD/IPFS Vector Search Engine implementation.

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Application Layer                          │
│  ┌───────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │  User Applications │  │  CLI Tools       │  │  MCP Tools      │ │
│  └───────────────────┘  └──────────────────┘  └─────────────────┘ │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                        Unified Interface Layer                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  VectorStoreManager                           │  │
│  │  • Store selection and initialization                         │  │
│  │  • Cross-store operations                                     │  │
│  │  • Configuration management                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  High-Level API                               │  │
│  │  • create_ipld_vector_store()                                 │  │
│  │  • migrate_store()                                            │  │
│  │  • search_unified()                                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                      Vector Store Implementations                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐│
│  │ IPLD Vector  │  │ FAISS Store  │  │Qdrant Store  │  │ Elastic │││
│  │    Store     │  │              │  │              │  │  search │││
│  │              │  │              │  │              │  │  Store  │││
│  │ ┌──────────┐ │  └──────────────┘  └──────────────┘  └─────────┘│
│  │ │ FAISS    │ │                                                  │
│  │ │ Index    │ │                                                  │
│  │ └──────────┘ │                                                  │
│  │ ┌──────────┐ │                                                  │
│  │ │ IPLD     │ │                                                  │
│  │ │ Storage  │ │                                                  │
│  │ └──────────┘ │                                                  │
│  └──────────────┘                                                  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                         Bridge Layer                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ FAISS Bridge │  │Qdrant Bridge │  │  ES Bridge   │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  Bridge Factory                               │  │
│  │  create_bridge(source_type, target_type, ...)                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                         Router Layer                                │
│  ┌──────────────────────┐        ┌──────────────────────┐          │
│  │  Embeddings Router   │        │  IPFS Backend Router │          │
│  │  • OpenRouter        │        │  • ipfs_accelerate   │          │
│  │  • Gemini CLI        │        │  • ipfs_kit_py       │          │
│  │  • HF Transformers   │        │  • Kubo CLI          │          │
│  └──────────────────────┘        └──────────────────────┘          │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                     Infrastructure Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ IPLD Storage │  │ FAISS Library│  │  IPFS Node   │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. IPLD Vector Store Internal Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        IPLDVectorStore                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                  Configuration Layer                          │ │
│  │  • UnifiedVectorStoreConfig                                   │ │
│  │  • Router flags (use_embeddings_router, use_ipfs_router)      │ │
│  │  • IPLD settings (auto_pin, car_export_dir)                   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌───────────────────────────▼───────────────────────────────────┐ │
│  │                  Router Integration Layer                     │ │
│  │  ┌─────────────────────┐    ┌─────────────────────┐          │ │
│  │  │ Embeddings Manager  │    │  IPFS Backend       │          │ │
│  │  │ • generate_embeddings│   │  • add_bytes        │          │ │
│  │  │ • batch processing   │    │  • cat              │          │ │
│  │  └─────────────────────┘    └─────────────────────┘          │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌───────────────────────────▼───────────────────────────────────┐ │
│  │                    Vector Operations Layer                    │ │
│  │  • add_embeddings() - Add vectors with metadata               │ │
│  │  • search() - Similarity search                               │ │
│  │  • get_by_id() - Retrieve by ID                               │ │
│  │  • delete_by_id() - Remove vectors                            │ │
│  │  • update_embedding() - Update existing vectors               │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌───────────────────────────▼───────────────────────────────────┐ │
│  │                   Collection Management                       │ │
│  │  • create_collection() - Initialize collection                │ │
│  │  • delete_collection() - Remove collection                    │ │
│  │  • collection_exists() - Check existence                      │ │
│  │  • Collections: Dict[name, CollectionInfo]                    │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌───────────────────────────┴───────────────────────────────────┐ │
│  │                                                                │ │
│  │  ┌──────────────────────┐        ┌──────────────────────┐    │ │
│  │  │   Index Layer (FAISS)│        │  Storage Layer (IPLD)│    │ │
│  │  │                      │        │                      │    │ │
│  │  │  • IndexFlatIP       │        │  • IPLDStorage       │    │ │
│  │  │  • IndexFlatL2       │        │  • Block storage     │    │ │
│  │  │  • IndexIVFFlat      │        │  • CID mapping       │    │ │
│  │  │  • IndexHNSWFlat     │        │  • Metadata blocks   │    │ │
│  │  │                      │        │  • DAG-PB encoding   │    │ │
│  │  │  Vector Search:      │        │                      │    │ │
│  │  │  • k-NN search       │        │  Persistence:        │    │ │
│  │  │  • Range search      │        │  • CAR export        │    │ │
│  │  │  • Batch search      │        │  • CAR import        │    │ │
│  │  └──────────────────────┘        └──────────────────────┘    │ │
│  │              │                              │                 │ │
│  │              └──────────────┬───────────────┘                 │ │
│  │                             │                                 │ │
│  │  ┌──────────────────────────▼──────────────────────────────┐ │ │
│  │  │              Serialization Layer                         │ │ │
│  │  │  • Vector serialization (numpy arrays)                   │ │ │
│  │  │  • Metadata serialization (JSON)                         │ │ │
│  │  │  • Index serialization (FAISS binary)                    │ │ │
│  │  │  • IPLD block creation                                   │ │ │
│  │  └──────────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────┘│
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. IPLD Storage Structure

```
Collection Root Block (CID: QmXXX...)
│
├── type: "vector_collection"
├── name: "my_collection"
├── version: "1.0"
├── created: "2026-02-16T00:00:00Z"
├── updated: "2026-02-16T00:00:00Z"
│
├── metadata_cid: QmYYY...
│   └─> Metadata Block
│       ├── dimension: 768
│       ├── metric: "cosine"
│       ├── count: 10000
│       ├── index_type: "FlatIP"
│       └── schema_version: "1.0"
│
├── vectors_cid: QmZZZ...
│   └─> Vectors Container Block
│       ├── chunks: [
│       │   QmAAA...,  // Chunk 0 (vectors 0-999)
│       │   QmBBB...,  // Chunk 1 (vectors 1000-1999)
│       │   QmCCC...   // Chunk 2 (vectors 2000-2999)
│       │ ]
│       └─> Each chunk contains:
│           ├── vector_data: [
│           │   {
│           │     id: "vec_001",
│           │     vector: [0.1, 0.2, ..., 0.768],
│           │     cid: QmVEC001...
│           │   }
│           │ ]
│           └── count: 1000
│
├── index_cid: QmDDD...
│   └─> FAISS Index Block
│       ├── index_type: "FlatIP"
│       ├── dimension: 768
│       ├── ntotal: 10000
│       └── index_data: <binary FAISS index>
│
└── metadata_map_cid: QmEEE...
    └─> Metadata Mappings Block
        ├── mappings: [
        │   {
        │     vector_id: "vec_001",
        │     metadata_cid: QmMETA001...,
        │     text: "Document text",
        │     timestamp: "2026-02-16T00:00:00Z"
        │   }
        │ ]
        └── count: 10000
```

## 4. Data Flow Diagrams

### 4.1 Add Embeddings Flow

```
User Code
   │
   │ texts = ["hello", "world"]
   │ await store.add_embeddings(texts)
   │
   ▼
IPLDVectorStore.add_embeddings()
   │
   ├──> Router Integration
   │    │
   │    ├──> embeddings_router.generate_embeddings(texts)
   │    │    │
   │    │    ├──> OpenRouter API
   │    │    ├──> Gemini CLI
   │    │    └──> HF Transformers
   │    │    │
   │    │    └──> Returns: vectors (List[List[float]])
   │    │
   │    └──> Returns: embeddings (List[EmbeddingResult])
   │
   ├──> Store Vectors to IPLD
   │    │
   │    └──> For each embedding:
   │         ├──> Create vector data block
   │         │    {
   │         │      vector: [0.1, 0.2, ...],
   │         │      text: "hello",
   │         │      metadata: {...}
   │         │    }
   │         │
   │         ├──> Serialize to bytes
   │         │
   │         ├──> ipfs_backend_router.add_bytes()
   │         │    │
   │         │    └──> IPFS Node
   │         │         └──> Returns: CID (QmXXX...)
   │         │
   │         └──> Store CID mapping
   │
   ├──> Update FAISS Index
   │    │
   │    └──> index.add(vectors_np)
   │
   ├──> Update Collection Root
   │    │
   │    ├──> Update vector count
   │    ├──> Add new CIDs to vectors list
   │    ├──> Serialize index to IPLD
   │    ├──> Create new root block
   │    └──> Store root to IPFS
   │         └──> Returns: root_cid (QmROOT...)
   │
   └──> Return vector IDs
        └──> ["vec_001", "vec_002"]
```

### 4.2 Search Flow

```
User Code
   │
   │ query = "search term"
   │ results = await store.search_by_text(query, top_k=5)
   │
   ▼
IPLDVectorStore.search_by_text()
   │
   ├──> Generate Query Embedding
   │    │
   │    └──> embeddings_router.generate_embeddings([query])
   │         └──> Returns: query_vector (List[float])
   │
   ├──> Search FAISS Index
   │    │
   │    └──> index.search(query_vector, top_k=5)
   │         └──> Returns: (distances, indices)
   │              distances: [0.95, 0.87, 0.82, 0.75, 0.70]
   │              indices:   [42, 105, 8, 999, 333]
   │
   ├──> Retrieve Vector Data from IPLD
   │    │
   │    └──> For each index:
   │         ├──> Get CID from mapping
   │         │    vector_cid = vector_cids[index]
   │         │
   │         ├──> Fetch from IPFS
   │         │    data = await ipfs_backend_router.cat(vector_cid)
   │         │
   │         └──> Deserialize vector data
   │              {
   │                id: "vec_042",
   │                vector: [...],
   │                text: "matching document",
   │                metadata: {...}
   │              }
   │
   ├──> Create SearchResults
   │    │
   │    └──> results = [
   │         SearchResult(
   │           id="vec_042",
   │           score=0.95,
   │           text="matching document",
   │           metadata={...}
   │         ),
   │         ...
   │       ]
   │
   └──> Return results
        └──> List[SearchResult]
```

### 4.3 Cross-Store Migration Flow

```
User Code
   │
   │ bridge = create_bridge(FAISS, IPLD, faiss_store, ipld_store)
   │ count = await bridge.migrate_collection("my_collection")
   │
   ▼
FAISSToIPLDBridge.migrate_collection()
   │
   ├──> Create Target Collection
   │    │
   │    └──> ipld_store.create_collection(
   │         name="my_collection",
   │         dimension=768,
   │         metric="cosine"
   │       )
   │
   ├──> Stream from Source
   │    │
   │    └──> async for batch in self.export_collection("my_collection"):
   │         │
   │         └──> faiss_store.get_all_embeddings(batch_size=1000)
   │              │
   │              ├──> Batch 1: embeddings[0:1000]
   │              ├──> Batch 2: embeddings[1000:2000]
   │              └──> ...
   │
   ├──> Import to Target
   │    │
   │    └──> For each batch:
   │         │
   │         ├──> ipld_store.add_embeddings(batch)
   │         │    │
   │         │    ├──> Store vectors to IPLD
   │         │    ├──> Update FAISS index
   │         │    └──> Update collection root
   │         │
   │         └──> Update progress counter
   │
   ├──> Verify Migration
   │    │
   │    └──> Compare counts:
   │         source_count = faiss_store.get_count()
   │         target_count = ipld_store.get_count()
   │         assert source_count == target_count
   │
   └──> Return total count
        └──> 10000
```

### 4.4 CAR Export/Import Flow

```
Export Flow:
-----------
User Code
   │
   │ await store.export_to_car("collection.car", "my_collection")
   │
   ▼
IPLDVectorStore.export_to_car()
   │
   ├──> Get Collection Root CID
   │    │
   │    └──> root_cid = collections["my_collection"]["root_cid"]
   │
   ├──> Traverse IPLD DAG
   │    │
   │    └──> Collect all CIDs:
   │         ├──> root_cid
   │         ├──> metadata_cid
   │         ├──> vectors_cid
   │         │    └──> All vector chunk CIDs
   │         ├──> index_cid
   │         └──> metadata_map_cid
   │
   ├──> Fetch All Blocks from IPFS
   │    │
   │    └──> For each CID:
   │         block_data = await ipfs_backend_router.block_get(cid)
   │
   ├──> Create CAR File
   │    │
   │    └──> IPLDStorage.export_to_car()
   │         │
   │         ├──> Write CAR header
   │         │    └──> roots: [root_cid]
   │         │
   │         └──> Write all blocks
   │              └──> For each (cid, data):
   │                   car.write_block(cid, data)
   │
   └──> Save to file
        └──> "collection.car" written

Import Flow:
-----------
User Code
   │
   │ await store.import_from_car("collection.car", "imported_collection")
   │
   ▼
IPLDVectorStore.import_from_car()
   │
   ├──> Read CAR File
   │    │
   │    └──> IPLDStorage.import_from_car()
   │         │
   │         ├──> Read CAR header
   │         │    └──> roots = [root_cid]
   │         │
   │         └──> Read all blocks
   │              └──> blocks = {cid: data, ...}
   │
   ├──> Store Blocks to IPFS
   │    │
   │    └──> For each (cid, data):
   │         ipfs_backend_router.block_put(data)
   │
   ├──> Reconstruct Collection
   │    │
   │    ├──> Load root block
   │    ├──> Load metadata
   │    ├──> Load vectors
   │    └──> Rebuild FAISS index
   │
   └──> Register Collection
        └──> collections["imported_collection"] = {...}
```

## 5. Component Interaction Matrix

| Component | Embeddings Router | IPFS Router | IPLD Storage | FAISS | Vector Stores |
|-----------|------------------|-------------|--------------|-------|---------------|
| IPLDVectorStore | ✅ Generate embeddings | ✅ Store/retrieve blocks | ✅ Primary storage | ✅ Search index | N/A |
| FAISSVectorStore | ✅ Generate embeddings | ❌ | ❌ | ✅ Primary storage | N/A |
| QdrantVectorStore | ✅ Generate embeddings | ❌ | ❌ | ❌ | N/A |
| Bridge | ❌ | ❌ | ❌ | ❌ | ✅ Source/Target |
| VectorStoreManager | ✅ Via stores | ✅ Via stores | ✅ Via stores | ✅ Via stores | ✅ Manages all |

## 6. Configuration Hierarchy

```
UnifiedVectorStoreConfig
├── base: VectorStoreConfig
│   ├── store_type: VectorStoreType
│   ├── collection_name: str
│   ├── dimension: int
│   ├── distance_metric: str
│   ├── host: Optional[str]
│   ├── port: Optional[int]
│   └── connection_params: Dict
│
├── router_config:
│   ├── use_embeddings_router: bool = True
│   ├── use_ipfs_router: bool = True
│   ├── embeddings_router_provider: Optional[str] = None
│   ├── ipfs_router_backend: Optional[str] = None
│   └── router_cache_enabled: bool = True
│
├── ipld_config:
│   ├── enable_ipld_export: bool = True
│   ├── auto_pin_to_ipfs: bool = False
│   ├── car_export_dir: Optional[str] = None
│   ├── chunk_size: int = 1000
│   └── compression: bool = False
│
├── performance_config:
│   ├── batch_size: int = 1000
│   ├── parallel_workers: int = 4
│   ├── cache_size: int = 10000
│   └── prefetch_enabled: bool = True
│
└── multi_store_config:
    ├── enable_multi_store_sync: bool = False
    ├── sync_stores: Optional[List[str]] = None
    └── sync_interval: int = 3600
```

## 7. Error Handling Flow

```
Operation Attempted
   │
   ▼
Try Operation
   │
   ├──> Success
   │    └──> Return Result
   │
   └──> Exception Caught
        │
        ├──> VectorStoreConnectionError
        │    ├──> Log error
        │    ├──> Attempt reconnection (if configured)
        │    └──> Raise or return error response
        │
        ├──> VectorStoreOperationError
        │    ├──> Log error with context
        │    ├──> Rollback transaction (if applicable)
        │    └──> Raise with helpful message
        │
        ├──> RouterError
        │    ├──> Log router failure
        │    ├──> Try fallback provider (if configured)
        │    └──> Raise if all providers fail
        │
        └──> IPLDStorageError
             ├──> Log IPLD/IPFS error
             ├──> Check IPFS node availability
             └──> Raise with diagnostic info
```

## 8. Security Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Security Layers                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Authentication Layer                                    │
│     ├── API Key validation (for remote endpoints)          │
│     ├── JWT token verification                             │
│     └── User identity management                           │
│                                                             │
│  2. Authorization Layer                                     │
│     ├── Collection-level access control                    │
│     ├── Operation-level permissions                        │
│     └── Resource quotas                                    │
│                                                             │
│  3. Data Protection Layer                                   │
│     ├── Encryption at rest (optional)                      │
│     ├── Encryption in transit (TLS)                        │
│     └── Sensitive data redaction                           │
│                                                             │
│  4. IPFS Security Layer                                     │
│     ├── Private IPFS network support                       │
│     ├── CID validation                                     │
│     └── Block integrity verification                       │
│                                                             │
│  5. Input Validation Layer                                  │
│     ├── Vector dimension validation                        │
│     ├── Metadata sanitization                             │
│     └── Query parameter validation                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 9. Scalability Architecture

```
Small Scale (< 10K vectors)
┌──────────────────────┐
│  Single Node         │
│  ┌────────────────┐  │
│  │ IPLDVectorStore│  │
│  │ • Flat Index   │  │
│  │ • In-memory    │  │
│  └────────────────┘  │
│  ┌────────────────┐  │
│  │ Local IPFS     │  │
│  └────────────────┘  │
└──────────────────────┘

Medium Scale (10K - 1M vectors)
┌──────────────────────────────────────┐
│  Optimized Single Node               │
│  ┌────────────────┐                  │
│  │ IPLDVectorStore│                  │
│  │ • IVF Index    │                  │
│  │ • Disk-backed  │                  │
│  └────────────────┘                  │
│  ┌────────────────┐                  │
│  │ IPFS Cluster   │                  │
│  │ • Replication  │                  │
│  └────────────────┘                  │
└──────────────────────────────────────┘

Large Scale (> 1M vectors)
┌─────────────────────────────────────────────────────┐
│  Distributed Architecture                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ Store Node 1│  │ Store Node 2│  │ Store Node 3│ │
│  │ • HNSW Index│  │ • HNSW Index│  │ • HNSW Index│ │
│  │ • Sharded   │  │ • Sharded   │  │ • Sharded   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
│         │                 │                 │        │
│  ┌──────┴─────────────────┴─────────────────┴────┐  │
│  │         Load Balancer / Router                │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │         IPFS Cluster (Distributed)            │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Related Documents:**
- [IPLD Vector Store Improvement Plan](./IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md)
- [Quick Start Guide](./IPLD_VECTOR_STORE_QUICKSTART.md)
