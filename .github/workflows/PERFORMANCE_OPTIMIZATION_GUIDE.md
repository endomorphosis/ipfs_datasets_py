# Performance Optimization Guide for GitHub Actions Workflows

**Date:** 2026-02-16  
**Purpose:** Best practices and patterns for optimizing GitHub Actions workflow performance

---

## Executive Summary

This guide provides strategies for improving GitHub Actions workflow performance through caching, parallel execution, and resource optimization.

**Key Opportunities:**
- Pip caching: Already implemented in most workflows ✅
- Checkout optimization: 2 workflows identified
- Parallel execution: Multiple opportunities
- Resource optimization: Ongoing improvements

**Expected Performance Gains:**
- 20-30% faster workflow execution
- 50-80% faster package installations (with caching)
- 80-90% faster git operations (with shallow clones)
- Reduced network bandwidth usage

---

## Table of Contents

1. [Caching Strategies](#caching-strategies)
2. [Checkout Optimization](#checkout-optimization)
3. [Parallel Execution](#parallel-execution)
4. [Resource Optimization](#resource-optimization)
5. [Performance Monitoring](#performance-monitoring)

---

## Caching Strategies

### 1. Pip Caching (Python)

**Status:** ✅ Already implemented in most workflows via setup-python

```yaml
- name: Set up Python
  uses: actions/setup-python@v5
  with:
    python-version: '3.12'
    cache: 'pip'  # Automatic pip caching
```

**Benefits:**
- 50-80% faster pip install
- Reduces PyPI load
- More reliable installations

**Best Practices:**
- Always use `cache: 'pip'` with setup-python
- Ensure requirements.txt or pyproject.toml is in repository root
- Cache is automatically invalidated when requirements change

### 2. npm/Yarn Caching (Node.js)

```yaml
- name: Set up Node.js
  uses: actions/setup-node@v4
  with:
    node-version: '18'
    cache: 'npm'  # or 'yarn', 'pnpm'
```

**Patterns for Manual Caching:**

```yaml
- name: Cache node modules
  uses: actions/cache@v4
  with:
    path: ~/.npm
    key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
    restore-keys: |
      ${{ runner.os }}-node-
```

### 3. Docker Layer Caching

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3
  
- name: Cache Docker layers
  uses: actions/cache@v4
  with:
    path: /tmp/.buildx-cache
    key: ${{ runner.os }}-buildx-${{ github.sha }}
    restore-keys: |
      ${{ runner.os }}-buildx-

- name: Build Docker image
  uses: docker/build-push-action@v5
  with:
    context: .
    cache-from: type=local,src=/tmp/.buildx-cache
    cache-to: type=local,dest=/tmp/.buildx-cache-new,mode=max
```

### 4. Cargo Caching (Rust)

```yaml
- name: Cache cargo registry
  uses: actions/cache@v4
  with:
    path: |
      ~/.cargo/registry
      ~/.cargo/git
      target
    key: ${{ runner.os }}-cargo-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: |
      ${{ runner.os }}-cargo-
```

### 5. Custom Cache Patterns

```yaml
- name: Cache test data
  uses: actions/cache@v4
  with:
    path: |
      ~/.cache/test-data
      test/fixtures
    key: test-data-${{ hashFiles('test/data-sources.json') }}
    restore-keys: |
      test-data-
```

---

## Checkout Optimization

### Shallow Clones (fetch-depth: 1)

**Use Case:** When you don't need git history

```yaml
- name: Checkout code
  uses: actions/checkout@v4
  with:
    fetch-depth: 1  # Shallow clone, 80-90% faster
```

**Benefits:**
- 80-90% faster clone for large repositories
- Reduces network bandwidth by ~90%
- Faster workflow startup

**When NOT to use:**
- Need git history (git log, git diff)
- Need tags (git tag --list)
- Generating changelogs
- Creating releases with git notes

### Full History (fetch-depth: 0)

**Use Case:** When you need complete git history

```yaml
- name: Checkout code with history
  uses: actions/checkout@v4
  with:
    fetch-depth: 0  # Full clone
```

**Required for:**
- Git log operations
- Tag comparison
- Blame annotations
- Merge base calculations

### Optimized Checkout Patterns

```yaml
# Pattern 1: Shallow clone for most jobs
- name: Checkout
  uses: actions/checkout@v4
  with:
    fetch-depth: 1

# Pattern 2: Fetch only specific branch
- name: Checkout specific branch
  uses: actions/checkout@v4
  with:
    ref: main
    fetch-depth: 1

# Pattern 3: No checkout when not needed
jobs:
  no-code-needed:
    runs-on: ubuntu-latest
    steps:
      # Skip checkout entirely if you don't need code
      - name: Run without code
        run: echo "No checkout needed"
```

### Current Analysis

**Opportunities:** 2 checkouts in continuous-queue-management.yml
**Potential Savings:** ~20 seconds per run, ~100MB bandwidth

---

## Parallel Execution

### 1. Matrix Strategy for Tests

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
        test-suite: ['unit', 'integration', 'e2e']
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pytest tests/${{ matrix.test-suite }}
```

**Benefits:**
- Run 9 test combinations in parallel
- Reduce total runtime from 90min to 30min
- Faster feedback on failures

### 2. Parallel Jobs

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Run linting
        run: flake8
  
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        run: pytest
  
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Build package
        run: python setup.py sdist
```

**Benefits:**
- lint, test, and build run simultaneously
- Total time = max(lint_time, test_time, build_time)
- Faster CI feedback

### 3. Job Dependencies

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Build
        run: make build
  
  test-unit:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Unit tests
        run: pytest tests/unit
  
  test-integration:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Integration tests
        run: pytest tests/integration
```

**Benefits:**
- Unit and integration tests run in parallel after build
- Optimal dependency graph
- Minimum total runtime

### 4. Concurrency Control

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

**Benefits:**
- Cancels outdated runs automatically
- Saves compute resources
- Faster feedback on latest changes

---

## Resource Optimization

### 1. Runner Selection

```yaml
# Use appropriate runner for workload
jobs:
  light-task:
    runs-on: ubuntu-latest  # Sufficient for most tasks
  
  heavy-task:
    runs-on: ubuntu-latest-8-cores  # More CPU for parallel builds
  
  gpu-task:
    runs-on: [self-hosted, linux, gpu]  # GPU-enabled runner
```

### 2. Conditional Execution

```yaml
jobs:
  expensive-job:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Expensive operation
        run: make expensive-build
```

**Benefits:**
- Skip unnecessary work
- Save compute resources
- Faster PR checks

### 3. Artifacts Management

```yaml
# Upload artifacts efficiently
- name: Upload artifacts
  uses: actions/upload-artifact@v4
  with:
    name: build-results
    path: dist/
    retention-days: 7  # Don't keep artifacts forever
    compression-level: 9  # Maximum compression
```

### 4. Step Optimization

```yaml
# Combine related operations
- name: Setup and test
  run: |
    pip install -r requirements.txt
    pytest tests/
```

```yaml
# Use shell parameters for efficiency
- name: Efficient shell operations
  shell: bash
  run: |
    set -euo pipefail  # Fast fail
    # Your operations
```

---

## Performance Monitoring

### 1. Workflow Timing

```yaml
- name: Start timer
  id: start
  run: echo "start_time=$(date +%s)" >> $GITHUB_OUTPUT

- name: Your operation
  run: # Your work here

- name: Calculate duration
  run: |
    START=${{ steps.start.outputs.start_time }}
    END=$(date +%s)
    DURATION=$((END - START))
    echo "Operation took ${DURATION} seconds"
```

### 2. Cache Hit Rate Monitoring

```yaml
- name: Restore cache
  id: cache
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}

- name: Log cache status
  run: |
    if [ "${{ steps.cache.outputs.cache-hit }}" == "true" ]; then
      echo "✅ Cache hit - saved time!"
    else
      echo "❌ Cache miss - full install required"
    fi
```

### 3. Resource Usage

```yaml
- name: Monitor resources
  run: |
    echo "=== CPU Info ==="
    nproc
    echo "=== Memory Info ==="
    free -h
    echo "=== Disk Info ==="
    df -h
```

### 4. Performance Regression Detection

```yaml
- name: Benchmark
  run: |
    time make build > build-time.txt
    
- name: Compare with baseline
  run: |
    CURRENT=$(cat build-time.txt | grep real | awk '{print $2}')
    BASELINE=60s  # Expected time
    # Compare and alert if regression detected
```

---

## Implementation Roadmap

### Phase 1: Quick Wins (COMPLETE) ✅
- [x] Pip caching already implemented
- [x] Timeout protection added (65 jobs)
- [x] Analysis tools created

### Phase 2: Checkout Optimization (30 minutes)
- [ ] Add fetch-depth: 1 to 2 checkouts in continuous-queue-management.yml
- [ ] Test workflows after changes
- [ ] Monitor for any issues

### Phase 3: Parallel Execution (2 hours)
- [ ] Identify workflows that can use matrix strategy
- [ ] Convert sequential tests to parallel
- [ ] Add concurrency controls

### Phase 4: Resource Optimization (2 hours)
- [ ] Review conditional execution opportunities
- [ ] Optimize artifact retention
- [ ] Implement performance monitoring

### Phase 5: Documentation (2 hours)
- [ ] Document optimization patterns
- [ ] Create performance baseline
- [ ] Setup monitoring dashboards

**Total Estimated Time:** 6-8 hours
**Expected Performance Gain:** 20-30% overall

---

## Best Practices Summary

### ✅ DO:
- Use caching for package managers (pip, npm, cargo)
- Use shallow clones (fetch-depth: 1) when possible
- Run independent jobs in parallel
- Add concurrency controls to cancel outdated runs
- Monitor cache hit rates
- Set appropriate artifact retention periods
- Use conditional execution to skip unnecessary work

### ❌ DON'T:
- Skip caching to "save space" (saves time instead)
- Use full clones when shallow is sufficient
- Run tests sequentially if they can be parallel
- Keep artifacts forever
- Run expensive operations on every commit
- Ignore performance regressions

---

## Performance Metrics

### Current Status

**Caching:**
- Pip caching: ✅ Implemented in 45+ workflows
- npm caching: ⏳ Not widely used (8 workflows)
- Docker caching: ⏳ Opportunistic (18 builds)

**Checkout:**
- Total checkouts: 3
- Optimizable: 2 (67%)
- Estimated savings: ~20s per run

**Parallel Execution:**
- Current parallelism: Moderate
- Opportunities: Many workflows could use matrix strategy
- Estimated savings: 30-40% reduction in total time

### Target Metrics

**Performance Goals:**
- Workflow startup: <30s (from checkout + setup)
- Package install: <2min with cache, <10min without
- Test execution: Parallel where possible
- Overall runtime: 20-30% faster than baseline

**Resource Goals:**
- Cache hit rate: >80%
- Artifact storage: <7 days retention
- Concurrent jobs: Optimal parallelism
- Runner utilization: Efficient job distribution

---

## Tools and Scripts

### Created Tools
1. `add_pip_caching.py` - Pip cache analysis (already applied)
2. `optimize_checkout.py` - Checkout optimization analysis
3. `add_timeouts_bulk.py` - Timeout management (complete)
4. `add_retry_logic.py` - Retry logic analysis (complete)

### Usage Examples

```bash
# Analyze checkout optimizations
python .github/scripts/optimize_checkout.py

# Analyze specific workflow
python .github/scripts/optimize_checkout.py --workflow gpu-tests.yml

# JSON output for automation
python .github/scripts/optimize_checkout.py --json
```

---

## Monitoring and Iteration

### Weekly Reviews
- Check workflow run times
- Review cache hit rates
- Identify new bottlenecks
- Adjust timeouts based on actual performance

### Monthly Optimization
- Review all workflows for new opportunities
- Update caching strategies
- Optimize parallel execution
- Measure performance improvements

### Continuous Improvement
- Monitor for performance regressions
- Stay updated on GitHub Actions features
- Share learnings with team
- Document new patterns

---

## Conclusion

Performance optimization is an ongoing process. The strategies in this guide provide a foundation for faster, more efficient workflows. Focus on high-impact optimizations first, measure results, and iterate based on data.

**Next Steps:**
1. Apply checkout optimizations (2 workflows)
2. Review parallel execution opportunities
3. Setup performance monitoring
4. Document baseline metrics
5. Iterate based on results

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Maintained By:** DevOps Team
