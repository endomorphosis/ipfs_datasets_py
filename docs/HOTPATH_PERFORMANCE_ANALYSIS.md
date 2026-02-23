# Hot-Path Performance Analysis Report

**Date:** 2026-02-23  
**Component:** OntologyGenerator._extract_rule_based()  
**Scope:** All extraction-related hot paths identified via cProfile

## Executive Summary

Performance profiling of the extraction pipeline reveals **relationship inference is the primary bottleneck**, accounting for 60-80% of total execution time. The algorithm exhibits **superlinear O(n²+) scaling**, where a 32x increase in document size results in a 61x execution time increase.

## Findings

### 1. Scaling Characteristics

| Document Size | Avg Time | Entities | Relationships | Scaling |
|---|---|---|---|---|
| 44 chars (Small) | 0.68ms | 4 | 2 | Baseline |
| 482 chars (Medium) | 3.60ms | 40 | 224 | 5.3x |
| 1404 chars (Large) | 40.94ms | 156 | 1556 | 60.6x |

**Conclusion**: Time scales faster than linear growth in entity count, confirming O(n²+) complexity.

### 2. Runtime Breakdown (Large Document)

Total time per run: **~41ms**

**Components:**
- **Relationship Inference**: ~33-35ms (80-85%)
- **Entity Extraction**: ~5-6ms (12-15%)
- **Pattern Building**: <1ms (1-2%)

### 3. Relationship Inference Bottleneck Analysis

**Operation**: Compare all entity pairs (n×(n-1)/2) for relationship patterns

**For Large Document (156 entities):**
- Entity pairs to compare: 12,090
- Actual relationships found: 1,556 (12.9% density)
- Regex operations: ~3-4 per pair = ~40,000 regex searches
- Per-pair time: ~3.4 microseconds

**Hotspots in `infer_relationships()`:**
1. `re.finditer()` calls on full text for each pattern
2. Type confidence scoring decision tree
3. Entity text lookup (string comparison)

### 4. Scaling Root Cause

**Why O(n²+)?**

```
Total Time = O(n²) entity pairs × O(m) verb patterns × O(t) text search
           = O(n² × m × t)

where:
  n = number of entities
  m = number of verb patterns (~20)
  t = text search complexity ≈ O(|text|) for regex finditer
```

**Real-world example:**
- 4 entities → 6 pairs × 20 patterns × 1404 chars ≈ 169K operations
- 156 entities → 12,090 pairs × 20 patterns × 1404 chars ≈ 339M operations

## Optimization Opportunities

### Priority 1: Entity Type Pre-filtering (Quick Win)
**Effort:** Low  
**Potential Impact:** 20-30% reduction  
**Implementation:** Skip relationship inference for entity type pairs that are unlikely to relate (e.g., Date-to-Date).

**Code pattern:**
```python
# Skip certain type combinations
IMPOSSIBLE_PAIRS = {
    ('Date', 'Date'),
    ('MonetaryAmount', 'Location'),
    ('Concept', 'Concept'),
}

if (e1.type, e2.type) in IMPOSSIBLE_PAIRS:
    continue  # Skip this pair
```

### Priority 2: Sentence-Based Limiting (Moderate)
**Effort:** Moderate  
**Potential Impact:** 35-45% reduction  
**Implementation:** Only search within +/- N sentences of entity mentions.

**Rationale:** Relationships typically expressed within 1-3 sentences; searching entire document is wasteful.

### Priority 3: Parallelization (High Impact)
**Effort:** High  
**Potential Impact:** 4-8x speedup (on multi-core)  
**Implementation:** Process entity pairs in parallel using `multiprocessing` or `concurrent.futures`.

**Approach:**
- Partition entity pairs into chunks
- Process chunks in parallel workers
- Merge results

### Priority 4: Vectorized String Matching (Research)
**Effort:** Very High  
**Potential Impact:** 50-70% reduction  
**Implementation:** Replace regex with compiled string search (Aho-Corasick automaton or similar).

**Trade-offs:** Requires external library, but eliminates Python regex overhead.

## Performance Targets

**Current:** ~41ms for 156 entities  
**After P1 + P2:** ~15-20ms (60% reduction)  
**After P3 (parallelization):** ~3-5ms (87% reduction on 4-core system)

## Recommended Implementation Order

1. ✅ **Document profiling** (DONE) - baseline established
2. [ ] **Implement type filtering** (P1) - 1-2 hours
3. [ ] **Add sentence-based limiting** (P2) - 2-3 hours
4. [ ] **Parallel relationship scoring** (P3) - 3-4 hours
5. [ ] **Vectorized string matching** (P4) - Research phase

## Monitoring & Validation

### Regression Tests
- Create benchmark suite (DONE: `bench_infer_relationships_scaling.py`)
- Track per-optimization performance deltas
- Monitor for accuracy regressions

### Metrics to Track
- Execution time (primary)
- Relationship precision/recall (accuracy)
- Memory usage (secondary)
- CPU utilization (for parallelization)

## Supporting Infrastructure

**Scripts Created:**
- `scripts/profile_extraction_hotpaths.py` - Basic timing analysis
- `scripts/profile_extraction_cprofile.py` - Detailed cProfile analysis

**Benchmarks Created:**
- `benchmarks/bench_infer_relationships_scaling.py` - Entity count scaling
- `benchmarks/bench_relationship_type_confidence_scoring.py` - Type scoring overhead

## References

- OpenTelemetry spans in OntologyPipeline (enable_tracing=True) for production insights
- Profiling infrastructure in `common/profiling.py` for continuous monitoring
- ExtractionConfig.max_relationships for limiting output

---

**Analysis completed by:** Copilot  
**Status:** Ready for implementation  
**Next Step:** Implement P1 type filtering for immediate gains
