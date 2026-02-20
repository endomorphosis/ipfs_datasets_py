# Sparse Embedding Tools

MCP tools for sparse (BM25/TF-IDF) vector embeddings and sparse-dense hybrid search.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `sparse_embedding_tools.py` | `generate_sparse_embeddings()`, `sparse_search()`, `build_bm25_index()`, `hybrid_sparse_dense_search()` | BM25/TF-IDF embeddings, sparse search, index building, hybrid search |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools import (
    generate_sparse_embeddings, build_bm25_index, hybrid_sparse_dense_search
)

# Generate BM25 sparse embeddings
sparse = await generate_sparse_embeddings(
    texts=["legal contract obligations", "privacy policy GDPR"],
    method="bm25"    # "bm25" | "tfidf" | "splade"
)
# Returns: {"sparse_vectors": [{"indices": [...], "values": [...]}], "vocab_size": 50000}

# Build a BM25 index over a corpus
index = await build_bm25_index(
    corpus="legal_dataset",
    output_index="legal_bm25"
)

# Hybrid sparse + dense search
results = await hybrid_sparse_dense_search(
    query="breach of contract damages",
    dense_index="legal_corpus_dense",
    sparse_index="legal_bm25",
    alpha=0.5           # 0.0 = pure sparse, 1.0 = pure dense
)
```

## Dependencies

- `rank_bm25` — BM25 implementation
- `scikit-learn` — TF-IDF
- `numpy` — sparse vector operations

## Status

| Tool | Status |
|------|--------|
| `sparse_embedding_tools` | ✅ Production ready |
