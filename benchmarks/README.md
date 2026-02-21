# MCP Server Performance Benchmarks (Phase E)

This directory contains `pytest-benchmark` scripts that measure the latency and
throughput of the core MCP server components.  They serve as a regression guard:
if any operation regresses by more than 20 % CI will fail.

## Installing dependencies

```bash
pip install pytest-benchmark
```

## Running the benchmarks

```bash
# Run everything (shows a summary table)
pytest benchmarks/ -v

# Compare against a saved baseline
pytest benchmarks/ --benchmark-compare --benchmark-compare-fail=mean:20%

# Save a new baseline
pytest benchmarks/ --benchmark-save=baseline
```

## Benchmark files

| File | What it measures |
|------|------------------|
| `bench_hierarchical_dispatch.py` | `HierarchicalToolManager.dispatch()` latency (warm/cold cache, valid/invalid category) |
| `bench_schema_cache.py` | `ToolCategory.get_tool_schema()` cache hit vs. miss overhead |
| `bench_tool_loading.py` | Lazy vs. eager category startup time |
| `bench_p2p_connection_pool.py` | P2P connection pool acquire/release latency |

## Key targets (Phase E)

| Operation | Target |
|-----------|--------|
| `dispatch()` (cache warm) | < 5 ms |
| `get_tool_schema()` (cached) | < 0.1 ms |
| Server category startup (lazy) | < 200 ms per category |
| P2P pool acquire (pool hit) | < 1 ms |
