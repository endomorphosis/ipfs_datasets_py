# IPLD/IPFS Vector Search Engine - Comprehensive Improvement Plan

**Date:** 2026-02-16  
**Status:** Planning Phase  
**Goal:** Create a production-ready IPLD/IPFS-native vector search engine with unified interface and cross-store bridges

## Executive Summary

This document outlines a comprehensive plan to build an IPLD/IPFS-compatible vector search engine in `ipfs_datasets_py/vector_stores/` that provides:

1. **IPLD-native vector storage** with content-addressing and decentralized capabilities
2. **Unified interface** for interacting with all supported vector stores
3. **Import/Export bridges** for FAISS, Qdrant, and Elasticsearch
4. **Router integration** with embeddings_router and ipfs_backend_router
5. **Production-ready** implementation with comprehensive tests and documentation

## Current State Analysis

### Existing Components

#### 1. Vector Store Implementations
Located in: `ipfs_datasets_py/vector_stores/`

- **BaseVectorStore** (`base.py`) - Abstract interface with async methods
  - Methods: `create_collection`, `add_embeddings`, `search`, `get_by_id`, `delete_by_id`, `update_embedding`
  - Uses schema from `ml/embeddings/schema.py`
  
- **FAISSVectorStore** (`faiss_store.py`) - Local similarity search
  - High-performance, memory-efficient
  - Supports multiple index types (Flat, IVF, HNSW)
  - GPU acceleration support
  - Auto-installer for dependencies
  
- **QdrantVectorStore** (`qdrant_store.py`) - Production vector database
  - Native filtering and metadata support
  - Distributed clustering
  - Real-time indexing
  
- **ElasticsearchVectorStore** (`elasticsearch_store.py`) - Hybrid search
  - Full-text + vector search
  - Advanced filtering
  - Scalable clusters

- **IPLDVectorStore** (`ipld.py`) - Partial IPLD implementation
  - Basic IPLD storage using `IPLDStorage`
  - FAISS-backed search
  - Limited interface compliance

#### 2. IPLD Infrastructure
Located in: `ipfs_datasets_py/processors/storage/ipld/`

- **IPLDStorage** (`storage.py`) - Core IPLD storage layer
  - Content-addressed storage
  - Block linking
  - Schema validation
  - CAR file import/export
  - Singleton pattern

- **IPLDVectorStore** (`vector_store.py`) - Processor-level vector store
  - Duplicate of `vector_stores/ipld.py` with variations
  - FAISS integration
  - Batch operations
  - Metrics tracking

- **OptimizedCodec** (`optimized_codec.py`) - Efficient IPLD encoding
  - DAG-PB serialization
  - Batch processing
  - Performance optimizations

- **dag_pb.py** - DAG-PB format support
  - Node creation and parsing
  - Link management

#### 3. Router Infrastructure

- **embeddings_router.py** - Embedding generation router
  - Multiple provider support (ipfs_accelerate_py, OpenRouter, Gemini CLI)
  - Local fallback via `embedding_adapter`
  - Caching support
  - Environment-based configuration
  
- **ipfs_backend_router.py** - IPFS operations router
  - Pluggable backend strategy
  - Providers: ipfs_accelerate_py, ipfs_kit_py, Kubo CLI
  - Operations: `add_bytes`, `cat`, `pin`, `unpin`, `block_put`, `block_get`, `add_path`, `dag_export`
  
- **router_deps.py** - Dependency injection for routers

#### 4. Schema Definitions
Located in: `ipfs_datasets_py/ml/embeddings/schema.py`

- **EmbeddingResult** - Embedding data structure
- **SearchResult** - Search result container
- **VectorStoreConfig** - Configuration for vector stores
- **VectorStoreType** - Enum of supported store types
- **ChunkingStrategy** - Text chunking strategies

### Identified Gaps

1. **Incomplete IPLD Integration**
   - Current `ipld.py` in `vector_stores/` doesn't fully implement `BaseVectorStore` interface
   - Lacks async support
   - Missing collection management methods
   - No unified interface with other stores

2. **Duplicate Implementations**
   - `vector_stores/ipld.py` vs `processors/storage/ipld/vector_store.py`
   - Inconsistent APIs and capabilities
   - No clear migration path

3. **Missing Bridges**
   - No import/export functionality between stores
   - Can't migrate data from FAISS → Qdrant
   - Can't export IPLD vectors to other formats

4. **Router Integration**
   - Vector stores don't leverage `embeddings_router` by default
   - No automatic IPFS storage via `ipfs_backend_router`
   - Manual configuration required

5. **Schema Inconsistencies**
   - Multiple `SearchResult` definitions across codebase
   - Some use `ml/embeddings/schema.py`, others define their own
   - IPLD implementations use custom schemas

## Improvement Plan

### Phase 1: Unified Interface & Schema Consolidation (4-6 hours)

**Goal:** Create a single, comprehensive interface that all vector stores implement.

#### 1.1 Enhance BaseVectorStore Interface
**File:** `ipfs_datasets_py/vector_stores/base.py`

Add IPLD-specific methods:
```python
@abstractmethod
async def export_to_ipld(self, collection_name: Optional[str] = None) -> str:
    """Export collection to IPLD format, return root CID."""
    pass

@abstractmethod
async def import_from_ipld(self, root_cid: str, collection_name: Optional[str] = None) -> bool:
    """Import collection from IPLD CID."""
    pass

@abstractmethod
async def export_to_car(self, output_path: str, collection_name: Optional[str] = None) -> bool:
    """Export collection to CAR file."""
    pass

@abstractmethod
async def import_from_car(self, car_path: str, collection_name: Optional[str] = None) -> bool:
    """Import collection from CAR file."""
    pass

@abstractmethod
async def get_store_info(self) -> Dict[str, Any]:
    """Get vector store metadata and statistics."""
    pass
```

#### 1.2 Create Unified Router-Aware Config
**File:** `ipfs_datasets_py/vector_stores/config.py`

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any
from ..ml.embeddings.schema import VectorStoreConfig

@dataclass
class UnifiedVectorStoreConfig(VectorStoreConfig):
    """Enhanced config with router integration."""
    
    # Router settings
    use_embeddings_router: bool = True
    use_ipfs_router: bool = True
    embeddings_router_provider: Optional[str] = None
    ipfs_router_backend: Optional[str] = None
    
    # IPLD settings
    enable_ipld_export: bool = True
    auto_pin_to_ipfs: bool = False
    car_export_dir: Optional[str] = None
    
    # Cross-store settings
    enable_multi_store_sync: bool = False
    sync_stores: Optional[List[str]] = None
```

#### 1.3 Consolidate Schema Definitions
**File:** `ipfs_datasets_py/vector_stores/schema.py`

- Import and re-export from `ml/embeddings/schema.py`
- Add IPLD-specific extensions
- Ensure backward compatibility

### Phase 2: IPLD Vector Store Implementation (8-10 hours)

**Goal:** Create production-ready IPLD-native vector store.

#### 2.1 Refactor IPLDVectorStore
**File:** `ipfs_datasets_py/vector_stores/ipld_vector_store.py`

Merge best features from:
- `vector_stores/ipld.py`
- `processors/storage/ipld/vector_store.py`

Key improvements:
- Full `BaseVectorStore` interface implementation
- Async/await support using `anyio`
- Collection management (create, delete, exists)
- Router integration (embeddings_router, ipfs_backend_router)
- Batch operations
- CAR file import/export
- Comprehensive error handling
- Performance metrics

Architecture:
```
IPLDVectorStore
├── Storage Layer (IPLDStorage)
│   ├── Block storage (CID-addressed)
│   ├── Metadata storage
│   └── Link management
├── Index Layer (FAISS)
│   ├── Vector indexing
│   ├── Similarity search
│   └── Distance metrics
├── Router Integration
│   ├── Embeddings generation (embeddings_router)
│   └── IPFS storage (ipfs_backend_router)
└── Serialization
    ├── CAR export/import
    ├── JSON metadata
    └── Binary vectors
```

#### 2.2 Implement Router Integration
**File:** `ipfs_datasets_py/vector_stores/router_integration.py`

```python
class RouterIntegration:
    """Helper class for router integration."""
    
    def __init__(self, config: UnifiedVectorStoreConfig):
        self.config = config
        self.embeddings_router = None
        self.ipfs_router = None
        
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using embeddings_router."""
        if not self.config.use_embeddings_router:
            raise ValueError("Embeddings router not enabled")
        
        from ..embeddings_router import generate_embeddings
        return await generate_embeddings(
            texts=texts,
            provider=self.config.embeddings_router_provider
        )
    
    async def store_to_ipfs(self, data: bytes) -> str:
        """Store data to IPFS using ipfs_backend_router."""
        if not self.config.use_ipfs_router:
            raise ValueError("IPFS router not enabled")
            
        from ..ipfs_backend_router import ipfs_add
        return await ipfs_add(data, pin=self.config.auto_pin_to_ipfs)
```

#### 2.3 Add Deprecation Notices
**File:** `ipfs_datasets_py/vector_stores/ipld.py`

Add deprecation warning pointing to new `ipld_vector_store.py`

**File:** `ipfs_datasets_py/processors/storage/ipld/vector_store.py`

Add deprecation warning pointing to `vector_stores/ipld_vector_store.py`

### Phase 3: Cross-Store Bridge Implementation (6-8 hours)

**Goal:** Enable data migration between all vector stores.

#### 3.1 Create Bridge Interface
**File:** `ipfs_datasets_py/vector_stores/bridges/base_bridge.py`

```python
from abc import ABC, abstractmethod
from typing import List, Optional, AsyncIterator
from ..base import BaseVectorStore
from ...ml.embeddings.schema import EmbeddingResult

class VectorStoreBridge(ABC):
    """Base class for vector store bridges."""
    
    def __init__(self, source_store: BaseVectorStore, target_store: BaseVectorStore):
        self.source_store = source_store
        self.target_store = target_store
    
    @abstractmethod
    async def export_collection(
        self, 
        collection_name: str,
        batch_size: int = 1000
    ) -> AsyncIterator[List[EmbeddingResult]]:
        """Stream embeddings from source store."""
        pass
    
    @abstractmethod
    async def import_collection(
        self,
        embeddings: AsyncIterator[List[EmbeddingResult]],
        collection_name: str,
        batch_size: int = 1000
    ) -> int:
        """Import embeddings to target store."""
        pass
    
    async def migrate_collection(
        self,
        collection_name: str,
        target_collection_name: Optional[str] = None,
        batch_size: int = 1000
    ) -> int:
        """Full collection migration."""
        target_name = target_collection_name or collection_name
        
        # Create target collection
        await self.target_store.create_collection(
            collection_name=target_name,
            dimension=self.source_store.dimension
        )
        
        # Stream and import
        count = 0
        async for batch in self.export_collection(collection_name, batch_size):
            await self.target_store.add_embeddings(batch, target_name)
            count += len(batch)
        
        return count
```

#### 3.2 Implement Specific Bridges

**File:** `ipfs_datasets_py/vector_stores/bridges/faiss_bridge.py`
- FAISS ↔ IPLD
- FAISS ↔ Qdrant
- FAISS ↔ Elasticsearch

**File:** `ipfs_datasets_py/vector_stores/bridges/qdrant_bridge.py`
- Qdrant ↔ IPLD
- Qdrant ↔ FAISS

**File:** `ipfs_datasets_py/vector_stores/bridges/elasticsearch_bridge.py`
- Elasticsearch ↔ IPLD

**File:** `ipfs_datasets_py/vector_stores/bridges/ipld_bridge.py`
- IPLD ↔ All stores
- CAR file export/import
- CID-based sharing

#### 3.3 Create Bridge Factory
**File:** `ipfs_datasets_py/vector_stores/bridges/__init__.py`

```python
def create_bridge(
    source_type: VectorStoreType,
    target_type: VectorStoreType,
    source_store: BaseVectorStore,
    target_store: BaseVectorStore
) -> VectorStoreBridge:
    """Factory for creating appropriate bridge."""
    bridge_map = {
        (VectorStoreType.FAISS, VectorStoreType.IPLD): FAISSToIPLDBridge,
        (VectorStoreType.IPLD, VectorStoreType.FAISS): IPLDToFAISSBridge,
        # ... more mappings
    }
    
    bridge_class = bridge_map.get((source_type, target_type))
    if not bridge_class:
        raise ValueError(f"No bridge for {source_type} -> {target_type}")
    
    return bridge_class(source_store, target_store)
```

### Phase 4: Unified Interface Layer (4-6 hours)

**Goal:** Single entry point for all vector operations.

#### 4.1 Create VectorStoreManager
**File:** `ipfs_datasets_py/vector_stores/manager.py`

```python
class VectorStoreManager:
    """Unified manager for all vector stores."""
    
    def __init__(self, config: UnifiedVectorStoreConfig):
        self.config = config
        self.stores: Dict[str, BaseVectorStore] = {}
        self.bridges: Dict[Tuple[str, str], VectorStoreBridge] = {}
        
    async def get_store(self, store_type: VectorStoreType) -> BaseVectorStore:
        """Get or create vector store instance."""
        if store_type not in self.stores:
            self.stores[store_type] = self._create_store(store_type)
        return self.stores[store_type]
    
    async def migrate(
        self,
        source_type: VectorStoreType,
        target_type: VectorStoreType,
        collection_name: str
    ) -> int:
        """Migrate collection between stores."""
        source = await self.get_store(source_type)
        target = await self.get_store(target_type)
        bridge = create_bridge(source_type, target_type, source, target)
        return await bridge.migrate_collection(collection_name)
    
    async def search_all(
        self,
        query_vector: List[float],
        stores: List[VectorStoreType],
        top_k: int = 10
    ) -> Dict[VectorStoreType, List[SearchResult]]:
        """Search across multiple stores."""
        results = {}
        for store_type in stores:
            store = await self.get_store(store_type)
            results[store_type] = await store.search(query_vector, top_k)
        return results
```

#### 4.2 Create High-Level API
**File:** `ipfs_datasets_py/vector_stores/api.py`

```python
# Simple API for common operations

async def create_ipld_vector_store(
    collection_name: str,
    dimension: int = 768,
    metric: str = "cosine",
    use_embeddings_router: bool = True,
    use_ipfs_router: bool = True
) -> IPLDVectorStore:
    """Create IPLD vector store with defaults."""
    config = UnifiedVectorStoreConfig(
        collection_name=collection_name,
        dimension=dimension,
        distance_metric=metric,
        use_embeddings_router=use_embeddings_router,
        use_ipfs_router=use_ipfs_router
    )
    return IPLDVectorStore(config)

async def migrate_store(
    source_store: BaseVectorStore,
    target_store: BaseVectorStore,
    collection_name: str
) -> int:
    """Migrate collection between stores."""
    # Detect store types and use appropriate bridge
    pass
```

### Phase 5: Router Integration Enhancement (4-5 hours)

**Goal:** Seamless integration with embeddings_router and ipfs_backend_router.

#### 5.1 Enhance Embeddings Router Integration
**File:** Modify `ipfs_datasets_py/embeddings_router.py`

Add vector store awareness:
```python
async def generate_and_store_embeddings(
    texts: List[str],
    vector_store: Optional[BaseVectorStore] = None,
    collection_name: Optional[str] = None,
    provider: Optional[str] = None
) -> List[str]:
    """Generate embeddings and store in vector store."""
    embeddings = await generate_embeddings(texts, provider)
    
    if vector_store:
        embedding_results = [
            EmbeddingResult(text=text, vector=vector, metadata={})
            for text, vector in zip(texts, embeddings)
        ]
        return await vector_store.add_embeddings(embedding_results, collection_name)
    
    return embeddings
```

#### 5.2 Enhance IPFS Router Integration
**File:** Modify `ipfs_datasets_py/ipfs_backend_router.py`

Add vector store helpers:
```python
async def store_vector_collection_to_ipfs(
    collection_data: Dict[str, Any],
    pin: bool = True
) -> str:
    """Store entire vector collection to IPFS."""
    # Serialize collection
    # Store to IPFS
    # Return root CID
    pass

async def load_vector_collection_from_ipfs(
    root_cid: str
) -> Dict[str, Any]:
    """Load vector collection from IPFS."""
    # Fetch from IPFS
    # Deserialize
    # Return collection data
    pass
```

#### 5.3 Create Router Factory
**File:** `ipfs_datasets_py/vector_stores/router_factory.py`

```python
def create_router_aware_store(
    store_type: VectorStoreType,
    config: UnifiedVectorStoreConfig
) -> BaseVectorStore:
    """Create vector store with router integration."""
    # Initialize store
    # Inject routers if enabled
    # Configure auto-export to IPFS
    # Return configured store
    pass
```

### Phase 6: Testing & Validation (6-8 hours)

**Goal:** Comprehensive test coverage for all components.

#### 6.1 Unit Tests

**File:** `tests/unit/vector_stores/test_ipld_vector_store.py`
- Collection management
- Vector operations (add, search, delete, update)
- Router integration
- Error handling

**File:** `tests/unit/vector_stores/test_bridges.py`
- Each bridge implementation
- Data integrity during migration
- Error scenarios

**File:** `tests/unit/vector_stores/test_manager.py`
- Manager operations
- Multi-store coordination
- Configuration handling

#### 6.2 Integration Tests

**File:** `tests/integration/vector_stores/test_ipld_integration.py`
- End-to-end IPLD storage and retrieval
- CAR file import/export
- Real IPFS operations

**File:** `tests/integration/vector_stores/test_cross_store_migration.py`
- FAISS → IPLD migration
- Qdrant → IPLD migration
- Round-trip migrations
- Data integrity verification

**File:** `tests/integration/vector_stores/test_router_integration.py`
- embeddings_router integration
- ipfs_backend_router integration
- Auto-storage workflows

#### 6.3 Performance Tests

**File:** `tests/performance/vector_stores/test_ipld_performance.py`
- Large-scale vector operations
- Search performance benchmarks
- Memory usage profiling
- Comparison with other stores

### Phase 7: Documentation (4-5 hours)

**Goal:** Comprehensive documentation for users and developers.

#### 7.1 User Documentation

**File:** `docs/vector_stores/IPLD_VECTOR_STORE_GUIDE.md`
- Quick start guide
- Configuration options
- Common use cases
- Best practices

**File:** `docs/vector_stores/CROSS_STORE_MIGRATION_GUIDE.md`
- Migration scenarios
- Bridge usage
- Data format considerations
- Troubleshooting

**File:** `docs/vector_stores/ROUTER_INTEGRATION_GUIDE.md`
- Embeddings router setup
- IPFS router configuration
- Auto-storage workflows

#### 7.2 API Documentation

**File:** `docs/api/vector_stores.md`
- Full API reference
- Method signatures
- Examples
- Error codes

#### 7.3 Examples

**File:** `examples/vector_stores/ipld_basic_usage.py`
**File:** `examples/vector_stores/cross_store_migration.py`
**File:** `examples/vector_stores/router_integration.py`
**File:** `examples/vector_stores/car_file_exchange.py`

### Phase 8: Update Existing Code (3-4 hours)

**Goal:** Update existing implementations to use new unified interface.

#### 8.1 Update Vector Store __init__.py
**File:** `ipfs_datasets_py/vector_stores/__init__.py`

```python
from .base import BaseVectorStore
from .ipld_vector_store import IPLDVectorStore
from .faiss_store import FAISSVectorStore
from .qdrant_store import QdrantVectorStore
from .elasticsearch_store import ElasticsearchVectorStore
from .manager import VectorStoreManager
from .api import create_ipld_vector_store, migrate_store
from .bridges import create_bridge
from .config import UnifiedVectorStoreConfig

__all__ = [
    'BaseVectorStore',
    'IPLDVectorStore',
    'FAISSVectorStore',
    'QdrantVectorStore',
    'ElasticsearchVectorStore',
    'VectorStoreManager',
    'create_ipld_vector_store',
    'migrate_store',
    'create_bridge',
    'UnifiedVectorStoreConfig',
]
```

#### 8.2 Add Deprecation Warnings

Add to old implementations:
- `vector_stores/ipld.py`
- `processors/storage/ipld/vector_store.py`
- `knowledge_graphs/ipld.py` (vector parts)

## Implementation Timeline

### Week 1 (20-25 hours)
- **Days 1-2:** Phase 1 - Unified Interface & Schema (6h)
- **Days 3-5:** Phase 2 - IPLD Vector Store (10h)
- **Day 5:** Phase 3 start - Bridge Interface (4h)

### Week 2 (20-25 hours)
- **Days 1-2:** Phase 3 complete - Bridge Implementations (6h)
- **Days 3-4:** Phase 4 - Unified Interface Layer (6h)
- **Day 5:** Phase 5 - Router Integration (5h)

### Week 3 (15-20 hours)
- **Days 1-3:** Phase 6 - Testing & Validation (8h)
- **Days 4-5:** Phase 7 - Documentation (5h)
- **Day 5:** Phase 8 - Update Existing Code (4h)

**Total Estimated Time:** 55-70 hours (7-9 working days)

## Success Criteria

### Functional Requirements
- ✅ IPLD vector store fully implements BaseVectorStore interface
- ✅ All async operations work correctly
- ✅ Router integration (embeddings_router, ipfs_backend_router) functional
- ✅ Bridges enable migration between all store types
- ✅ CAR file import/export works reliably
- ✅ Performance matches or exceeds existing implementations

### Quality Requirements
- ✅ 90%+ test coverage on new code
- ✅ All integration tests passing
- ✅ No breaking changes to existing APIs
- ✅ Comprehensive documentation
- ✅ Type hints on all public APIs
- ✅ Follows existing code style and patterns

### Performance Requirements
- ✅ Search latency < 50ms for 10K vectors
- ✅ Storage overhead < 20% vs native stores
- ✅ Migration throughput > 1000 vectors/second
- ✅ Memory usage scales linearly with vector count

## Reusable IPLD Implementations

### From ipfs_datasets_py
1. **IPLDStorage** (`processors/storage/ipld/storage.py`)
   - Reuse: Core storage layer, block management, CAR export
   
2. **OptimizedCodec** (`processors/storage/ipld/optimized_codec.py`)
   - Reuse: Efficient serialization, batch processing

3. **dag_pb.py** (`processors/storage/ipld/dag_pb.py`)
   - Reuse: DAG-PB format support

### External Libraries
1. **ipld-car** (pip package)
   - CAR file reading/writing
   - CID manipulation

2. **multiformats** (pip package)
   - CID encoding/decoding
   - Multicodec support

3. **py-ipfs-http-client** (pip package)
   - IPFS HTTP API client
   - Alternative to CLI

## Dependencies

### Required
- `numpy` - Vector operations
- `anyio` - Async support
- `faiss-cpu` or `faiss-gpu` - Vector indexing
- Existing routers and schemas

### Optional
- `ipld-car` - CAR file support
- `multiformats` - CID operations
- `py-ipfs-http-client` - IPFS API client
- `qdrant-client` - Qdrant operations
- `elasticsearch` - Elasticsearch operations

## Risk Mitigation

### Risk 1: Breaking Changes
**Mitigation:** 
- Maintain backward compatibility
- Use deprecation warnings
- Provide migration guides

### Risk 2: Performance Degradation
**Mitigation:**
- Benchmark early and often
- Profile memory usage
- Optimize hot paths
- Use caching strategically

### Risk 3: Complex Dependencies
**Mitigation:**
- Make IPLD features optional
- Graceful fallbacks
- Clear error messages
- Auto-installation where possible

### Risk 4: Router Conflicts
**Mitigation:**
- Clear documentation of router behavior
- Environment variable overrides
- Explicit configuration options
- Testing with router variations

## Future Enhancements

### Phase 9 (Future)
- Multi-node IPLD cluster support
- Advanced indexing strategies (HNSW, IVF)
- GPU acceleration for IPLD stores
- Streaming search results
- Incremental updates to IPFS
- Distributed search coordination
- Integration with IPFS pubsub for real-time sync

### Phase 10 (Future)
- Web UI for vector store management
- GraphQL API for queries
- WebAssembly vector search
- Mobile SDK support

## Appendix

### A. File Structure
```
ipfs_datasets_py/vector_stores/
├── __init__.py                  # Public API
├── base.py                      # Enhanced base interface
├── schema.py                    # Consolidated schemas
├── config.py                    # Unified configuration
├── manager.py                   # Vector store manager
├── api.py                       # High-level API
├── router_integration.py        # Router helpers
├── router_factory.py            # Router-aware factory
├── ipld_vector_store.py         # Main IPLD implementation
├── faiss_store.py              # Updated FAISS store
├── qdrant_store.py             # Updated Qdrant store
├── elasticsearch_store.py       # Updated Elasticsearch store
├── ipld.py                      # DEPRECATED - use ipld_vector_store.py
└── bridges/
    ├── __init__.py
    ├── base_bridge.py
    ├── faiss_bridge.py
    ├── qdrant_bridge.py
    ├── elasticsearch_bridge.py
    └── ipld_bridge.py
```

### B. Example Usage

```python
# Create IPLD vector store with router integration
from ipfs_datasets_py.vector_stores import create_ipld_vector_store

store = await create_ipld_vector_store(
    collection_name="documents",
    dimension=768,
    use_embeddings_router=True,
    use_ipfs_router=True
)

# Add vectors (embeddings generated automatically)
texts = ["Hello world", "IPFS is great"]
ids = await store.add_texts(texts, collection_name="documents")

# Search
results = await store.search_by_text(
    "greeting message",
    top_k=5,
    collection_name="documents"
)

# Export to IPFS
root_cid = await store.export_to_ipld("documents")
print(f"Collection stored at: ipfs://{root_cid}")

# Migrate to Qdrant
from ipfs_datasets_py.vector_stores import QdrantVectorStore, migrate_store

qdrant = QdrantVectorStore(config)
count = await migrate_store(store, qdrant, "documents")
print(f"Migrated {count} vectors")
```

### C. References

- [IPLD Specification](https://ipld.io/)
- [FAISS Documentation](https://github.com/facebookresearch/faiss/wiki)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [CAR Format Specification](https://ipld.io/specs/transport/car/)
- [Embeddings Router Code](../ipfs_datasets_py/embeddings_router.py)
- [IPFS Backend Router Code](../ipfs_datasets_py/ipfs_backend_router.py)

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Author:** GitHub Copilot Agent  
**Status:** Ready for Implementation
