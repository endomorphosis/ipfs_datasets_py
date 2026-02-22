# Provenance Tools

MCP tools for recording, querying, and exporting data provenance information (lineage,
transformations, sources). Thin wrappers around `ipfs_datasets_py.audit`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `record_provenance.py` | `record_provenance()` | Record a provenance event (source, transformation, actor) for a dataset |
| `provenance_tools_claudes.py` | `ClaudesProvenanceTool` class | Legacy/Claude toolbox provenance tool (placeholder for migration) |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.provenance_tools import record_provenance

# Record provenance when creating a new dataset version
await record_provenance(
    dataset_id="legal_corpus_v2",
    event_type="transformation",
    source_datasets=["legal_corpus_v1"],
    transformation="deduplicate + re-embed",
    actor="pipeline_user_42",
    output_cid="QmXxx...",
    metadata={"rows_before": 50000, "rows_after": 48231}
)

# Query provenance
from ipfs_datasets_py.mcp_server.tools.provenance_tools import query_provenance

history = await query_provenance(
    dataset_id="legal_corpus_v2",
    include_ancestors=True
)
```

## Core Module

- `ipfs_datasets_py.audit` — provenance log storage

## Status

| Tool | Status |
|------|--------|
| `record_provenance` | ✅ Production ready |
| `provenance_tools_claudes` | ⚠️ Placeholder — migration from claudes_toolbox-1 pending |
