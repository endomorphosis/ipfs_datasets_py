# Vector Store Tools

MCP tools for vector store operations: create indexes, upsert vectors, search, and manage
multi-backend vector stores (FAISS, Qdrant, Elasticsearch). Engine logic in
`vector_store_engine.py`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `vector_store_engine.py` | `VectorStoreEngine` (mock services) | Business logic and mock services for testing (not MCP-facing) |
| `vector_store_tools.py` | `create_vector_index()`, `upsert_vectors()`, `search_vectors()`, `delete_vectors()` | Core vector store CRUD |
| `enhanced_vector_store_tools.py` | `create_collection()`, `bulk_upsert()`, `filtered_search()`, `get_collection_stats()`, … | Enhanced operations: collections, bulk upsert, filtered search, statistics |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.vector_store_tools import (
    create_vector_index, upsert_vectors, search_vectors
)

# Create an index
index = await create_vector_index(
    name="legal_embeddings",
    dimensions=384,
    metric="cosine",
    backend="faiss"            # "faiss" | "qdrant" | "elasticsearch"
)

# Upsert vectors
await upsert_vectors(
    index_name="legal_embeddings",
    vectors=[
        {"id": "doc_1", "vector": [0.1, 0.2, ...], "metadata": {"title": "Contract v1"}},
        {"id": "doc_2", "vector": [0.3, 0.1, ...], "metadata": {"title": "Privacy Policy"}},
    ]
)

# Search
results = await search_vectors(
    index_name="legal_embeddings",
    query_vector=[0.15, 0.25, ...],
    top_k=10,
    filter={"category": "contract"}   # Optional metadata filter
)
```

### Enhanced operations

```python
from ipfs_datasets_py.mcp_server.tools.vector_store_tools import (
    bulk_upsert, filtered_search, get_collection_stats
)

# Bulk upsert from embeddings file
await bulk_upsert(
    index_name="legal_embeddings",
    source_file="/data/embeddings.parquet",
    batch_size=1000
)

# Filtered search with metadata conditions
results = await filtered_search(
    index_name="legal_embeddings",
    query="employment contract obligations",
    filters={"year": {"gte": 2020}, "jurisdiction": "US-CA"},
    top_k=20
)

# Collection statistics
stats = await get_collection_stats(index_name="legal_embeddings")
# Returns: {"vectors": 50000, "dimensions": 384, "size_mb": 75.4, "backend": "faiss"}
```

## Core Module

- `vector_store_engine.VectorStoreEngine` — mock services for testing

## Dependencies

- `faiss-cpu` / `faiss-gpu` — FAISS backend
- `qdrant-client` — Qdrant backend
- `elasticsearch` — Elasticsearch backend

## Status

| Tool | Status |
|------|--------|
| `vector_store_tools` | ✅ Production ready |
| `enhanced_vector_store_tools` | ✅ Production ready |
