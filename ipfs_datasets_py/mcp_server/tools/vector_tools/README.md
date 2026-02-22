# Vector Tools

MCP tools for vector index lifecycle management and similarity search. Vector store engine
logic is in `vector_store_management_engine.py`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `create_vector_index.py` | `create_vector_index()` | Create a new vector similarity index |
| `search_vector_index.py` | `search_vector_index()` | Similarity search in an existing vector index |
| `vector_store_management.py` | `manage_vector_store()`, `get_vector_store_info()` | MCP thin wrapper for vector store management |
| `vector_store_management_engine.py` | `VectorStoreManager` class | Reusable vector store engine (not MCP-facing) |
| `vector_stores.py` | `create_store()`, `load_store()`, `save_store()`, `list_stores()` | High-level vector store CRUD |
| `shared_state.py` | — | Shared `ServerContext` state for vector indexes across tool calls |

## Usage

### Create and search a vector index

```python
from ipfs_datasets_py.mcp_server.tools.vector_tools import (
    create_vector_index, search_vector_index
)

# Create index
index = await create_vector_index(
    name="my_embeddings",
    dimensions=384,
    metric="cosine",            # "cosine" | "l2" | "dot"
    index_type="hnsw"           # "hnsw" | "flat" | "ivf"
)

# Search by vector
results = await search_vector_index(
    index_name="my_embeddings",
    query_vector=[0.1, 0.2, ...],  # Pre-computed embedding
    top_k=10
)
# Returns: {"results": [{"id": "doc_1", "score": 0.94, "metadata": {...}}]}
```

### Vector store management

```python
from ipfs_datasets_py.mcp_server.tools.vector_tools import (
    create_store, list_stores, manage_vector_store
)

# Create a named store
store = await create_store(
    name="legal_corpus",
    backend="faiss",
    persist_path="/data/stores/legal_corpus"
)

# List all stores
stores = await list_stores()

# Get store info
info = await manage_vector_store(
    store_name="legal_corpus",
    action="info"               # "info" | "optimize" | "export" | "import"
)
```

## Core Module

- `vector_store_management_engine.VectorStoreManager` — all vector store business logic
- `shared_state` — `ServerContext` for cross-tool state sharing

## Dependencies

- `faiss-cpu` — FAISS vector store
- `numpy` — vector arithmetic

## Related

- [`vector_store_tools/`](../vector_store_tools/) — enhanced multi-backend vector store operations
- [`embedding_tools/`](../embedding_tools/) — generate embeddings to populate these stores

## Status

| Tool | Status |
|------|--------|
| `create_vector_index` | ✅ Production ready |
| `search_vector_index` | ✅ Production ready |
| `vector_store_management` | ✅ Production ready |
| `vector_stores` | ✅ Production ready |
