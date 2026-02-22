# Analysis Tools

MCP thin wrapper for data analysis operations. Business logic lives in
`ipfs_datasets_py.analytics.analysis_engine`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `analysis_tools.py` | `analyze_data()`, `generate_statistics()`, `detect_patterns()`, `compare_datasets()` | Statistical analysis, pattern detection, dataset comparison |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.analysis_tools import analyze_data

result = await analyze_data(
    data_source="my_dataset",
    analysis_type="statistics",   # "statistics" | "patterns" | "comparison"
    columns=["age", "income"],
    output_format="json"
)
# Returns: {"mean": {...}, "std": {...}, "percentiles": {...}}
```

## Core Module

- `ipfs_datasets_py.analytics.analysis_engine` — all business logic

## Status

| Tool | Status |
|------|--------|
| `analysis_tools` | ✅ Production ready |
