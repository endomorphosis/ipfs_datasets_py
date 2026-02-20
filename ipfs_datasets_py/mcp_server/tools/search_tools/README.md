# Search Tools

MCP thin wrapper for semantic and keyword search. Note: for web/archive search see
[`web_archive_tools/`](../web_archive_tools/); for vector similarity search see
[`vector_tools/`](../vector_tools/).

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `search_tools.py` | `search()`, `semantic_search()`, `keyword_search()`, `hybrid_search()` | Search over indexed datasets; keyword, semantic, or hybrid mode |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.search_tools import search, hybrid_search

# Keyword search
results = await search(
    query="IPFS content addressing",
    index_name="my_corpus",
    search_type="keyword",
    max_results=20
)

# Hybrid search (keyword + semantic)
results = await hybrid_search(
    query="decentralized AI model training",
    index_name="research_papers",
    vector_weight=0.6,     # Balance between vector (0.6) and keyword (0.4)
    max_results=10
)
# Returns: {"results": [{"id": "...", "score": 0.91, "text": "...", "metadata": {...}}]}
```

## Core Module

- `ipfs_datasets_py.mcp_server.tool_registry.ClaudeMCPTool` — tool registry integration
- `ipfs_datasets_py.mcp_server.validators` — input validation

## Status

| Tool | Status |
|------|--------|
| `search_tools` | ✅ Production ready |
