# MCP++ Performance Benchmarks (Phase 3.2)

This directory contains benchmark scripts to validate the 50-70% latency reduction target for P2P tools using the dual-runtime architecture.

## Overview

The Phase 3.2 benchmarks validate:
1. **P2P Latency**: Compare FastAPI vs Trio execution across all 26 P2P tools
2. **Runtime Comparison**: Test performance across different workloads
3. **Concurrent Workflows**: Validate workflow execution at scale
4. **Memory Usage**: Track memory efficiency and detect leaks

## Benchmark Scripts

### 1. P2P Latency (`p2p_latency.py`)

Measures latency for all 26 P2P tools to validate the 50-70% improvement target.

**Usage:**
```bash
# Test all tools
python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency

# Test specific tool
python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency --tool workflow_submit

# More iterations for accuracy
python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency --iterations 200

# Save results
python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency --output results/p2p_latency.json
```

**Metrics:**
- Average latency (ms)
- P95/P99 latency (ms)
- Min/max latency (ms)
- Improvement percentage
- Per-tool breakdown

**Success Criteria:** 50-70% latency reduction for P2P tools

### 2. Runtime Comparison (`runtime_comparison.py`)

Compares runtime performance across different workloads: sequential, concurrent, and mixed.

**Usage:**
```bash
# Test all workloads
python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison

# Test specific workload
python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison --workload concurrent

# Higher concurrency
python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison --concurrency 50

# Save results
python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison --output results/runtime.json
```

**Workloads:**
- `sequential`: Run tools one after another
- `concurrent`: Run tools concurrently with specified concurrency level
- `mixed`: Mix of P2P and general tools (30:70 ratio)
- `all`: Run all workloads

**Metrics:**
- Throughput (requests/sec)
- Latency (avg, p95, p99)
- CPU usage (%)
- Memory usage (MB)

**Success Criteria:** No degradation for general tools, improved P2P performance

### 3. Concurrent Workflows (`concurrent_workflows.py`)

Tests workflow execution at scale with various complexity levels.

**Usage:**
```bash
# Test all scenarios
python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows

# Test specific scenario
python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --scenario complex

# More workflows
python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --workflows 200

# Monitor execution (adds overhead)
python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --monitor

# Save results
python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --output results/workflows.json
```

**Scenarios:**
- `simple`: 2-3 step workflows
- `complex`: 10+ step workflows with dependencies
- `dag`: Complex DAG dependencies
- `mixed`: Mix of all types
- `all`: Run all scenarios

**Metrics:**
- Submission throughput (workflows/sec)
- Submission latency (ms)
- Execution time (if monitoring)
- Success/failure rates

**Success Criteria:** Linear scaling with concurrent requests

### 4. Memory Usage (`memory_usage.py`)

Tracks memory efficiency and detects potential memory leaks.

**Usage:**
```bash
# Run all tests
python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage

# Run specific test
python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --test leak_detection

# More iterations for leak detection
python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --iterations 2000

# Test specific runtime
python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --runtime fastapi

# Save results
python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --output results/memory.json
```

**Tests:**
- `baseline`: Measure baseline memory without operations
- `per_request`: Calculate memory usage per request
- `leak_detection`: Detect memory leaks over time
- `gc_impact`: Measure garbage collection impact
- `all`: Run all tests

**Metrics:**
- Baseline memory (MB)
- Peak memory (MB)
- Memory per request (KB)
- Memory growth over time
- GC timing and efficiency

**Success Criteria:** Comparable or better memory usage, no leaks detected

## Quick Start

Run all benchmarks with default settings:

```bash
# Create results directory
mkdir -p results

# Run all benchmarks
python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency --output results/p2p_latency.json
python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison --output results/runtime.json
python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --output results/workflows.json
python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --output results/memory.json
```

## Requirements

- Python 3.12+
- `psutil` for system monitoring
- RuntimeRouter (Phase 3.1)
- P2P tools (Phase 2)

## Interpreting Results

### P2P Latency

Look for:
- ✅ **50-70% improvement** for Trio vs FastAPI
- Consistent improvement across all tool categories
- Low standard deviation (stable performance)

Example output:
```
workflow_submit:
  Trio Runtime:    avg=65.2ms  p95=87.3ms  p99=98.1ms
  FastAPI Runtime: avg=198.5ms p95=245.7ms p99=289.3ms
  ✅ Improvement: 67.1%
```

### Runtime Comparison

Look for:
- High throughput for concurrent workloads
- Low CPU and memory usage
- Linear scaling with concurrency

### Concurrent Workflows

Look for:
- High submission throughput
- Low submission latency
- Successful completion of workflows

### Memory Usage

Look for:
- Stable baseline memory
- Low memory per request
- ✅ No leak detected
- Fast GC cycles

## Troubleshooting

### "P2P tools not available"

The tools may not be imported. Check:
```python
from ipfs_datasets_py.mcp_server.tools import mcplusplus_workflow_tools
```

### "RuntimeRouter not available"

Ensure Phase 3.1 is complete:
```python
from ipfs_datasets_py.mcp_server.runtime_router import RuntimeRouter
```

### High memory usage

This is normal for intensive benchmarks. The memory tests validate that:
1. Memory grows linearly (not exponentially)
2. GC properly frees memory
3. No leaks are detected

### Benchmark fails with "Tool call failed"

This is expected and logged as debug. The benchmarks measure latency even when tools gracefully degrade (MCP++ not available).

## Automated Testing

To run benchmarks in CI/CD:

```bash
#!/bin/bash
# run_benchmarks.sh

set -e

echo "Running Phase 3.2 benchmarks..."

# Create results directory
mkdir -p benchmark_results

# Run benchmarks with reduced iterations for CI
python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency \
  --iterations 50 \
  --output benchmark_results/p2p_latency.json

python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison \
  --workload concurrent \
  --concurrency 10 \
  --iterations 50 \
  --output benchmark_results/runtime.json

python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows \
  --scenario simple \
  --workflows 50 \
  --output benchmark_results/workflows.json

python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage \
  --test per_request \
  --iterations 500 \
  --output benchmark_results/memory.json

echo "✅ Benchmarks complete! Results in benchmark_results/"
```

## Contributing

When adding new benchmarks:
1. Follow the existing structure (argparse, async/await, JSON output)
2. Include comprehensive docstrings
3. Add to this README
4. Validate results make sense

## References

- Phase 3.1: RuntimeRouter implementation
- Phase 2: 26 P2P tools
- Phase 1: MCP++ integration foundation
- PHASE_3_PROGRESS_SUMMARY.md: Detailed progress and architecture
