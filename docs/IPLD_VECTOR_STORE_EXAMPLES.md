# IPLD/IPFS Vector Store - Usage Examples

Comprehensive examples for using the IPLD/IPFS vector search engine.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Configuration](#configuration)
3. [Basic Operations](#basic-operations)
4. [Router Integration](#router-integration)
5. [IPLD Export/Import](#ipld-exportimport)
6. [Cross-Store Migration](#cross-store-migration)
7. [Multi-Store Management](#multi-store-management)
8. [Advanced Usage](#advanced-usage)

## Quick Start

### Create an IPLD Vector Store

```python
import asyncio
from ipfs_datasets_py.vector_stores import create_vector_store, add_texts_to_store, search_texts

async def quick_start():
    # Create IPLD store with router integration
    store = await create_vector_store(
        "ipld",
        "documents",
        dimension=768,
        use_embeddings_router=True,  # Auto-generate embeddings
        use_ipfs_router=True,        # Store to IPFS
        auto_pin_to_ipfs=False
    )
    
    # Create collection
    await store.create_collection()
    
    # Add texts (embeddings auto-generated)
    texts = [
        "IPFS is a distributed file system",
        "IPLD provides data structures for IPFS",
        "Content addressing enables decentralization"
    ]
    
    ids = await add_texts_to_store(store, texts)
    print(f"Added {len(ids)} documents")
    
    # Search by text (query embedding auto-generated)
    results = await search_texts(store, "What is IPFS?", top_k=3)
    
    for i, result in enumerate(results):
        print(f"{i+1}. Score: {result.score:.3f}")
        print(f"   Text: {result.content}")
    
    # Export to IPFS
    cid = await store.export_to_ipld()
    print(f"Collection available at: ipfs://{cid}")

# Run
asyncio.run(quick_start())
```

## Configuration

### IPLD Configuration

```python
from ipfs_datasets_py.vector_stores import create_ipld_config

# Basic configuration
config = create_ipld_config(
    collection_name="documents",
    dimension=768,
    distance_metric="cosine"
)

# Full configuration with all options
config = create_ipld_config(
    collection_name="documents",
    dimension=768,
    distance_metric="cosine",
    # Router integration
    use_embeddings_router=True,
    use_ipfs_router=True,
    embeddings_router_provider="openrouter",  # or "gemini", "hf"
    ipfs_router_backend="kubo",               # or "accelerate", "kit"
    # IPLD settings
    enable_ipld_export=True,
    auto_pin_to_ipfs=False,
    car_export_dir="/path/to/exports",
    ipld_chunk_size=1000,
    ipld_compression=True,
    max_block_size=1048576,
    # Performance
    batch_size=1000,
    parallel_workers=4,
    cache_size=10000,
    prefetch_enabled=True
)
```

### FAISS Configuration

```python
from ipfs_datasets_py.vector_stores import create_faiss_config

config = create_faiss_config(
    collection_name="documents",
    dimension=768,
    distance_metric="cosine"
)
```

### Qdrant Configuration

```python
from ipfs_datasets_py.vector_stores import create_qdrant_config

config = create_qdrant_config(
    collection_name="documents",
    dimension=768,
    distance_metric="cosine",
    qdrant_url="http://localhost:6333"
)
```

## Basic Operations

### Create Store and Collection

```python
from ipfs_datasets_py.vector_stores import IPLDVectorStore, create_ipld_config

# Create store
config = create_ipld_config("docs", 768, use_ipfs_router=False)
store = IPLDVectorStore(config)

# Create collection
await store.create_collection("my_documents", dimension=768)

# Check if exists
exists = await store.collection_exists("my_documents")
print(f"Collection exists: {exists}")

# List all collections
collections = await store.list_collections()
print(f"Collections: {collections}")
```

### Add Embeddings

```python
from ipfs_datasets_py.vector_stores.schema import EmbeddingResult
import numpy as np

# With pre-computed embeddings
embeddings = [
    EmbeddingResult(
        chunk_id=f"doc_{i}",
        content=f"Document {i} text",
        embedding=np.random.rand(768).tolist(),
        metadata={"source": "example", "index": i}
    )
    for i in range(100)
]

ids = await store.add_embeddings(embeddings, "my_documents")
print(f"Added {len(ids)} embeddings")
```

### Search

```python
# Create query vector
query_vector = np.random.rand(768).tolist()

# Search
results = await store.search(
    query_vector,
    top_k=10,
    collection_name="my_documents",
    filter_dict={"source": "example"}  # Optional metadata filter
)

for result in results:
    print(f"ID: {result.chunk_id}, Score: {result.score}")
    print(f"Content: {result.content}")
    print(f"Metadata: {result.metadata}")
```

### Get and Delete by ID

```python
# Get by ID
embedding = await store.get_by_id("doc_5", "my_documents")
if embedding:
    print(f"Found: {embedding.content}")

# Delete by ID
success = await store.delete_by_id("doc_5", "my_documents")
print(f"Deleted: {success}")
```

## Router Integration

### Automatic Embedding Generation

```python
from ipfs_datasets_py.vector_stores import create_vector_store, EmbeddingResult

# Create store with embeddings router enabled
store = await create_vector_store(
    "ipld",
    "docs",
    dimension=768,
    use_embeddings_router=True,
    embeddings_router_provider="openrouter"  # or "gemini", "hf"
)

await store.create_collection()

# Add text without embeddings - will be auto-generated
embeddings = [
    EmbeddingResult(
        chunk_id=f"doc_{i}",
        content=f"This is document {i} about AI and machine learning",
        embedding=None,  # Router will generate this
        metadata={"topic": "AI"}
    )
    for i in range(10)
]

ids = await store.add_embeddings(embeddings)
```

### Automatic IPFS Storage

```python
# Create store with IPFS router enabled
store = await create_vector_store(
    "ipld",
    "docs",
    dimension=768,
    use_ipfs_router=True,
    ipfs_router_backend="kubo",
    auto_pin_to_ipfs=True  # Pin vectors to IPFS
)

await store.create_collection()

# Vectors are automatically stored to IPFS with CIDs
ids = await store.add_embeddings(embeddings)

# Get collection info to see CIDs
info = await store.get_collection_info()
print(f"Root CID: {info.get('root_cid')}")
```

## IPLD Export/Import

### Export Collection to IPLD

```python
from ipfs_datasets_py.vector_stores import export_collection_to_ipfs

# Export collection to IPFS/IPLD
root_cid = await export_collection_to_ipfs(store, "my_documents")
print(f"Collection exported to: ipfs://{root_cid}")

# Or directly via store
root_cid = await store.export_to_ipld("my_documents")
```

### Import Collection from IPLD

```python
from ipfs_datasets_py.vector_stores import import_collection_from_ipfs

# Import from CID
success = await import_collection_from_ipfs(
    store,
    root_cid="QmXXXXXXXXX",
    collection_name="imported_docs"
)

# Or directly via store
success = await store.import_from_ipld("QmXXXXXXXXX", "imported_docs")
```

### CAR File Export/Import

```python
# Export to CAR file
success = await store.export_to_car(
    "/path/to/collection.car",
    "my_documents"
)

# Import from CAR file
success = await store.import_from_car(
    "/path/to/collection.car",
    "restored_docs"
)
```

## Cross-Store Migration

### Migrate Between Stores

```python
from ipfs_datasets_py.vector_stores import migrate_collection

# Create source and target stores
faiss_store = await create_vector_store("faiss", "docs", dimension=768)
ipld_store = await create_vector_store("ipld", "docs", dimension=768)

# ... populate faiss_store ...

# Migrate from FAISS to IPLD
count = await migrate_collection(
    faiss_store,
    ipld_store,
    "documents",
    target_collection_name="documents_ipld",
    batch_size=1000,
    verify=True
)

print(f"Migrated {count} vectors")
```

### Using Bridges Directly

```python
from ipfs_datasets_py.vector_stores.bridges import create_bridge

# Create bridge
bridge = create_bridge(faiss_store, ipld_store)

# Migrate
count = await bridge.migrate_collection(
    "documents",
    target_collection_name="documents_ipld",
    batch_size=1000
)

# Verify migration
verification = await bridge.verify_migration(
    "documents",
    "documents_ipld"
)
print(f"Verification: {verification}")
```

## Multi-Store Management

### Create and Use Manager

```python
from ipfs_datasets_py.vector_stores import create_manager, create_ipld_config, create_faiss_config

# Create manager
manager = create_manager()

# Register multiple stores
manager.register_store("ipld_primary", create_ipld_config("docs", 768))
manager.register_store("ipld_backup", create_ipld_config("docs", 768))
manager.register_store("faiss_cache", create_faiss_config("docs", 768))

# Get store
ipld_store = await manager.get_store("ipld_primary")

# Use store
await ipld_store.create_collection()
# ... operations ...
```

### Cross-Store Search

```python
import numpy as np

# Search across multiple stores
query_vector = np.random.rand(768).tolist()

results = await manager.search_all(
    query_vector,
    stores=["ipld_primary", "faiss_cache"],
    collection_name="documents",
    top_k=5
)

for store_name, store_results in results.items():
    print(f"\nResults from {store_name}:")
    for result in store_results:
        print(f"  - {result.content} (score: {result.score})")
```

### Collection Synchronization

```python
# Sync collection across stores
results = await manager.sync_collections(
    collection_name="documents",
    primary_store="ipld_primary",
    replica_stores=["ipld_backup", "faiss_cache"],
    batch_size=1000
)

for store, count in results.items():
    print(f"Synced {count} vectors to {store}")
```

### Health Monitoring

```python
# Check health of all stores
health = await manager.get_all_health()

for store_name, status in health.items():
    print(f"\n{store_name}:")
    print(f"  Healthy: {status['healthy']}")
    if status['info']:
        print(f"  Collections: {status['info']['total_collections']}")
        print(f"  Vectors: {status['info']['total_vectors']}")
    if status['error']:
        print(f"  Error: {status['error']}")
```

## Advanced Usage

### Custom Configuration

```python
from ipfs_datasets_py.vector_stores import UnifiedVectorStoreConfig, VectorStoreType

config = UnifiedVectorStoreConfig(
    store_type=VectorStoreType.IPLD,
    collection_name="advanced",
    dimension=1536,
    distance_metric="cosine",
    # Router settings
    use_embeddings_router=True,
    use_ipfs_router=True,
    embeddings_router_provider="openrouter",
    ipfs_router_backend="accelerate",
    # IPLD settings
    enable_ipld_export=True,
    auto_pin_to_ipfs=True,
    car_export_dir="/exports",
    ipld_chunk_size=500,
    ipld_compression=True,
    max_block_size=524288,
    # Performance
    batch_size=2000,
    parallel_workers=8,
    cache_size=50000,
    prefetch_enabled=True,
    # Multi-store sync
    enable_multi_store_sync=True,
    sync_stores=["ipld_backup", "faiss_cache"],
    sync_interval=3600
)

store = IPLDVectorStore(config)
```

### Batch Processing

```python
# Process large datasets in batches
texts = [...]  # Large list of texts
batch_size = 1000

for i in range(0, len(texts), batch_size):
    batch_texts = texts[i:i + batch_size]
    batch_embeddings = [
        EmbeddingResult(
            chunk_id=f"doc_{i+j}",
            content=text,
            embedding=None,  # Auto-generated
            metadata={"batch": i // batch_size}
        )
        for j, text in enumerate(batch_texts)
    ]
    
    ids = await store.add_embeddings(batch_embeddings)
    print(f"Processed batch {i // batch_size}: {len(ids)} documents")
```

### Collection Info and Stats

```python
# Get detailed collection information
info = await store.get_collection_info("documents")
print(f"Collection: {info['name']}")
print(f"Vectors: {info['count']}")
print(f"Dimension: {info['dimension']}")
print(f"Metric: {info['metric']}")
print(f"Root CID: {info.get('root_cid', 'N/A')}")
print(f"Chunked: {info['chunked']}")
print(f"Chunk Size: {info['chunk_size']}")

# Get store-wide information
store_info = await store.get_store_info()
print(f"\nStore Type: {store_info['store_type']}")
print(f"Collections: {store_info['collections']}")
print(f"Total Vectors: {store_info['total_vectors']}")
print(f"IPFS Enabled: {store_info['ipfs_enabled']}")
print(f"Embeddings Enabled: {store_info['embeddings_enabled']}")
```

## Error Handling

```python
from ipfs_datasets_py.vector_stores import VectorStoreError

try:
    await store.create_collection("test", dimension=768)
    await store.add_embeddings(embeddings)
    results = await store.search(query_vector, top_k=10)
except VectorStoreError as e:
    print(f"Vector store error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Best Practices

1. **Use Router Integration** - Enable embeddings_router for automatic embedding generation
2. **Batch Operations** - Process large datasets in batches (1000-2000 items)
3. **IPFS Pinning** - Only pin important collections to avoid storage overhead
4. **Metadata** - Use metadata for filtering and organization
5. **Health Checks** - Monitor store health in production
6. **Backup** - Use collection sync for redundancy
7. **CAR Export** - Export collections to CAR files for portability

## Next Steps

- Check the API documentation for complete method signatures
- Review the architecture documentation for system design
- See the test suite for more examples
- Explore the planning documents for implementation details
