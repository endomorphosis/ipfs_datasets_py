# Relationship Inference Performance Analysis

**Date:** 2025-02-20  
**Task:** Profile `infer_relationships()` bottlenecks (P2 Priority 1)  
**Status:** COMPLETED  

---

## Executive Summary

Profiling reveals that `infer_relationships()` exhibits **O(n²)** scaling behavior due to co-occurrence window calculations. Performance degrades dramatically with entity count:

- **20 entities**: 159K rels/sec (0.5ms total)
- **100 entities**: 45K rels/sec (10ms total) — **3.5x slower per relationship**
- **500 entities**: 2K rels/sec (1.1s total) — **79x slower**
- **1000 entities**: 0.5K rels/sec (8.7s total) — **315x slower**

**Primary Bottlenecks:**
1. **String `.lower()` calls** — 4ms cumulative (33% of execution time)
2. **String `.find()` calls** — 3ms cumulative (25% of execution time)
3. **Nested entity iteration** — O(n²) loop structure accounting for 4,950 pairs in 100-entity test

**Impact:** For large ontology extraction workloads (500+ entities), relationship inference becomes the dominant bottleneck, consuming seconds instead of milliseconds.

---

## Profiling Data

### Methodology

**Profiling Script:** `/home/barberb/complaint-generator/ipfs_datasets_py/scripts/profile_infer_relationships.py`

**Test Configuration:**
- **Warm-up:** 10 entities, 1000 chars to populate pattern caches
- **Measurement:** Full entity set, realistic legal text corpus
- **Profiler:** Python `cProfile` with cumulative/time sorting

**Sample Data:**
- Entity types: Person, Organization, Location, Document, Event, Obligation, Contract, Payment, Statute, Case
- Text corpus: Legal complaint templates with verb frames ("X owns Y", "X obligates Y to pay")
- Realistic co-occurrence density (~200 char proximity windows)

### Benchmark Results

```
Size         Entities       Rels     Time (s)     Rels/sec
----------------------------------------------------------------
small              20         78       0.0005    159,138.85
medium            100        449       0.0098     45,923.40
large             500       2211       1.0951      2,018.98
xlarge           1000       4410       8.7194       505.77
```

**Scaling Analysis:**
- 5x entity increase (20→100): **3.5x throughput decrease**
- 5x entity increase (100→500): **22.7x throughput decrease**
- 2x entity increase (500→1000): **4x throughput decrease**

**Conclusion:** Near-quadratic scaling confirms O(n²) complexity hypothesis.

### Top Functions by Time

**Medium Entity Set (100 entities, 0.012s total):**

| Function | Calls | Time (s) | % Total | Category |
|----------|-------|----------|---------|----------|
| `.lower()` | 11,298 | 0.0040 | 33% | **String operations** |
| `infer_relationships()` | 1 | 0.0040 | 33% | Core logic |
| `.find()` | 5,052 | 0.0030 | 25% | **String search** |
| `abs()` | 4,950 | 0.0001 | 1% | Distance calc |
| `_make_rel_id()` | 449 | 0.0001 | 1% | ID generation |
| Other | — | 0.0007 | 6% | Misc overhead |

**Key Observations:**
1. **58% of time** spent on string operations (`.lower()` + `.find()`)
2. **11,298 `.lower()` calls** for 100 entities → ~113 calls per entity (heavy duplication)
3. **5,052 `.find()` calls** for co-occurrence search → O(n²) nested loops
4. **4,950 `abs()` calls** → ~50 distance calculations per entity (co-occurrence pairs)

---

## Root Cause Analysis

### 1. Repeated String Lowercasing (33% of time)

**Code Path:** [ontology_generator.py:2782-2820](../ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/ontology_generator.py#L2782-L2820)

**Problem:**
```python
entity_texts = {e.text.lower(): e for e in entities}  # Call 1: Dict construction
entity_ids_by_text = {e.text.lower(): e.id for e in entities}  # Call 2: Duplicate lowering

# Later in co-occurrence loop:
for i, e1 in enumerate(entity_list):
    pos1 = text.lower().find(e1.text.lower())  # Call 3: e1.text lowered again
    for e2 in entity_list[i + 1:]:
        pos2 = text.lower().find(e2.text.lower())  # Call 4: e2.text lowered again
```

**Impact:**
- Each entity text lowered **multiple times** (dict construction + nested loop)
- For 100 entities with ~50 pairs each: **~11K `.lower()` calls**
- **4ms cumulative time** (33% of total)

**Solution:** Pre-compute lowercased strings once, cache in `Entity` preprocessing or local dict.

### 2. Redundant Text Searching (25% of time)

**Code Path:** [ontology_generator.py:2882-2885](../ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/ontology_generator.py#L2882-L2885)

**Problem:**
```python
for i, e1 in enumerate(entity_list):
    pos1 = text.lower().find(e1.text.lower())  # Search entire text for e1
    if pos1 < 0:
        continue
    for e2 in entity_list[i + 1:]:
        pos2 = text.lower().find(e2.text.lower())  # Search entire text for e2
        if pos2 < 0:
            continue
        distance = abs(pos1 - pos2)  # Calculate distance
```

**Impact:**
- **5,052 `.find()` calls** for 100 entities (nested loop behavior)
- Linear scan of entire text corpus for each entity pair
- **3ms cumulative time** (25% of total)

**Solution:** Pre-compute entity positions once before loop, store in dict/list.

### 3. O(n²) Loop Complexity

**Code Path:** [ontology_generator.py:2880-2930](../ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/ontology_generator.py#L2880-L2930)

**Problem:**
```python
for i, e1 in enumerate(entity_list):
    for e2 in entity_list[i + 1:]:  # O(n²) nested iteration
        # Process (e1, e2) pair
```

**Impact:**
- **4,950 pairs** for 100 entities → `n(n-1)/2` pairs checked
- For 500 entities: **124,750 pairs** → 1.1s execution time
- For 1000 entities: **499,500 pairs** → 8.7s execution time

**Solutions:**
1. **Spatial indexing:** Use R-tree or interval tree to query only entities within 200-char proximity window
2. **Early termination:** Skip distant pairs based on sorted position index
3. **Parallel processing:** Parallelize pair processing with `multiprocessing` for large entity sets

---

## Optimization Recommendations

### Priority 1: String Operation Caching (High Impact, Low Effort)

**Problem:** 11,298 redundant `.lower()` calls for 100 entities

**Solution:**
```python
def infer_relationships(self, entities, context, data=None):
    text = str(data) if data is not None else ""
    text_lower = text.lower()  # ✅ Compute once
    
    # Pre-compute lowercased entity texts (avoid repeated lowering)
    entity_lower_map = {e.id: e.text.lower() for e in entities}  # ✅ One pass
    entity_texts = {entity_lower_map[e.id]: e for e in entities}
    entity_ids_by_text = {entity_lower_map[e.id]: e.id for e in entities}
    
    # Later in co-occurrence loop:
    for i, e1 in enumerate(entity_list):
        e1_text_lower = entity_lower_map[e1.id]  # ✅ Cached lookup
        pos1 = text_lower.find(e1_text_lower)  # ✅ Use pre-lowered text
```

**Expected Impact:**
- **Eliminates ~10K redundant `.lower()` calls** (90% reduction)
- **Saves ~3-4ms per 100 entities** (~33% speedup)
- **Simple implementation** (5 LOC change)

### Priority 1: Position Pre-Computation (High Impact, Medium Effort)

**Problem:** 5,052 redundant `.find()` calls for 100 entities

**Solution:**
```python
def infer_relationships(self, entities, context, data=None):
    text_lower = text.lower()
    entity_lower_map = {e.id: e.text.lower() for e in entities}
    
    # ✅ Pre-compute positions for all entities ONCE
    entity_positions = {}
    for e in entities:
        pos = text_lower.find(entity_lower_map[e.id])
        if pos >= 0:
            entity_positions[e.id] = pos
    
    # Co-occurrence loop using cached positions
    for i, e1 in enumerate(entity_list):
        pos1 = entity_positions.get(e1.id)
        if pos1 is None:
            continue
        for e2 in entity_list[i + 1:]:
            pos2 = entity_positions.get(e2.id)
            if pos2 is None:
                continue
            distance = abs(pos1 - pos2)  # ✅ No redundant searching
```

**Expected Impact:**
- **Eliminates ~5K redundant `.find()` calls** (99% reduction to single pass)
- **Saves ~3ms per 100 entities** (~25% speedup)
- **Combined with Priority 1:** ~50-60% total speedup for 100 entities

### Priority 2: Regex Pattern Pre-Compilation (Medium Impact, Low Effort)

**Problem:** Verb-frame patterns compiled on first access, but `re.finditer()` overhead still present

**Current Implementation:** Patterns already lazy-loaded via `_get_verb_patterns()`, but compilation check happens per call.

**Solution:**
```python
# At class level (already done, but verify compiled status)
_COMPILED_VERB_PATTERNS = None

@classmethod
def _get_verb_patterns(cls):
    if cls._COMPILED_VERB_PATTERNS is None:
        import re
        cls._COMPILED_VERB_PATTERNS = [
            (re.compile(pattern, re.IGNORECASE), rel_type)  # ✅ Pre-compile
            for pattern, rel_type in _RAW_VERB_PATTERNS
        ]
    return cls._COMPILED_VERB_PATTERNS

# Usage:
for pattern_re, rel_type in _VERB_PATTERNS:
    for m in pattern_re.finditer(text):  # ✅ Use compiled regex directly
```

**Expected Impact:**
- **Reduces regex overhead** (~0.5-1ms per 100 entities)
- **Already partially implemented** (lazy loading exists, verify compilation)
- **Minimal code change** (ensure storing compiled objects, not strings)

### Priority 2: Spatial Indexing for Co-Occurrence (High Impact, High Effort)

**Problem:** O(n²) pair iteration wastes time on distant entities that won't meet 200-char proximity threshold

**Solution:**
```python
from intervaltree import IntervalTree

def infer_relationships(self, entities, context, data=None):
    # Build interval tree: [pos, pos+len] → entity
    tree = IntervalTree()
    entity_lower_map = {e.id: e.text.lower() for e in entities}
    entity_positions = {}
    
    for e in entities:
        text_lower_e = entity_lower_map[e.id]
        pos = text_lower.find(text_lower_e)
        if pos >= 0:
            entity_positions[e.id] = pos
            tree.add(Interval(pos, pos + len(text_lower_e), e))
    
    # Query only entities within 200-char window
    for e1 in entities:
        pos1 = entity_positions.get(e1.id)
        if pos1 is None:
            continue
        
        # ✅ Query tree for entities in [pos1-200, pos1+200] range
        nearby = tree.overlap(pos1 - 200, pos1 + 200)
        for interval in nearby:
            e2 = interval.data
            if e1.id >= e2.id:  # Avoid duplicates
                continue
            pos2 = entity_positions[e2.id]
            distance = abs(pos1 - pos2)
            # ... create relationship
```

**Expected Impact:**
- **Reduces from O(n²) to O(n log n)** for sparse entity distributions
- **Dramatic speedup for large entity sets** (500+ entities)
- **Example:** 1000 entities with 10% proximity rate: 499K pairs → ~50K pairs (10x reduction)
- **Dependencies:** Requires `intervaltree` library

**Trade-offs:**
- Added complexity (~30 LOC)
- External dependency
- Most beneficial for large, sparse entity distributions

---

## Implementation Plan

### Phase 1: Quick Wins (Priority 1 — Target: 50-60% speedup)

**Week 1:**
1. ✅ Create profiling script (`profile_infer_relationships.py`) — **DONE**
2. ✅ Run baseline benchmarks — **DONE**
3. Implement string operation caching (`.lower()` deduplication) — **~2 hours**
4. Implement position pre-computation (`.find()` deduplication) — **~3 hours**
5. Write unit tests for optimizations — **~2 hours**
6. Re-run benchmarks and validate speedup — **~1 hour**

**Expected Outcome:** 100-entity workload: 0.012s → **0.005-0.006s** (~50-60% faster)

### Phase 2: Pattern Optimization (Priority 2 — Target: 10% additional speedup)

**Week 2:**
1. Verify regex pattern pre-compilation working correctly — **~1 hour**
2. Add compilation status logging/assertion — **~1 hour**
3. Benchmark regex performance — **~1 hour**

**Expected Outcome:** 100-entity workload: +0.5-1ms improvement

### Phase 3: Algorithmic Improvement (Priority 2 — Target: 10x+ for large workloads)

**Future Sprint:**
1. Evaluate intervaltree vs. custom sorted-list implementation — **~4 hours**
2. Implement spatial indexing for co-occurrence — **~8 hours**
3. Add integration tests with large entity sets (500-1000 entities) — **~4 hours**
4. Document usage and performance characteristics — **~2 hours**

**Expected Outcome:** 1000-entity workload: 8.7s → **<1s** (10x+ faster)

---

## Testing Strategy

### Regression Tests

**File:** `ipfs_datasets_py/tests/unit/optimizers/graphrag/test_infer_relationships_performance.py`

**Test Cases:**
1. **Correctness validation:** Ensure optimized version produces identical relationships as baseline
2. **Edge cases:** Empty entity sets, single entity, no text data
3. **Performance benchmarks:** Assert <= 0.010s for 100 entities on reference hardware
4. **Scaling validation:** Assert relationship count consistency across optimizations

### Benchmark Comparison

**Before/After Comparison:**
| Entity Count | Baseline (s) | Optimized (s) | Speedup |
|--------------|--------------|---------------|---------|
| 20 | 0.0005 | TBD | TBD |
| 100 | 0.0098 | TBD | TBD |
| 500 | 1.0951 | TBD | TBD |
| 1000 | 8.7194 | TBD | TBD |

---

## Success Metrics

### Phase 1 (Quick Wins) — Target Completion: Week 1

- [x] **Profiling complete** — Baseline established
- [ ] **50% speedup** for 100-entity workloads (0.012s → 0.006s)
- [ ] **Zero regressions** — All existing tests pass
- [ ] **Correctness verified** — Identical relationship sets produced

### Phase 2 (Pattern Optimization) — Target Completion: Week 2

- [ ] **60% cumulative speedup** for 100-entity workloads
- [ ] **Regex overhead < 5%** of total execution time

### Phase 3 (Algorithmic) — Future Sprint

- [ ] **10x speedup** for 1000-entity workloads (8.7s → <1s)
- [ ] **O(n log n) scaling** demonstrated empirically
- [ ] **Documentation updated** with spatial indexing usage guidelines

---

## Recommendations Summary

**Immediate Actions (This Week):**
1. ✅ Complete profiling baseline — **DONE**
2. Implement Priority 1 optimizations (caching) — **High ROI, low risk**
3. Write regression tests — **Prevent correctness issues**

**Short-Term Actions (Next Sprint):**
4. Verify regex compilation working correctly
5. Document performance characteristics in code comments

**Long-Term Actions (Future):**
6. Consider spatial indexing for production deployments with large entity sets (500+ entities)
7. Explore parallel processing for multi-document batch extraction

**Do Not Optimize (Low ROI):**
- `abs()` calls — Already optimized (~1% of time)
- `_make_rel_id()` — Trivial overhead
- Logging — Only 2 calls per invocation

---

## Appendix: Profiling Output

### Full cProfile Output (Medium Entity Set)

```
================================================================================
TOP FUNCTIONS BY CUMULATIVE TIME
================================================================================
         27033 function calls in 0.012 seconds

   Ordered by: cumulative time
   List reduced from 76 to 25 due to restriction <25>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.004    0.004    0.012    0.012 ontology_generator.py:2782(infer_relationships)
    11298    0.004    0.000    0.004    0.000 {method 'lower' of 'str' objects}
     5052    0.003    0.000    0.003    0.000 {method 'find' of 'str' objects}
     4950    0.000    0.000    0.000    0.000 {built-in method builtins.abs}
      449    0.000    0.000    0.000    0.000 {method 'append' of 'list' objects}
      449    0.000    0.000    0.000    0.000 {method 'add' of 'set' objects}
```

### Bottleneck Identification

```
⚠️  Case folding overhead: {method 'lower' of 'str' objects} (33.3% of time)
    → Consider caching lowercased strings

⚠️  String search overhead: {method 'find' of 'str' objects} (25.0% of time)
    → Consider position caching or indexing
```

### Benchmark Scaling Data

```
BENCHMARK: Relationship Inference Scaling
================================================================================
Size         Entities       Rels     Time (s)     Rels/sec
--------------------------------------------------------------------------------
small              20         78       0.0005    159138.85
medium            100        449       0.0098     45923.40
large             500       2211       1.0951      2018.98
xlarge           1000       4410       8.7194       505.77
```

**Complexity Analysis:**
- **20 → 100 entities:** 5x increase → 19.6x time increase (near O(n²))
- **100 → 500 entities:** 5x increase → 111.8x time increase (super-quadratic due to cache effects)
- **500 → 1000 entities:** 2x increase → 8.0x time increase (cache-limited quadratic)

---

**Status:** Profiling complete, optimization roadmap defined  
**Next Steps:** Implement Phase 1 optimizations (string caching, position pre-computation)  
**Owner:** TBD  
**Reviewers:** TBD  
**Last Updated:** 2025-02-20
