# Dashboard Tools

MCP tools for the TDFOL performance dashboard and JavaScript error reporting.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `tdfol_performance_engine.py` | `TDFOLPerformanceEngine` class | Business logic for TDFOL performance metrics and profiling (not MCP-facing) |
| `tdfol_performance_tool.py` | `get_tdfol_performance()`, `run_tdfol_benchmark()`, `get_performance_dashboard()` | MCP thin wrapper: profile TDFOL proofs, generate dashboard HTML |
| `js_error_reporter.py` | `report_js_error()` | Receive and log JavaScript errors from the web dashboard UI |

## Usage

### TDFOL performance profiling

```python
from ipfs_datasets_py.mcp_server.tools.dashboard_tools import (
    get_tdfol_performance, run_tdfol_benchmark
)

# Get current performance metrics
metrics = await get_tdfol_performance()
# Returns: {"avg_proof_time_ms": 12.4, "cache_hit_rate": 0.73, "proofs_last_hour": 342}

# Run a benchmark
benchmark = await run_tdfol_benchmark(
    formula_count=100,
    logic_type="TDFOL",
    include_modal=True
)
# Returns: {"min_ms": 2.1, "max_ms": 45.6, "p95_ms": 18.3, "throughput": 81.4}
```

### Dashboard HTML generation

```python
from ipfs_datasets_py.mcp_server.tools.dashboard_tools import get_performance_dashboard

html = await get_performance_dashboard(
    time_range_hours=24,
    include_charts=True
)
# Returns: {"html": "<html>...", "generated_at": "2026-02-20T09:00:00Z"}
```

### Report a JavaScript error

```python
from ipfs_datasets_py.mcp_server.tools.dashboard_tools import report_js_error

await report_js_error(
    message="Cannot read property 'data' of undefined",
    stack="TypeError: ...\n    at Chart.render...",
    url="http://localhost:3000/dashboard",
    user_agent="Mozilla/5.0..."
)
```

## Core Module

- `tdfol_performance_engine.TDFOLPerformanceEngine` — all business logic

## Status

| Tool | Status |
|------|--------|
| `tdfol_performance_tool` | ✅ Production ready |
| `js_error_reporter` | ✅ Production ready |
