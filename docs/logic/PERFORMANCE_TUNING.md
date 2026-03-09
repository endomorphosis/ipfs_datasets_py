# Logic Module Performance Tuning Guide

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Production Guide

---

## Table of Contents

- [Performance Overview](#performance-overview)
- [Quick Wins](#quick-wins)
- [Caching Strategies](#caching-strategies)
- [Batch Processing](#batch-processing)
- [Memory Optimization](#memory-optimization)
- [Parallel Processing](#parallel-processing)
- [Profiling and Monitoring](#profiling-and-monitoring)
- [Advanced Optimization](#advanced-optimization)

---

## Performance Overview

### Current Baselines

| Operation | Target | Typical | Optimized |
|-----------|--------|---------|-----------|
| Simple FOL conversion | <100ms | 80-120ms | 40-60ms |
| Complex FOL conversion | <500ms | 400-600ms | 200-300ms |
| Simple proof | <1s | 500-1500ms | 200-500ms |
| Complex proof | <5s | 3-7s | 1-3s |
| Cache hit | <10ms | 5-15ms | 2-5ms |
| Batch 100 formulas | <10s | 8-12s | 4-6s |

### Performance Factors

**Good Performance:**
- ✅ Proof caching enabled (14x speedup)
- ✅ Simple, direct formulas
- ✅ Batch processing used
- ✅ Warm cache

**Poor Performance:**
- ❌ No caching (cold start)
- ❌ Complex nested formulas
- ❌ Processing one-by-one
- ❌ Large formula sets without limits

---

## Quick Wins

### 1. Enable Proof Caching (14x Speedup)

**Impact:** 🚀🚀🚀 **Critical** - 14x faster for repeated formulas

```python
from ipfs_datasets_py.logic.integration import prove_formula

# SLOW: No caching
for formula in formulas:
    result = prove_formula(formula, use_cache=False)

# FAST: Caching enabled (default)
for formula in formulas:
    result = prove_formula(formula)  # Automatically cached
```

**When to use:**
- Proving same or similar formulas repeatedly
- Production deployments
- Testing with fixed formula sets

**When to disable:**
- Testing cache behavior
- Debugging proof issues
- One-time proofs with unique formulas

---

### 2. Use Batch Processing (2-3x Speedup)

**Impact:** 🚀🚀 **High** - 2-3x faster than sequential processing

```python
from ipfs_datasets_py.logic.fol import FOLConverter

# SLOW: Process one-by-one
converter = FOLConverter()
results = []
for text in texts:
    result = converter.convert(text)
    results.append(result)

# FAST: Batch processing
converter = FOLConverter()
results = converter.convert_batch(texts, batch_size=50)
```

**Batch Size Guidelines:**
- **Small (<10 items):** No batch needed
- **Medium (10-100 items):** `batch_size=20-50`
- **Large (100-1000 items):** `batch_size=50-100`
- **Very large (1000+ items):** Use streaming or chunking

---

### 3. Set Appropriate Timeouts

**Impact:** 🚀 **Medium** - Prevents hanging on hard problems

```python
# SLOW: No timeout, may hang forever
result = prove_formula(complex_formula)

# FAST: Reasonable timeout
result = prove_formula(complex_formula, timeout=30)  # 30 seconds

# FASTEST: Lower timeout for simple cases
result = prove_formula(simple_formula, timeout=5)
```

**Timeout Guidelines:**
- **Simple proofs:** 5-10 seconds
- **Medium complexity:** 10-30 seconds
- **Complex proofs:** 30-60 seconds
- **Research/exploration:** 60-300 seconds

---

### 4. Use Fallback Mode Appropriately

**Impact:** Variable - Faster startup, slower conversion

```python
# FASTER STARTUP: Fallback mode (no spaCy/SymbolicAI loading)
converter = FOLConverter(use_fallback=True)

# FASTER CONVERSION: Full mode (if dependencies available)
converter = FOLConverter(use_symbolic=True)
```

**When to use fallback:**
- First-time setup or testing
- Minimal dependencies environment
- Simple conversions
- Startup time more important than conversion speed

**When to use full mode:**
- Production with dependencies installed
- Complex natural language
- Highest accuracy needed
- Processing many formulas

---

### 5. Optimize Formula Complexity

**Impact:** 🚀🚀 **High** - Exponential improvement for complex formulas

```python
# SLOW: Deeply nested
formula = "∀x ∀y ∀z (P(x) → (Q(y) → (R(z) → S(x,y,z))))"

# FASTER: Flattened
formula = "∀x ∀y ∀z (P(x) ∧ Q(y) ∧ R(z) → S(x,y,z))"

# FASTEST: Split into smaller formulas
formulas = [
    "∀x (P(x) → T(x))",
    "∀y (Q(y) → T(y))",
    "∀z (R(z) → T(z))",
    "∀x∀y∀z (T(x) ∧ T(y) ∧ T(z) → S(x,y,z))"
]
```

**Complexity Factors:**
- **Nesting depth** - Each level adds ~2x time
- **Quantifier count** - Each quantifier adds ~1.5x time
- **Formula length** - Linear relationship
- **Conjunction vs Disjunction** - AND is faster than OR

---

## Caching Strategies

### Proof Cache Architecture

```python
from ipfs_datasets_py.logic.integration.caching import (
    ProofCache,
    get_global_cache,
)

# Global cache (shared across application)
cache = get_global_cache()
print(f"Cache stats: {cache.stats()}")

# Local cache (isolated)
local_cache = ProofCache(max_size=1000, ttl_seconds=3600)
```

### Cache Configuration

```python
# High-memory server: Large cache
cache = ProofCache(
    max_size=10000,      # Cache up to 10K proofs
    ttl_seconds=86400,   # 24 hour TTL
)

# Low-memory server: Small cache
cache = ProofCache(
    max_size=100,        # Cache up to 100 proofs
    ttl_seconds=3600,    # 1 hour TTL
)

# Infinite cache (use with caution!)
cache = ProofCache(
    max_size=None,       # No size limit
    ttl_seconds=None,    # No expiration
)
```

### Cache Key Strategies

```python
# Option 1: Text-based keys (simple but less precise)
cache_key = hash(formula_text)

# Option 2: Structural keys (more precise)
from ipfs_datasets_py.logic.fol import normalize_formula
normalized = normalize_formula(formula_text)
cache_key = hash(normalized)

# Option 3: Semantic keys (most precise, slower)
from ipfs_datasets_py.logic.fol import parse_formula
ast = parse_formula(formula_text)
cache_key = hash(ast.to_canonical())
```

### IPFS-Backed Cache

```python
from ipfs_datasets_py.logic.integration.caching import IPFSProofCache

# Distributed cache across multiple nodes
ipfs_cache = IPFSProofCache(
    ipfs_host="localhost",
    ipfs_port=5001,
    max_size=1000,
)

# Store proof in IPFS
result = prove_formula(formula, cache=ipfs_cache)

# Retrieve from IPFS on any node
result = prove_formula(formula, cache=ipfs_cache)  # Fetches from IPFS if not local
```

**Benefits:**
- Shared cache across multiple servers
- Persistent across restarts
- Content-addressed storage
- Automatic deduplication

**Trade-offs:**
- Network latency (slower than memory)
- IPFS daemon must be running
- More complex setup

---

## Batch Processing

### Parallel Batch Processing

```python
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter()

# Sequential batch (safe, predictable)
results = converter.convert_batch(
    texts,
    batch_size=50,
    parallel=False,
)

# Parallel batch (faster, more memory)
results = converter.convert_batch(
    texts,
    batch_size=50,
    parallel=True,
    n_workers=4,  # Number of worker processes
)
```

**Worker Count Guidelines:**
- **CPU-bound tasks:** `n_workers = cpu_count()`
- **Mixed workload:** `n_workers = cpu_count() // 2`
- **Memory-constrained:** `n_workers = 2-4`
- **I/O-bound tasks:** `n_workers = cpu_count() * 2`

### Streaming Large Datasets

```python
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter()

# Don't load all into memory
with open("formulas.txt") as f:
    for chunk in chunked(f, size=100):
        results = converter.convert_batch(chunk)
        process_results(results)
        # Results can be garbage collected

def chunked(iterable, size):
    """Yield successive chunks."""
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
```

### Memory-Bounded Batch Processing

```python
import psutil

def adaptive_batch_convert(texts, max_memory_mb=1000):
    """Adjust batch size based on available memory."""
    converter = FOLConverter()
    
    process = psutil.Process()
    results = []
    
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        batch_results = converter.convert_batch(batch)
        results.extend(batch_results)
        
        # Check memory usage
        memory_mb = process.memory_info().rss / (1024 * 1024)
        if memory_mb > max_memory_mb:
            # Reduce batch size if using too much memory
            batch_size = max(10, batch_size // 2)
        elif memory_mb < max_memory_mb * 0.5:
            # Increase batch size if plenty of memory
            batch_size = min(200, batch_size * 2)
    
    return results
```

---

## Memory Optimization

### Use __slots__ for Large Formula Sets

```python
# Memory-heavy: Regular class
class Formula:
    def __init__(self, type, args):
        self.type = type
        self.args = args

# Memory-light: __slots__
class Formula:
    __slots__ = ['type', 'args', '_hash']
    
    def __init__(self, type, args):
        self.type = type
        self.args = args
        self._hash = None  # Lazy computation
```

**Impact:** 30-40% memory reduction for large formula sets

### Generator-Based Proof Search

```python
# Memory-heavy: Build all proofs upfront
def find_all_proofs(formula):
    proofs = []
    for depth in range(1, 10):
        for proof in search_at_depth(formula, depth):
            proofs.append(proof)
    return proofs

# Memory-light: Yield proofs as found
def find_proofs(formula):
    for depth in range(1, 10):
        for proof in search_at_depth(formula, depth):
            yield proof
            if proof.status == ProofStatus.PROVED:
                return  # Stop early
```

### Limit Proof Search Depth

```python
# Memory-heavy: Unlimited search
result = prove_formula(formula)  # May explore 1000+ states

# Memory-light: Limited search
result = prove_formula(formula, max_depth=5)  # Explore ≤200 states
```

### Clear Caches Periodically

```python
from ipfs_datasets_py.logic.integration.caching import get_global_cache

cache = get_global_cache()

# Check cache size
if cache.size() > 5000:
    # Clear oldest entries
    cache.evict_lru(keep=1000)

# Or clear completely
if memory_pressure():
    cache.clear()
```

---

## Parallel Processing

### Multi-Process Proving

```python
from concurrent.futures import ProcessPoolExecutor
from ipfs_datasets_py.logic.integration import prove_formula

def prove_many(formulas, n_workers=4):
    """Prove multiple formulas in parallel."""
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = [
            executor.submit(prove_formula, f)
            for f in formulas
        ]
        results = [f.result() for f in futures]
    return results

# Usage
results = prove_many(formulas, n_workers=8)
```

### Thread-Based Conversion

```python
from concurrent.futures import ThreadPoolExecutor
from ipfs_datasets_py.logic.fol import FOLConverter

def convert_many(texts, n_workers=4):
    """Convert multiple texts in parallel (thread-safe)."""
    converter = FOLConverter()
    
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        results = list(executor.map(converter.convert, texts))
    
    return results
```

**When to use threads vs processes:**
- **Threads:** I/O-bound tasks, shared cache, lower overhead
- **Processes:** CPU-bound tasks, no GIL contention, isolated failures

---

## Profiling and Monitoring

### Built-in Performance Monitoring

```python
from ipfs_datasets_py.logic.common import UtilityMonitor, track_performance

# Enable monitoring
monitor = UtilityMonitor()

# Track specific operation
with track_performance("my_conversion") as metrics:
    result = converter.convert(text)

# Get statistics
stats = monitor.get_stats()
print(f"Average conversion time: {stats['my_conversion']['avg_ms']}ms")
print(f"P95 latency: {stats['my_conversion']['p95_ms']}ms")
```

### Profile Slow Operations

```python
import cProfile
import pstats

# Profile a function
profiler = cProfile.Profile()
profiler.enable()

result = slow_operation()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 slowest functions
```

### Memory Profiling

```python
from memory_profiler import profile

@profile
def memory_intensive_operation():
    results = []
    for i in range(1000):
        result = converter.convert(f"Formula {i}")
        results.append(result)
    return results

# Run and see memory usage line-by-line
memory_intensive_operation()
```

### Real-Time Monitoring

```python
from ipfs_datasets_py.logic.monitoring import PerformanceMonitor

monitor = PerformanceMonitor(
    log_interval=60,  # Log stats every 60s
    alert_threshold_ms=1000,  # Alert if operation >1s
)

with monitor.track("conversion"):
    result = converter.convert(text)

# Metrics exported to stdout, logs, or metrics service
```

---

## Advanced Optimization

### Pre-compilation and Caching

```python
import re

class OptimizedFallback:
    # Compile patterns once at class level
    QUANTIFIER_PATTERN = re.compile(
        r'\b(all|every|each|some|exists?)\b',
        re.IGNORECASE
    )
    PREDICATE_PATTERN = re.compile(
        r'([A-Z][a-z]*)\s*\(',
        re.MULTILINE
    )
    
    def extract_quantifiers_fast(self, text):
        # Single pass with compiled pattern
        return self.QUANTIFIER_PATTERN.findall(text)
```

### AST Caching

```python
from functools import lru_cache

class CachedConverter:
    @lru_cache(maxsize=1000)
    def parse(self, text: str):
        """Parse with automatic AST caching."""
        return self._slow_parse(text)
    
    def convert(self, text: str):
        ast = self.parse(text)  # Cached!
        return self.generate_fol(ast)
```

### Lazy Evaluation

```python
class LazyFormula:
    def __init__(self, text):
        self._text = text
        self._ast = None
        self._normalized = None
    
    @property
    def ast(self):
        """Parse only when needed."""
        if self._ast is None:
            self._ast = parse_formula(self._text)
        return self._ast
    
    @property
    def normalized(self):
        """Normalize only when needed."""
        if self._normalized is None:
            self._normalized = normalize(self.ast)
        return self._normalized
```

### Algorithm Optimizations

```python
# SLOW: O(n²) tree traversal
def find_variables_slow(formula):
    variables = []
    for node in formula.nodes:
        for child in node.children:
            if child.is_variable():
                variables.append(child)
    return list(set(variables))

# FAST: O(n) single-pass traversal
def find_variables_fast(formula):
    variables = set()
    def visit(node):
        if node.is_variable():
            variables.add(node)
        for child in node.children:
            visit(child)
    visit(formula.root)
    return list(variables)
```

---

## Performance Checklist

### Before Production

- [ ] Enable proof caching
- [ ] Set appropriate timeouts
- [ ] Use batch processing for multiple items
- [ ] Configure cache size based on available memory
- [ ] Test with representative data
- [ ] Profile slow operations
- [ ] Monitor memory usage
- [ ] Set up performance monitoring
- [ ] Document expected performance
- [ ] Plan for scale (10x current load)

### Ongoing Optimization

- [ ] Review cache hit rates (aim for >80%)
- [ ] Monitor P95/P99 latencies
- [ ] Profile new features
- [ ] Test with production data
- [ ] Optimize slow paths
- [ ] Update performance baselines
- [ ] Document optimization wins
- [ ] Share performance tips with team

---

## Performance Troubleshooting

### "Conversions are slow"

1. **Check if caching is enabled**
   ```python
   converter = FOLConverter(use_cache=True)
   ```

2. **Use batch processing**
   ```python
   results = converter.convert_batch(texts)
   ```

3. **Profile to find bottleneck**
   ```python
   python -m cProfile -o profile.stats script.py
   ```

### "High memory usage"

1. **Use streaming for large datasets**
2. **Set cache size limits**
3. **Use generators instead of lists**
4. **Clear cache periodically**
5. **Limit proof search depth**

### "Timeouts occur frequently"

1. **Increase timeout**
   ```python
   result = prove_formula(formula, timeout=60)
   ```

2. **Simplify formulas**
3. **Split into smaller problems**
4. **Use faster prover backend**

---

## Benchmarking

### Run Built-in Benchmarks

```bash
cd ipfs_datasets_py/logic
python benchmarks.py --quick
python benchmarks.py --full
python benchmarks.py --compare baseline.json
```

### Custom Benchmarks

```python
import time
import statistics

def benchmark(func, *args, iterations=100):
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func(*args)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)  # Convert to ms
    
    return {
        'mean': statistics.mean(times),
        'median': statistics.median(times),
        'stdev': statistics.stdev(times) if len(times) > 1 else 0,
        'min': min(times),
        'max': max(times),
        'p95': sorted(times)[int(len(times) * 0.95)],
        'p99': sorted(times)[int(len(times) * 0.99)],
    }

# Run benchmark
stats = benchmark(converter.convert, "All cats are animals")
print(f"Mean: {stats['mean']:.2f}ms, P95: {stats['p95']:.2f}ms")
```

---

## Summary

**Quick Wins:**
1. ✅ Enable proof caching (14x speedup)
2. ✅ Use batch processing (2-3x speedup)
3. ✅ Set appropriate timeouts
4. ✅ Choose right fallback mode
5. ✅ Optimize formula complexity

**Advanced:**
- Parallel processing with threads/processes
- Memory optimization with __slots__ and generators
- AST caching and lazy evaluation
- Algorithm optimizations
- Custom benchmarking

**Monitoring:**
- Built-in performance monitoring
- cProfile for profiling
- memory_profiler for memory
- Real-time metrics

**For more details:**
- [PHASE7_PERFORMANCE_OPTIMIZATION_PLAN.md](./PHASE7_PERFORMANCE_OPTIMIZATION_PLAN.md) - Performance roadmap
- [CACHING_ARCHITECTURE.md](./CACHING_ARCHITECTURE.md) - Cache design
- [API_REFERENCE.md](./API_REFERENCE.md) - API documentation

---

**Document Status:** Production Guide  
**Maintained By:** Logic Module Maintainers  
**Review Frequency:** Every MINOR release
