# Embedding Tools

MCP tools for generating, searching, and managing vector embeddings. These tools wrap the
IPFS embeddings integration and support distributed embedding generation.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `embedding_generation.py` | `generate_embeddings()`, `generate_batch_embeddings()` | Generate embeddings for text/documents using configurable models |
| `advanced_embedding_generation.py` | `advanced_generate_embeddings()`, `generate_multimodal_embeddings()` | Advanced embedding generation with model selection and batching |
| `advanced_search.py` | `semantic_search()`, `similarity_search()`, `batch_search()` | Semantic and similarity search over vector stores |
| `embedding_tools.py` | `embed_text()`, `embed_batch()` | Lightweight compatibility wrappers |
| `cluster_management.py` | `create_cluster()`, `manage_cluster()` | Manage embedding cluster and sharding across IPFS nodes |
| `shard_embeddings.py` | `shard_embeddings()`, `merge_shards()` | Shard large embedding datasets for distributed storage |
| `shard_embeddings_tool.py` | `shard_embedding_dataset()` | MCP-facing shard wrapper with progress tracking |
| `tool_registration.py` | — | Internal: embedding tool registration for lazy loading |
| `enhanced_embedding_tools.py` | Multiple | Enhanced wrappers with caching and retry logic |

## Usage

### Generate embeddings

```python
from ipfs_datasets_py.mcp_server.tools.embedding_tools import generate_embeddings

result = await generate_embeddings(
    texts=["hello world", "IPFS is decentralized storage"],
    model="sentence-transformers/all-MiniLM-L6-v2",  # or "text-embedding-ada-002"
    batch_size=32,
    normalize=True
)
# Returns: {"status": "success", "embeddings": [[0.1, 0.2, ...], ...], "model": "...", "dim": 384}
```

### Semantic search

```python
from ipfs_datasets_py.mcp_server.tools.embedding_tools import semantic_search

result = await semantic_search(
    query="decentralized AI training",
    index_name="my_embeddings",     # Name of an existing vector index
    top_k=10,
    threshold=0.75                  # Minimum similarity score
)
# Returns: {"status": "success", "results": [{"text": "...", "score": 0.92, "id": "..."}]}
```

### Shard large embeddings to IPFS

```python
from ipfs_datasets_py.mcp_server.tools.embedding_tools import shard_embeddings

result = await shard_embeddings(
    embedding_source="my_embeddings",
    shard_size=10000,              # Embeddings per shard
    output_format="parquet",
    pin_to_ipfs=True
)
# Returns: {"status": "success", "shards": [{"cid": "Qm...", "count": 10000}], ...}
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.embeddings` — embedding model wrappers
- `ipfs_datasets_py.ipfs_embeddings_py` — IPFS-integrated embedding storage

## Dependencies

**Required:**
- Standard library: `logging`, `typing`

**Optional (graceful degradation if missing):**
- `sentence-transformers` — open-source embedding models
- `torch` — required by most transformer models
- `openai` — for OpenAI embedding API
- `numpy` — for vector operations
- `faiss-cpu` / `faiss-gpu` — for approximate nearest-neighbour search
- `qdrant-client` — for Qdrant vector store backend
- `elasticsearch` — for Elasticsearch vector backend

All optional dependencies degrade gracefully with informative error messages.

## Status

| Tool | Status |
|------|--------|
| `generate_embeddings` | ✅ Production ready |
| `semantic_search` | ✅ Production ready |
| `shard_embeddings` | ✅ Production ready |
| `cluster_management` | ⚠️ Requires IPFS cluster |
