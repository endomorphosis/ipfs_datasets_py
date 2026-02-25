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

## Utility Micro-Benchmarks

These scripts emit JSON metrics and can be run directly with Python.

| File | What it measures |
|------|------------------|
| `bench_query_validation_cache_key.py` | `QueryValidationMixin.generate_cache_key()` timing on nested payloads |
| `bench_logic_validator_validate_ontology.py` | `LogicValidator.validate_ontology()` timing on synthetic 100-entity ontologies |
| `bench_ontology_generator_extract_entities_10k.py` | `OntologyGenerator.extract_entities()` timing on ~10k-token text (`sentence_window=0` vs `2`) |
| `bench_query_optimizer_under_load.py` | `GraphRAGQueryOptimizer.optimize_query()` latency/throughput under small/medium/large query payloads |

Example:

```bash
python benchmarks/bench_logic_validator_validate_ontology.py
```

## Key targets (Phase E)

| Operation | Target |
|-----------|--------|
| `dispatch()` (cache warm) | < 5 ms |
| `get_tool_schema()` (cached) | < 0.1 ms |
| Server category startup (lazy) | < 200 ms per category |
| P2P pool acquire (pool hit) | < 1 ms |
