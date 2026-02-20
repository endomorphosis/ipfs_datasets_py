# Data Processing Tools

MCP thin wrapper for data transformation, chunking, format conversion, and preprocessing.
Business logic lives in `ipfs_datasets_py.data_transformation`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `data_processing_tools.py` | `chunk_text()`, `transform_data()`, `validate_schema()`, `normalize_dataset()`, `deduplicate()` | Text chunking, schema validation, data normalisation, deduplication |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.data_processing_tools import chunk_text, deduplicate

# Chunk text for LLM context windows
chunks = await chunk_text(
    text=long_document,
    chunk_size=512,          # tokens
    overlap=50,
    strategy="sentence"      # "sentence" | "paragraph" | "fixed"
)

# Deduplicate a dataset
result = await deduplicate(
    dataset="my_corpus",
    key_columns=["url", "content_hash"],
    strategy="exact"         # "exact" | "fuzzy" | "semantic"
)
```

## Core Module

- `ipfs_datasets_py.data_transformation` — all business logic

## Status

| Tool | Status |
|------|--------|
| `data_processing_tools` | ✅ Production ready |
