# TDFOL Performance Dashboard

Comprehensive real-time performance monitoring and visualization system for TDFOL theorem proving.

## 📊 Overview

The TDFOL Performance Dashboard provides production-ready monitoring and analysis of theorem proving performance with:

- **Real-time Metrics Collection**: Track proof times, cache hits/misses, strategy selections
- **Statistics Aggregation**: Percentiles (P50, P95, P99), success rates, cache speedup
- **Interactive Visualizations**: HTML dashboards with Chart.js for beautiful, responsive charts
- **JSON Export**: Export all metrics for external monitoring tools (Prometheus, Grafana, etc.)
- **Strategy Comparison**: Compare performance across different proving strategies

## 🚀 Quick Start

```python
from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import OptimizedProver

# Create dashboard
dashboard = PerformanceDashboard()

# Prove something
prover = OptimizedProver(kb)
result = prover.prove(formula)

# Record metrics
dashboard.record_proof(result, metadata={'strategy': 'forward'})

# Get statistics
stats = dashboard.get_statistics()
print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")
print(f"Avg proof time: {stats['timing']['avg_ms']:.2f}ms")

# Generate HTML dashboard
dashboard.generate_html('dashboard.html')

# Export to JSON
dashboard.export_json('metrics.json')
```

## 📋 Features

### 1. Real-time Metrics Collection

Record proof attempts with comprehensive metadata:

```python
dashboard.record_proof(
    proof_result,
    metadata={
        'strategy': 'forward',
        'cache_hit': False,
        'memory_mb': 256.5
    }
)
```

Captured metrics include:
- Proof time (ms)
- Success/failure
- Formula complexity
- Number of proof steps
- Strategy used
- Cache hits/misses
- Memory usage
- Formula type (temporal, deontic, modal, propositional)

### 2. Custom Metrics

Record arbitrary metrics for monitoring:

```python
dashboard.record_metric('cpu_usage_percent', 45.2, tags={'process': 'prover'})
dashboard.record_metric('memory_usage_mb', 512.0, tags={'process': 'prover'})
dashboard.record_metric('disk_io_mb', 128.5, tags={'operation': 'cache_write'})
```

### 3. Statistics Aggregation

Get comprehensive statistics:

```python
stats = dashboard.get_statistics()

# Overall metrics
print(f"Total proofs: {stats['total_proofs']}")
print(f"Success rate: {stats['success_rate']:.1%}")
print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")

# Timing statistics
print(f"Avg time: {stats['timing']['avg_ms']:.2f}ms")
print(f"Median: {stats['timing']['median_ms']:.2f}ms")
print(f"P95: {stats['timing']['p95_ms']:.2f}ms")
print(f"P99: {stats['timing']['p99_ms']:.2f}ms")

# Cache performance
print(f"Cache speedup: {stats['avg_speedup_from_cache']:.1f}x")

# Strategy breakdown
for strategy, count in stats['strategies']['counts'].items():
    success_rate = stats['strategies']['success_rates'][strategy]
    avg_time = stats['strategies']['avg_times_ms'][strategy]
    print(f"{strategy}: {count} proofs, {success_rate:.1%} success, {avg_time:.1f}ms avg")
```

### 4. Strategy Comparison

Compare performance across strategies:

```python
comparison = dashboard.compare_strategies()

for strategy, metrics in comparison['strategies'].items():
    print(f"{strategy}:")
    print(f"  Count: {metrics['count']}")
    print(f"  Success rate: {metrics['success_rate']:.1%}")
    print(f"  Cache hit rate: {metrics['cache_hit_rate']:.1%}")
    print(f"  Avg time: {metrics['avg_time_ms']:.2f}ms")
    print(f"  Median time: {metrics['median_time_ms']:.2f}ms")
```

### 5. HTML Dashboard Generation

Generate beautiful, interactive dashboards:

```python
dashboard.generate_html('performance_dashboard.html')
```

The HTML dashboard includes:
- **Line charts**: Proof times over time
- **Bar charts**: Strategy performance comparison
- **Pie charts**: Cache hit/miss distribution, formula type distribution
- **Histograms**: Proof time distribution
- **Tables**: Detailed strategy comparison
- **Summary cards**: Key metrics at a glance

Features:
- Responsive design (works on mobile)
- Interactive charts with hover tooltips
- Beautiful gradient styling
- No external dependencies (self-contained HTML)

### 6. JSON Export

Export all metrics for external tools:

```python
dashboard.export_json('metrics.json')
```

JSON structure:
```json
{
  "metadata": {
    "dashboard_start_time": 1234567890.0,
    "export_time": 1234567900.0,
    "total_proofs": 100,
    "total_metrics": 250
  },
  "statistics": {
    "total_proofs": 100,
    "success_rate": 0.85,
    "cache_hit_rate": 0.30,
    "timing": {
      "avg_ms": 125.5,
      "median_ms": 95.0,
      "p95_ms": 350.0,
      "p99_ms": 480.0
    },
    "strategies": { ... },
    "formula_types": { ... }
  },
  "proof_metrics": [ ... ],
  "timeseries_metrics": [ ... ],
  "strategy_comparison": { ... }
}
```

## 📊 Example Workflows

### Continuous Monitoring

Monitor a long-running proof session:

```python
dashboard = PerformanceDashboard()

# Run proofs
for formula in formulas:
    result = prover.prove(formula)
    dashboard.record_proof(result, metadata={'strategy': prover.strategy})
    
    # Check performance every 10 proofs
    if len(dashboard.proof_metrics) % 10 == 0:
        stats = dashboard.get_statistics()
        print(f"Avg time: {stats['timing']['avg_ms']:.1f}ms")

# Generate final report
dashboard.generate_html('final_report.html')
```

### Strategy Selection

Find the best strategy for your workload:

```python
dashboard = PerformanceDashboard()

strategies = ['forward', 'backward', 'bidirectional', 'tableaux']

for formula in test_set:
    for strategy in strategies:
        result = prover.prove(formula, strategy=strategy)
        dashboard.record_proof(result, metadata={'strategy': strategy})

# Compare strategies
comparison = dashboard.compare_strategies()

# Find best strategy
best = min(comparison['strategies'].items(), 
           key=lambda x: x[1]['avg_time_ms'])

print(f"Best strategy: {best[0]}")
print(f"Avg time: {best[1]['avg_time_ms']:.2f}ms")
print(f"Success rate: {best[1]['success_rate']:.1%}")
```

### Performance Regression Testing

Track performance over time:

```python
import json

# Run tests
dashboard = PerformanceDashboard()
run_test_suite(dashboard)

# Export metrics
dashboard.export_json(f'metrics_{version}.json')

# Compare with baseline
with open('metrics_baseline.json') as f:
    baseline = json.load(f)

current = dashboard.get_statistics()

print("Performance comparison:")
print(f"  Avg time: {current['timing']['avg_ms']:.1f}ms "
      f"(baseline: {baseline['statistics']['timing']['avg_ms']:.1f}ms)")
print(f"  P95 time: {current['timing']['p95_ms']:.1f}ms "
      f"(baseline: {baseline['statistics']['timing']['p95_ms']:.1f}ms)")
```

## 🔧 Integration with Prover

### With OptimizedProver

```python
from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import OptimizedProver
from ipfs_datasets_py.logic.TDFOL.performance_dashboard import get_global_dashboard

# Use global dashboard
dashboard = get_global_dashboard()

# Create prover
prover = OptimizedProver(kb, enable_cache=True, enable_zkp=True)

# Prove and record
result = prover.prove(formula)

# Extract metadata from prover state
metadata = {
    'strategy': prover.default_strategy.value,
    'cache_hit': hasattr(result, '_from_cache') and result._from_cache,
    'memory_mb': prover.get_memory_usage() if hasattr(prover, 'get_memory_usage') else 0.0,
}

dashboard.record_proof(result, metadata)
```

### With Batch Processing

```python
def batch_prove_with_monitoring(formulas, prover, dashboard):
    """Prove multiple formulas with monitoring."""
    results = []
    
    for i, formula in enumerate(formulas):
        result = prover.prove(formula)
        
        dashboard.record_proof(result, metadata={
            'strategy': prover.default_strategy.value,
            'batch_index': i,
        })
        
        results.append(result)
        
        # Progress update every 10 proofs
        if (i + 1) % 10 == 0:
            stats = dashboard.get_statistics()
            print(f"Progress: {i+1}/{len(formulas)} "
                  f"(avg: {stats['timing']['avg_ms']:.1f}ms)")
    
    return results
```

## 📈 Dashboard Screenshots

The HTML dashboard includes:

1. **Header with Key Metrics**
   - Total proofs
   - Success rate
   - Cache hit rate
   - Average/median/P95/P99 times
   - Cache speedup

2. **Proof Times Over Time** (Line Chart)
   - Track performance trends
   - Identify performance degradation
   - See impact of optimizations

3. **Strategy Performance** (Bar Charts)
   - Compare average times
   - Compare success rates
   - Identify best strategy

4. **Proof Time Distribution** (Histogram)
   - Understand timing distribution
   - Identify outliers

5. **Cache Distribution** (Pie Chart)
   - Visualize cache effectiveness

6. **Formula Type Distribution** (Pie Chart)
   - See workload composition

7. **Strategy Comparison Table**
   - Detailed metrics for each strategy
   - Min/max/avg/median times
   - Success and cache hit rates

## 🎯 Performance Metrics Explained

### Timing Metrics

- **avg_ms**: Mean proof time
- **median_ms**: 50th percentile (P50) - half of proofs are faster
- **p95_ms**: 95th percentile - 95% of proofs are faster
- **p99_ms**: 99th percentile - 99% of proofs are faster
- **min_ms**: Fastest proof
- **max_ms**: Slowest proof

### Cache Metrics

- **cache_hit_rate**: Percentage of proofs served from cache
- **avg_speedup_from_cache**: How much faster cached proofs are (e.g., 10x)

### Success Metrics

- **success_rate**: Percentage of proofs that succeeded
- **strategy_success_rates**: Success rate per strategy

## 🔍 Use Cases

1. **Development**: Monitor performance during development
2. **Testing**: Track performance in CI/CD pipelines
3. **Production**: Monitor production proof systems
4. **Optimization**: Identify bottlenecks and measure improvements
5. **Research**: Analyze proving strategies and algorithms
6. **Debugging**: Understand why proofs are slow
7. **Reporting**: Generate reports for stakeholders

## 🛠️ API Reference

### PerformanceDashboard

#### `__init__()`
Initialize a new dashboard.

#### `record_proof(proof_result, metadata=None)`
Record metrics from a proof attempt.

**Parameters:**
- `proof_result`: ProofResult object (must have: formula, time_ms, status/is_proved, method, proof_steps)
- `metadata`: Optional dict with additional metadata (strategy, cache_hit, memory_mb, etc.)

#### `record_metric(metric_name, value, tags=None)`
Record a custom metric.

**Parameters:**
- `metric_name`: Name of the metric
- `value`: Metric value (float)
- `tags`: Optional dict of tags

#### `get_statistics() -> Dict`
Get aggregated statistics.

**Returns:** Dictionary with comprehensive statistics

#### `compare_strategies() -> Dict`
Compare performance across strategies.

**Returns:** Dictionary with strategy comparison

#### `generate_html(output_path)`
Generate interactive HTML dashboard.

**Parameters:**
- `output_path`: Path to output HTML file

#### `export_json(output_path)`
Export metrics to JSON.

**Parameters:**
- `output_path`: Path to output JSON file

#### `clear()`
Clear all recorded metrics.

### Global Dashboard

#### `get_global_dashboard() -> PerformanceDashboard`
Get or create the global dashboard instance.

#### `reset_global_dashboard()`
Reset the global dashboard.

## 🧪 Testing

Run the test suite:

```bash
# All tests
pytest tests/unit/logic/TDFOL/test_performance_dashboard.py -v

# Specific test
pytest tests/unit/logic/TDFOL/test_performance_dashboard.py::test_record_proof -v

# With coverage
pytest tests/unit/logic/TDFOL/test_performance_dashboard.py --cov=ipfs_datasets_py.logic.TDFOL.performance_dashboard --cov-report=html
```

## 🎬 Demonstration

Run the comprehensive demonstration:

```bash
# Basic demonstration
python ipfs_datasets_py/logic/TDFOL/demonstrate_performance_dashboard.py

# With more proofs
python ipfs_datasets_py/logic/TDFOL/demonstrate_performance_dashboard.py --num-proofs 200

# Custom output directory
python ipfs_datasets_py/logic/TDFOL/demonstrate_performance_dashboard.py --output-dir ./my_dashboard

# Quick demo
python ipfs_datasets_py/logic/TDFOL/demonstrate_performance_dashboard.py --quick
```

The demonstration includes:
1. Basic usage
2. Strategy comparison
3. Custom metrics
4. HTML generation
5. JSON export
6. Real-time monitoring simulation
7. Performance analysis
8. Global dashboard usage

## 📝 Best Practices

1. **Use Global Dashboard**: For application-wide monitoring
   ```python
   dashboard = get_global_dashboard()
   ```

2. **Record All Proofs**: Don't skip failed proofs - they're important!

3. **Add Metadata**: Include as much context as possible
   ```python
   metadata = {
       'strategy': 'forward',
       'cache_hit': False,
       'memory_mb': 256.0,
       'formula_source': 'test_suite',
       'worker_id': 'worker_1',
   }
   ```

4. **Regular Exports**: Export metrics periodically for long-running sessions
   ```python
   if dashboard.proof_metrics % 100 == 0:
       dashboard.export_json(f'metrics_{time.time()}.json')
   ```

5. **Monitor Trends**: Generate HTML dashboard regularly to spot trends

6. **Compare Baselines**: Keep baseline metrics for regression testing

## 🔗 Related Components

- **OptimizedProver**: Uses proof caching and ZKP acceleration
- **ProofCache**: Caches proof results for instant lookup
- **ZKPTDFOLProver**: Zero-knowledge proof integration
- **ModalTableau**: Modal logic prover

## 📄 License

Part of the IPFS Datasets Python project.

## 🙏 Acknowledgments

Built as the final task of Phase 11 of the TDFOL project, completing the comprehensive theorem proving pipeline from mathematical logic to verified proofs to performance monitoring.
