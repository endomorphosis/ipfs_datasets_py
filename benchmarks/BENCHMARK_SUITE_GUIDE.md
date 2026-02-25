# GraphRAG Benchmark Suite Guide

Comprehensive guide to the GraphRAG performance and quality benchmark suite.

## Quick Start

```bash
# Run the full suite
python benchmarks/bench_graphrag_suite.py

# Run specific categories
python benchmarks/bench_graphrag_suite.py --categories extraction,validation

# Run in CI mode (fails on regressions)
python benchmarks/bench_graphrag_suite.py --ci

# Update baseline (after verifying improvements)
python benchmarks/bench_graphrag_suite.py --update-baseline
```

## Table of Contents

- [Overview](#overview)
- [Benchmark Categories](#benchmark-categories)
- [Standard Datasets](#standard-datasets)
- [Running Benchmarks](#running-benchmarks)
- [Interpreting Results](#interpreting-results)
- [CI/CD Integration](#cicd-integration)
- [Adding New Benchmarks](#adding-new-benchmarks)
- [Troubleshooting](#troubleshooting)

## Overview

The GraphRAG benchmark suite provides:

1. **Performance benchmarks**: Measure latency, throughput, memory usage
2. **Quality benchmarks**: Evaluate extraction accuracy, relationship precision
3. **Regression detection**: Automatically detect performance degradations >10%
4. **Standard datasets**: Reproducible test cases across domains
5. **CI integration**: Fail builds on regressions

### Architecture

```
benchmarks/
├── bench_graphrag_suite.py          # Orchestrator script
├── standard_datasets.py              # Curated test datasets
├── BENCHMARK_SUITE_GUIDE.md          # This file
├── results/                          # Benchmark outputs
│   ├── baseline.json                 # Performance baseline
│   ├── suite_latest.json             # Most recent run
│   └── suite_20240315_143022.json    # Historical runs
└── bench_*.py                        # Individual benchmarks
```

## Benchmark Categories

### 1. Extraction Benchmarks

Measure entity and relationship extraction performance.

| Benchmark | What it measures |
|-----------|------------------|
| `bench_ontology_extraction_baseline.py` | Baseline performance across token sizes (1k, 5k, 10k, 20k) |
| `bench_ontology_generator_extract_entities_10k.py` | Entity extraction on 10k-token documents |
| `bench_extraction_strategy_performance.py` | Strategy comparison (rule-based vs LLM) |

**Key metrics:**
- Latency (ms): Time to extract entities/relationships
- Throughput (docs/sec): Documents processed per second
- Entity count: Number of entities extracted
- Relationship count: Number of relationships inferred
- Precision/Recall: Accuracy vs ground truth (when available)

**Target performance:**
- 10k-token extraction: <500ms (p95)
- Entity accuracy: >85% precision, >75% recall
- Relationship accuracy: >70% precision, >60% recall

### 2. Relationship Inference Benchmarks

Measure relationship detection and confidence scoring.

| Benchmark | What it measures |
|-----------|------------------|
| `bench_infer_relationships_scaling.py` | Scaling behavior with entity count (10, 50, 100, 200 entities) |
| `bench_relationship_type_confidence_scoring.py` | Confidence score accuracy and calibration |

**Key metrics:**
- Inference latency: Time to infer relationships between N entities
- Confidence calibration: Alignment between predicted and actual confidence
- Type accuracy: Correctness of relationship type classification

**Target performance:**
- 100 entities: <2s inference (p95)
- Confidence calibration error: <15%
- Type accuracy: >80%

### 3. Validation Benchmarks

Measure ontology validation logic performance.

| Benchmark | What it measures |
|-----------|------------------|
| `bench_logic_validator_validate_ontology.py` | Validation on synthetic 100-entity ontologies |

**Key metrics:**
- Validation latency: Time to validate ontology
- Rule evaluation count: Number of validation rules checked
- Error detection rate: Percentage of injected errors found

**Target performance:**
- 100-entity validation: <100ms (p95)
- Error detection: >95% recall on injected errors

### 4. Generator Benchmarks

Measure full ontology generation pipelines.

| Benchmark | What it measures |
|-----------|------------------|
| `bench_ontology_generator_generate.py` | Full pipeline: parse → extract → infer → validate |
| `bench_ontology_generator_rule_based.py` | Rule-based generation without LLM |

**Key metrics:**
- End-to-end latency: Total time for complete generation
- Step breakdown: Time spent in each pipeline stage
- Memory usage: Peak memory consumption

**Target performance:**
- 10k-token end-to-end: <2s (p95)
- Memory: <500MB peak for 10k-token document

### 5. Query Optimization Benchmarks

Measure query optimizer performance and caching.

| Benchmark | What it measures |
|-----------|------------------|
| `bench_query_validation_cache_key.py` | Cache key generation for complex nested queries |
| `bench_query_optimizer_under_load.py` | Optimizer latency under concurrent load |

**Key metrics:**
- Cache key generation: Time to generate deterministic cache keys
- Optimization latency: Time to optimize query
- Cache hit rate: Percentage of queries served from cache

**Target performance:**
- Cache key generation: <1ms (p95)
- Query optimization: <50ms (p95)
- Cache hit rate: >80% in production

### 6. End-to-End Benchmarks

Measure complete workflows including iteration and refinement.

| Benchmark | What it measures |
|-----------|------------------|
| `bench_end_to_end_pipeline_performance.py` | Generation → critique → refinement cycles |

**Key metrics:**
- Total pipeline time: Complete workflow including N iterations
- Quality improvement: Score increase from iteration 0 to N
- Convergence rate: Iterations needed to reach target score

**Target performance:**
- 3-iteration pipeline: <10s total (p95)
- Quality improvement: >20% score increase
- Convergence: <5 iterations to reach score 0.85

## Standard Datasets

The `standard_datasets.py` module provides curated test cases for reproducibility.

### Dataset Categories

| Domain | Datasets | Complexity Levels |
|--------|----------|-------------------|
| Legal | Employment agreements, contracts | Simple, Moderate |
| Medical | Clinical notes, trial protocols | Simple, Complex |
| Business | Org charts, M&A transactions | Moderate, Complex |
| Technical | API docs, architecture specs | Simple |
| News | Press releases, investigative journalism | Simple |

### Example Usage

```python
from benchmarks.standard_datasets import (
    get_dataset,
    get_datasets_by_domain,
    Domain,
    Complexity,
)

# Get specific dataset
dataset = get_dataset("legal_employment_simple")
print(f"Text: {dataset.text}")
print(f"Expected entities: {dataset.expected_entities}")

# Get all legal datasets
legal_datasets = get_datasets_by_domain(Domain.LEGAL)

# Get simple datasets
simple_datasets = get_datasets_by_complexity(Complexity.SIMPLE)
```

### Dataset Properties

Each dataset includes:
- **Text content**: The actual text to process
- **Expected metrics**: Entity/relationship counts with ±tolerance
- **Token count**: Approximate token count (gpt-4 encoding)
- **Complexity**: Simple/Moderate/Complex classification
- **Domain**: Legal/Medical/Business/Technical/News
- **Description**: Human-readable summary

## Running Benchmarks

### Full Suite

Run all benchmarks and generate comprehensive report:

```bash
python benchmarks/bench_graphrag_suite.py
```

Output:
```
======================================================================
GraphRAG Benchmark Suite
======================================================================
Benchmark dir: /path/to/benchmarks
Results dir: /path/to/benchmarks/results

======================================================================
Running: bench_ontology_extraction_baseline.py
Category: extraction
Description: Baseline extraction performance across token sizes
======================================================================

✓ bench_ontology_extraction_baseline.py completed in 45.23s
...

✓ JSON results saved to: results/suite_20240315_143022.json
✓ Markdown report saved to: results/suite_20240315_143022.md
✓ Latest results saved to: results/suite_latest.json, results/suite_latest.md

======================================================================
SUITE SUMMARY
======================================================================
Total: 11
Passed: 10
Failed: 0
Skipped: 1
Total time: 234.56s

✓ All benchmarks passed
```

### Category Filtering

Run only specific benchmark categories:

```bash
# Run extraction benchmarks only
python benchmarks/bench_graphrag_suite.py --categories extraction

# Run extraction and validation benchmarks
python benchmarks/bench_graphrag_suite.py --categories extraction,validation
```

Categories: `extraction`, `relationships`, `validation`, `generator`, `query`, `end_to_end`

### Baseline Management

Establish or update performance baselines:

```bash
# First run: establishes baseline
python benchmarks/bench_graphrag_suite.py

# Future runs: compare against baseline (auto-detect regressions)
python benchmarks/bench_graphrag_suite.py

# After verifying improvements: update baseline
python benchmarks/bench_graphrag_suite.py --update-baseline
```

Baseline format (`results/baseline.json`):

```json
{
  "timestamp": "2024-03-15T14:30:22",
  "benchmarks": [
    {
      "name": "bench_ontology_extraction_baseline.py",
      "category": "extraction",
      "status": "passed",
      "execution_time_s": 45.23,
      "metrics": {...}
    }
  ]
}
```

### CI Mode

Fail builds on performance regressions (>10% slower than baseline):

```bash
python benchmarks/bench_graphrag_suite.py --ci
```

Exit codes:
- `0`: All benchmarks passed, no regressions
- `1`: Benchmark failures or regressions detected (>10% slower)

## Interpreting Results

### JSON Output

Complete machine-readable results saved to `results/suite_<timestamp>.json`:

```json
{
  "timestamp": "2024-03-15T14:30:22",
  "total_benchmarks": 11,
  "passed": 10,
  "failed": 0,
  "skipped": 1,
  "total_time_s": 234.56,
  "regressions": [
    "bench_extraction_strategy_performance.py: 15.3% slower (3.45s vs 2.99s baseline)"
  ],
  "improvements": [
    "bench_query_validation_cache_key.py: 22.1% faster (0.78s vs 1.00s baseline)"
  ],
  "benchmarks": [...]
}
```

### Markdown Report

Human-readable report saved to `results/suite_<timestamp>.md`:

```markdown
# GraphRAG Benchmark Suite Report

**Timestamp:** 2024-03-15T14:30:22  
**Total Benchmarks:** 11  
**Passed:** 10  
**Failed:** 0  
**Skipped:** 1  
**Total Time:** 234.56s  

## ⚠️ Performance Regressions

- bench_extraction_strategy_performance.py: 15.3% slower (3.45s vs 2.99s baseline)

## ✨ Performance Improvements

- bench_query_validation_cache_key.py: 22.1% faster (0.78s vs 1.00s baseline)

## Extraction Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_ontology_extraction_baseline.py | ✓ passed | 45.23 |
| bench_ontology_generator_extract_entities_10k.py | ✓ passed | 12.34 |
| bench_extraction_strategy_performance.py | ✓ passed | 3.45 |
```

### Regression Threshold

Regressions detected when execution time >10% slower than baseline:

```
regression_detected = (current_time - baseline_time) / baseline_time > 0.10
```

Improvements detected when >10% faster:

```
improvement_detected = (baseline_time - current_time) / baseline_time > 0.10
```

## CI/CD Integration

### GitHub Actions Example

`.github/workflows/benchmark.yml`:

```yaml
name: Benchmark Suite

on:
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM

jobs:
  benchmark:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest-benchmark
      
      - name: Run benchmark suite
        run: |
          python benchmarks/bench_graphrag_suite.py --ci
      
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: benchmark-results
          path: benchmarks/results/suite_latest.*
      
      - name: Comment PR with results
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('benchmarks/results/suite_latest.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });
```

### Jenkins Example

```groovy
pipeline {
    agent any
    
    stages {
        stage('Benchmark Suite') {
            steps {
                sh 'python benchmarks/bench_graphrag_suite.py --ci'
            }
        }
    }
    
    post {
        always {
            archiveArtifacts artifacts: 'benchmarks/results/suite_latest.*'
            
            script {
                def report = readFile('benchmarks/results/suite_latest.md')
                echo report
            }
        }
    }
}
```

## Adding New Benchmarks

### 1. Create Benchmark Script

Create `benchmarks/bench_my_feature.py`:

```python
#!/usr/bin/env python3
"""Benchmark for my new feature."""

import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.standard_datasets import get_dataset

def benchmark_my_feature():
    """Run benchmark."""
    dataset = get_dataset("legal_employment_simple")
    
    start = time.time()
    # ... do work ...
    elapsed = time.time() - start
    
    print(f"My Feature Benchmark: {elapsed:.2f}s")
    return elapsed


if __name__ == "__main__":
    result = benchmark_my_feature()
    sys.exit(0 if result < 5.0 else 1)  # Fail if >5s
```

### 2. Register in Suite

Edit `benchmarks/bench_graphrag_suite.py`:

```python
BENCHMARKS = [
    # ... existing benchmarks ...
    
    ("bench_my_feature.py", "extraction",
     "My new feature performance"),
]
```

### 3. Run and Update Baseline

```bash
# Test new benchmark
python benchmarks/bench_my_feature.py

# Run suite with new benchmark
python benchmarks/bench_graphrag_suite.py

# Update baseline after verifying
python benchmarks/bench_graphrag_suite.py --update-baseline
```

### 4. Add Standard Dataset (Optional)

Edit `benchmarks/standard_datasets.py`:

```python
MY_CUSTOM_DATASET = BenchmarkDataset(
    name="my_custom_dataset",
    domain=Domain.LEGAL,
    complexity=Complexity.MODERATE,
    approx_tokens=500,
    expected_entities=20,
    expected_relationships=30,
    description="My custom test case",
    text="""...""",
)

ALL_DATASETS = [
    # ... existing datasets ...
    MY_CUSTOM_DATASET,
]
```

## Troubleshooting

### Benchmark Timeouts

Default timeout: 300s (5 minutes)

To increase timeout, edit `bench_graphrag_suite.py`:

```python
result = subprocess.run(
    [sys.executable, str(script_path)],
    capture_output=True,
    text=True,
    timeout=600,  # Increase to 10 minutes
)
```

### Skipped Benchmarks

Benchmarks are skipped if script file not found:

```
⚠️  Benchmark script not found: /path/to/bench_missing.py
```

Solution: Remove from `BENCHMARKS` list or create the script.

### False Positives (Regressions)

Noise in benchmark results can cause false regressions. Solutions:

1. **Run multiple times**: Average 3-5 runs
2. **Increase threshold**: Change threshold from 10% to 15%
3. **Use dedicated hardware**: Run on same machine/environment
4. **Disable CPU scaling**: Pin CPU frequency for consistency

```bash
# Disable CPU scaling (Linux)
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

### Memory Errors

Large benchmarks may OOM. Monitor with:

```python
import tracemalloc

tracemalloc.start()
# ... benchmark code ...
current, peak = tracemalloc.get_traced_memory()
print(f"Peak memory: {peak / 1024 / 1024:.2f} MB")
tracemalloc.stop()
```

Reduce memory by:
- Smaller test datasets
- Batch processing
- Explicit garbage collection (`gc.collect()`)

## Best Practices

1. **Consistent environment**: Run benchmarks on same hardware/OS
2. **Minimal load**: Close other applications during benchmarking
3. **Multiple runs**: Average 3-5 runs to reduce noise
4. **Version control baseline**: Commit `baseline.json` to git
5. **Regular updates**: Run full suite weekly, update baseline monthly
6. **Document changes**: Note performance improvements/regressions in PRs
7. **Profile regressions**: Use `cProfile` to diagnose slowdowns
8. **Standard datasets**: Use `standard_datasets.py` for reproducibility

## References

- [pytest-benchmark documentation](https://pytest-benchmark.readthedocs.io/)
- [Performance testing best practices](https://martinfowler.com/articles/performance-testing.html)
- [Statistical analysis of benchmarks](https://www.brendangregg.com/methodology.html)

---

**Last Updated:** 2024-03-15  
**Maintainer:** Infrastructure Team  
**Questions:** Ask in #benchmarking Slack channel
