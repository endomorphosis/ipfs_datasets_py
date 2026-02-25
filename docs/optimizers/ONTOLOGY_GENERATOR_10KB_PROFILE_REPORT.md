# OntologyGenerator 10kB Profile Report

Date: 2026-02-25

## Scope

- Target: `OntologyGenerator.generate_ontology()`
- Input size: ~10kB (`10269` bytes)
- Domain/strategy: `legal` + `RULE_BASED`
- Config: `sentence_window=2`
- Script: `benchmarks/profile_ontology_generator_generate_10kb.py`

## Measurement Summary

- Average latency: `8.0447 ms`
- Median latency: `7.9959 ms`
- p95 latency: `9.9263 ms`
- Output size (sampled profile run):
  - Entities: `7`
  - Relationships: `15`

## Top Hotspots (cProfile cumulative)

1. `ontology_generator.py:3239(extract_entities)`
2. `ontology_generator.py:3339(_extract_with_llm_fallback)` / `ontology_generator.py:4924(_extract_rule_based)`
3. Language detection path:
   - `ontology_generator.py:3186(_build_language_aware_context)`
   - `language_router.py:329(detect_language_with_confidence)`
   - `logic/CEC/nl/language_detector.py`

Notable primitive hotspot:

- `re.Pattern.search` accounted for a large share of cumulative time in the sampled run.

## Follow-up Optimization Candidates

- Short-circuit language detection for obviously monolingual ASCII-heavy text.
- Reduce repeated regex scans in extraction and relationship inference paths.
- Reuse precomputed context artifacts across repeated calls in benchmark-like workloads.
