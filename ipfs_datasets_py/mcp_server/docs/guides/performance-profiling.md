# Performance Profiling Guide (v6 — K50)

This document describes how to profile and benchmark the MCP server's hot
paths, particularly `dispatch_parallel`, to identify bottlenecks and measure
the impact of tuning changes.

---

## Scope

The v6 profiling effort targets:

| Component | Metric | v5 Baseline | v6 Target |
|---|---|---|---|
| `dispatch_parallel` (10 calls) | mean latency | ~1.2 ms | ≤ 1.1 ms |
| `dispatch_parallel` (100 calls) | mean latency | ~12 ms | ≤ 11 ms |
| `dispatch_parallel` (1000 calls) | mean latency | ~120 ms | ≤ 110 ms |
| `CircuitBreaker.call` (no-op) | mean latency | ~0.05 ms | ≤ 0.05 ms |
| `EnhancedParameterValidator.validate_text_input` | mean latency | ~0.01 ms | ≤ 0.01 ms |

---

## Quick Start

### 1. Install profiling dependencies

```bash
pip install pyinstrument memray pytest-benchmark
```

### 2. Run the built-in benchmark script

```bash
cd ipfs_datasets_py/mcp_server
python -m benchmarks.dispatch_bench
```

This script runs `dispatch_parallel` with N=10, N=100, N=1000 calls using a
no-op tool category and prints P50 / P90 / P99 latencies.

### 3. Profile with pyinstrument (wall-clock)

```bash
python -m pyinstrument -o profile.html -r html \
    -m pytest tests/mcp/unit/test_k51_l52_l53_l54_session50.py::TestDispatchParallelAdaptiveBatch \
    -x -q
```

Open `profile.html` in a browser for a flame-chart view.

### 4. Memory profile with memray

```bash
python -m memray run -o output.bin \
    -m pytest tests/mcp/unit/test_k51_l52_l53_l54_session50.py -x -q
python -m memray flamegraph output.bin
```

---

## Bottleneck Inventory (v6 findings)

After profiling 1000 concurrent `dispatch_parallel` calls the following hot
spots were identified:

### 1. `anyio.create_task_group` overhead

**Impact:** ~3–5 μs per call.

`dispatch_parallel` creates one `TaskGroup` per batch.  For unbounded
concurrency (all 1000 calls in one group) the overhead is minimal.  With
`max_concurrent=10` (100 groups × 10 calls each) the group-creation overhead
adds ~400 μs total.

**Mitigation (K51):** `max_concurrent` is only recommended when calls exceed
a downstream rate limit.  For pure throughput, keep `max_concurrent=None`.

### 2. `ToolCategory._ensure_loaded` lock contention

**Impact:** Serialises first-access loads; subsequent calls are lock-free.

**Mitigation:** Pre-warm categories before the first dispatch burst:

```python
await asyncio.gather(*[manager.dispatch(cat, "_noop") for cat in manager.list_categories()])
```

### 3. `CircuitBreaker.state` property

**Impact:** O(1) but calls `time.monotonic()` on every access.

Under extremely high call rates (>100K/s) this can show up in profiles.
Mitigation: cache the state locally for the duration of a tight loop.

---

## Adaptive Batch Sizing (K51)

The `max_concurrent` parameter allows trading raw throughput for reliability
when downstream services have rate limits.

**Recommended values:**

| Downstream rate limit | `max_concurrent` |
|---|---|
| None (local / fast) | `None` (unlimited) |
| 10 req/s | `10` |
| 50 req/s | `50` |
| 100 req/s | `100` |

**Rule of thumb:** set `max_concurrent ≈ rate_limit × expected_latency_seconds`.

For example, if each tool call takes ~0.1 s and the downstream limit is
100 req/s, set `max_concurrent = 100 × 0.1 = 10`.

---

## Continuous Benchmarking

Add a CI step to catch regressions:

```yaml
# .github/workflows/benchmarks.yml
- name: MCP dispatch benchmark
  run: |
    pip install pyinstrument
    python -m benchmarks.dispatch_bench --fail-above-ms 15
```

The `--fail-above-ms` flag causes the script to exit non-zero if the P99
latency for 100 calls exceeds the threshold.

---

## References

- `hierarchical_tool_manager.py` — `dispatch_parallel`, `CircuitBreaker`
- `benchmarks/dispatch_bench.py` — benchmark script
- `MASTER_IMPROVEMENT_PLAN_2026_v6.md` — K50/K51 tasks
- ADR-005 — design rationale for adaptive batching
