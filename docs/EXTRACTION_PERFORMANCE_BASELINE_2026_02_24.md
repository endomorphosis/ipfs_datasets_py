# Extract Entities 10k+ Token Performance Baseline
**Captured**: 2026-02-24
**Benchmark**: `benchmarks/bench_ontology_generator_extract_entities_10k.py`
**System**: Linux, Python 3.12+

## Overview
Comprehensive performance baseline for `OntologyGenerator.extract_entities()` on 10k+ token documents across different extraction contexts.

## Baseline Results

### General Window (Context: DocumentWindow=0)
- **Iterations**: 20 (with 3 warmup iterations)
- **Average**: 176.33 ms/extraction
- **Median**: 174.85 ms/extraction
- **P95**: 186.92 ms/extraction
- **Max**: 190.32 ms/extraction
- **Average Entities Extracted**: 14
- **Average Relationships Extracted**: 70

### Legal Window (Context: DocumentWindow=2)
- **Iterations**: 20 (with 3 warmup iterations)
- **Average**: 184.19 ms/extraction
- **Median**: 182.32 ms/extraction
- **P95**: 194.07 ms/extraction
- **Max**: 198.36 ms/extraction
- **Average Entities Extracted**: 14
- **Average Relationships Extracted**: 58

## Performance Analysis

### Key Observations
1. **Consistency**: Both contexts show tight distribution with P95 < 200ms
2. **Context Impact**: Legal extraction (2) is ~4.4% slower than general window (0)
3. **Relationship Density**: General window produces more relationships (70 vs 58)
4. **Reliability**: Max time stays within 200ms, indicating predictable performance

### Throughput Estimates
- **General**: ~5.7 extractions/sec (1000 ms / 176.33 ms)
- **Legal**: ~5.4 extractions/sec (1000 ms / 184.19 ms)

### Regression Thresholds
For future regression testing:
- ❌ **Regression Alert** if avg > 250ms (1.4x baseline)
- ⚠️ **Warning Threshold** if avg > 220ms (1.25x baseline)
- ✅ **Healthy** if avg <= 200ms

## Document Characteristics
- **Token Count**: ~15,000 tokens (sentence * 1500 repetitions)
- **Entity Types**: Person, Organization, Date, Location, Currency, Obligation
- **Entity Density**: ~1 entity per ~1,071 tokens
- **Relationship Density**: ~70 relationships for general context

## Reproduction Steps
```bash
cd ipfs_datasets_py
python benchmarks/bench_ontology_generator_extract_entities_10k.py
```

## Implementation Notes
- Benchmark uses realistic entity extraction scenarios with multiple context windows
- Warmup iterations (3) are performed to stabilize JIT compilation and caching
- Results use `time.perf_counter()` for high-precision measurements
- Output captured in JSON format for CI integration and trend analysis

## Next Steps
- Track these metrics in CI/CD pipeline
- Compare against baseline quarterly
- Investigate if average exceeds 220ms threshold
- Profile hotspots if P95 exceeds 210ms
