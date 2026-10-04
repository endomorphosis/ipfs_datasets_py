# GraphRAG Benchmark Suite Report

**Timestamp:** 2026-02-24T22:23:32.139929  
**Total Benchmarks:** 11  
**Passed:** 5  
**Failed:** 6  
**Skipped:** 0  
**Total Time:** 24.42s  

## End_To_End Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_end_to_end_pipeline_performance.py | ✗ failed | 0.10 |

## Extraction Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_ontology_extraction_baseline.py | ✓ passed | 4.02 |
| bench_ontology_generator_extract_entities_10k.py | ✓ passed | 9.65 |
| bench_extraction_strategy_performance.py | ✗ failed | 0.10 |

## Generator Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_ontology_generator_generate.py | ✗ failed | 0.08 |
| bench_ontology_generator_rule_based.py | ✗ failed | 0.09 |

## Query Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_query_validation_cache_key.py | ✓ passed | 0.52 |
| bench_query_optimizer_under_load.py | ✓ passed | 4.31 |

## Relationships Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_infer_relationships_scaling.py | ✗ failed | 0.14 |
| bench_relationship_type_confidence_scoring.py | ✗ failed | 0.10 |

## Validation Benchmarks

| Benchmark | Status | Time (s) |
|-----------|--------|----------|
| bench_logic_validator_validate_ontology.py | ✓ passed | 5.32 |
