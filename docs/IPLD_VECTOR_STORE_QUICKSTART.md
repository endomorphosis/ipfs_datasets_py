# IPLD Vector Store - Quick Start Guide

**Date:** 2026-02-16  
**Status:** Implementation Guide

## Overview

This guide provides a quick reference for implementing the IPLD/IPFS vector search engine as outlined in [IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md](./IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md).

## Quick Implementation Checklist

### ✅ Prerequisites Check
- [ ] Review existing implementations:
  - `vector_stores/base.py` - Interface contract
  - `vector_stores/faiss_store.py` - Reference implementation
  - `processors/storage/ipld/storage.py` - IPLD operations
  - `embeddings_router.py` - Embedding generation
  - `ipfs_backend_router.py` - IPFS operations

### 🎯 Phase 1: Foundation (Day 1)
- [ ] Create `vector_stores/config.py`
  - `UnifiedVectorStoreConfig` dataclass
  - Router integration flags
  - IPLD-specific settings
  
- [ ] Update `vector_stores/base.py`
  - Add `export_to_ipld()` method
  - Add `import_from_ipld()` method
  - Add `export_to_car()` method
  - Add `import_from_car()` method
  - Add `get_store_info()` method

- [ ] Create `vector_stores/schema.py`
  - Import from `ml/embeddings/schema.py`
  - Add IPLD extensions
  - Maintain backward compatibility

### 🚀 Phase 2: Core Implementation (Days 2-3)
- [ ] Create `vector_stores/ipld_vector_store.py`
  - Class: `IPLDVectorStore(BaseVectorStore)`
  - Implement all abstract methods
  - Add router integration
  - Add FAISS backend for indexing
  - Add CAR import/export
  
- [ ] Create `vector_stores/router_integration.py`
  - Class: `RouterIntegration`
  - Method: `get_embeddings()` using embeddings_router
  - Method: `store_to_ipfs()` using ipfs_backend_router
  - Method: `load_from_ipfs()` for retrieval

### 🌉 Phase 3: Bridges (Days 4-5)
- [ ] Create `vector_stores/bridges/base_bridge.py`
  - Class: `VectorStoreBridge` (ABC)
  - Method: `export_collection()`
  - Method: `import_collection()`
  - Method: `migrate_collection()`

- [ ] Create store-specific bridges:
  - [ ] `bridges/faiss_bridge.py`
  - [ ] `bridges/qdrant_bridge.py`
  - [ ] `bridges/elasticsearch_bridge.py`
  - [ ] `bridges/ipld_bridge.py`

- [ ] Create `vector_stores/bridges/__init__.py`
  - Function: `create_bridge()` factory

### 🎛️ Phase 4: Management Layer (Day 6)
- [ ] Create `vector_stores/manager.py`
  - Class: `VectorStoreManager`
  - Method: `get_store()` - Lazy initialization
  - Method: `migrate()` - Cross-store migration
  - Method: `search_all()` - Multi-store search

- [ ] Create `vector_stores/api.py`
  - Function: `create_ipld_vector_store()`
  - Function: `migrate_store()`
  - Function: `search_unified()`

### 🧪 Phase 5: Testing (Days 7-8)
- [ ] Unit tests:
  - [ ] `tests/unit/vector_stores/test_ipld_vector_store.py`
  - [ ] `tests/unit/vector_stores/test_bridges.py`
  - [ ] `tests/unit/vector_stores/test_manager.py`
  - [ ] `tests/unit/vector_stores/test_router_integration.py`

- [ ] Integration tests:
  - [ ] `tests/integration/vector_stores/test_ipld_integration.py`
  - [ ] `tests/integration/vector_stores/test_cross_store_migration.py`
  - [ ] `tests/integration/vector_stores/test_router_integration.py`

### 📚 Phase 6: Documentation (Day 9)
- [ ] User guides:
  - [ ] `docs/vector_stores/IPLD_VECTOR_STORE_GUIDE.md`
  - [ ] `docs/vector_stores/CROSS_STORE_MIGRATION_GUIDE.md`
  - [ ] `docs/vector_stores/ROUTER_INTEGRATION_GUIDE.md`

- [ ] Examples:
  - [ ] `examples/vector_stores/ipld_basic_usage.py`
  - [ ] `examples/vector_stores/cross_store_migration.py`
  - [ ] `examples/vector_stores/router_integration.py`

## Key Design Decisions

### 1. Router Integration Pattern
```python
# Config-driven router usage
config = UnifiedVectorStoreConfig(
    use_embeddings_router=True,
    use_ipfs_router=True
)

# Automatic routing in store methods
store = IPLDVectorStore(config)
await store.add_texts(texts)  # Uses embeddings_router internally
```

### 2. Bridge Pattern for Migration
```python
# Factory creates appropriate bridge
bridge = create_bridge(
    source_type=VectorStoreType.FAISS,
    target_type=VectorStoreType.IPLD,
    source_store=faiss_store,
    target_store=ipld_store
)

# Simple migration API
count = await bridge.migrate_collection("my_collection")
```

### 3. IPLD Storage Architecture
```
Collection Root (CID)
├── Metadata Block
│   ├── dimension: int
│   ├── metric: str
│   ├── count: int
│   └── created: timestamp
├── Vectors Block (or chunked)
│   └── CIDs to vector data blocks
├── Index Block (FAISS)
│   └── Serialized FAISS index
└── Metadata Mappings
    └── vector_id -> metadata CID
```

### 4. Async/Await Throughout
```python
# All methods are async
async def add_embeddings(
    self, 
    embeddings: List[EmbeddingResult],
    collection_name: Optional[str] = None
) -> List[str]:
    """Async method implementation."""
    # Use anyio for cross-platform async
    async with anyio.create_task_group() as tg:
        # Parallel operations
        pass
```

## Implementation Tips

### Tip 1: Reuse Existing Code
```python
# Leverage existing IPLD infrastructure
from ipfs_datasets_py.processors.storage.ipld import (
    IPLDStorage,
    OptimizedEncoder,
    create_dag_node
)

# Use existing routers
from ipfs_datasets_py import embeddings_router, ipfs_backend_router
```

### Tip 2: Graceful Fallbacks
```python
# Handle optional dependencies gracefully
try:
    import faiss
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False
    # Use numpy-based fallback

if not HAVE_FAISS:
    logger.warning("FAISS not available, using slower numpy search")
```

### Tip 3: Maintain Backward Compatibility
```python
# Deprecation pattern
import warnings

# In old ipld.py
warnings.warn(
    "ipfs_datasets_py.vector_stores.ipld is deprecated. "
    "Use ipfs_datasets_py.vector_stores.ipld_vector_store instead.",
    DeprecationWarning,
    stacklevel=2
)

# Keep old imports working
from .ipld_vector_store import IPLDVectorStore as _IPLDVectorStore
IPLDVectorStore = _IPLDVectorStore
```

### Tip 4: Comprehensive Error Handling
```python
class VectorStoreError(Exception):
    """Base exception for vector store errors."""
    pass

class VectorStoreConnectionError(VectorStoreError):
    """Connection-related errors."""
    pass

class VectorStoreOperationError(VectorStoreError):
    """Operation-related errors."""
    pass

# Use in implementation
try:
    result = await self._perform_operation()
except Exception as e:
    logger.error(f"Operation failed: {e}")
    raise VectorStoreOperationError(f"Failed to perform operation: {e}")
```

### Tip 5: Router Configuration
```python
# Check routers are available
from ipfs_datasets_py.router_deps import get_default_router_deps

deps = get_default_router_deps()
if self.config.use_embeddings_router:
    self.embeddings_manager = deps.get_embeddings_manager()
if self.config.use_ipfs_router:
    self.ipfs_backend = deps.get_ipfs_backend()
```

## Common Patterns

### Pattern 1: Collection Management
```python
async def create_collection(
    self, 
    collection_name: Optional[str] = None,
    dimension: Optional[int] = None, 
    **kwargs
) -> bool:
    """Create new collection with metadata."""
    name = collection_name or self.collection_name
    dim = dimension or self.dimension
    
    # Create metadata block
    metadata = {
        "name": name,
        "dimension": dim,
        "metric": self.distance_metric,
        "created": datetime.utcnow().isoformat(),
        "type": "vector_collection"
    }
    
    # Store metadata to IPLD
    metadata_cid = await self._store_metadata(metadata)
    
    # Initialize empty index
    index = self._create_index(dim)
    
    # Store collection info
    self.collections[name] = {
        "metadata_cid": metadata_cid,
        "index": index,
        "count": 0
    }
    
    return True
```

### Pattern 2: Vector Addition with Router
```python
async def add_embeddings(
    self,
    embeddings: List[EmbeddingResult],
    collection_name: Optional[str] = None
) -> List[str]:
    """Add embeddings to collection."""
    name = collection_name or self.collection_name
    
    # Batch process
    cids = []
    vectors = []
    metadata_list = []
    
    for emb in embeddings:
        # Store vector data to IPLD
        vector_data = {
            "vector": emb.vector.tolist(),
            "text": emb.text,
            "metadata": emb.metadata
        }
        cid = await self._store_vector_data(vector_data)
        cids.append(cid)
        vectors.append(emb.vector)
        metadata_list.append(emb.metadata)
    
    # Update FAISS index
    vectors_np = np.array(vectors, dtype=np.float32)
    self._index.add(vectors_np)
    
    # Update collection metadata
    await self._update_collection_root(name, cids, metadata_list)
    
    return cids
```

### Pattern 3: CAR Export
```python
async def export_to_car(
    self,
    output_path: str,
    collection_name: Optional[str] = None
) -> bool:
    """Export collection to CAR file."""
    name = collection_name or self.collection_name
    collection = self.collections.get(name)
    
    if not collection:
        raise VectorStoreError(f"Collection {name} not found")
    
    # Get all CIDs in collection
    root_cid = collection["root_cid"]
    all_cids = await self._collect_all_cids(root_cid)
    
    # Export to CAR using IPLD storage
    await self.storage.export_to_car(
        root_cid=root_cid,
        output_path=output_path,
        include_cids=all_cids
    )
    
    return True
```

### Pattern 4: Bridge Migration
```python
async def migrate_collection(
    self,
    collection_name: str,
    target_collection_name: Optional[str] = None,
    batch_size: int = 1000
) -> int:
    """Migrate collection from source to target."""
    target_name = target_collection_name or collection_name
    
    # Get source metadata
    metadata = await self.source_store.get_store_info()
    
    # Create target collection
    await self.target_store.create_collection(
        collection_name=target_name,
        dimension=metadata["dimension"],
        distance_metric=metadata["metric"]
    )
    
    # Stream and migrate
    total = 0
    async for batch in self.export_collection(collection_name, batch_size):
        await self.target_store.add_embeddings(batch, target_name)
        total += len(batch)
        logger.info(f"Migrated {total} vectors so far...")
    
    logger.info(f"Migration complete: {total} vectors")
    return total
```

## Testing Strategy

### Unit Test Template
```python
import pytest
import numpy as np
from ipfs_datasets_py.vector_stores import IPLDVectorStore
from ipfs_datasets_py.ml.embeddings.schema import EmbeddingResult

@pytest.mark.asyncio
async def test_ipld_vector_store_add_and_search():
    """Test basic add and search operations."""
    # GIVEN
    store = IPLDVectorStore(
        config=UnifiedVectorStoreConfig(
            collection_name="test",
            dimension=128,
            use_embeddings_router=False,  # Don't use router in tests
            use_ipfs_router=False
        )
    )
    
    await store.create_collection()
    
    # Create test embeddings
    embeddings = [
        EmbeddingResult(
            text=f"Document {i}",
            vector=np.random.rand(128).tolist(),
            metadata={"index": i}
        )
        for i in range(10)
    ]
    
    # WHEN
    ids = await store.add_embeddings(embeddings)
    
    # Search
    query_vector = np.random.rand(128).tolist()
    results = await store.search(query_vector, top_k=5)
    
    # THEN
    assert len(ids) == 10
    assert len(results) == 5
    assert all(r.score >= 0 for r in results)
```

### Integration Test Template
```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_faiss_to_ipld_migration():
    """Test migration from FAISS to IPLD."""
    # GIVEN - FAISS store with data
    faiss_store = FAISSVectorStore(config=faiss_config)
    await faiss_store.create_collection("test")
    
    embeddings = create_test_embeddings(100)
    await faiss_store.add_embeddings(embeddings)
    
    # Create IPLD store
    ipld_store = IPLDVectorStore(config=ipld_config)
    
    # WHEN - Migrate
    bridge = create_bridge(
        VectorStoreType.FAISS,
        VectorStoreType.IPLD,
        faiss_store,
        ipld_store
    )
    count = await bridge.migrate_collection("test")
    
    # THEN - Verify migration
    assert count == 100
    
    # Verify search works in IPLD
    query = embeddings[0].vector
    results = await ipld_store.search(query, top_k=5)
    assert len(results) == 5
    assert results[0].id == embeddings[0].id  # Exact match first
```

## Performance Considerations

### 1. Batch Operations
```python
# Process in batches to manage memory
async def add_embeddings_batch(
    self,
    embeddings: List[EmbeddingResult],
    batch_size: int = 1000
) -> List[str]:
    """Add embeddings in batches."""
    all_ids = []
    for i in range(0, len(embeddings), batch_size):
        batch = embeddings[i:i + batch_size]
        ids = await self.add_embeddings(batch)
        all_ids.extend(ids)
    return all_ids
```

### 2. Parallel IPLD Operations
```python
# Use anyio task groups for parallel operations
import anyio

async def _store_vectors_parallel(
    self,
    vectors: List[Dict[str, Any]]
) -> List[str]:
    """Store vectors in parallel."""
    cids = []
    
    async def store_one(vector_data):
        return await self._store_vector_data(vector_data)
    
    async with anyio.create_task_group() as tg:
        for vector in vectors:
            cids.append(await tg.start_soon(store_one, vector))
    
    return cids
```

### 3. Index Optimization
```python
# Use appropriate FAISS index type
def _create_optimized_index(self, dimension: int, count_estimate: int):
    """Create optimized index based on expected size."""
    if count_estimate < 10000:
        # Small collection - flat index
        return faiss.IndexFlatIP(dimension)
    elif count_estimate < 1000000:
        # Medium - IVF index
        quantizer = faiss.IndexFlatIP(dimension)
        return faiss.IndexIVFFlat(quantizer, dimension, 100)
    else:
        # Large - HNSW index
        return faiss.IndexHNSWFlat(dimension, 32)
```

## Next Steps

After implementing this plan:

1. **Test thoroughly** - Run all unit and integration tests
2. **Benchmark performance** - Compare with existing implementations
3. **Document edge cases** - Note any limitations or gotchas
4. **Gather feedback** - Share with team for review
5. **Iterate** - Refine based on feedback and testing

## Support

For questions or issues during implementation:
- Review the [main improvement plan](./IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md)
- Check existing implementations in `vector_stores/`
- Refer to router documentation in `embeddings_router.py` and `ipfs_backend_router.py`
- Consult IPLD storage code in `processors/storage/ipld/`

---

**Version:** 1.0  
**Last Updated:** 2026-02-16  
**Ready for:** Implementation
