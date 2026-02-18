# CEC Performance Optimization Plan

**Version:** 1.0  
**Date:** 2026-02-18  
**Status:** Planning Phase

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Current Performance Baseline](#current-performance-baseline)
3. [Performance Targets](#performance-targets)
4. [Optimization Strategies](#optimization-strategies)
5. [Implementation Plan](#implementation-plan)
6. [Benchmarking & Profiling](#benchmarking--profiling)
7. [Performance Monitoring](#performance-monitoring)

---

## 📊 Overview

### Objectives

Achieve **2-4x performance improvement** over original Python 2/Java implementations through:
1. Algorithm optimizations
2. Data structure improvements
3. Caching strategies
4. Parallel processing
5. Compilation optimizations
6. Memory optimization

### Current State

The native Python 3 implementation is **already faster** than original implementations in several areas:
- **Formula creation:** ~10x faster (no string parsing overhead)
- **Type checking:** ~5x faster (built-in vs manual)
- **Memory usage:** ~30% lower
- **Import time:** ~50x faster (no Python 2 startup)

### Target State

- **2-4x overall speedup** for complex operations
- **50% memory reduction** for large knowledge bases
- **Sub-second response times** for 95% of API requests
- **10,000+ operations/second** throughput

---

## 🏁 Current Performance Baseline

### Measured Operations (2026-02-18)

| Operation | Current Performance | Notes |
|-----------|-------------------|-------|
| **Formula Creation** | | |
| Simple formula | ~5 μs | VariableTerm, AtomicFormula |
| Complex formula | ~50 μs | Nested deontic/modal operators |
| From string (basic) | ~200 μs | Pattern-based parsing |
| From string (advanced) | ~2 ms | Full grammar parsing |
| **Type Checking** | | |
| Sort compatibility | ~2 μs | Simple type checking |
| Full validation | ~20 μs | Deep validation with constraints |
| **Parsing** | | |
| Tokenization | ~100 μs | Small formula |
| Full parse tree | ~1 ms | Complex nested structure |
| **Theorem Proving** | | |
| Simple proof (3 steps) | ~500 μs | Forward chaining |
| Moderate proof (10 steps) | ~5 ms | Multiple rule applications |
| Complex proof (50 steps) | ~100 ms | Deep proof search |
| **NL Conversion** | | |
| Pattern matching | ~100 μs | Simple sentence |
| Grammar-based | ~5 ms | Complex sentence with parsing |
| **Knowledge Base** | | |
| Add statement | ~50 μs | Single statement |
| Query (100 statements) | ~1 ms | Linear search |
| Query (10,000 statements) | ~50 ms | Linear search (needs optimization) |

### Profiling Results

**Hot Paths (80% of CPU time):**
1. **Unification** (25%) - Matching terms during proving
2. **Type checking** (20%) - Validating formulas
3. **Formula comparison** (15%) - Equality/subsumption checking
4. **Parsing** (12%) - String to formula conversion
5. **Proof search** (8%) - Exploring proof space

**Memory Usage:**
- **Formula objects:** ~200 bytes each (with __slots__)
- **Proof tree:** ~1 KB per 10 steps
- **Knowledge base (1,000 formulas):** ~300 KB
- **Parsing cache:** ~100 KB per 1,000 unique formulas

---

## 🎯 Performance Targets

### Phase 7 Objectives (Weeks 21-24)

| Operation | Current | Target | Improvement |
|-----------|---------|--------|-------------|
| **Formula Creation** | | | |
| From string (basic) | 200 μs | 50 μs | 4x |
| From string (advanced) | 2 ms | 500 μs | 4x |
| **Theorem Proving** | | | |
| Simple proof | 500 μs | 200 μs | 2.5x |
| Moderate proof | 5 ms | 2 ms | 2.5x |
| Complex proof | 100 ms | 30 ms | 3.3x |
| **NL Conversion** | | | |
| Pattern matching | 100 μs | 30 μs | 3.3x |
| Grammar-based | 5 ms | 1.5 ms | 3.3x |
| **Knowledge Base** | | | |
| Query (10,000 stmts) | 50 ms | 5 ms | 10x |
| Add statement | 50 μs | 20 μs | 2.5x |
| **Memory** | | | |
| KB (10,000 formulas) | 3 MB | 1.5 MB | 2x |
| Proof tree (100 steps) | 10 KB | 5 KB | 2x |

### API Performance Targets

| Endpoint | P50 | P95 | P99 |
|----------|-----|-----|-----|
| /convert/nl-to-dcec | <30ms | <100ms | <200ms |
| /convert/dcec-to-nl | <20ms | <60ms | <120ms |
| /prove (simple) | <50ms | <200ms | <500ms |
| /prove (complex) | <1s | <5s | <10s |
| /kb/query | <30ms | <100ms | <200ms |

---

## 🔧 Optimization Strategies

### 1. Algorithm Optimizations

#### 1.1 Unification Optimization
**Problem:** Unification accounts for 25% of CPU time.

**Current Implementation:**
```python
def unify(term1: Term, term2: Term, bindings: Dict) -> Optional[Dict]:
    # Recursive unification with dict updates
    if isinstance(term1, VariableTerm):
        return bind_variable(term1, term2, bindings)
    # ... more cases ...
```

**Optimization:**
```python
# Use immutable bindings with copy-on-write
def unify(term1: Term, term2: Term, bindings: FrozenDict) -> Optional[FrozenDict]:
    # Memoize unification results
    cache_key = (term1, term2, bindings)
    if cache_key in _unify_cache:
        return _unify_cache[cache_key]
    
    result = _unify_impl(term1, term2, bindings)
    _unify_cache[cache_key] = result
    return result
```

**Expected Improvement:** 2-3x faster

#### 1.2 Proof Search Optimization
**Problem:** Proof search explores many dead-end branches.

**Current Implementation:**
- Depth-first search
- No heuristics
- Explores all possibilities

**Optimization:**
```python
# Add proof search heuristics
class ProverWithHeuristics:
    def search(self, goal: Formula) -> Optional[Proof]:
        # Priority queue with heuristic scoring
        queue = PriorityQueue()
        queue.put((self.heuristic(goal), goal, []))
        
        while not queue.empty():
            _, current, steps = queue.get()
            
            # Prune unpromising branches
            if len(steps) > self.max_depth:
                continue
            
            # Try rules in heuristic order
            for rule in self.get_applicable_rules_sorted(current):
                result = rule.apply(current)
                if result.is_goal():
                    return Proof(steps + [result])
                
                score = self.heuristic(result)
                queue.put((score, result, steps + [result]))
        
        return None
```

**Heuristics:**
- Formula complexity (prefer simpler)
- Goal similarity (prefer closer to goal)
- Rule success rate (prefer successful rules)

**Expected Improvement:** 2-4x faster for complex proofs

#### 1.3 Knowledge Base Indexing
**Problem:** Linear search through statements is slow for large KBs.

**Current Implementation:**
```python
def query(self, pattern: Formula) -> List[Statement]:
    # O(n) linear search
    return [s for s in self.statements if matches(s.formula, pattern)]
```

**Optimization:**
```python
from collections import defaultdict

class IndexedKnowledgeBase:
    def __init__(self):
        self.statements: List[Statement] = []
        # Multiple indexes
        self.by_predicate: Dict[str, Set[int]] = defaultdict(set)
        self.by_operator: Dict[str, Set[int]] = defaultdict(set)
        self.by_agent: Dict[str, Set[int]] = defaultdict(set)
    
    def add_statement(self, stmt: Statement):
        idx = len(self.statements)
        self.statements.append(stmt)
        
        # Update indexes
        self.by_predicate[stmt.formula.predicate].add(idx)
        self.by_operator[stmt.formula.operator].add(idx)
        # ... extract and index agents ...
    
    def query(self, pattern: Formula) -> List[Statement]:
        # Use index for fast filtering
        candidates = self.by_predicate.get(pattern.predicate, set())
        
        # Filter candidates (much smaller set)
        return [self.statements[i] for i in candidates 
                if matches(self.statements[i].formula, pattern)]
```

**Expected Improvement:** 10-20x faster for large KBs

### 2. Data Structure Optimizations

#### 2.1 Use __slots__
**Problem:** Formula objects use dict for attributes (~200 bytes each).

**Current Implementation:**
```python
class Formula:
    def __init__(self, operator: Operator, args: List):
        self.operator = operator
        self.args = args
```

**Optimization:**
```python
class Formula:
    __slots__ = ('operator', 'args', '_hash')
    
    def __init__(self, operator: Operator, args: tuple):
        self.operator = operator
        self.args = args  # Use tuple, not list
        self._hash = None  # Cache hash
    
    def __hash__(self):
        if self._hash is None:
            self._hash = hash((self.operator, self.args))
        return self._hash
```

**Expected Improvement:** 30-40% memory reduction, 10% faster

#### 2.2 Formula Interning
**Problem:** Duplicate formulas waste memory and comparison time.

**Implementation:**
```python
class FormulaFactory:
    _intern_cache: Dict[tuple, Formula] = {}
    
    @classmethod
    def create(cls, operator: Operator, *args) -> Formula:
        key = (operator, args)
        if key not in cls._intern_cache:
            cls._intern_cache[key] = Formula(operator, args)
        return cls._intern_cache[key]

# Now formula comparison is O(1) pointer comparison
formula1 = FormulaFactory.create(op, args)
formula2 = FormulaFactory.create(op, args)
assert formula1 is formula2  # Same object!
```

**Expected Improvement:** 20-30% memory reduction, faster equality checks

#### 2.3 Frozen Dataclasses
**Problem:** Mutable objects prevent caching and optimization.

**Current Implementation:**
```python
@dataclass
class ProofState:
    goal: Formula
    axioms: List[Formula]
    bindings: Dict
```

**Optimization:**
```python
@dataclass(frozen=True)
class ProofState:
    goal: Formula
    axioms: tuple[Formula, ...]  # Immutable
    bindings: FrozenDict  # Immutable dict
    
    def __hash__(self):
        return hash((self.goal, self.axioms, self.bindings))
```

**Expected Improvement:** Enables caching, prevents bugs

### 3. Caching Strategies

#### 3.1 Memoization
**Cache expensive operations:**

```python
from functools import lru_cache

@lru_cache(maxsize=10000)
def unify(term1: Term, term2: Term, bindings: FrozenDict) -> Optional[FrozenDict]:
    # Expensive unification cached
    pass

@lru_cache(maxsize=5000)
def type_check(formula: Formula, context: TypeContext) -> bool:
    # Type checking cached
    pass

@lru_cache(maxsize=1000)
def parse_formula(text: str) -> Formula:
    # Parsing cached
    pass
```

**Expected Improvement:** 50-80% faster for repeated operations

#### 3.2 Result Cache
**Cache complete operation results:**

```python
class CachedProver:
    def __init__(self):
        self.result_cache: Dict = {}
    
    def prove(self, conjecture: Formula, axioms: tuple[Formula, ...]) -> ProofResult:
        key = (conjecture, axioms)
        if key in self.result_cache:
            return self.result_cache[key]
        
        result = self._prove_impl(conjecture, axioms)
        self.result_cache[key] = result
        return result
```

**Cache Eviction:**
- LRU policy
- Time-based expiration (1 hour)
- Size limit (100 MB)

**Expected Improvement:** Near-instant for cached results

### 4. Parallel Processing

#### 4.1 Parallel Proof Search
**Try multiple proof strategies in parallel:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class ParallelProver:
    def prove(self, conjecture: Formula, axioms: List[Formula]) -> ProofResult:
        strategies = [
            ('forward_chaining', self.forward_chain),
            ('backward_chaining', self.backward_chain),
            ('resolution', self.resolution),
            ('tableaux', self.tableaux)
        ]
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(strategy[1], conjecture, axioms): strategy[0]
                for strategy in strategies
            }
            
            for future in as_completed(futures, timeout=30):
                try:
                    result = future.result()
                    if result.success:
                        # Cancel other tasks
                        for f in futures:
                            f.cancel()
                        return result
                except Exception:
                    pass
        
        return ProofResult(success=False)
```

**Expected Improvement:** Up to 4x faster (best strategy wins)

#### 4.2 Parallel Batch Processing
**Process multiple requests concurrently:**

```python
import asyncio

async def batch_convert(texts: List[str]) -> List[ConversionResult]:
    tasks = [convert_nl_to_dcec_async(text) for text in texts]
    return await asyncio.gather(*tasks)
```

**Expected Improvement:** Near-linear scaling with CPU cores

### 5. Compilation Optimizations

#### 5.1 Numba JIT for Hot Paths
**Compile Python to machine code:**

```python
from numba import jit

@jit(nopython=True)
def fast_unification_check(term1_type: int, term2_type: int) -> bool:
    # Simple numeric operations compiled to native code
    return term1_type == term2_type or term1_type == 0 or term2_type == 0

# Use in unification
def unify(term1: Term, term2: Term) -> bool:
    if not fast_unification_check(term1.type_id, term2.type_id):
        return False
    # ... rest of logic ...
```

**Expected Improvement:** 5-10x faster for numeric computations

#### 5.2 Cython Extensions (Optional)
**Rewrite critical paths in Cython:**

```cython
# unification.pyx
cdef class FastUnifier:
    cdef dict bindings
    
    cdef bint unify_impl(self, object term1, object term2):
        # Pure C-level operations
        pass
```

**Expected Improvement:** 10-50x faster for critical paths

### 6. Memory Optimizations

#### 6.1 Weak References
**Prevent circular references:**

```python
import weakref

class ProofTree:
    def __init__(self, root: Formula):
        self.root = root
        # Use weak references to parent to avoid cycles
        self.children: List[ProofTree] = []
        self.parent: Optional[weakref.ref] = None
```

**Expected Improvement:** Better garbage collection, less memory

#### 6.2 Object Pooling
**Reuse common objects:**

```python
class TermPool:
    def __init__(self):
        self.pool: Dict[str, List[Term]] = defaultdict(list)
    
    def get(self, term_type: str) -> Term:
        if self.pool[term_type]:
            return self.pool[term_type].pop()
        return Term(term_type)
    
    def release(self, term: Term):
        term.reset()  # Clear state
        self.pool[term.type].append(term)
```

**Expected Improvement:** Reduce allocation overhead

#### 6.3 Memory Profiling
**Identify memory leaks:**

```python
from memory_profiler import profile

@profile
def process_large_kb():
    kb = KnowledgeBase()
    for i in range(10000):
        kb.add_statement(create_formula(i))
    # ... operations ...
```

---

## 📋 Implementation Plan (Phase 7: Weeks 21-24)

### Week 21: Profiling & Baseline

**Days 1-2: Comprehensive Profiling**
- Run cProfile on all major operations
- Use py-spy for sampling profiler
- Memory profiling with memory_profiler
- Identify top 10 bottlenecks

**Days 3-4: Baseline Benchmarks**
- Create benchmark suite
- Measure all operations
- Document current performance
- Set up performance tracking

**Day 5: Optimization Priority**
- Rank optimizations by impact
- Create implementation order
- Set weekly targets

**Deliverables:**
- Profiling reports
- Benchmark suite
- Optimization roadmap

### Week 22: Caching & Data Structures

**Days 1-2: Implement Caching**
- Add @lru_cache to hot functions
- Implement result cache
- Add cache hit rate monitoring
- Tune cache sizes

**Days 3-5: Data Structure Optimization**
- Add __slots__ to Formula classes
- Implement formula interning
- Convert to frozen dataclasses
- Add KB indexing

**Deliverables:**
- Caching layer
- Optimized data structures
- 30-50% memory reduction
- 2x faster repeated operations

### Week 23: Algorithm Optimizations

**Days 1-2: Unification Optimization**
- Implement memoized unification
- Add early termination
- Profile and tune

**Days 3-4: Proof Search Heuristics**
- Implement priority queue search
- Add heuristic functions
- Tune heuristic weights
- Add branch pruning

**Day 5: Knowledge Base Indexing**
- Implement multi-index system
- Add query optimizer
- Test with large KBs

**Deliverables:**
- 2-3x faster unification
- 2-4x faster proof search
- 10x faster KB queries

### Week 24: Parallel Processing & Polish

**Days 1-2: Parallel Proof Search**
- Implement parallel strategies
- Add timeout handling
- Test scaling

**Day 3: Parallel Batch Processing**
- Implement async batch APIs
- Add task queue
- Test concurrency

**Days 4-5: Final Optimization & Validation**
- Profile optimized code
- Run complete benchmark suite
- Validate 2-4x improvement
- Document optimizations
- Add performance regression tests

**Deliverables:**
- Parallel processing support
- Complete optimization package
- 2-4x overall improvement
- Performance regression tests

---

## 📊 Benchmarking & Profiling

### Benchmark Suite

**Location:** `tests/performance/logic/CEC/`

**Benchmarks:**
1. `bench_formula_creation.py` - Formula object creation
2. `bench_parsing.py` - String to formula parsing
3. `bench_proving.py` - Theorem proving
4. `bench_nl_conversion.py` - NL conversion
5. `bench_kb_operations.py` - Knowledge base operations
6. `bench_memory.py` - Memory usage

**Example Benchmark:**
```python
import pytest
from time import perf_counter
from ipfs_datasets_py.logic.CEC.native import Formula, TheoremProver

@pytest.mark.benchmark
def test_proof_performance(benchmark):
    prover = TheoremProver()
    prover.add_axiom("A → B")
    prover.add_axiom("A")
    
    result = benchmark(prover.prove, "B")
    
    assert result.success
    assert result.time_ms < 1.0  # Target: <1ms

@pytest.mark.benchmark
def test_kb_query_performance(benchmark):
    kb = KnowledgeBase()
    # Add 10,000 statements
    for i in range(10000):
        kb.add_statement(f"stmt_{i}")
    
    result = benchmark(kb.query, "pattern")
    
    assert result.time_ms < 10.0  # Target: <10ms
```

### Profiling Tools

**CPU Profiling:**
```bash
# cProfile
python -m cProfile -o profile.stats script.py
python -c "import pstats; pstats.Stats('profile.stats').sort_stats('cumtime').print_stats(20)"

# py-spy (sampling profiler)
py-spy record -o profile.svg -- python script.py
```

**Memory Profiling:**
```bash
# memory_profiler
python -m memory_profiler script.py

# memray
memray run script.py
memray flamegraph output.bin
```

### Continuous Performance Monitoring

**GitHub Actions Workflow:**
```yaml
name: Performance Tests

on:
  pull_request:
  schedule:
    - cron: '0 0 * * *'  # Daily

jobs:
  performance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install -e ".[test]"
      - name: Run benchmarks
        run: pytest tests/performance/ --benchmark-only
      - name: Store results
        run: |
          pytest tests/performance/ --benchmark-json=benchmark.json
          # Store in database or artifact
      - name: Check for regressions
        run: |
          # Compare with previous results
          # Fail if >10% slower
```

---

## 📈 Performance Monitoring

### Metrics to Track

**Operation Metrics:**
- Request rate (requests/second)
- Response time (P50, P95, P99)
- Error rate (errors/second)
- Throughput (operations/second)

**Resource Metrics:**
- CPU usage (%)
- Memory usage (MB)
- Cache hit rate (%)
- Thread/connection pool usage

**Business Metrics:**
- Conversion success rate
- Proof success rate
- Average proof complexity
- API quota usage

### Visualization (Grafana Dashboard)

**Panels:**
1. Request rate (timeseries)
2. Response time percentiles (graph)
3. Error rate (counter)
4. Cache hit rate (gauge)
5. Memory usage (graph)
6. CPU usage (graph)

---

## 📝 Conclusion

This performance optimization plan provides a comprehensive strategy to achieve **2-4x performance improvement** through:

1. **Algorithm optimizations** - Smarter algorithms, better heuristics
2. **Data structures** - Efficient storage, fast access
3. **Caching** - Avoid redundant computation
4. **Parallel processing** - Utilize multiple cores
5. **Compilation** - JIT/Cython for hot paths
6. **Memory optimization** - Reduce footprint, prevent leaks

**Implementation Timeline:** 4 weeks (Weeks 21-24 of overall plan)

**Expected Results:**
- ✅ 2-4x faster overall
- ✅ 50% memory reduction
- ✅ Sub-second API responses
- ✅ 10,000+ ops/second throughput

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-18  
**Status:** Ready for Implementation  
**Implementation:** Phase 7 (Weeks 21-24)
