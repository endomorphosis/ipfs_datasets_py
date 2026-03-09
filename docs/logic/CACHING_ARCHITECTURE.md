# Caching Architecture Guide

**Last Updated:** 2026-02-20  
**Status:** Production-Ready  
**Version:** 1.0

## Overview

The Logic Module employs a sophisticated multi-layered caching architecture to achieve significant performance improvements while maintaining consistency and correctness. This document provides comprehensive guidance on caching strategies, implementation patterns, and best practices.

## Key Achievements

- **14x cache speedup** - Validated on FOL converter
- **48x utility cache speedup** - Performance monitoring with caching
- **Proof cache** - Thread-safe, IPFS-backed persistent caching
- **Graceful degradation** - Works without IPFS, falls back to in-memory

## Cache Layers

### Layer 1: Proof Execution Cache

Caches complete proof execution results including:
- Query (goal formula)
- Context (axioms)
- Proof result
- Metadata (time, method, confidence)

**Usage:**
```python
from ipfs_datasets_py.logic.integration.caching import ProofCache

cache = ProofCache(
    max_entries=1000,
    ttl_seconds=3600,
    use_ipfs=True
)

# Check cache
result = cache.get(goal, axioms)
if result:
    return result

# Compute proof
result = prover.prove(goal, axioms)

# Store in cache
cache.set(goal, axioms, result)
```

**Benefits:**
- Avoids expensive proof recomputation
- Fast proof verification
- IPFS-backed persistence (optional)

### Layer 2: Formula Conversion Cache

Caches text → formula conversions with:
- Input text
- Output formula
- Confidence score
- Parse metadata

**Usage:**
```python
from ipfs_datasets_py.logic.common import BoundedCache

cache = BoundedCache(
    max_size=500,
    ttl_seconds=3600,
    eviction_policy="lru"
)

# Check cache
formula = cache.get(text)
if formula:
    return formula

# Convert text to formula
formula = convert_text_to_formula(text)

# Cache result
cache.set(text, formula)
```

**Benefits:**
- Reuse formula conversions
- Avoid NLP overhead
- Confidence-aware caching

### Layer 3: Conversion Result Cache

Caches complete conversion results:
- Input
- Output formula
- Confidence
- Metadata (source, domain, etc.)

**Implementation:**
```python
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter(
    use_cache=True,
    cache_max_size=1000,
    use_ml=True
)

# Automatic caching
result = converter.convert("All humans are mortal")
print(f"Cached: {result.from_cache}")
print(f"Confidence: {result.confidence}")
```

## Cache Types

### BoundedCache

Thread-safe in-memory cache with TTL and LRU eviction.

**Features:**
- Configurable max size (default: 100)
- TTL support (optional)
- LRU eviction policy
- Thread-safe operations
- Memory efficient

**Usage:**
```python
from ipfs_datasets_py.logic.common import BoundedCache

# Basic usage
cache = BoundedCache(max_size=500)
cache.set("key", "value")
value = cache.get("key")

# With TTL
cache = BoundedCache(
    max_size=1000,
    ttl_seconds=3600  # 1 hour
)

# Clear
cache.clear()
cache.delete("key")

# Statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Size: {stats['size']}/{stats['max_size']}")
```

### ProofCache

Specialized cache for proof results with IPFS backing.

**Features:**
- Proof result persistence
- IPFS-backed optional storage
- Metadata tracking
- Batch operations

**Usage:**
```python
from ipfs_datasets_py.logic.integration.caching import ProofCache

cache = ProofCache(
    max_entries=1000,
    ttl_seconds=86400,  # 24 hours
    use_ipfs=True
)

# Store proof result
cache.set(goal, axioms, proof_result)

# Retrieve
result = cache.get(goal, axioms)

# Batch operations
cache.set_batch([(g1, a1, r1), (g2, a2, r2)])
results = cache.get_batch([(g1, a1), (g2, a2)])
```

## Caching Patterns

### Pattern 1: Eager Caching

Cache results immediately after computation.

```python
def convert_formula(text):
    cache_key = hash_text(text)
    
    # Check cache
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    # Compute
    result = _convert_uncached(text)
    
    # Store immediately
    cache.set(cache_key, result)
    
    return result
```

**When to use:**
- High-cost operations
- Predictable access patterns
- Available cache capacity

### Pattern 2: Lazy Caching

Cache only when memory allows.

```python
def convert_formula(text):
    result = _convert_uncached(text)
    
    # Try to cache (fails silently if full)
    try:
        cache.set(text, result)
    except CacheFullError:
        pass  # Cache full, skip
    
    return result
```

**When to use:**
- Low-cost operations
- Unpredictable access patterns
- Limited memory

### Pattern 3: Batch Caching

Preload cache with common inputs.

```python
def initialize_cache(common_texts):
    for text in common_texts:
        formula = _convert_uncached(text)
        cache.set(text, formula)

# Preload
initialize_cache([
    "All humans are mortal",
    "P -> Q",
    "forall x. P(x)"
])
```

**When to use:**
- Known workload patterns
- Startup optimization
- High-value inputs

## Performance Guidelines

### Cache Hit Rates

Target cache hit rates by operation:

| Operation | Target Hit Rate | Note |
|-----------|-----------------|------|
| Proof verification | 85-95% | Proofs often repeat |
| Formula conversion | 70-85% | Common formulas |
| Domain extraction | 60-80% | Repeated texts |
| Type checking | 90%+ | Consistent types |

### Size Recommendations

```python
# Estimated sizing
# Formula cache: 50-100 UTF-8 chars average
# Proof cache: 500-1000 bytes average

# Cache size in entries
formula_cache_size = available_memory_mb * 1000 / 0.05  # 50 bytes avg
proof_cache_size = available_memory_mb * 1000 / 0.75    # 750 bytes avg

# Example: 100MB available memory
formula_cache = 100 * 1000 / 0.05      # 2M entries
proof_cache = 100 * 1000 / 0.75        # 133K entries
```

### TTL Strategies

**Short TTL (1-5 minutes):**
- Frequently changing data
- User session cache
- Temporary results

**Medium TTL (1-24 hours):**
- Stable formulas
- Proof results
- Domain knowledge

**Long TTL (24+ hours):**
- Reference data
- Type definitions
- Rarely changing content

```python
# Example: Tiered TTL strategy
cache = BoundedCache(max_size=10000)

# Set different TTLs based on type
if is_user_specific(data):
    ttl = 300  # 5 minutes
elif is_proof(data):
    ttl = 3600  # 1 hour
else:
    ttl = 86400  # 24 hours

cache.set(key, value, ttl=ttl)
```

## IPFS Integration

### Persistent Cache with IPFS

Store cache in IPFS for distributed access and persistence.

**Usage:**
```python
from ipfs_datasets_py.logic.integration.caching import ProofCache

# IPFS-backed cache
cache = ProofCache(
    max_entries=1000,
    use_ipfs=True,
    ipfs_gateway="http://localhost:5001"
)

# Store in IPFS
proof = generate_proof(goal, axioms)
cache.set(goal, axioms, proof)

# Retrieve (checks IPFS if not in memory)
cached_proof = cache.get(goal, axioms)

# Access IPFS directly
ipfs_hash = cache.get_ipfs_hash(goal, axioms)
```

**Benefits:**
- Distributed caching
- Immutable storage
- Content-addressable
- Transparent failover

### Graceful Fallback

Cache automatically degrades without IPFS.

```python
# Works with or without IPFS
cache = ProofCache(use_ipfs=True)

# If IPFS unavailable, uses in-memory cache
# If IPFS available, syncs to IPFS
# Transparent to caller
```

## Monitoring & Debugging

### Cache Statistics

```python
from ipfs_datasets_py.logic.common import BoundedCache

cache = BoundedCache(max_size=1000)

# Get statistics
stats = cache.get_stats()
print(f"Hits: {stats['hits']}")
print(f"Misses: {stats['misses']}")
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Size: {stats['size']}/{stats['max_size']}")
print(f"Age: {stats['age_seconds']}s")
```

### Performance Tracking

```python
from ipfs_datasets_py.logic.common import track_performance

@track_performance
def expensive_operation(data):
    return process(data)

# Metrics recorded automatically
result = expensive_operation(data)
# Prints: "expensive_operation: 125.34ms"
```

### Debug Mode

```python
import logging

# Enable debug logging
logging.getLogger('ipfs_datasets_py.logic.common').setLevel(logging.DEBUG)

# See cache operations
cache.debug = True
cache.set(k, v)  # Logs: "Cache SET k (size: 1/100)"
cache.get(k)     # Logs: "Cache HIT k"
```

## Best Practices

### 1. Choose Appropriate Cache Size

**Too small:** High miss rate, low benefit
**Too large:** Memory waste, slower eviction

```python
# Rule of thumb: 2-5 minutes of typical operations
operations_per_minute = 1000
cache_size = operations_per_minute * 3  # 3000 entries
```

### 2. Set Realistic TTLs

```python
# Cache for as long as data is valid
if data_changes_frequently:
    ttl = 60  # 1 minute
elif data_stable:
    ttl = 3600  # 1 hour
else:
    ttl = None  # No expiration
```

### 3. Monitor Hit Rates

```python
import time

def monitor_cache(cache, interval_seconds=60):
    while True:
        stats = cache.get_stats()
        if stats['hit_rate'] < 0.5:
            logging.warning(
                f"Low cache hit rate: {stats['hit_rate']:.1%}"
            )
        time.sleep(interval_seconds)
```

### 4. Use Batch Operations

```python
# Inefficient: Individual operations
for text in texts:
    cache.set(text, convert(text))

# Efficient: Batch operation
results = [convert(text) for text in texts]
cache.set_batch(zip(texts, results))
```

### 5. Clear Cache When Needed

```python
def clear_expired():
    cache.clear()  # Clear all
    
def clear_pattern(pattern):
    for key in cache.keys():
        if pattern in key:
            cache.delete(key)
```

## Troubleshooting

### Issue: Low Cache Hit Rate

**Symptoms:**
- Cache hit rate < 50%
- Memory usage low
- Performance not improved

**Solutions:**
1. Increase cache size
2. Check TTL settings (might be too short)
3. Verify cache key stability
4. Profile access patterns

```python
# Analyze patterns
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Size used: {stats['size']}/{stats['max_size']}")

if stats['hit_rate'] < 0.5 and stats['size'] < stats['max_size']:
    # Cache has room but low hits - TTL too short
    logging.warning("TTL might be too short")
```

### Issue: Memory Pressure

**Symptoms:**
- High memory usage
- OOM errors
- Frequent evictions

**Solutions:**
1. Reduce cache size
2. Use shorter TTL
3. Implement stricter eviction
4. Clear cache periodically

```python
# Reduce memory imprint
cache = BoundedCache(
    max_size=100,  # Smaller
    ttl_seconds=300  # Shorter
)

# Periodic cleanup
def cleanup_cache():
    stats = cache.get_stats()
    if stats['size'] > stats['max_size'] * 0.9:
        cache.clear()
```

### Issue: Stale Data

**Symptoms:**
- Cached data not reflecting updates
- TTL settings seem wrong
- Inconsistency issues

**Solutions:**
1. Shorter TTL
2. Manual invalidation on updates
3. Cache versioning

```python
# Invalidate on update
def update_formula(text, new_formula):
    formula_cache.delete(text)
    store_formula(text, new_formula)

# Version-aware caching
cache.set(f"formula:v1:{text}", formula)
cache.get(f"formula:v{version}:{text}")
```

## Configuration Examples

### Development Setup

```python
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter(
    use_cache=True,
    cache_max_size=100,      # Small for quick testing
    use_ml=False             # Skip ML for speed
)
```

### Production Setup

```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.integration.caching import ProofCache

# Formula converter with caching
fol_converter = FOLConverter(
    use_cache=True,
    cache_max_size=10000,
    use_ml=True
)

# Proof cache with IPFS
proof_cache = ProofCache(
    max_entries=5000,
    ttl_seconds=86400,
    use_ipfs=True
)
```

### High-Performance Setup

```python
# Multi-layer caching
fol_cache = BoundedCache(max_size=50000, ttl_seconds=3600)
proof_cache = ProofCache(max_entries=10000, use_ipfs=True)
utility_cache = BoundedCache(max_size=100000, ttl_seconds=1800)

# Batch preloading
preload_formulas = load_common_formulas()
for formula in preload_formulas:
    fol_cache.set(formula.text, formula)
```

## Migration Guide

### From Legacy Cache

If migrating from old caching system:

```python
# Old style
old_cache = {}
def convert(text):
    if text in old_cache:
        return old_cache[text]
    result = _convert(text)
    old_cache[text] = result
    return result

# New style
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter(use_cache=True)
result = converter.convert(text)  # Automatic caching
```

## References

- **[README.md](./README.md)** - Module overview
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - System architecture
- **[common/README.md](./common/README.md)** - Common utilities
- **[PERFORMANCE_TUNING.md](./PERFORMANCE_TUNING.md)** - Performance optimization

---

**Version:** 1.0  
**Last Updated:** 2026-02-20  
**Status:** Production-Ready  
**Maintainers:** Logic Module Team
