# Vector Stores - IPLD/IPFS-Native Vector Search

Unified interface for multiple vector database backends with IPLD/IPFS-native content-addressed storage.

## Overview

This package provides a comprehensive vector storage solution combining:

- **Content-Addressed Storage**: IPLD/IPFS-native storage with CIDs
- **Fast Similarity Search**: FAISS backend for efficient vector search
- **Router Integration**: Automatic embeddings generation and IPFS operations
- **Cross-Store Migration**: Seamless data movement between vector stores
- **Multi-Store Management**: Unified interface for multiple store types

## Supported Stores

1. **IPLDVectorStore** ⭐ NEW - IPLD/IPFS-native with content addressing
2. **FAISSVectorStore** - Fast similarity search with FAISS
3. **QdrantVectorStore** - Qdrant vector database
4. **ElasticsearchVectorStore** - Elasticsearch backend

## Quick Start

```python
from ipfs_datasets_py.vector_stores import create_vector_store, add_texts_to_store, search_texts

# Create IPLD store with router integration
store = await create_vector_store(
    "ipld",
    "documents",
    dimension=768,
    use_embeddings_router=True,  # Auto-generate embeddings
    use_ipfs_router=True          # Store to IPFS
)

await store.create_collection()

# Add texts (embeddings auto-generated)
texts = ["IPFS is great", "Content addressing is powerful"]
ids = await add_texts_to_store(store, texts)

# Search (query embedding auto-generated)
results = await search_texts(store, "What is IPFS?", top_k=5)

# Export to IPFS
cid = await store.export_to_ipld()
print(f"Collection at: ipfs://{cid}")
```

## Key Features

### Content-Addressed Storage

```python
from ipfs_datasets_py.vector_stores import IPLDVectorStore, create_ipld_config

config = create_ipld_config("documents", 768, use_ipfs_router=True)
store = IPLDVectorStore(config)

# Vectors stored with CIDs
ids = await store.add_embeddings(embeddings)

# Export entire collection
root_cid = await store.export_to_ipld()

# Import from any CID
await store.import_from_ipld(root_cid, "restored")
```

### Cross-Store Migration

```python
from ipfs_datasets_py.vector_stores import migrate_collection

# Migrate between any stores
count = await migrate_collection(faiss_store, ipld_store, "documents")
```

### Multi-Store Management

```python
from ipfs_datasets_py.vector_stores import create_manager

manager = create_manager()
manager.register_store("ipld", create_ipld_config("docs", 768))
manager.register_store("faiss", create_faiss_config("docs", 768))

# Search across stores
results = await manager.search_all(query_vector, stores=["ipld", "faiss"])
```

## Documentation

- **[Usage Examples](../../docs/IPLD_VECTOR_STORE_EXAMPLES.md)** - Complete guide
- **[Architecture](../../docs/IPLD_VECTOR_STORE_ARCHITECTURE.md)** - System design
- **[Quick Start](../../docs/IPLD_VECTOR_STORE_QUICKSTART.md)** - Developer guide

## Testing

```bash
pytest tests/unit/vector_stores/ -v
```

## Migration Guide

**Old IPLD implementation:**
```python
from ipfs_datasets_py.vector_stores.ipld import IPLDVectorStore
```

**New IPLD implementation:**
```python
from ipfs_datasets_py.vector_stores import IPLDVectorStore, create_ipld_config

config = create_ipld_config("collection", 768)
store = IPLDVectorStore(config)
```

## Requirements

- Python 3.12+
- numpy, anyio
- faiss-cpu (recommended)
- ipld-car (optional for CAR files)

See [Usage Examples](../../docs/IPLD_VECTOR_STORE_EXAMPLES.md) for complete documentation.
