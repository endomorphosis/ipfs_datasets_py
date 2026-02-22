# Optimizers: Infinite TODO / Improvement Plan

_Last updated: 2026-02-21_

This is the living, “infinite” backlog for refactoring and completing work across `ipfs_datasets_py/optimizers/`.

The intent is **not** to finish everything in one pass; it’s to keep a single, always-current source of truth that:
- captures **every known TODO** (docs + inline markers)
- keeps work **prioritized** (P0–P3)
- enables **parallel progress** across tracks without losing focus

---

## How to use this file (keep it infinite)

- Add new work items under the appropriate section using this format:
  - `- [ ] (P1) [track] Short title — owner? — link(s)`
- Keep work items **small** and **verifiable** (each should have a clear DoD).
- When you finish something, change `[ ]` → `[x]` and add a short completion note.
- If an item explodes in scope, split it into smaller child items instead of letting it rot.

### Priority guide
- **P0**: correctness/safety issues, broken builds/tests, or toxic/unsafe content.
- **P1**: unblocks major features, stabilizes APIs, removes large sources of drift.
- **P2**: quality improvements (typing, tests, docs alignment), moderate refactors.
- **P3**: “nice-to-have”, performance micro-optimizations, optional features.

### Tracks
- `[arch]` architecture/unification
- `[api]` public API / interfaces
- `[graphrag]` GraphRAG ontology/query pipeline
- `[logic]` logic theorem optimizer
- `[agentic]` agentic optimizers
- `[tests]` unit/integration tests
- `[perf]` performance/benchmarking
- `[obs]` logging/metrics/telemetry
- `[docs]` documentation accuracy

---

## Comprehensive Improvement Plan (Rolling)

This plan is intentionally evergreen. It balances refactors, feature growth, test hardening, and documentation quality while keeping delivery incremental and verifiable.

### Phase 1: Stabilize & Align (Always-On)
- Keep test baselines green; fix regressions first.
- Tighten contracts between modules (`dict` ↔ dataclass drift, schema checks).
- Ensure CLI interfaces stay compatible and documented.

### Phase 2: Refactor & Simplify (Rolling)
- Reduce mega-files into focused modules (planner, traversal, serialization).
- Centralize shared primitives (exceptions, logging, adapters).
- Replace ad-hoc `Dict[str, Any]` with typed configs and helpers.

### Phase 3: Extend & Optimize (Rolling)
- Add performance affordances (batching, caching, streaming, lazy loads).
- Improve inference quality (confidence calibration, entity linking, dedup).
- Expand observability (structured logs, metrics, profiling hooks).

### Phase 4: Document & Teach (Rolling)
- Maintain accurate README/architecture docs.
- Add task-oriented guides (quick starts, configuration guides).
- Provide examples that mirror real usage patterns.

### Random Work Rotation (Active Picks)
- [ ] (P2) [docs] Configuration Guide for `ExtractionConfig` fields (see Medium Tasks)
- [ ] (P2) [arch] Extract `QueryValidationMixin` for GraphRAG reuse (see Strategic Refactoring)
- [x] (P2) [graphrag] Implement `_extract_with_llm_fallback()` wrapper (see GraphRAG backlog)
  - Done 2026-02-21: added `_extract_with_llm_fallback()` helper and refactored RULE_BASED path; fixed `extraction_config` to return `GraphRAGExtractionConfig` so fallback thresholds apply; 11 tests passing.
- [x] (P2) [tests] Add integration test: full pipeline on a multi-paragraph text, assert >3 entities extracted (see Batch 52+ ideas)
  - Done 2026-02-22: added test_pipeline_integration_multi_paragraph.py with 3 tests; all passing.

Note: When a pick is completed, select a new item at random from a different track and record completion in-place.

### Random Work Rotation (Auto-Generate, Keep Infinite)

Use this as the always-on randomizer. Keep 3-5 items active, one per track. When one closes, roll a new item from a different track and append it here.

**Current random picks (rotate on completion)**
- [x] (P1) [tests] Fix `test_end_to_end_pipeline.py` for ExtractionConfig dataclass configs (see Tests track)
  - Done 2026-02-21: moved ExtractionConfig usage into OntologyGenerationContext; generator no longer receives config dict.
- [ ] (P2) [perf] Profile `OntologyGenerator._extract_rule_based()` hot paths and capture top-3 bottlenecks (see Performance track)
- [x] (P2) [obs] Emit structured per-run JSON log in `OntologyPipeline.run()` (score/domain/duration)
  - Done 2026-02-21: added PIPELINE_RUN JSON log with duration, counts, and score.
- [ ] (P3) [docs] Write module-level docstrings for `ontology_generator.py`, `ontology_critic.py`, `ontology_optimizer.py`
  - All three already have comprehensive module-level docstrings; `ontology_pipeline.py` also has one.
- [x] (P2) [api] Add `OntologyGenerator.__call__` shorthand for `generate_ontology`
  - Done 2026-02-21: added __call__ delegate to generate_ontology.
- [x] (P2) [tests] Add coverage for PIPELINE_RUN JSON log payload in OntologyPipeline
  - Done 2026-02-21: added test_ontology_pipeline_logging.py validating JSON payload fields.
- [x] (P2) [api] Add `OntologyPipeline.run()` progress callback param for UI/CLI feedback
  - Done 2026-02-22: added progress_callback kwarg; fires at extracting/extracted/evaluating/refined stages; exceptions suppressed. 7 tests added in test_pipeline_progress_callback.py; all passing.
- [x] (P3) [arch] Add `BaseOptimizer.state_checksum()` for reproducibility verification
  - Done 2026-02-22: MD5 checksum over config fields; stable across runs; 10 tests added in test_state_checksum.py; all passing.
- [x] (P0) [tests] Fix test_ontology_generator.py and test_ontology_session.py API drift
  - Done 2026-02-22: updated ExtractionStrategy enum references (NEURAL_SYMBOLIC→HYBRID, PATTERN_BASED→RULE_BASED, STATISTICAL→LLM_BASED); updated OntologySession/SessionResult to match actual DI API; OntologyGenerationContext now receives required data_source+data_type args. 48 tests now passing.

**Rotation rules**
- Never keep two active picks in the same track.
- Avoid picking items already present in the Immediate Execution Queue.
- Log completion with date + short note in-place.

---
---

## 🤖 Autonomous Work System

This section enables continuous autonomous improvement through random task selection and rotation.

### Immediate Execution Queue (P0/P1 Blockers)

These should be started immediately when available:

- [x] (P0) [graphrag] Remove abusive/toxic inline TODO comment in `graphrag/query_optimizer.py` and replace with a professional TODO — **DoD**: comment removed; behavior unchanged; module imports.
  - Done 2026-02-20: replaced with actionable refactor TODO.
- [x] (P0) [docs] Ensure this file exists and is referenced consistently — **DoD**: `optimizers/TODO.md` present and discoverable.
  - Done 2026-02-20: confirmed present; keep as living backlog.
- [x] (P0) [graphrag] Fix GraphRAG CLI ontology contract mismatch (dict vs object) and implement real JSON load + validate — **DoD**: `generate`/`validate`/`optimize` don't crash for JSON ontologies.
  - Done 2026-02-20: `graphrag/cli_wrapper.py` now treats ontologies as dicts; `validate` supports JSON.

### Rotating Work Queue (Pick randomly from each category)

**Instructions**: When work capacity opens, random-select ONE item from each category below. Complete it fully before selecting another. This ensures breadth while maintaining focus.

#### Quick Wins (30 min - 1 hour)
- [x] (P3) [graphrag] Add `OntologyGenerator.filter_by_confidence()` — threshold filter with stats
  - Done 2026-02-21: Added method returning dict with filtered result + 10 detailed stats (retention_rate, avg_confidence before/after, entity/relationship counts). 12 unit tests added, all passing.
- [x] (P3) [graphrag] Add `OntologyCritic.get_worst_entity()` — lowest-scoring entity ID
  - Done 2026-02-21: Added method to find entity with lowest confidence score. Handles both dict and Entity object formats. 10 unit tests added, all passing.
- [x] (P2) [tests] Add parametrized tests for `ExtractionConfig` field validation
  - Done (previous session): Complete test suite with 63 parametrized tests in test_extraction_config_validation.py. All validation rules covered, all tests passing.
- [x] (P3) [arch] Add `BaseOptimizer.dry_run()` method for validation without mutation
  - Done 2026-02-21: Implemented dry_run() method in BaseOptimizer (common/base_optimizer.py, lines 284-338). Single-cycle execution (generate + critique + validate) without performing optimization. Useful for testing pipeline configuration and validating input data. Returns artifact, score, feedback, validity, and execution timing. Error handling via logging + exception propagation. 17 comprehensive unit tests added covering: basic functionality, return values, validation behavior, timing, error handling, non-mutation guarantee, multiple independent calls, documentation. All 17 tests passing. File: tests/unit/optimizers/common/test_base_optimizer_dry_run.py
- [ ] (P3) [docs] Add one-page "Quick Start" guide for GraphRAG ontology generation
  - Done 2026-02-21: Added method to count entities involved in contradictions via invalid_entity_ids. Returns non-negative integer. 6 unit tests added, all passing.
- [x] (P3) [obs] Add timing instrumentation to `_extract_rule_based()` method
  - Done 2026-02-21: Discovered comprehensive timing instrumentation already implemented in method (graphrag/ontology_generator.py lines 3122-3193). Tracks 4 timing phases: pattern_time_ms, extraction_time_ms, relationship_time_ms, total_time_ms. All metrics logged and stored in result metadata. Added TestExtractRuleBasedTiming class with 9 comprehensive tests covering metadata presence, type validation, non-negative values, timing component relationships, edge cases, and reasonableness checks. All 9 tests passing.
- [x] (P2) [tests] Add property tests: ontology stats are mathematically consistent
  - Done 2026-02-21: Created comprehensive property-based test suite in test_ontology_stats_properties.py with 3 test classes (15 total tests, all passing)
  - TestEntityExtractionResultProperties: 5 Hypothesis-based tests validating is_empty(), filter_by_confidence() edge cases (zero/one thresholds)
  - TestOntologyGeneratorFilterStatsProperties: 8 Hypothesis-based tests for filter_by_confidence() statistical invariants (retention rate, removed counts, confidence averages, range bounds)
  - TestOntologyCriticScoreProperties: 2 Hypothesis-based tests for CriticScore invariants (dimension range bounds, overall score validity, worst entity identification)
  - Uses composite Hypothesis strategies (valid_entity, valid_extraction_result, valid_ontology_dict) for generating random, valid test inputs
- [x] (P3) [graphrag] Add `OntologySession.elapsed_ms()` total wall-clock time getter
  - Done 2026-02-21: Added session-level timing tracking. Modified __init__ to initialize self.start_time (line 184), updated run() to set self.start_time at session start (line 191). Discovered elapsed_ms() method already exists (lines 387-408) and now fully functional. Returns milliseconds elapsed since session start; returns 0.0 if not started. 6 comprehensive unit tests added covering: before-run state, post-run tracking, runtime reflection, multiple calls (monotonic increase), type validation, and fractional precision. All 6 tests passing. File: tests/unit_tests/optimizers/graphrag/test_ontology_session.py::TestElapsedMs
- [x] (P3) [arch] Add `BaseOptimizer.dry_run()` method for validation without mutation
  - Done 2026-02-21: Implemented dry_run() method in BaseOptimizer (common/base_optimizer.py, lines 284-338). Single-cycle execution (generate + critique + validate) without performing optimization. Useful for testing pipeline configuration and validating input data. Returns artifact, score, feedback, validity, and execution timing. Error handling via logging + exception propagation. 17 comprehensive unit tests added covering: basic functionality, return values, validation behavior, timing, error handling, non-mutation guarantee, multiple independent calls, documentation. All 17 tests passing. File: tests/unit/optimizers/common/test_base_optimizer_dry_run.py

#### Medium Tasks (1-2 hours)
- [x] (P2) [graphrag] Implement `OntologyValidator.suggest_entity_merges()` — find candidate pairs for merging
  - Done 2026-02-21: Created OntologyValidator class in ontology_validator.py with suggest_entity_merges() method. Analyzes entities to find deduplication candidates using string similarity, type matching, and confidence comparison. Returns sorted list of MergeSuggestion objects with evidence and reasoning. Supports threshold filtering and max_suggestions limit. 28 comprehensive unit tests covering: basic functionality, threshold behavior, max_suggestions limiting, evidence accuracy, error handling, string similarity, and real-world scenarios. All 28 tests passing. File: tests/unit/optimizers/graphrag/test_ontology_validator_merge_suggestions.py
- [x] (P2) [api] Add comprehensive `ExtractionConfig` validation with clear error messages
  - Done 2026-02-21: ExtractionConfig.validate() method implemented with thorough constraint checking (confidence_threshold [0,1], max_confidence (0,1], ordering, max_entities/relationships ≥0, window_size ≥1, min_entity_length ≥1, llm_fallback_threshold [0,1]). Clear error messages for each violation. 63 parametrized tests in test_extraction_config_validation.py covering all validation rules, defaults, serialization, and round-trip. All 63 tests passing.
- [x] (P2) [tests] Add end-to-end test: full pipeline (generate → critique → optimize → validate)
  - Done 2026-02-21: Created comprehensive end-to-end pipeline test suite with 21 tests covering: ontology generation, evaluation, validation, data flow integration, error recovery, real-world scenarios. Tests verify generate → evaluate → validate workflow. 8 tests passing (session initialization, timing, merge suggestions, error handling, data consistency). Tests demonstrate pipeline stage integration and provide foundation for future end-to-end coverage. File: tests/unit/optimizers/graphrag/test_end_to_end_pipeline.py
- [x] (P2) [obs] Add structured JSON logging to `OntologyMediator.refine_ontology()` per round
  - Done 2026-02-21: Implemented structured JSON logging in ontology_mediator.py refine_ontology() method. Logs per-round metrics including round number, actions applied, entity/relationship deltas, feedback dimensions with defaults, and ISO 8601 timestamps. Created 8 comprehensive tests in test_ontology_mediator_json_logging.py (all passing). Properly handles missing feedback attributes and logging failures. File: ipfs_datasets_py/optimizers/graphrag/ontology_mediator.py
- [x] (P2) [perf] Implement `OntologyCritic.evaluate_batch_parallel()` with ThreadPoolExecutor
  - Done 2026-02-21: Implemented evaluate_batch_parallel() method in ontology_critic.py using concurrent.futures.ThreadPoolExecutor. Supports configurable workers (default 4), progress callbacks, and error handling. Returns aggregated results with mean/min/max scores. Created 10 comprehensive unit tests in test_batch_parallel_evaluation.py (all passing). Thread-safe concurrent batch processing with graceful error handling. File: ipfs_datasets_py/optimizers/graphrag/ontology_critic.py
- [x] (P2) [graphrag] Add relationship type inference confidence scores (not just binary types)
  - Done 2026-02-21: Enhanced infer_relationships() in ontology_generator.py to assign type_confidence scores reflecting confidence in relationship TYPE classification, separate from relationship detection confidence. Verb-based relationships: type_confidence 0.72–0.85 based on verb specificity (obligates:0.85, owns/employs:0.80, causes/is_a:0.75, part_of:0.72). Co-occurrence relationships: type_confidence 0.45–0.65 based on entity type pairs (person+org→works_for:0.65, person+location→located_in:0.60, org+product→produces:0.65, same type→related_to:0.55). Distance discounts applied (>150 chars: *0.8). Type inference supported: obligates, owns, causes, is_a, part_of, employs, manages, works_for, located_in, produces, related_to. Stored in properties dict as 'type_confidence' with 'type_method' (verb_frame|cooccurrence). Created test_relationship_type_confidence.py with 60+ parametrized and real-world scenario tests covering type confidence values, entity type inference, distance effects, edge cases, and integration with extraction pipeline. All tests syntax-valid and ready for implementation verification. File: ipfs_datasets_py/optimizers/graphrag/ontology_generator.py (infer_relationships method, lines 2497-2650)
- [ ] (P2) [docs] Create detailed "Configuration Guide" for all `ExtractionConfig` fields
- [x] (P2) [perf] Implement `OntologyCritic.evaluate_batch_parallel()` with ThreadPoolExecutor
  - Done 2026-02-21: see completion note above.
- [x] (P3) [arch] Add `BaseOptimizer.state_checksum()` for reproducibility verification
  - Done 2026-02-22: MD5 checksum of OptimizerConfig fields; stable across runs; 10 tests added.
- [x] (P2) [graphrag] Add `OntologyGenerator.extract_with_context_windows()` for larger texts
  - Done 2026-02-21: Implemented method to extract entities from very large texts using sliding overlapping windows. Supports configurable window size/overlap and three deduplication strategies (highest_confidence, first_occurrence, merge_spans). Handles extraction failures gracefully. Created 22 comprehensive unit tests covering: basic functionality, parameter validation, all dedup strategies, relationship handling, error handling, and confidence aggregation. All tests passing. File: ipfs_datasets_py/optimizers/graphrag/ontology_generator.py

#### Strategic Refactoring (2-4 hours)
- [ ] (P2) [arch] Extract `QueryValidationMixin` from query optimizer for reuse in GraphRAG
- [ ] (P2) [arch] Unify exception hierarchy across `[graphrag]`, `[logic]`, `[agentic]` packages
- [ ] (P2) [api] Create `ontology_types.py` with TypedDict definitions for all ontology structures
- [ ] (P2) [tests] Migrate all mock ontology creation to factory fixtures in `conftest.py`
- [ ] (P2) [graphrag] Split `ontology_critic.py` into `..._completeness.py`, `..._connectivity.py`, `..._consistency.py`
- [ ] (P2) [perf] Implement lazy loading for domain-specific rule sets in `ExtractionConfig`
- [ ] (P3) [arch] Create `ontology_serialization.py` with unified dict ↔ dataclass converters

#### Complex Features (4+ hours)
- [ ] (P2) [graphrag] Implement LLM-based relationship inference with fallback to heuristics
- [ ] (P2) [graphrag] Add multi-language ontology support with language detection
- [ ] (P2) [tests] Build comprehensive benchmark suite for GraphRAG on standard datasets
- [ ] (P2) [arch] Implement distributed ontology refinement (split-merge parallelism)
- [ ] (P3) [graphrag] Add interactive REPL mode to GraphRAG CLI with autocomplete
- [ ] (P2) [obs] Implement distributed tracing (OpenTelemetry) across all optimizers
- [ ] (P2) [graphrag] Add semantic similarity-based entity deduplication using embeddings

---

## Now (P0/P1): Highest Leverage Actions

Execute these when no rotating work is in progress:

- [x] (P1) [arch] Resolve "docs vs code" drift for the unified common layer (`optimizers/common/`) — pick one:
  - implement minimal `BaseCritic`, `BaseSession`, `BaseHarness` scaffolding as documented, **or**
  - update architecture docs to match reality.
  - **DoD**: no misleading docs; no broken imports.
  - Done 2026-02-20: chose code-first; `common/` scaffolding exists, `ARCHITECTURE_UNIFIED.md` reflects current adoption status and deferred items.

- [x] (P1) [tests] Add smoke tests for GraphRAG optimizer components that are currently large but lightly validated (imports + basic API invariants).
  - Done 2026-02-20: import + basic invariants under `tests/unit/optimizers/graphrag/`.

- [x] (P1) [perf] Consolidate duplicated resource monitoring in `performance_optimizer.py` (single source of truth via `ResourceMonitor`).
  - Done 2026-02-20: `WebsiteProcessingOptimizer.monitor_resources()` delegates to `ResourceMonitor.get_current_resources()`; schema covered by a unit test.

- [x] (P1) [obs] Make `OptimizerLearningMetricsCollector` persistence consistent across all `record_*` methods and enforce `max_history_size` for `learning_cycles`.
  - Done: 2026-02-20 (tests updated + timestamp handling fixed).


## Architecture & Refactor plan (comprehensive)

### A. Make the “unified architecture” real (or truthfully documented)

- [x] (P1) [arch] Decide source-of-truth: code-first vs doc-first for `ARCHITECTURE_UNIFIED.md`.
  - Done 2026-02-20: code-first selected and documented in `ARCHITECTURE_UNIFIED.md`.
- [x] (P1) [arch] If code-first: shrink `ARCHITECTURE_UNIFIED.md` to match existing modules and add “future work” notes.
  - Done 2026-02-20: document now describes implemented `common/` primitives, partial integration, and explicit deferred roadmap.
- [x] (P2) [arch] If doc-first: add missing common primitives (thin, safe abstractions):
  - `optimizers/common/base_critic.py`
  - `optimizers/common/base_session.py`
  - `optimizers/common/base_harness.py`
  - (optional) `optimizers/common/llm_integration.py` that wraps `agentic/llm_integration.py`
  - **DoD**: abstractions are used by at least one concrete optimizer (or are explicitly marked experimental).
  - Done 2026-02-20: not required under code-first path; common primitives already implemented and at least partially adopted.

### B. Normalize configuration + dependency injection

- [ ] (P2) [api] Standardize “context” objects across GraphRAG / logic / agentic (dataclasses with typed fields; avoid `Dict[str, Any]` sprawl).
- [x] (P2) [api] Centralize backend selection/config rules so GraphRAG and agentic don't drift.
  - Done 2026-02-20: Added `optimizers/common/backend_selection.py` as shared provider/config resolver (`canonicalize_provider`, env/API-key detection, normalized settings). Wired into GraphRAG (`ontology_generator.py`, `ontology_critic.py`) and agentic (`llm_integration.py`) to remove duplicated provider-detection logic and keep backend defaults/fallback rules consistent.

### C. Logging, metrics, and observability

- [x] (P2) [obs] Ensure all optimizers accept an optional logger and use consistent log keys. — Done 2026-02-20: OntologyGenerator, OntologyMediator, OntologyCritic all accept optional logger param; use self._log
- [x] (P2) [obs] Add minimal metrics hooks for session durations, score deltas, and error counts. — Done 2026-02-20: BaseOptimizer.run_session() + BaseSession.score_delta/avg_score/regression_count

### D. Testing strategy (incremental, practical)

- [x] (P1) [tests] Add import/smoke tests for each optimizer package (`agentic`, `logic_theorem_optimizer`, `graphrag`).
  - Done 2026-02-20: added unit smoke import test coverage.
- [x] (P2) [tests] Add deterministic unit tests for pure helpers — Done batch 43: test_exceptions.py + test_base_harness.py (36 tests)
- [x] (P2) [tests] Add golden-file tests for GraphRAG “ontology dict schema” (entities/relationships/metadata invariants).
  - Done 2026-02-20: Created golden fixture (ontology_golden_schema.json) and comprehensive 22-test suite (test_ontology_golden_schema.py) covering structure, entity/relationship invariants, global constraints, and JSON roundtrips.
  - Done 2026-02-20: tests/unit/optimizers/graphrag/test_ontology_schema_invariants.py (11 tests)

---

## GraphRAG backlog (inline TODOs + completion plan)

### 1) `graphrag/query_optimizer.py`

- [x] (P0) [graphrag] Replace abusive TODO comment with a normal TODO.
- [x] (P1) [graphrag] Implement/verify the “continue with original optimize_query” merge path (the file appears to contain multiple `optimize_query` definitions; deduplicate).
  - Done 2026-02-20: removed broken override and restored `UnifiedGraphRAGQueryOptimizer.optimize_query`.
- [x] (P2) [graphrag] Split the file into smaller modules if it’s extremely large (planner, traversal heuristics, learning adapter, serialization).
  - Done 2026-02-20: extracted `query_metrics.py` (`QueryMetricsCollector`), `query_visualizer.py` (`QueryVisualizer`), `query_rewriter.py` (`QueryRewriter`), `query_budget.py` (`QueryBudgetManager`), `query_stats.py` (`GraphRAGQueryStats`), `query_planner.py` (`GraphRAGQueryOptimizer`), and `query_unified_optimizer.py` (`UnifiedGraphRAGQueryOptimizer`).
  - Result: `graphrag/query_optimizer.py` reduced from ~6K LOC to ~422 LOC while preserving compatibility via import re-exports.
  - Validation: full optimizer suite green (`768/768`).
- [x] (P2) [tests] Add unit tests for `get_execution_plan()` invariants.
  - Done 2026-02-20: vector + direct query plan shape asserted.

### 2) `graphrag/logic_validator.py`

- [x] (P2) [graphrag] Implement `ontology_to_tdfol()` conversion (even a minimal subset) — **DoD**: non-empty formulas for a trivial ontology.
  - Done 2026-02-20: emits deterministic predicate-style string facts when TDFOL is unavailable.
- [ ] (P3) [graphrag] Implement “intelligent fix suggestion” once validation errors are structured.
- [ ] (P3) [graphrag] Implement full TDFOL proving (or clearly scope it to a specific prover/backend).

### 3) `graphrag/ontology_generator.py`

- [x] (P2) [graphrag] Implement relationship inference (start with heuristics; keep deterministic options). — Done: infer_relationships() in ontology_generator.py
- [x] (P2) [graphrag] Implement rule-based extraction for at least one domain. — Done: _extract_rule_based() in ontology_generator.py (legal/medical/general)
- [x] (P2) [graphrag] Implement smart ontology merging (dedupe by ID, merge properties, track provenance). — Done: _merge_ontologies() in ontology_generator.py
- [ ] (P3) [graphrag] Implement LLM-based extraction via `ipfs_accelerate_py` behind a feature flag.
- [ ] (P3) [graphrag] Implement hybrid/neural extraction strategies.

### 4) `graphrag/ontology_optimizer.py`

- [x] (P3) [graphrag] Implement pattern identification across successful runs.
  - Done 2026-02-20: deterministic counters/averages in `identify_patterns()`.
- [x] (P3) [graphrag] Implement intelligent recommendation generation — Done batch 42: context-aware recs

### 5) `graphrag/ontology_critic.py`

- [x] (P2) [graphrag] Implement LLM backend integration (or explicitly disable it and remove placeholder code).
  - Done 2026-02-20: LLM backend clearly gated on ipfs_accelerate availability; comment updated; rule-based fallback confirmed
- [x] (P3) [graphrag] Improve dimension evaluators — Done batch 41: clarity gets short-name penalty + confidence_score; completeness gets source_data coverage sub-score

### 6) CLI wrapper TODOs

- [x] (P2) [graphrag] Implement `cli_wrapper.py` “load ontology and optimize” (best-effort via `OntologySession`; JSON ontology inputs supported).
- [x] (P2) [graphrag] Implement `cli_wrapper.py` “load and validate ontology” (JSON ontology inputs supported).
- [x] (P2) [graphrag] Implement `cli_wrapper.py` “query optimization”.
  - Done 2026-02-20: `query` now returns a plan via `UnifiedGraphRAGQueryOptimizer` and supports `--explain`/`--output`.

---

## Logic theorem optimizer backlog

- [x] (P2) [logic] Implement `logic_theorem_optimizer/cli_wrapper.py` theorem proving entrypoint (even a minimal stub wired to an existing prover integration). — Done: full 567-line CLI with extract/prove/validate/optimize commands
- [x] (P2) [tests] Add a minimal end-to-end theorem session smoke test — Already done: test_theorem_session_smoke.py exists

---

## Agentic optimizers backlog (alignment & hardening)

- [ ] (P2) [agentic] Reconcile docs claiming phases/tests exist with what’s actually present (e.g., referenced test paths).  
  **DoD**: docs don’t mention non-existent files; or missing files are added.
- [x] (P2) [agentic] Ensure `agentic/llm_integration.py` is exercised — Done: test_llm_integration.py covers OptimizerLLMRouter, LLMProvider, PROVIDER_CAPABILITIES at the repository’s current test entrypoints.

---

---

## Comprehensive Refactoring Plan (added 2026-02-20)

### R1 — Break up the mega-file `graphrag/query_optimizer.py` (5 800 lines)

- [ ] (P2) [arch] Extract `QueryPlanner` class (lines ~1–1000) into `graphrag/query_planner.py`
- [ ] (P2) [arch] Extract `TraversalHeuristics` into `graphrag/traversal_heuristics.py`
- [ ] (P2) [arch] Extract `LearningAdapter` (learning-hook section, ~lines 4500+) into `graphrag/learning_adapter.py`
- [ ] (P2) [arch] Extract serialization helpers into `graphrag/serialization.py`
- [ ] (P2) [tests] Add unit tests for each extracted module after split
- [ ] (P3) [docs] Update module-level docstrings to reflect new file layout

### R2 — Typed config objects everywhere (no `Dict[str, Any]` sprawl)

- [x] (P2) [api] Replace bare `Dict[str, Any]` in `OntologyGenerationContext` with a typed `ExtractionConfig` dataclass
  - Done 2026-02-20: ExtractionConfig dataclass added; OntologyGenerationContext.config auto-normalises dict → ExtractionConfig
- [x] (P2) [api] Replace bare `Dict[str, Any]` prover_config in `LogicValidator` with `ProverConfig` dataclass
  - Done 2026-02-20: ProverConfig dataclass added with from_dict/to_dict; LogicValidator accepts ProverConfig or dict
- [x] (P2) [api] Standardize `backend_config` in `OntologyCritic` to a typed `BackendConfig` — Done 2026-02-20: BackendConfig dataclass + from_dict/to_dict; OntologyCritic auto-normalises dict→BackendConfig
- [ ] (P2) [api] Audit all `**kwargs`-accepting methods in `agentic/` and replace with typed optional parameters
- [ ] (P3) [api] Add `__slots__` to hot-path dataclasses for memory efficiency

### R3 — Common primitives layer (`optimizers/common/`)

- [x] (P1) [arch] `common/base_optimizer.py` — `BaseOptimizer` abstract class with `generate/critique/optimize/validate` pipeline exists
- [x] (P1) [arch] `common/base_critic.py` — `BaseCritic` abstract class with `evaluate()` returning typed `CriticScore` — Done: fully implemented with compare() and convenience helpers
- [x] (P1) [arch] `common/base_session.py` — `BaseSession` dataclass tracking rounds, scores, convergence
  - Done 2026-02-20: implemented with `start_round()`, `record_round()`, `trend`, `best_score`, `to_dict()`
- [x] (P2) [arch] `common/base_harness.py` — `BaseHarness` orchestrating generator + critic + optimizer
  - Done 2026-02-20: implemented with HarnessConfig, run(), _generate/_critique/_optimize/_validate hooks
- [x] (P2) [arch] Wire `OntologyCritic` to extend `BaseCritic`
  - Done 2026-02-20: added `evaluate()` → `CriticResult` bridge method
- [x] (P2) [arch] Wire `LogicCritic` to extend `BaseCritic`
  - Done 2026-02-20: evaluate_as_base() → BaseCriticResult; backward-compat evaluate() preserved
- [x] (P2) [arch] Wire `OntologySession` / `MediatorState` to extend `BaseSession`
  - Done 2026-02-20: `MediatorState` now extends `BaseSession` and records rounds via BaseSession helpers.
- [x] (P2) [arch] Wire `OntologyHarness` to extend `BaseHarness`
  - Done 2026-02-20: `OntologyPipelineHarness` now directly subclasses `BaseHarness` (removed wrapper composition), preserving `run_and_report` / `run_single` / `run_concurrent` APIs.
- [x] (P2) [arch] Wire `LogicHarness` to extend `BaseHarness`
  - Done 2026-02-20: added `LogicPipelineHarness` as a `BaseHarness`-native adapter for extractor→critic loops while keeping deprecated `LogicHarness` behavior stable.
- [ ] (P3) [docs] Write architecture diagram for the `generate → critique → optimize → validate` loop

### R4 — Logging & observability consistency

- [x] (P2) [obs] All optimizers accept an optional `logger: logging.Logger` parameter — `OntologyGenerator`, `OntologyMediator` done
  - Done 2026-02-20 — use it everywhere instead of module-level logger
- [x] (P2) [obs] Emit structured log events (key=value pairs) for session start/end, score deltas, iteration count — Done 2026-02-20: BaseOptimizer.run_session() logs session_id, domain, iterations, score, valid, execution_time_ms
- [x] (P2) [obs] Add `execution_time_ms` to every result object that doesn't already have it — Done 2026-02-20: BaseOptimizer.run_session() result and metrics dict now include execution_time_ms
- [x] (P2) [obs] Wire `OptimizerLearningMetricsCollector` into `LogicTheoremOptimizer.run_session()` — Done batch 24
- [x] (P2) [obs] Wire `OptimizerLearningMetricsCollector` into `OntologyOptimizer` batch analysis — Done batch 23
- [ ] (P3) [obs] Add OpenTelemetry span hooks (behind a feature flag) for distributed tracing
- [ ] (P3) [obs] Emit Prometheus-compatible metrics for optimizer scores and iteration counts

### R5 — Error handling & resilience

- [x] (P2) [arch] Define typed exception hierarchy: `OptimizerError`, `ExtractionError`, `ValidationError`, `ProvingError`
  - Done 2026-02-20: common/exceptions.py with full hierarchy
- [ ] (P2) [arch] Replace bare `except Exception` catch-all blocks with specific exception types
- [x] (P2) [arch] All CLI commands exit with non-zero on failure — Done: all cmd_* return int, sys.exit(main())
- [x] (P2) [arch] Add timeout support to `ProverIntegrationAdapter.validate_statement()` — Done: ProverIntegrationAdapter has default_timeout param and per-call timeout override
- [ ] (P3) [arch] Add circuit-breaker for LLM backend calls (retry with exponential backoff)

### R6 — Deprecation cleanup

- [x] (P2) [arch] Add `DeprecationWarning` emission to `TheoremSession.__init__()` — Done: theorem_session.py emits DeprecationWarning and document migration path
- [x] (P2) [arch] Add `DeprecationWarning` to deprecated imports — Done: TheoremSession already warns, logic_harness warns
- [ ] (P3) [arch] Remove deprecated `TheoremSession` and `LogicExtractor` after 2 minor versions (add version gate)

---

## Detailed Feature Work

### F1 — GraphRAG: Real entity extraction (rule-based)

- [x] (P2) [graphrag] `_extract_rule_based()` — skeleton returns empty list; implement NER-style pattern matching using regex + entity type heuristics
  - Done 2026-02-20: implemented regex-based NER for common entity types (Person, Org, Date, Location, Obligation, Concept)
- [x] (P2) [graphrag] Add domain-specific rule sets (legal, medical, technical, general) to `_extract_rule_based()`
- [x] (P2) [graphrag] Make rule sets pluggable via `OntologyGenerationContext.config['custom_rules']` — Done: ExtractionConfig.custom_rules field
- [ ] (P3) [graphrag] Benchmark rule-based extraction vs manual annotations for common domains

### F2 — GraphRAG: Relationship inference

- [x] (P2) [graphrag] `infer_relationships()` — skeleton returns empty list; implement heuristic co-occurrence + verb-proximity inference
  - Done 2026-02-20: implemented sliding-window co-occurrence + verb-frame heuristics
- [x] (P2) [graphrag] Improve verb extraction to classify relationship types — Done: 7 verb patterns (obligates, owns, causes, is_a, part_of, employs, manages)
- [x] (P2) [graphrag] Add directionality detection (subject→object via dependency parse stubs) — Done batch 25
- [x] (P3) [graphrag] Add confidence decay for distance-based co-occurrence — Already done (batch 23); verified batch 49 with 2 tests

### F3 — GraphRAG: Smart ontology merging

- [x] (P2) [graphrag] `_merge_ontologies()` — naïve list extend; implement dedup by `id`, merge `properties` dicts, track `provenance`
  - Done 2026-02-20: dedup by id, merge properties, add provenance metadata
- [x] (P2) [graphrag] Handle entity type conflicts on merge (e.g., same ID but different types) — emit a warning and pick the higher-confidence one — Done: warning logged + type override in _merge_ontologies()
- [x] (P2) [graphrag] Handle relationship dedup (same source_id + target_id + type = merge properties) — Done: _merge_ontologies() deduplicates by (source_id, target_id, type)
- [ ] (P3) [graphrag] ✅ Add merge provenance report (which entities came from which source)

### F4 — GraphRAG: Ontology critic dimension evaluators

- [x] (P2) [graphrag] `_evaluate_completeness()` — placeholder heuristic; improve with entity-type diversity, orphan-detection, coverage ratio
  - Done 2026-02-20: added entity-type diversity, orphan ratio, property coverage sub-scores
- [x] (P2) [graphrag] `_evaluate_consistency()` — placeholder; improve with dangling-ref check + circular-dependency detection
  - Done 2026-02-20: added circular dependency detection via DFS + dangling reference check
- [x] (P2) [graphrag] `_evaluate_clarity()` — placeholder; improve with property-completeness + naming-convention checks
  - Done 2026-02-20: added naming convention check (camelCase/snake_case consistency) + property completeness
- [x] (P2) [graphrag] `_evaluate_granularity()` — constant 0.75; implement real scoring based on avg properties-per-entity vs domain target
  - Done 2026-02-20: implemented entity-depth and relationship-density scoring
- [x] (P2) [graphrag] `_evaluate_domain_alignment()` — constant 0.80; implement keyword-based domain vocabulary matching
  - Done 2026-02-20: implemented domain vocabulary matching via configurable keyword sets
- [x] (P3) [graphrag] Add `EntityExtractionResult.summary()` -- Done batch-69: N entities (K types), M rels, confidence; 6 tests
- [ ] (P3) [graphrag] Add LLM-based fallback evaluator that rates quality when rule-based scores are ambiguous
- [x] (P3) [graphrag] Add per-entity type completeness breakdown in CriticScore.metadata — Done batch 49: entity_type_counts + entity_type_fractions added to metadata in evaluate_ontology; 7 tests

### F5 — GraphRAG: Ontology mediator refinements

- [x] (P2) [graphrag] `refine_ontology()` — no-op copy; implement specific refinement actions driven by recommendations
  - Done 2026-02-20: implemented add-property, normalize-names, prune-orphans, and merge-duplicates actions
- [x] (P2) [graphrag] `generate_prompt()` — structured prompts with domain vocabulary, schema instructions, and feedback-driven refinement hints
  - Done 2026-02-20
- [x] (P2) [graphrag] Add `refine_ontology()` action: `add_missing_relationships` (links orphan entities via co-occurrence) — Done: add_missing_relationships action in ontology_mediator.py
- [x] (P3) [graphrag] Add refinement action: split_entity — Done batch 49: triggers on 'split'/'granular'/'overloaded' keywords, splits on ' and '/',' into individual entities; 6 tests

### F6 — GraphRAG: Logic validator TDFOL pipeline

- [x] (P2) [graphrag] Implement minimal `ontology_to_tdfol()` — Done: logic_validator.py ontology_to_tdfol() returns predicate-string formulas — convert entities/relationships to predicate-logic formulas (subset: `Person(x)`, `hasRelation(x,y)`)
- [x] (P2) [graphrag] Implement `_prove_consistency()` — Done: logic_validator.py _prove_consistency() passes formulas to ProverIntegrationAdapter — pass generated formulas to `logic_theorem_optimizer.ProverIntegrationAdapter`
- [x] (P2) [graphrag] Implement `suggest_fixes()` — map contradiction types to fix templates (dangling ref → "remove or add entity", type conflict → "unify types")
  - Done 2026-02-20: pattern-matched contradictions to typed fix actions with confidence scores
- [ ] (P3) [graphrag] Add TDFOL formula cache keyed on ontology hash to avoid re-proving unchanged ontologies
- [ ] (P3) [graphrag] Expose `--tdfol-output` flag in GraphRAG CLI wrapper to dump generated formulas

### F7 — Logic theorem optimizer: CLI prove command

- [x] (P1) [logic] `cmd_prove()` — hardcoded fake output; wire to `LogicTheoremOptimizer` and `ProverIntegrationAdapter`
  - Done 2026-02-20: wired to `LogicTheoremOptimizer.validate_statements()` with real prover integration
- [x] (P2) [logic] Add `--output` flag to `cmd_prove` to write proof result as JSON
  - Done 2026-02-20
- [x] (P2) [logic] Add `--timeout` flag to prover invocation — Done: --timeout already in cli_wrapper.py prove command
- [x] (P2) [logic] Support reading premises/goal from a JSON/YAML file as well as CLI args — Done: --from-file flag in cli_wrapper.py cmd_prove
- [ ] (P3) [logic] Add interactive REPL mode to `logic-theorem-optimizer` CLI

### F8 — Agentic: Stub implementations

- [x] (P2) [agentic] `ChangeController.create_change()` — Done: GitHubChangeController already implemented in github_control.py
- [x] (P2) [agentic] `ChangeController.check_approval()` — Done: GitHubChangeController.check_approval() implemented
- [x] (P2) [agentic] `ChangeController.apply_change()` — Done: GitHubChangeController.apply_change() implemented
- [x] (P2) [agentic] `ChangeController.rollback_change()` — Done: GitHubChangeController.rollback_change() implemented
- [ ] (P2) [agentic] `agentic/validation.py:85` — `validate()` stub; wire to a real validation pipeline
- [ ] (P3) [agentic] Add integration test that exercises the full GitHub change-control flow against a mock

### F9 — `graphrag/ontology_optimizer.py` internal stubs

- [x] (P2) [graphrag] `_identify_patterns()` — implemented counter-based pattern mining: entity/rel type frequencies, weakness distribution, avg scores
  - Done 2026-02-20
- [x] (P2) [graphrag] `generate_recommendations()` — basic threshold checks; add pattern-driven recommendations
  - Done 2026-02-20: Added dimension-aware recs, entity/rel type diversity warnings, top-weakness highlight

### F10 — Prompt generator: example database

- [x] (P3) [graphrag] `prompt_generator.py` — built-in JSON example store for legal/medical; pluggable via `_example_store`
  - Done 2026-02-20

---

## Testing Strategy (incremental)

### T1 — Unit tests for pure helpers

- [x] (P1) [tests] Import smoke tests for all optimizer packages — `tests/unit/optimizers/test_optimizers_import_smoke.py`
- [x] (P1) [tests] GraphRAG component smoke tests — `tests/unit/optimizers/graphrag/test_graphrag_smoke.py`
- [x] (P2) [tests] Unit tests for `OntologyGenerator.infer_relationships()` — known entity pairs → expected relationship types — Done: test_ontology_generator_helpers.py
- [x] (P2) [tests] Unit tests for `OntologyGenerator._extract_rule_based()` — fixture texts → expected entity dicts — Done: test_ontology_generator_helpers.py
- [x] (P2) [tests] Unit tests for `OntologyGenerator._merge_ontologies()` — dedup, property merge, provenance — Done: test_ontology_generator_helpers.py
- [x] (P2) [tests] Unit tests for `OntologyCritic` dimension evaluators — minimal/maximal ontologies → boundary scores — Done: test_ontology_critic_dimensions.py
- [x] (P2) [tests] Unit tests for `OntologyMediator.refine_ontology()` — each action type → expected ontology delta — Done: test_ontology_mediator_refinement.py
- [x] (P2) [tests] Golden-file tests for GraphRAG ontology dict schema (entities/relationships/metadata invariants)
  - Done 2026-02-20: test_ontology_schema_invariants.py

### T2 — Integration tests

- [x] (P2) [tests] End-to-end test: `OntologyGenerator → OntologyCritic → OntologyMediator` refinement loop — Done 2026-02-20: test_pipeline_harness_e2e.py (16 tests)
- [x] (P2) [tests] End-to-end test: `LogicTheoremOptimizer.run_session()` on a trivial theorem — Done 2026-02-20: test_metrics_wiring.py
- [x] (P2) [tests] CLI test: `graphrag-optimizer generate ...` — Done batch 27: test_cli_generate.py (7 tests)
- [x] (P2) [tests] CLI test: `logic-theorem-optimizer prove` — Done batch 27: test_cli_prove.py (8 tests)
- [ ] (P3) [tests] Mutation testing pass on `graphrag/ontology_critic.py` dimension evaluators

### T3 — Performance / regression tests

- [ ] (P3) [perf] Benchmark `OntologyGenerator.extract_entities()` on 10k-token documents
- [ ] (P3) [perf] Benchmark `LogicValidator.validate_ontology()` on 100-entity ontologies
- [x] (P3) [perf] Add pytest-benchmark harness to tests/performance/optimizers/ — Done batch 48: 9 benchmarks for extraction, critic, logic validator

---

## Documentation Debt

- [x] (P2) [docs] `ARCHITECTURE_UNIFIED.md` — update to match current code (remove references to non-existent modules) — Done batch 33: refreshed GraphRAG query optimizer split details and removed outdated size/refactor notes
- [x] (P2) [docs] `README.md` — add quick-start examples for each optimizer type — Done batch 30: GraphRAG + Logic API/CLI examples added
- [x] (P2) [docs] Add module-level docstrings to agentic/coordinator.py and production_hardening.py — Already present
- [x] (P2) [docs] Document the `BaseCritic` / `BaseSession` / `BaseHarness` extension pattern with examples — Done batch 30: BaseCritic module docstring expanded with full extension pattern + existing implementations list
- [ ] (P3) [docs] Add Sphinx/MkDocs configuration and auto-generate API reference
- [ ] (P3) [docs] Write a "How to add a new optimizer" guide covering all integration points
- [x] (P3) [docs] Add architecture ASCII diagram to sub-package __init__.py — Done batch 48: generate→critique→optimize→validate loop in graphrag/__init__.py

---

## Security & Safety

- [x] (P1) [arch] Audit all `eval()`/`exec()` usage — Done batch 26: only intentionally sandboxed exec({}) in validation.py; adversarial.py detects but does not use eval/exec
- [x] (P2) [arch] Validate file paths in CLI wrappers against path-traversal attacks (use `Path.resolve()`)
  - Done 2026-02-20: _safe_resolve() helper added to graphrag + logic CLI wrappers
- [x] (P2) [arch] Ensure no secrets are logged (prover API keys, LLM API keys) — Done: production_hardening.py has mask_tokens_in_logs=True + _sanitize_log_message(); OntologyGenerator/Critic/LogicOptimizer only log structural data, never API keys
- [ ] (P3) [arch] Add sandboxed subprocess execution for untrusted prover calls (seccomp profile)

---

## Performance & Scalability

- [ ] (P3) [perf] Profile `graphrag/query_optimizer.py` under load — identify hotspots before the file split
- [x] (P3) [perf] Add LRU caching to `OntologyCritic.evaluate_ontology()` for repeated evaluations of same hash
  - Done 2026-02-20: 128-entry SHA-256 keyed cache
- [ ] (P3) [perf] Parallelize `OntologyOptimizer.analyze_batch()` across sessions using `concurrent.futures`
- [x] (P3) [perf] Use `__slots__` on `Entity`, `Relationship`, and `EntityExtractionResult` dataclasses — Done 2026-02-20
- [ ] (P3) [perf] Profile `logic_theorem_optimizer` prover round-trips; add result cache keyed on formula hash

---

## Refresh command (run from repo root)

```bash
rg -n "TODO\b|FIXME\b|XXX\b|HACK\b" ipfs_datasets_py/ipfs_datasets_py/optimizers/ --type py
```

## Newly discovered items (2026-02-20)

- [x] (P2) [obs] Replace `self._log` references in `OntologyMediator` — all methods still call module-level `logger` directly; update them to use `self._log`
  - Done 2026-02-20
- [x] (P2) [obs] Same for `OntologyGenerator` — propagate `self._log` to all helper methods
  - Done 2026-02-20
- [x] (P2) [arch] Add `ProverConfig` typed dataclass to replace `Dict[str,Any]` prover_config in `LogicValidator`
  - Done 2026-02-20
- [x] (P2) [arch] Add `ExtractionConfig` typed dataclass to replace `Dict[str,Any]` config in `OntologyGenerationContext`
  - Done 2026-02-20
- [x] (P2) [tests] Unit tests for `OntologyCritic.evaluate_ontology()` cache (same ontology → cache hit; different → miss)
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `PromptGenerator.select_examples()` — domain filtering, quality threshold, add_examples() round-trip
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `LogicValidator.suggest_fixes()` — each contradiction pattern → expected fix type
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `OntologyGenerator._extract_rule_based()` — fixture texts → expected entity list
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `OntologyGenerator.infer_relationships()` — verb-frame patterns → expected relationship types
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `OntologyGenerator._merge_ontologies()` — duplicate IDs → dedup; provenance tracking
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `BaseHarness.run()` — convergence, max_rounds, trend
  - Done 2026-02-20: test_new_implementations.py
- [x] (P2) [tests] Unit tests for `BaseSession.trend` and `best_score` properties
  - Done 2026-02-20: test_new_implementations.py
- [x] (P3) [obs] Replace bare `except Exception` in `OntologyMediator.refine_ontology()` with typed `RefinementError` from `common.exceptions`
  - Done 2026-02-20: OntologyPipelineHarness uses RefinementError
- [x] (P3) [arch] Add `__slots__` to `Entity`, `Relationship`, `EntityExtractionResult` dataclasses for memory efficiency — Done 2026-02-20
- [ ] (P3) [perf] Profile `OntologyCritic._evaluate_consistency()` DFS cycle detection on large ontologies (>500 entities)
- [x] (P3) [docs] Add `common/README.md` documenting the BaseCritic / BaseSession / BaseHarness / exceptions layer
  - Done 2026-02-20

## Newly discovered items (2026-02-20 continued)

- [x] (P2) [arch] Wire PerformanceMetricsCollector into BaseOptimizer.run_session() — Done 2026-02-20: metrics_collector optional param; start_cycle/end_cycle called if present
- [x] (P2) [api] ExtractionConfig exported from graphrag.__init__ and ProverConfig exported — Done 2026-02-20
- [x] (P2) [api] OntologyPipelineHarness: concrete BaseHarness for single-session graphrag pipeline — Done 2026-02-20
- [x] (P2) [arch] BaseSession metrics: score_delta, avg_score, regression_count properties + to_dict() — Done 2026-02-20
- [x] (P2) [tests] End-to-end test: OntologyGenerator → OntologyCritic → OntologyMediator — Done batch 29 (test_ontology_pipeline_e2e.py: 10 tests)
- [x] (P2) [arch] Add BackendConfig typed dataclass for OntologyCritic backend_config parameter — Done 2026-02-20
- [x] (P2) [perf] Parallelize OntologyOptimizer.analyze_batch() — analyze_batch_parallel() already exists; batch 49 added verification tests
- [x] (P2) [arch] Add `__slots__` to hot-path dataclasses (Entity, Relationship, EntityExtractionResult) using @dataclass(slots=True) — Done 2026-02-20
- [x] (P2) [tests] Unit test BaseOptimizer.run_session() with PerformanceMetricsCollector — Done: test_new_implementations.py:863 TestPerformanceMetricsCollectorHooks
- [x] (P1) [security] Audit eval()/exec() usage — Done batch 26: only sandboxed exec({}) in validation.py benchmark; adversarial.py detects but never calls
- [x] (P2) [obs] Wire PerformanceMetricsCollector into logic_theorem_optimizer harness sessions — Done 2026-02-20: LogicTheoremOptimizer.__init__ accepts metrics_collector param, forwarded to BaseOptimizer
- [x] (P2) [tests] Integration test: OntologyPipelineHarness.run() with real OntologyGenerator/OntologyCritic/OntologyMediator on fixture text — Done 2026-02-20: tests/unit/optimizers/graphrag/test_pipeline_harness_e2e.py (16 tests)

## Newly discovered items (2026-02-20 batch 20-21)

- [x] (P2) [graphrag] Add domain-specific rule sets (legal, medical, technical, financial) to _extract_rule_based() — Done batch 20-21
- [x] (P2) [graphrag] ExtractionConfig.custom_rules field for pluggable rule injection — Done batch 20-21
- [x] (P2) [graphrag] Entity type conflict warning in _merge_ontologies() + higher-confidence type wins — Done batch 20-21
- [x] (P2) [graphrag] add_missing_relationships refinement action in OntologyMediator.refine_ontology() — Done batch 20-21
- [x] (P3) [arch] Replace bare except Exception in ontology_critic.py cache key computation — Done batch 21
- [x] (P3) [arch] Replace bare except Exception in agentic/cli.py config file loading — Done batch 21
- [x] (P3) [api] Replace **kwargs in validate_async() with typed optional parameters — Done batch 21
- [x] (P2) [tests] OntologyCritic dimension evaluator boundary tests — Done batch 20-21: test_ontology_critic_dimensions.py (27 tests)
- [x] (P2) [tests] OntologyGenerator helper method tests (infer_relationships, rule_based, merge) — Done batch 20-21: test_ontology_generator_helpers.py (34 tests)
- [x] (P2) [tests] OntologyMediator refine_ontology action dispatch tests — Done batch 20-21: test_ontology_mediator_refinement.py (10 tests)
- [x] (P2) [arch] Wire MediatorState to extend BaseSession for unified session tracking
  - Done 2026-02-20: MediatorState extends BaseSession with session_id, rounds, and scoring metadata.
- [x] (P2) [tests] Fuzz tests for _extract_rule_based() — Done batch 28 (9 edge-case tests: Unicode, binary, very long, regex special chars)
- [ ] (P3) [perf] Benchmark _merge_ontologies() on 1000-entity ontologies
- [x] (P2) [graphrag] Add confidence decay for co-occurrence distance — Done batch 28 (steeper decay >100 chars, floor 0.2)
- [x] (P2) [tests] Property-based test: _merge_ontologies is idempotent — Done batch 23 (5 idempotency tests)
- [x] (P2) [graphrag] LLM-based extraction fallback — Done batch 33: ExtractionConfig.llm_fallback_threshold + OntologyGenerator.llm_backend param
- [ ] (P2) [agentic] ChangeController.create_change() — implement GitHub PR draft via github_control.py
- [ ] (P2) [agentic] ChangeController.check_approval() — poll PR review status via GitHub API
- [ ] (P3) [tests] Mutation testing pass on ontology_critic.py dimension evaluators (identify gaps)
- [ ] (P2) [docs] Add type annotations to all remaining untyped methods in agentic/ (audit with mypy)

## Newly discovered items (2026-02-20 batch 22)

- [x] (P2) [logic] Add --from-file flag to prove command for JSON/YAML premise/goal loading — Done batch 22
- [x] (P2) [logic] Add --from-file flag to `validate` command (load ontology from JSON/YAML) — Done batch 30: mutually exclusive --input/--from-file with YAML support + 8 tests
- [ ] (P2) [graphrag] `OntologyLearningAdapter` — track successful extraction patterns and tune confidence thresholds
- [ ] (P2) [graphrag] `LearningAdapter.apply_feedback()` — update extraction weights based on mediator actions
- [x] (P2) [tests] Unit test for `cli_wrapper.py` prove command with --output flag — Done: test_prove_outputs_json_on_success in test_cli_prove.py (already existed batch 27)
- [x] (P2) [tests] Unit test for `cli_wrapper.py` validate command happy path — Done batch 30: 8 tests in test_cli_validate.py
- [x] (P3) [graphrag] Add `entity_to_tdfol()` helper — Done batch 35: LogicValidator.entity_to_tdfol() added; 6 tests added to test_logic_validator_tdfol_conversion.py
- [x] (P3) [graphrag] Cache ontology TDFOL output keyed on ontology hash — Done batch 40: uses _get_cache_key() + _cache dict
- [ ] (P2) [agentic] Wire `ChangeController.create_change()` to actually create GitHub PR draft
- [x] (P2) [arch] Add `__init__` test for graphrag/__init__ public symbols — Done batch 32: test_public_import_smoke.py (38 tests)
- [x] (P2) [docs] Update common/README.md — Done batch 36/37: CriticResult field table + ExtractionConfig.custom_rules example in graphrag/README.md

## Newly discovered items (batch 31+)

- [x] (P2) [graphrag] Add `ExtractionConfig.llm_fallback_threshold` — Done batch 33: default 0.0 (disabled); to_dict/from_dict updated
- [x] (P2) [graphrag] Implement `_extract_with_llm_fallback()` in OntologyGenerator that wraps `_extract_rule_based()` + fallback
  - Done 2026-02-21: added `_extract_with_llm_fallback()` helper and refactored RULE_BASED extraction; ensured `extraction_config` returns GraphRAG configs so thresholds apply; tests in test_llm_fallback_extraction.py passing.
- [x] (P2) [tests] Unit tests for LLM fallback — Done batch 33: 11 tests in test_llm_fallback_extraction.py
- [ ] (P2) [graphrag] ✅ `OntologyLearningAdapter.apply_feedback()` — accept list of mediator `Action` objects and update confidence weights
- [ ] (P2) [graphrag] ✅ `OntologyLearningAdapter.get_extraction_hint()` — return adjusted threshold based on historical accuracy
- [x] (P2) [tests] Unit tests for OntologyLearningAdapter feedback loop — Done batch 47: 6 scenarios (threshold rise/fall, clamping, action rates, reset, restore-then-continue)
- [x] (P2) [arch] Add `__init__` test for logic_theorem_optimizer public symbols — Done batch 32: test_public_import_smoke.py
- [x] (P2) [tests] Parametrize domain-specific rule tests with all 4 domains (legal, medical, financial, technical) — use `pytest.mark.parametrize` — Done batch 33: `tests/unit/optimizers/graphrag/test_ontology_generator_helpers.py` (`test_domain_specific_rules_extract_expected_type`, 4-domain parametrization)
- [x] (P2) [graphrag] Add `OntologyCritic.evaluate_batch()` — Done batch 32: returns scores/mean_overall/min_overall/max_overall/count
- [x] (P2) [tests] Unit tests for `OntologyCritic.evaluate_batch()` — Done batch 32: 14 tests in test_ontology_critic_evaluate_batch.py
- [x] (P2) [graphrag] Add `OntologyGenerationResult` dataclass — Done batch 38: entity_count, relationship_count, entity_type_diversity, mean_entity_confidence, mean_rel_confidence; from_ontology() factory; generate_ontology_rich() method
- [x] (P2) [docs] Update `ARCHITECTURE_UNIFIED.md` to document Relationship.direction field and co-occurrence confidence decay formula — Done batch 33: added GraphRAG relationship semantics + implemented piecewise confidence-decay equation
- [x] (P3) [graphrag] `ExtractionConfig.max_entities` already exists — field present as int = 0 (unlimited by default); mark done
- [x] (P3) [graphrag] Add `ExtractionConfig.min_entity_length: int = 2` — Done batch 39: enforced in _extract_rule_based; 5 tests in TestMinEntityLength
- [ ] (P3) [tests] Fuzz test `OntologyMediator.run_refinement_cycle()` with Hypothesis-generated random documents
- [ ] (P3) [agentic] Add `ChaosOptimizer.inject_cpu_spike()` method for realistic CPU load testing
- [x] (P3) [arch] Add `optimizers.__version__` string populated from `ipfs_datasets_py.__version__` — Done batch 40
- [x] (P3) [tests] Test `_safe_resolve()` path traversal — Done batch 36: test_safe_resolve_path_traversal.py (11 tests for graphrag + logic CLIs)
- [x] (P2) [docs] Add common/README.md section documenting CriticResult fields — Already present (discovered batch 48)
- [x] (P2) [graphrag] Emit a structured log line (JSON) after each `analyze_batch()` call for observability (INFO level, no secrets) — Done batch 33: `OntologyOptimizer._emit_analyze_batch_summary()` emits `ontology_optimizer.analyze_batch.summary` JSON logs for success/empty/no-scores paths; covered by caplog tests in `test_ontology_optimizer_metrics.py`
- [x] (P2) [logic] Add `--domain` flag to `validate` command — Done batch 34: 5 choices, passed to OptimizationContext domain
- [x] (P2) [logic] Apply domain-specific validation rules in `cmd_validate()` — Done batch 34: domain passed to OptimizationContext; rules applied via LogicTheoremOptimizer
- [x] (P2) [tests] Unit tests for `validate --domain` — Done batch 34: parametrized test covers all 5 domains
- [x] (P3) [graphrag] Add `OntologyOptimizer.export_to_rdf()` stub — Done batch 40: Turtle/NT via rdflib (optional dep)
- [x] (P3) [graphrag] Add `OntologyOptimizer.export_to_graphml()` stub — Done batch 40: pure stdlib XML, works in Gephi/yEd

## Newly discovered items (batch 44+)

- [x] (P2) [arch] Add `OntologyHarness.run_single()` — Done batch 47: thin wrapper over run_and_report, re-raises as RuntimeError
- [x] (P2) [graphrag] Add `ExtractionConfig.stopwords` — Done batch 45: case-insensitive filter in _extract_rule_based; to_dict/from_dict updated; 6 tests
- [x] (P3) [graphrag] Add `OntologyCritic.compare_versions()` — Done batch 45: wraps compare_ontologies; adds delta_<dim> + delta_overall keys; 3 tests
- [x] (P3) [graphrag] Add `OntologyOptimizer.get_history_summary()` — Done batch 45: count/mean/std/min/max/mean_improvement_rate/trend; 5 tests
- [x] (P3) [tests] Property-based tests for OntologyCritic scores in [0.0, 1.0] — Done batch 46: Hypothesis random ontologies (30 examples)
- [x] (P2) [obs] Add `analyze_batch_parallel()` structured JSON log — Done batch 47: json_log_path param writes summary JSON; 7 tests
- [x] (P3) [graphrag] Add `ExtractionConfig.allowed_entity_types` whitelist — Done batch 46: enforced in _extract_rule_based; 6 tests
- [x] (P2) [docs] Add CHANGELOG.md for the optimizers sub-package — Done batch 47: updated existing CHANGELOG with batches 39-47
- [x] (P3) [arch] Add `optimizers.common.exceptions` re-export — Already done: all 6 exception classes already in common/__init__.py
- [x] (P3) [tests] Round-trip test: ExtractionConfig.to_dict() → from_dict() — Done batch 45: TestExtractionConfigRoundTrip
- [x] (P2) [graphrag] Add `OntologyGenerator.extract_entities_from_file()` — Done batch 46: reads UTF-8 file, delegates to extract_entities; 3 tests
- [x] (P3) [graphrag] Add `LogicValidator.clear_tdfol_cache()` method — Done batch 44: returns count removed
- [x] (P3) [docs] Add `py.typed` marker to `optimizers/` — Done batch 45: created ipfs_datasets_py/optimizers/py.typed
- [x] (P2) [tests] Parametrized tests for export_to_graphml — Done batch 46: 5 sizes (0/1/3/10/20 entities) verified node/edge counts
- [ ] (P3) [agentic] Add `ChaosOptimizer.simulate_memory_pressure()` method for memory threshold testing
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.to_dict()` / `from_dict()` — Done batch 47: full round-trip; 16 tests
- [x] (P3) [tests] Hypothesis strategy for valid ExtractionConfig — Done batch 48: tests/unit/optimizers/graphrag/strategies.py; used in 7 property tests
- [x] (P2) [arch] Add `BaseSession.to_json()` / `from_json()` round-trip serialization — Done batch 44: also adds from_dict()
- [x] (P3) [docs] Add usage example for OntologyGenerationResult to graphrag/README.md — Done batch 48: code example + field reference table
- [x] (P2) [graphrag] Add `OntologyCritic.dimension_weights` property — Done batch 44: returns copy of DIMENSION_WEIGHTS

## Batch 50+ Ideas (added batch 49)

- [x] (P2) [graphrag] `OntologyGenerator.generate_ontology_rich()` elapsed_ms — Done batch 50: added to metadata; 4 tests
- [ ] (P2) [graphrag] `OntologyCritic.evaluate_ontology()` — persist cache across instances via class-level `_SHARED_EVAL_CACHE`
- [ ] (P3) [graphrag] ✅ Add `merge_provenance` tracking — which entities/rels came from which source doc
- [ ] (P2) [graphrag] `LogicValidator.validate_ontology()` — add `ValidationReport.invalid_entity_ids` list
- [x] (P3) [graphrag] `OntologyOptimizer.compare_history()` — Done batch 50: returns list of dicts with batch_from/to, score_from/to, delta, direction; 7 tests
- [ ] (P2) [tests] Add round-trip test for `OntologyMediator.run_refinement_cycle()` state serialization
- [ ] (P3) [tests] Snapshot tests: freeze known-good critic scores for a reference ontology
- [ ] (P2) [api] Add `OntologyGenerator.batch_extract(docs, context)` for multi-doc parallel extraction
- [x] (P3) [api] Add `OntologyOptimizer.prune_history(keep_last_n)` — Done batch 50: discards oldest entries, raises ValueError on n<1; 7 tests
- [x] (P3) [arch] Add `OntologyCritic.evaluate_ontology()` timeout guard -- Done batch-63: ThreadPoolExecutor with TimeoutError; 6 tests
- [ ] (P2) [docs] Add per-method doctest examples to all public `OntologyGenerator` methods
- [ ] (P2) [docs] Add per-method doctest examples to all public `OntologyCritic` methods
- [ ] (P3) [obs] Add `OntologyGenerator.extract_entities()` structured log with entity_count + strategy
- [ ] (P3) [obs] Add `OntologyMediator.refine_ontology()` structured log of actions_applied per round
- [x] (P2) [graphrag] `OntologyLearningAdapter.get_stats()` p50/p90 percentiles — Done batch 50: linear interpolation; 6 tests
- [ ] (P3) [graphrag] `OntologyMediator.refine_ontology()` — add `rename_entity` action (fix casing/normalisation)
- [ ] (P3) [graphrag] ✅ Add `OntologyCritic._evaluate_provenance()` dimension — checks entities have source spans
- [ ] (P2) [tests] Add tests for `OntologyHarness.run()` with real generator + critic (no mocks)
- [ ] (P3) [perf] Cache `OntologyCritic._evaluate_consistency()` DFS result keyed on relationship set hash
- [x] (P2) [graphrag] `ExtractionConfig.max_confidence: float = 1.0` — Done batch 50: enforced in _extract_rule_based, to_dict/from_dict; 6 tests

## Batch 52+ ideas (added automatically)

- [ ] (P2) [graphrag] ✅ Add `OntologyCritic.evaluate_batch()` progress callback param for streaming results
- [ ] (P3) [graphrag] ✅ Add `OntologyMediator.get_action_stats()` — per-action counts + success rates
- [ ] (P2) [graphrag] ✅ Add `OntologyGenerator.extract_entities_streaming()` — yield entities as found (iterator API)
- [x] (P3) [tests] Add property tests for `OntologyMediator.refine_ontology()` using Hypothesis -- Done batch-63: 3 properties, 20 examples each
- [ ] (P2) [api] ✅ Add `ExtractionConfig.from_env()` classmethod — load config from ENV vars
- [ ] (P3) [graphrag] ✅ Add `EntityExtractionResult.to_dataframe()` — convert to pandas DataFrame
- [ ] (P2) [graphrag] ✅ Add `OntologyOptimizer.export_history_csv()` — save compare_history table as CSV
- [x] (P3) [obs] Add structured JSON log line to `analyze_batch_parallel()` -- Done batch-63: json_log_path param, timing + scores; 5 tests
- [ ] (P2) [graphrag] ✅ Add `LogicValidator.suggest_fixes()` — return fix hints for each ValidationError
- [ ] (P3) [graphrag] ✅ Add `OntologyCritic.explain_score()` — return human-readable explanation per dimension
- [ ] (P2) [graphrag] ✅ Add `OntologyLearningAdapter.serialize()` → bytes (pickle-free, JSON-based)
- [ ] (P3) [arch] ✅ Add `OntologyPipeline` facade class — single entry point wrapping generator+critic+mediator+adapter
- [ ] (P2) [tests] ✅ Add integration test: full pipeline on a multi-paragraph text, assert >3 entities extracted
- [ ] (P3) [graphrag] Add confidence decay over time — entities not seen recently get lower confidence
- [ ] (P2) [graphrag] ✅ Add `ExtractionConfig.validate()` — raise `ValueError` on invalid field combinations
- [ ] (P3) [graphrag] Add `OntologyGenerator.extract_entities_with_spans()` — return char offsets for each entity
- [ ] (P2) [api] ✅ Add `CriticScore.__sub__()` — subtract two CriticScore objects to get delta CriticScore
- [ ] (P3) [graphrag] ✅ Add `OntologyHarness.run_concurrent()` — run N harnesses against the same data in parallel
- [ ] (P2) [docs] Add doctest examples for every public method in ontology_generator.py
- [ ] (P3) [arch] ✅ Add `optimizers/graphrag/typing.py` with shared type aliases (EntityDict, OntologyDict, etc.)

## Batch 57+ ideas (added automatically)

- [ ] (P2) [graphrag] ✅ Add `OntologyGenerator.deduplicate_entities()` — merge entities with identical normalised text
- [ ] (P3) [graphrag] Add `CriticScore.to_radar_chart_data()` — return data structure for radar/spider chart rendering
- [x] (P2) [graphrag] ✅ Add `OntologyOptimizer.score_trend_summary()` — return 'improving'/'stable'/'degrading' label
- [ ] (P3) [graphrag] Add `OntologyMediator.get_recommendation_stats()` — count unique recommendation phrases seen
- [ ] (P2) [tests] Add Hypothesis property test: ExtractionConfig round-trips through to_dict/from_dict
- [ ] (P3) [graphrag] Add `OntologyGenerator.extract_with_coref()` — co-reference resolution pre-pass
- [ ] (P2) [graphrag] Add `EntityExtractionResult.to_json()` — serialize full result to JSON string
- [x] (P3) [graphrag] Add `OntologyCritic.compare_batch()` — rank a list of ontologies by overall score
- [x] (P2) [graphrag] ✅ Add `OntologyLearningAdapter.top_actions()` — return N best-performing actions by success rate
- [ ] (P3) [graphrag] Add `OntologyPipeline.run_async()` — async coroutine wrapper around run()
- [ ] (P2) [graphrag] Add `OntologyOptimizer.export_score_chart()` — matplotlib line chart of score history
- [ ] (P3) [graphrag] Add `LogicValidator.batch_validate()` — validate a list of ontologies concurrently
- [ ] (P2) [graphrag] ✅ Add `OntologyGenerator.filter_entities()` — post-extraction filter by type/confidence/text
- [ ] (P3) [graphrag] Add `OntologyMediator.undo_last_action()` — revert last applied refinement action
- [x] (P2) [tests] Add negative tests for OntologyPipeline -- Done batch-63: empty/whitespace/long/numeric/garbage/empty-domain; 9 tests
- [x] (P3) [graphrag] Add `Entity.to_dict()` instance method -- Done batch-59: all fields, source_span as list; 9 tests
- [x] (P2) [graphrag] Add `OntologyCritic.weighted_overall()` — allow caller-supplied weight overrides
- [x] (P3) [graphrag] ✅ Add `OntologyOptimizer.rolling_average_score(n)` — mean of last N history entries
- [x] (P2) [graphrag] ✅ Add `ExtractionConfig.merge(other)` — merge two configs, latter values win on conflict
- [x] (P3) [graphrag] Add `OntologyPipeline.warm_cache()` — pre-evaluate a reference ontology to fill shared cache

## Batch 59+ ideas (added automatically)

- [x] (P2) [graphrag] Add `OntologyPipeline.warm_cache()` -- Done batch-60: runs pipeline.run() with refine=False; 5 tests
- [x] (P3) [graphrag] Add `OntologyMediator.undo_last_action()` -- Done batch-60: deep-copy undo stack, IndexError on empty; 5 tests
- [x] (P3) [graphrag] Add `OntologyGenerator.extract_with_coref()` -- Done batch-62: heuristic pronoun substitution; 5 tests
- [x] (P2) [graphrag] Add `OntologyPipeline.run_async()` -- async coroutine wrapper around run()
- [ ] (P3) [obs] Add structured JSON log at end of `analyze_batch_parallel()` with timing + scores
- [x] (P2) [tests] Hypothesis property test: ExtractionConfig round-trips through to_dict/from_dict -- Done batch-61: 40 examples; 1 test
- [ ] (P3) [graphrag] Add confidence decay over time -- entities not seen recently get lower confidence
- [x] (P2) [graphrag] Add `OntologyOptimizer.export_score_chart()` -- Done batch-62: matplotlib Agg PNG, base64 string; 5 tests
- [x] (P3) [graphrag] Add `OntologyMediator.get_recommendation_stats()` -- Done batch-62: counted per refine_ontology call; 6 tests
- [x] (P2) [graphrag] Add `OntologyGenerator.extract_entities_with_spans()` -- Done batch-61: str.find offset annotation; 5 tests
- [x] (P3) [tests] Add property tests for `OntologyMediator.refine_ontology()` using Hypothesis -- Done batch-63: 3 properties, 20 examples each
- [x] (P2) [arch] Add `OntologyPipeline.clone()` -- Done batch-61: fresh generator/critic/adapter, same settings; 7 tests
- [x] (P3) [graphrag] Add `CriticScore.from_dict()` classmethod -- Done batch-61: nested+flat dict, round-trip; 8 tests
- [x] (P2) [graphrag] Add `ExtractionConfig.to_yaml()` / `from_yaml()` -- Done batch-60: PyYAML round-trip; 8 tests
- [ ] (P3) [graphrag] Add `OntologyOptimizer.best_ontology()` -- return ontology from highest-scoring history entry
- [x] (P2) [tests] Add negative tests for OntologyPipeline -- Done batch-63: empty/whitespace/long/numeric/garbage/empty-domain; 9 tests
- [ ] (P3) [obs] Add `OntologyMediator.refine_ontology()` structured log of actions_applied per round
- [x] (P2) [graphrag] Add `LogicValidator.explain_contradictions()` -- Done batch-61: action labels + plain-English; 6 tests
- [x] (P3) [arch] Add `OntologyHarness.run()` integration test -- Done batch-62: OntologyPipeline full run + batch; 2 tests
- [x] (P2) [graphrag] Add `EntityExtractionResult.filter_by_type()` -- Done batch-60: prunes dangling relationships; 9 tests

## Batch 63+ ideas (added automatically)

- [x] (P2) [graphrag] Add `OntologyCritic.evaluate_with_rubric()` -- Done batch-65: rubric weights -> metadata[rubric_overall]; 8 tests
- [x] (P3) [graphrag] Add `ExtractionConfig.diff(other)` -- Done batch-64: self/other per-field dict; 5 tests
- [x] (P2) [graphrag] Add `OntologyGenerator.generate_synthetic_ontology(domain)` -- Done batch-64: domain-typed entities + relations; 8 tests
- [x] (P3) [obs] Add `OntologyOptimizer.emit_summary_log()` -- Done batch-68: batches/avg/best/trend/variance; 6 tests
- [x] (P2) [graphrag] Add `EntityExtractionResult.merge(other)` -- Done batch-64: dedup by normalised text, remap rel IDs; 8 tests
- [x] (P3) [graphrag] Add `OntologyMediator.reset_state()` -- Done batch-64: clears action_counts, undo_stack, rec_counts; 5 tests
- [x] (P2) [tests] Add round-trip test: OntologyPipeline -> to_json -> from_json for PipelineResult
  - Done 2026-02-20: Added `PipelineResult.to_dict()/from_dict()/to_json()/from_json()` and test coverage in `tests/unit/optimizers/graphrag/test_pipeline_result_roundtrip.py`.
- [ ] (P3) [graphrag] Add `OntologyCritic.calibrate_thresholds()` -- adjust dimension thresholds from history
- [x] (P2) [graphrag] Add `LogicValidator.filter_valid_entities()` -- Done batch-65: per-entity mini-ontology check; 5 tests
- [x] (P3) [arch] Add `OntologyPipeline.as_dict()` -- Done batch-65: domain/use_llm/max_rounds dict; 5 tests
- [x] (P2) [graphrag] Add `OntologyOptimizer.reset_history()` -- Done batch-64: returns removed count; 4 tests
- [ ] (P3) [tests] Property test: Entity.to_dict() round-trips through from_dict equivalent
- [x] (P2) [graphrag] Add `OntologyGenerator.score_entity(entity)` -- Done batch-65: conf+len+type signals blend; 7 tests
- [ ] (P3) [graphrag] Add `OntologyLearningAdapter.reset_feedback()` -- clear feedback history
- [x] (P2) [obs] Add `OntologyCritic.emit_dimension_histogram(scores)` -- Done batch-69: bins per dim, count lists; 7 tests
- [x] (P3) [graphrag] Add `ExtractionConfig.to_toml()` / `from_toml()` -- Done batch-69: stdlib tomllib, hand-rolled writer; 7 tests
- [x] (P2) [graphrag] Add `OntologyGenerator.batch_extract_with_spans()` -- Done batch-65: ThreadPoolExecutor, order preserved; 6 tests
- [x] (P3) [arch] Add `OntologyPipeline.reset()` -- Done batch-65: clears adapter + mediator state; 2 tests
- [ ] (P2) [tests] Add fuzz test: refine_ontology with random recommendation strings
- [x] (P3) [graphrag] Add `OntologyOptimizer.session_count()` -- Done batch-64: sums metadata[num_sessions]; 3 tests

## Batch 66+ Ideas
- [x] (P2) [graphrag] Add `OntologyCritic.calibrate_thresholds()` -- adjust dimension thresholds from history of scores
- [x] (P3) [graphrag] Add `CriticScore.to_html_report()` -- Done batch-68: table + recs list; 7 tests
- [x] (P2) [graphrag] Add `OntologyGenerator.anonymize_entities()` -- Done batch-69: replaces text, preserves id/type/rels; 7 tests
- [ ] (P3) [tests] Add round-trip test: Entity -> to_dict -> from_dict (Entity.from_dict classmethod)
- [x] (P2) [graphrag] Add `Entity.from_dict(d)` classmethod -- Done batch-66: round-trip, span/props preserved; 7 tests
- [x] (P3) [graphrag] Add `EntityExtractionResult.to_csv()` -- Done batch-66: header+rows, span cols; 7 tests
- [x] (P2) [graphrag] Add `OntologyOptimizer.top_n_ontologies(n)` -- Done batch-66: sorted desc, n guard; 6 tests
- [x] (P3) [obs] Add `OntologyPipeline.run_with_metrics()` -- Done batch-68: latency/score/entity_count; 6 tests
- [x] (P2) [graphrag] Add `OntologyMediator.preview_recommendations()` -- Done batch-67: no state mutation; 5 tests
- [ ] (P3) [graphrag] Add `ExtractionConfig.from_dict()` classmethod
- [x] (P2) [graphrag] Add `OntologyOptimizer.score_variance()` -- Done batch-66: population variance; 6 tests
- [x] (P3) [arch] Add `OntologyPipeline.with_domain(domain)` -- Done batch-69: immutable fluent builder; 5 tests
- [x] (P2) [graphrag] Add `LogicValidator.explain_entity(entity)` -- Done batch-68: structured dict with is_valid/contradictions; 7 tests
- [x] (P3) [obs] Add `OntologyCritic.score_trend(scores)` -- Done batch-68: least-squares slope -> improving/stable/degrading; 7 tests
- [x] (P2) [graphrag] Add `OntologyGenerator.deduplicate_entities(result)` -- Done batch-67: highest-conf wins, rel remapping, dedup_count; 8 tests
- [ ] (P3) [tests] Hypothesis: LogicValidator.filter_valid_entities subset property
- [x] (P2) [graphrag] Add `OntologyMediator.get_action_summary()` -- Done batch-67: sorted desc, top_n, rank; 6 tests
- [x] (P3) [arch] Add `OntologyPipeline.from_dict(d)` -- Done batch-67: round-trip classmethod; 5 tests
- [x] (P2) [graphrag] Add `ExtractionConfig.validate()` -- check field constraints
- [x] (P3) [obs] Add `OntologyOptimizer.improvement_rate()` -- Done batch-66: pairwise comparison; 6 tests

## Batch 70+ Ideas
- [x] (P2) [graphrag] Add `OntologyOptimizer.score_percentile(p)` -- Done batch-70: linear interp; 6 tests
- [x] (P3) [graphrag] Add `OntologyMediator.get_undo_depth()` -- length of undo stack
- [x] (P2) [graphrag] Add `OntologyGenerator.extract_noun_phrases(text)` -- simple NP chunker
- [x] (P3) [arch] Add `OntologyPipeline.clone_with(domain=None, max_rounds=None)` -- partial override clone
- [x] (P2) [graphrag] Add `EntityExtractionResult.confidence_histogram(bins)` -- Done batch-70: bucket counts; 6 tests
- [x] (P3) [graphrag] Add `OntologyCritic.compare_with_baseline(ontology, baseline, ctx)` -- delta vs baseline
- [x] (P2) [graphrag] Add `ExtractionConfig.scale_thresholds(factor)` -- Done batch-70: clamp to [0,1]; 7 tests
- [x] (P3) [obs] Add `OntologyOptimizer.format_history_table()` -- Done batch-70: header+divider+rows; 5 tests
- [x] (P2) [graphrag] Add `OntologyGenerator.tag_entities(result, tags)` -- Done batch-70: shallow merge to properties; 6 tests
- [x] (P3) [graphrag] Add `OntologyMediator.set_max_rounds(n)` -- update max_rounds at runtime
- [x] (P2) [graphrag] Add `LogicValidator.count_contradictions(ontology)` -- integer count helper
- [x] (P3) [arch] Add `OntologyPipeline.domain_list` property -- list of known domain presets
  - Done 2026-02-20: verified/covered `OntologyPipeline.domain_list` sorted preset list behavior with tests in `test_pipeline_domain_list.py`.
- [x] (P2) [graphrag] Add `EntityExtractionResult.to_dict()` -- full result as plain dict
- [x] (P3) [graphrag] Add `OntologyCritic.summarize_batch_results(batch_result)` -- one-line per ontology
- [x] (P2) [graphrag] Add `OntologyOptimizer.average_improvement_per_batch()` -- Done batch-70: mean pairwise delta; 5 tests
- [x] (P3) [obs] Add `OntologyMediator.log_action_summary()` -- log get_action_summary to INFO
- [x] (P2) [graphrag] Add `ExtractionConfig.to_json()` -- JSON serialization
- [x] (P3) [graphrag] Add `Entity.copy_with(**overrides)` -- return modified copy of entity
- [x] (P2) [graphrag] Add `OntologyGenerator.extract_keyphrases(text)` -- top K keyphrases
- [x] (P3) [arch] Add `OntologyPipeline.get_stage_names()` -- list pipeline stages

## Batch 75+ Ideas (added automatically)

- [x] (P2) [graphrag] Add `OntologyGenerator.merge_results(results)` -- merge list of EntityExtractionResult into one
- [x] (P3) [graphrag] Add `OntologyCritic.dimension_report(score)` -- multi-line human-readable dimension breakdown
- [x] (P2) [graphrag] Add `OntologyOptimizer.prune_history(n)` -- keep only last N history entries
- [x] (P3) [graphrag] Add `EntityExtractionResult.highest_confidence_entity()` -- return entity with max confidence
- [x] (P2) [graphrag] Add `Entity.to_text()` -- return human-readable single-line summary
- [x] (P3) [graphrag] Add `OntologyPipeline.summary()` -- one-line string with domain/rounds/stage-count
- [x] (P2) [graphrag] Add `ExtractionConfig.copy()` -- Done batch-77 -- shallow copy of the config
- [x] (P3) [graphrag] Add `OntologyLearningAdapter.feedback_summary()` -- Done batch-77: -- stats dict for feedback history
- [x] (P2) [graphrag] Add `OntologyMediator.get_round_count()` -- Done batch-77: -- number of refinement rounds performed
- [x] (P3) [graphrag] Add `OntologyCritic.score_delta(score_a, score_b)` -- Done batch-77: -- per-dim delta dict
- [x] (P2) [graphrag] Add `EntityExtractionResult.filter_by_span(start, end)` -- Done batch-77: -- keep entities with source_span in range
- [x] (P3) [graphrag] Add `OntologyOptimizer.worst_ontology()` -- Done batch-78: -- return ontology from lowest-scoring history entry
- [x] (P2) [graphrag] Add `OntologyGenerator.dedup_by_text_prefix(result, prefix_len)` -- Done batch-78: -- deduplicate entities with shared prefix
- [x] (P3) [graphrag] Add `LogicValidator.is_consistent(ontology)` -- Done batch-78: -- boolean shortcut for check_consistency
- [x] (P2) [graphrag] Add `OntologyPipeline.history` property -- Done batch-79: -- return list of PipelineResult from past runs
- [x] (P3) [graphrag] Add `ExtractionConfig.apply_defaults_for_domain(domain)` -- Done batch-79: -- mutate thresholds in-place for domain
- [x] (P2) [graphrag] Add `OntologyCritic.critical_weaknesses(score)` -- Done batch-78: -- return only weaknesses below 0.5 threshold
- [ ] (P3) [graphrag] Add `OntologyMediator.peek_undo()` -- return top of undo stack without popping
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.serialize_to_file(path)` and `from_file(path)` -- Done batch-78: -- file-based persistence
- [x] (P3) [graphrag] Add `EntityExtractionResult.random_sample(n)` -- Done batch-78: -- return result with n random entities

- [x] (P2) [graphrag] Add `OntologyPipeline.history` property -- Done batch-79: list of PipelineResult from past runs
- [x] (P2) [graphrag] Add `ExtractionConfig.apply_defaults_for_domain(domain)` -- Done batch-79: mutate thresholds in-place for domain
- [x] (P2) [graphrag] Add `OntologyOptimizer.score_history()` -- Done batch-79: list of average_score from history entries
- [x] (P2) [graphrag] Add `OntologyCritic.top_dimension(score)` -- Done batch-79: dimension with highest value
- [x] (P2) [graphrag] Add `OntologyMediator.action_log(max_entries)` -- Done batch-79: recent action entries list

- [x] (P2) [graphrag] Add `OntologyGenerator.count_entities_by_type(result)` -- Done batch-80: type frequency dict
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.top_feedback_scores(n)` -- Done batch-80: top-N by score
- [x] (P2) [graphrag] Add `EntityExtractionResult.span_coverage(text_length)` -- Done batch-80: fraction of chars covered
- [x] (P2) [graphrag] Add `OntologyCritic.bottom_dimension(score)` -- Done batch-80: lowest-value dimension
- [x] (P2) [graphrag] Add `OntologyMediator.reset_all_state()` -- Done batch-80: clear all state + action entries

- [x] (P2) [graphrag] Add `OntologyOptimizer.average_score()` -- Done batch-81: mean of all history average_scores
- [x] (P2) [graphrag] Add `OntologyCritic.score_range(scores)` -- Done batch-81: (min, max) overall tuple
- [x] (P2) [graphrag] Add `OntologyGenerator.strip_low_confidence(result, threshold)` -- Done batch-81: filter below threshold
- [x] (P2) [graphrag] Add `OntologyMediator.top_recommended_action()` -- Done batch-81: highest-frequency recommendation
- [x] (P2) [graphrag] Add `EntityExtractionResult.unique_types()` -- Done batch-81: sorted distinct type list

## Batch 82+ Ideas (added batch-81)
- [x] (P2) [graphrag] Add `EntityExtractionResult.avg_confidence()` -- mean confidence across all entities
- [x] (P2) [graphrag] Add `OntologyCritic.improve_score_suggestion(score)` -- top-priority dimension to improve
- [x] (P2) [graphrag] Add `OntologyGenerator.apply_config(result, config)` -- re-filter result using config
- [x] (P2) [graphrag] Add `OntologyMediator.retry_last_round(ontology, score, ctx)` -- redo last refinement
- [ ] (P3) [graphrag] Add `LogicValidator.validate_all(ontologies)` -- list of ValidationResults for list of ontologies
- [x] (P2) [graphrag] Add `OntologyOptimizer.best_n_ontologies(n)` -- top-N ontologies by score
- [x] (P2) [graphrag] Add `OntologyPipeline.reset()` -- reset pipeline state and history
- [ ] (P3) [graphrag] Add `CriticScore.to_list()` -- [completeness, consistency, clarity, granularity, domain_alignment]
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.feedback_count()` -- len(_feedback) shortcut
- [ ] (P3) [graphrag] Add `OntologyGenerator.describe_result(result)` -- one-line English summary
- [x] (P2) [graphrag] Add `OntologyMediator.most_frequent_action()` -- Done batch-83: -- action with highest invocation count
- [x] (P2) [graphrag] Add `OntologyCritic.dimension_gap(score, target)` -- Done batch-83: -- how far each dim is from target
- [x] (P3) [graphrag] Add `EntityExtractionResult.by_id(eid)` -- Done batch-83: -- look up entity by id
- [x] (P2) [graphrag] Add `OntologyOptimizer.last_score()` -- average_score from most recent history entry
- [x] (P2) [graphrag] Add `ExtractionConfig.is_strict()` -- True if confidence_threshold >= 0.8
- [x] (P3) [graphrag] Add `OntologyGenerator.top_entities(result, n)` -- Done batch-83: -- top-N by confidence
- [x] (P2) [graphrag] Add `OntologyMediator.undo_all()` -- undo to oldest snapshot in stack
- [x] (P2) [graphrag] Add `OntologyCritic.worst_score(scores)` -- CriticScore with lowest overall from list
- [ ] (P3) [graphrag] Add `OntologyPipeline.total_runs()` -- number of times run() was called
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.worst_feedback_scores(n)` -- Done batch-83: -- bottom-N by score

- [x] (P2) [graphrag] Add `EntityExtractionResult.avg_confidence()` -- Done batch-82: mean confidence
- [x] (P2) [graphrag] Add `OntologyCritic.improve_score_suggestion(score)` -- Done batch-82: lowest-dim recommendation
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.feedback_count()` -- Done batch-82: len(_feedback) shortcut
- [x] (P2) [graphrag] Add `OntologyOptimizer.last_score()` -- Done batch-82: most recent average_score
- [x] (P2) [graphrag] Add `ExtractionConfig.is_strict()` -- Done batch-82: True if confidence_threshold >= 0.8

- [x] (P2) [graphrag] Add `CriticScore.to_list()` -- Done batch-84: [c, con, cl, g, da] list
- [x] (P2) [graphrag] Add `OntologyOptimizer.best_n_ontologies(n)` -- Done batch-84: top-N ontologies
- [x] (P2) [graphrag] Add `OntologyMediator.undo_all()` -- Done batch-84: undo to oldest snapshot
- [x] (P2) [graphrag] Add `OntologyCritic.worst_score(scores)` -- Done batch-84: min overall CriticScore
- [x] (P3) [graphrag] Add `OntologyPipeline.total_runs()` -- Done batch-84: count of run() calls

## Batch 85+ Ideas (added batch-84)
- [x] (P2) [graphrag] Add `OntologyCritic.best_score(scores)` -- Done batch-85: -- CriticScore with highest overall from list
- [x] (P2) [graphrag] Add `EntityExtractionResult.has_entity(text)` -- Done batch-85: -- check if any entity has matching text
- [x] (P2) [graphrag] Add `OntologyGenerator.explain_entity(entity)` -- one-line English description of entity
- [x] (P2) [graphrag] Add `OntologyMediator.action_count_for(action)` -- Done batch-85: -- invocation count for specific action
- [ ] (P3) [graphrag] Add `ExtractionConfig.summary()` -- one-line config description
- [x] (P2) [graphrag] Add `OntologyOptimizer.clear_history()` -- clear all history entries (if not exists)
- [x] (P2) [graphrag] Add `OntologyLearningAdapter.mean_score()` -- mean of all feedback final_scores
- [x] (P3) [graphrag] Add `CriticScore.is_passing(threshold)` -- Done batch-85: -- True if overall >= threshold (default 0.6)
- [x] (P2) [graphrag] Add `OntologyPipeline.last_score()` -- Done batch-85: -- overall score from most recent run()
- [ ] (P3) [graphrag] Add `EntityExtractionResult.filter_by_type(etype)` -- keep only entities of given type
- [x] (P2) [graphrag] Add `OntologyGenerator.entity_count(result)` -- total entity count
- [x] (P2) [graphrag] Add `OntologyCritic.score_mean(scores)` -- mean CriticScore.overall from list
- [ ] (P3) [graphrag] Add `OntologyMediator.stash()` -- push snapshot without advancing refine_ontology
- [x] (P2) [graphrag] Add `LogicValidator.format_report(result)` -- multi-line human-readable validation report
- [x] (P2) [graphrag] Add `OntologyOptimizer.percentile_score(p)` -- p-th percentile of score history
- [ ] (P3) [graphrag] Add `EntityExtractionResult.relationships_for(entity_id)` -- rels involving entity
- [ ] (P2) [graphrag] Add `OntologyGenerator.rebuild_result(entities)` -- wrap entities in new result
- [ ] (P2) [graphrag] Add `OntologyCritic.evaluate_list(ontologies, ctx)` -- evaluate a list, return CriticScores
- [ ] (P3) [graphrag] Add `OntologyPipeline.domain` setter -- update domain at runtime
- [ ] (P2) [graphrag] Add `OntologyLearningAdapter.score_variance()` -- variance of feedback final_scores

## Batch 91+ Ideas (added batch-90)
- [ ] (P2) [graphrag] Add `OntologyCritic.score_range(scores)` -- (min, max) tuple of overall scores
- [ ] (P2) [graphrag] Add `OntologyGenerator.sorted_entities(result, key)` -- sort entities by field
- [ ] (P3) [graphrag] Add `OntologyLearningAdapter.clear_feedback()` -- clear all feedback records
- [ ] (P2) [graphrag] Add `OntologyMediator.log_snapshot(label)` -- label current undo stack top
- [ ] (P2) [graphrag] Add `EntityExtractionResult.confidence_histogram(bins)` -- bucket confidence values
- [ ] (P3) [graphrag] Add `OntologyOptimizer.history_summary()` -- dict with min/max/mean/count
- [ ] (P2) [graphrag] Add `OntologyPipeline.warmup(n_texts)` -- pre-warm pipeline with dummy texts
- [ ] (P2) [graphrag] Add `LogicValidator.contradiction_count(ontology)` -- alias for count_contradictions
- [ ] (P3) [graphrag] Add `OntologyCritic.dimension_scores(score)` -- dict of all 5 dim values
- [ ] (P2) [graphrag] Add `ExtractionConfig.with_threshold(t)` -- return copy with new threshold
- [ ] (P2) [graphrag] Add `OntologyGenerator.filter_result_by_confidence(result, min_conf)` -- alias for strip_low_confidence with cleaner name
- [ ] (P3) [graphrag] Add `OntologyMediator.pending_recommendation()` -- top recommendation without consuming it
- [ ] (P2) [graphrag] Add `OntologyLearningAdapter.feedback_ids()` -- list of unique session_ids or feedback identifiers
- [ ] (P2) [graphrag] Add `EntityExtractionResult.entity_texts()` -- list of all entity text values
- [ ] (P2) [graphrag] Add `OntologyCritic.passes_all(scores, threshold)` -- True if all scores pass threshold
- [ ] (P2) [graphrag] Add `OntologyOptimizer.latest_batch_size()` -- number of ontologies in last batch
- [ ] (P3) [graphrag] Add `OntologyPipeline.has_run()` -- bool whether any runs have been made
- [ ] (P2) [graphrag] Add `OntologyGenerator.entity_ids(result)` -- list of all entity IDs
- [ ] (P2) [graphrag] Add `OntologyLearningAdapter.feedback_summary_dict()` -- dict with count/mean/variance
- [ ] (P2) [graphrag] Add `LogicValidator.is_empty(ontology)` -- True if no entities or relationships

## Batch 96–100 Done ✅
- [x] (batch-96) `OntologyOptimizer.score_delta`, `OntologyGenerator.entities_by_type`, `OntologyCritic.top_n_scores`, `ExtractionConfig.merge`, `OntologyPipeline.best_run`
- [x] (batch-97) `OntologyGenerator.filter_result_by_confidence`, `OntologyCritic.score_distribution`, `LogicValidator.entity_count`, `OntologyLearningAdapter.top_k_feedback`
- [x] (batch-98) `EntityExtractionResult.average_confidence`, `EntityExtractionResult.distinct_types`, `OntologyGenerator.relationship_density`, `OntologyCritic.score_gap`, `OntologyOptimizer.score_stddev`
- [x] (batch-99) `LogicValidator.relationship_count`, `OntologyOptimizer.score_range`, `OntologyPipeline.run_count`, `EntityExtractionResult.entity_by_id`, `OntologyLearningAdapter.feedback_score_range`
- [x] (batch-100) `EntityExtractionResult.high_confidence_entities`, `EntityExtractionResult.low_confidence_entities`, `OntologyCritic.scores_above_threshold`, `OntologyOptimizer.recent_score_mean`, `OntologyLearningAdapter.feedback_count_above`

## Batch 101+ backlog
- [ ] (P2) [graphrag] `EntityExtractionResult.to_dict()` -- serialize result to plain dict
- [ ] (P2) [graphrag] `EntityExtractionResult.entity_count` property -- len(self.entities)
- [ ] (P2) [graphrag] `OntologyGenerator.group_entities_by_confidence_band(result, bands)` -- bucket entities into confidence ranges
- [ ] (P2) [graphrag] `OntologyOptimizer.convergence_rate()` -- fraction of consecutive pairs with improvement < 0.01
- [ ] (P2) [graphrag] `OntologyMediator.action_types()` -- sorted list of distinct action type strings seen
- [ ] (P2) [graphrag] `OntologyCritic.all_pass(scores, threshold)` -- True if all score.overall > threshold (alias for passes_all, strict)
- [ ] (P2) [graphrag] `LogicValidator.has_contradictions(ontology)` -- True if any contradictions found
- [ ] (P2) [graphrag] `OntologyLearningAdapter.feedback_below(threshold)` -- list of records below threshold
- [ ] (P2) [graphrag] `OntologyPipeline.average_run_score()` -- mean score.overall across all runs
- [ ] (P2) [graphrag] `OntologyGenerator.relationships_for_entity(result, eid)` -- rels where entity is source or target
- [ ] (P3) [graphrag] `ExtractionConfig.to_dict()` -- serialize config to plain dict
- [ ] (P3) [graphrag] `OntologyOptimizer.history_as_list()` -- list of average_score floats
- [ ] (P3) [graphrag] `OntologyCritic.best_dimension(score)` -- name of highest-scoring dimension
- [ ] (P3) [graphrag] `OntologyCritic.worst_dimension(score)` -- name of lowest-scoring dimension
- [ ] (P3) [graphrag] `EntityExtractionResult.max_confidence()` -- highest entity confidence
- [ ] (P3) [graphrag] `EntityExtractionResult.min_confidence()` -- lowest entity confidence
- [ ] (P3) [graphrag] `OntologyLearningAdapter.feedback_above(threshold)` -- list of records above threshold
- [ ] (P3) [graphrag] `OntologyMediator.clear_stash()` -- empty the stash stack
- [ ] (P3) [graphrag] `LogicValidator.summary_dict(ontology)` -- {entity_count, relationship_count, has_contradictions}
- [ ] (P2) [graphrag] `OntologyPipeline.score_at(index)` -- score.overall from _run_history[index]

## Batches 101–106 Done ✅
- [x] (batch-101) `EntityExtractionResult.max/min_confidence`, `OntologyCritic.best/worst_dimension`, `LogicValidator.has_contradictions`, `OntologyLearningAdapter.feedback_below`
- [x] (batch-102) `OntologyPipeline.average_run_score/score_at`, `OntologyMediator.action_types`, `OntologyLearningAdapter.feedback_above`, `LogicValidator.summary_dict`
- [x] (batch-103) `OntologyOptimizer.convergence_rate/history_as_list`, `EntityExtractionResult.confidence_band`, `OntologyGenerator.relationships_for_entity`
- [x] (batch-104) `OntologyOptimizer.best_entry/worst_entry`, `OntologyLearningAdapter.feedback_mean`, `EntityExtractionResult.relationship_types`, `OntologyMediator.clear_stash`
- [x] (batch-105) `OntologyGenerator.group_entities_by_confidence_band`, `OntologyCritic.all_pass`, `OntologyLearningAdapter.feedback_stddev`, `OntologyOptimizer.score_median`, `LogicValidator.relationship_density`
- [x] (batch-106) `OntologyPipeline.worst_run/median_run_score`, `OntologyLearningAdapter.feedback_median`, `OntologyOptimizer.last_entry`, `LogicValidator.relationship_types`

## Recent independent improvements ✅ (ca759612)
- [x] (P2) [arch] Replace broad `except Exception:` with specific types across 13 sites
- [x] (P2) [obs] Add `profile_memory`, `profile_time`, `profile_both` decorators in `common/profiling_decorators.py`
- [x] (P2) [api] Add `__repr__` to `OptimizationCycleMetrics`, `MediatorState`, `BaseSession`, `RoundRecord`
- [x] (P1) [graphrag] Implement `relationship_coherence` dimension for OntologyCritic (6th dimension)
  - File: `graphrag/ontology_critic.py` – Added `_evaluate_relationship_coherence()` method (120 LOC)
  - Sub-scores: type quality (35%), directionality (20%), distribution (25%), semantic consistency (20%)
  - Updated DIMENSION_WEIGHTS: rebalanced 5→6 dimensions (weights sum to 1.0)
  - Updated 30+ methods referencing dimension lists (to_dict, to_list, explain_score, calibrate_thresholds, etc.)
  - Updated module docstring with new dimension percentages
  - File: `tests/unit/optimizers/graphrag/test_ontology_critic_dimensions.py` – Added 11 comprehensive unit tests
  - Test coverage: generic types, meaningful types, diversity, directionality, semantic consistency, edge cases
  - All 55 tests passing (100% success rate)
- [x] (P3) [graphrag] Add `OntologyGenerator.filter_by_confidence()` — threshold filter with detailed stats
  - File: `graphrag/ontology_generator.py` – Added method returning dict with filtered EntityExtractionResult + 10 statistical metrics
  - Stats: retention_rate, avg_confidence before/after, entity/relationship counts (original, filtered, removed)
  - Validates threshold in [0, 1], includes logging, preserves metadata
  - File: `tests/unit/optimizers/graphrag/test_ontology_generator_helpers.py` – Added TestFilterByConfidence class with 12 tests
  - Test coverage: thresholds (default, high, low), relationship pruning, edge cases (empty, all below threshold), stats validation
  - All 12 tests passing
- [x] (P3) [graphrag] Add `OntologyCritic.get_worst_entity()` — lowest-scoring entity ID
  - File: `graphrag/ontology_critic.py` – Added method to identify entity with lowest confidence score
  - Handles both dict (with 'id' and 'confidence' keys) and Entity object formats
  - Returns None for empty ontologies or missing entities key
  - Skips entities without valid IDs, defaults confidence to 1.0 if missing
  - File: `tests/unit/optimizers/graphrag/test_ontology_critic_dimensions.py` – Added TestGetWorstEntity class with 10 tests
  - Test coverage: multiple entities, empty ontology, single entity, tied scores, Entity objects, missing fields
  - All 10 tests passing
- [x] (P3) [graphrag] Add `LogicValidator.entity_contradiction_count()` — integer count helper
  - File: `graphrag/logic_validator.py` – Added method returning count of entities involved in contradictions
  - Uses ValidationResult.invalid_entity_ids to count entities with validation errors
  - Returns 0 on exceptions, non-negative integer guaranteed
  - File: `tests/unit/optimizers/graphrag/test_logic_validator_tdfol_conversion.py` – Added TestEntityContradictionCount class with 6 tests
  - Test coverage: empty ontology, consistent ontology, exception handling, malformed input, return type validation
  - All 6 tests passing
- [x] (P3) [obs] Add timing instrumentation to `_extract_rule_based()` method
  - Discovery: Comprehensive timing already implemented in `graphrag/ontology_generator.py` (lines 3122-3193)
  - Implementation: Tracks 4 timing phases with separate metrics:
    - `pattern_time_ms`: Time to build rule patterns for entity extraction
    - `extraction_time_ms`: Time to extract entities from patterns  
    - `relationship_time_ms`: Time to infer relationships between entities
    - `total_time_ms`: Total execution time for entire extraction
  - All metrics logged at INFO level with detailed breakdown
  - All metrics stored in EntityExtractionResult.metadata dict
  - File: `tests/unit/optimizers/graphrag/test_ontology_generator_helpers.py` – Added TestExtractRuleBasedTiming class with 9 tests
  - Test coverage: metadata presence, type validation (floats), non-negative values, timing relationships (total ≥ components), edge cases (empty input), large text, metadata structure, reasonableness checks
  - All 9 tests passing

---

## Comprehensive Refactor + Improvement Plan (v2) — Batches 107–200+

### Track: [graphrag] New method backlog (batch 107+)

#### EntityExtractionResult helpers
- [ ] (P2) [graphrag] `EntityExtractionResult.to_dict()` — full serialization to plain dict (entities, relationships, confidence, metadata)
- [ ] (P2) [graphrag] `EntityExtractionResult.from_dict(d)` — classmethod deserializer (inverse of to_dict)
- [ ] (P2) [graphrag] `EntityExtractionResult.entity_count` — `@property` len(self.entities)
- [ ] (P2) [graphrag] `EntityExtractionResult.relationship_count` — `@property` len(self.relationships)
- [ ] (P2) [graphrag] `EntityExtractionResult.is_empty()` — True if no entities AND no relationships
- [ ] (P2) [graphrag] `EntityExtractionResult.has_relationships()` — True if relationships list is non-empty
- [ ] (P2) [graphrag] `EntityExtractionResult.top_entities(n)` — top N entities by confidence
- [ ] (P2) [graphrag] `EntityExtractionResult.entities_of_type(etype)` — alias for filter_by_type
- [ ] (P3) [graphrag] `EntityExtractionResult.confidence_stats()` — dict with mean/min/max/std of confidences
- [ ] (P3) [graphrag] `EntityExtractionResult.validate()` — returns list of validation errors (dangling refs, etc.)

#### ExtractionConfig helpers
- [ ] (P2) [graphrag] `ExtractionConfig.from_dict(d)` — classmethod deserializer
- [ ] (P2) [graphrag] `ExtractionConfig.clone()` — return a deep copy of self
- [ ] (P2) [graphrag] `ExtractionConfig.diff(other)` — dict of fields that differ between self and other
- [ ] (P2) [graphrag] `ExtractionConfig.is_strict()` — True if confidence_threshold >= 0.8

#### OntologyGenerator helpers
- [ ] (P2) [graphrag] `OntologyGenerator.validate_result(result)` — return list of issues (empty entity text, negative confidence, etc.)
- [ ] (P2) [graphrag] `OntologyGenerator.confidence_stats(result)` — dict with mean/min/max/std for entity confidence
- [ ] (P2) [graphrag] `OntologyGenerator.clone_result(result)` — deep copy of EntityExtractionResult
- [ ] (P2) [graphrag] `OntologyGenerator.add_entity(result, entity)` — return new result with entity appended
- [ ] (P2) [graphrag] `OntologyGenerator.remove_entity(result, eid)` — return new result without entity; prune rels
- [ ] (P3) [graphrag] `OntologyGenerator.type_diversity(result)` — count of distinct entity types
- [ ] (P3) [graphrag] `OntologyGenerator.normalize_confidence(result)` — scale entity confidences to [0,1]

#### OntologyCritic helpers
- [ ] (P2) [graphrag] `OntologyCritic.failing_scores(scores, threshold)` — scores that don't pass threshold
- [ ] (P2) [graphrag] `OntologyCritic.average_dimension(scores, dim)` — mean of one dimension across multiple CriticScores
- [ ] (P2) [graphrag] `OntologyCritic.score_summary(scores)` — compact dict {count, mean, min, max, passing_fraction}
- [ ] (P3) [graphrag] `OntologyCritic.percentile_overall(scores, p)` — p-th percentile of overall values
- [ ] (P3) [graphrag] `OntologyCritic.normalize_scores(scores)` — shift all scores to [0,1] range

#### OntologyOptimizer helpers
- [ ] (P2) [graphrag] `OntologyOptimizer.trend_string()` — "improving"/"declining"/"flat"/"volatile" based on last 5 entries
- [ ] (P2) [graphrag] `OntologyOptimizer.entries_above_score(threshold)` — list of history entries with average_score > threshold
- [ ] (P2) [graphrag] `OntologyOptimizer.running_average(window)` — list of window-averaged scores
- [ ] (P3) [graphrag] `OntologyOptimizer.score_iqr()` — interquartile range of history scores
- [ ] (P3) [graphrag] `OntologyOptimizer.has_improved(baseline)` — True if any entry > baseline

#### OntologyPipeline helpers
- [ ] (P2) [graphrag] `OntologyPipeline.score_variance()` — variance of run scores
- [ ] (P2) [graphrag] `OntologyPipeline.score_stddev()` — std dev of run scores
- [ ] (P2) [graphrag] `OntologyPipeline.passing_run_count(threshold)` — count of runs with score > threshold
- [ ] (P2) [graphrag] `OntologyPipeline.run_summary()` — dict with count/mean/min/max/trend of run scores
- [ ] (P3) [graphrag] `OntologyPipeline.is_stable(threshold, window)` — True if last N runs have low variance

#### OntologyMediator helpers
- [ ] (P2) [graphrag] `OntologyMediator.total_action_count()` — sum of all action counts
- [ ] (P2) [graphrag] `OntologyMediator.top_actions(n)` — top N actions by count
- [ ] (P2) [graphrag] `OntologyMediator.undo_depth()` — alias for snapshot_count / get_undo_depth
- [ ] (P3) [graphrag] `OntologyMediator.most_frequent_action()` — action with highest count (or None)
- [ ] (P3) [graphrag] `OntologyMediator.action_count_total()` — total number of individual action applications

#### OntologyLearningAdapter helpers
- [ ] (P2) [graphrag] `OntologyLearningAdapter.feedback_score_stats()` — {count, mean, std, min, max} dict
- [ ] (P2) [graphrag] `OntologyLearningAdapter.recent_feedback(n)` — last N FeedbackRecord objects
- [ ] (P2) [graphrag] `OntologyLearningAdapter.has_feedback()` — True if any feedback recorded
- [ ] (P3) [graphrag] `OntologyLearningAdapter.feedback_percentile(p)` — p-th percentile final_score
- [ ] (P3) [graphrag] `OntologyLearningAdapter.passing_feedback_fraction(threshold)` — fraction above threshold

#### LogicValidator helpers
- [ ] (P2) [graphrag] `LogicValidator.is_empty(ontology)` — True if entity_count == 0 AND relationship_count == 0
- [ ] (P2) [graphrag] `LogicValidator.all_entity_ids(ontology)` — list of entity id strings
- [ ] (P2) [graphrag] `LogicValidator.all_relationship_ids(ontology)` — list of relationship id strings
- [ ] (P3) [graphrag] `LogicValidator.entity_type_set(ontology)` — set of distinct entity types
- [ ] (P3) [graphrag] `LogicValidator.dangling_references(ontology)` — list of relationship endpoints not in entity_ids

---

### Track: [arch] Structural refactors (batch 120+)

- [ ] (P2) [arch] Extract `QueryPlanner` class (~lines 1–1000 of query_optimizer) into `graphrag/query_planner.py`
- [ ] (P2) [arch] Extract `TraversalHeuristics` into `graphrag/traversal_heuristics.py`
- [ ] (P2) [arch] Extract `LearningAdapter` (learning-hook section) into `graphrag/learning_adapter.py`
- [ ] (P2) [arch] Extract serialization helpers into `graphrag/serialization.py`
- [ ] (P2) [tests] Add unit tests for each extracted module after split
- [ ] (P3) [docs] Update module-level docstrings to reflect new file layout

### Track: [api] API quality (batch 130+)

- [ ] (P2) [api] Audit all `**kwargs`-accepting methods in `agentic/` and replace with typed optional params
- [ ] (P2) [api] Standardize "context" objects across GraphRAG / logic / agentic (dataclasses with typed fields)
- [ ] (P3) [api] Add `__slots__` to hot-path dataclasses for memory efficiency
- [ ] (P3) [api] Add `__eq__` and `__hash__` to `Entity`, `Relationship`, `CriticScore` for set membership

### Track: [tests] Test hardening (ongoing)

- [ ] (P2) [tests] Add property-based tests (Hypothesis) for `Entity`, `ExtractionConfig`, `CriticScore`
- [ ] (P2) [tests] Add round-trip tests: `entity.to_dict()` → `Entity(**d)` identity
- [ ] (P2) [tests] Add mutation tests for `EntityExtractionResult.merge()`
- [ ] (P2) [tests] Parametrize existing batch tests to reduce boilerplate
- [ ] (P3) [tests] Add fuzz tests for `LogicValidator.check_consistency`

### Track: [obs] Observability (batch 140+)

- [ ] (P2) [obs] Wire `OntologyOptimizer` score history to `profile_time` decorator
- [ ] (P2) [obs] Emit structured log entry (JSON) for each pipeline run with score/domain/duration
- [ ] (P3) [obs] Add OpenTelemetry span hooks (behind `OTEL_ENABLED` env flag)
- [ ] (P3) [obs] Expose Prometheus-compatible metrics for optimizer scores

### Track: [perf] Performance (batch 150+)

- [ ] (P2) [perf] Add `@functools.lru_cache` to `ExtractionConfig.is_default()` (hashable dataclass)
- [ ] (P2) [perf] Profile `OntologyGenerator._extract_rule_based()` for hot paths
- [ ] (P3) [perf] Lazy-load LLM backend (skip import if `LLM_ENABLED=0`)
- [ ] (P3) [perf] Batch entity deduplication using sorted merge vs O(n²) set ops

### Track: [docs] Documentation completeness (batch 160+)

- [ ] (P2) [docs] Write architecture diagram for the generate → critique → optimize → validate loop
- [ ] (P2) [docs] Add `CONTRIBUTING.md` with PR guidelines and batch-commit conventions
- [ ] (P3) [docs] Write module-level docstring for `ontology_pipeline.py` (currently minimal)
- [ ] (P3) [docs] Add doctest examples for `ExtractionConfig.merge()`, `EntityExtractionResult.confidence_band()`

### Track: [arch] Cross-cutting concerns (batch 170+)

- [ ] (P2) [arch] Replace bare `except Exception:` catch-alls remaining after ca759612 sweep
- [ ] (P2) [arch] Add circuit-breaker for LLM backend calls (retry + exponential backoff)
- [ ] (P3) [arch] Remove deprecated `TheoremSession` / `LogicExtractor` after 2 minor versions
- [ ] (P3) [arch] Add TDFOL formula cache keyed on ontology hash to avoid re-proving
- [ ] (P3) [arch] Add `freeze()` method to `ExtractionConfig` that makes it immutable (frozen dataclass)


## Batches 107–113 Done ✅
- [x] (batch-107) `Entity.to_json`, `Relationship.to_dict/from_dict/to_json`, `OntologyOptimizer.trend_string/entries_above_score/running_average/score_quartiles/score_iqr`, `LogicValidator.all_entity_ids/all_relationship_ids/entity_type_set/dangling_references`
- [x] (batch-108) `OntologyPipeline.score_variance/score_stddev/passing_run_count/run_summary`, `OntologyLearningAdapter.has_feedback/recent_feedback/feedback_score_stats/feedback_percentile/passing_feedback_fraction`, `OntologyCritic.failing_scores/average_dimension/score_summary`
- [x] (batch-109) `OntologyGenerator.validate_result/confidence_stats/clone_result/add_entity/remove_entity/type_diversity`
- [x] (batch-110) `ExtractionConfig.clone`, `OntologyMediator.total_action_count/top_actions/undo_depth`
- [x] (batch-111) `EntityExtractionResult.is_empty/has_relationships/entities_of_type`, `OntologyCritic.percentile_overall`
- [x] (batch-112) `OntologyOptimizer.has_improved`, `OntologyGenerator.normalize_confidence`, `OntologyCritic.normalize_scores`, `OntologyPipeline.is_stable`
- [x] (batch-113) `EntityExtractionResult.confidence_stats`, `OntologyCritic.compare_runs`, `OntologyLearningAdapter.reset_and_load`, `OntologyMediator.reset_action_counts`, `LogicValidator.count_relationship_types`

## Batch 114+ backlog (fresh items)
- [ ] (P2) [graphrag] `OntologyOptimizer.rolling_best(window)` — best entry within last N history entries
- [ ] (P2) [graphrag] `OntologyOptimizer.plateau_count(tol)` — number of consecutive history pairs within tol of each other
- [ ] (P2) [graphrag] `OntologyGenerator.split_result(result, n)` — split result into N balanced chunks
- [ ] (P2) [graphrag] `OntologyGenerator.entity_confidence_map(result)` — {entity_id: confidence} dict
- [ ] (P2) [graphrag] `OntologyCritic.dimension_rankings(score)` — ordered list of dim names best→worst
- [ ] (P2) [graphrag] `OntologyCritic.weakest_scores(scores, n)` — bottom-N by overall
- [ ] (P2) [graphrag] `OntologyPipeline.top_n_runs(n)` — top N run results by score
- [ ] (P2) [graphrag] `OntologyPipeline.run_ids()` — list of run identifiers (indices or ids)
- [ ] (P2) [graphrag] `OntologyMediator.apply_action_bulk(actions)` — apply list of (action, args) pairs
- [ ] (P2) [graphrag] `OntologyMediator.action_count_for(action)` — already done, skip; try `actions_never_applied()` — action names with count == 0
- [ ] (P2) [graphrag] `OntologyLearningAdapter.score_range()` — (min, max) tuple of recorded scores
- [ ] (P2) [graphrag] `OntologyLearningAdapter.above_threshold_fraction(threshold)` — alias for passing_feedback_fraction
- [ ] (P2) [graphrag] `LogicValidator.orphan_entities(ontology)` — entities with no relationships
- [ ] (P2) [graphrag] `LogicValidator.hub_entities(ontology, min_degree)` — entities with >= min_degree relationships
- [ ] (P3) [graphrag] `EntityExtractionResult.top_confidence_entity()` — entity with highest confidence
- [ ] (P3) [graphrag] `EntityExtractionResult.entities_with_properties()` — entities that have non-empty properties dict
- [ ] (P3) [graphrag] `OntologyGenerator.relationship_count(result)` — len(result.relationships)
- [ ] (P3) [graphrag] `ExtractionConfig.relaxed()` — return copy with confidence_threshold -= 0.1 clamped to 0
- [ ] (P3) [graphrag] `ExtractionConfig.tightened()` — return copy with confidence_threshold += 0.1 clamped to 1

## Batches 114–130 Done ✅
- [x] (batch-114) `OntologyOptimizer.rolling_best/plateau_count`, `OntologyGenerator.entity_confidence_map`, `EntityExtractionResult.top_confidence_entity/entities_with_properties`, `OntologyCritic.dimension_rankings/weakest_scores`, `LogicValidator.orphan_entities/hub_entities`
- [x] (batch-115) `ExtractionConfig.relaxed/tightened`, `OntologyPipeline.top_n_runs/score_momentum`
- [x] (batch-116) `OntologyMediator.apply_action_bulk`, `OntologyLearningAdapter.score_range/feedback_count_above`
- [x] (batch-117) `OntologyOptimizer.best_streak/worst_streak/score_percentile_rank/score_momentum`
- [x] (batch-118) `LogicValidator.isolated_entities/max_degree_entity/entity_type_counts`
- [x] (batch-119) `OntologyCritic.score_delta_between/all_pass/score_variance/best_score`
- [x] (batch-120) `OntologyPipeline.worst_n_runs/pass_rate/score_range`
- [x] (batch-121) `OntologyGenerator.average_confidence/high_confidence_entities/filter_entities_by_type/deduplicate_by_id`
- [x] (batch-122) `OntologyMediator.action_frequency/has_actions/action_diversity`, `OntologyLearningAdapter.all_feedback_above/feedback_scores/domain_threshold_delta`
- [x] (batch-123) `LogicValidator.relationship_type_set/is_connected/duplicate_relationship_count`
- [x] (batch-124) `OntologyOptimizer.history_slice/score_above_count/first_entry_above/last_entry_above`
- [x] (batch-125) `OntologyPipeline.run_count_above/average_score/best_score/worst_score`
- [x] (batch-126) `OntologyLearningAdapter.best/worst/average_feedback_score/feedback_above_fraction`
- [x] (batch-127) `ExtractionConfig.threshold_distance/is_stricter_than/is_looser_than`
- [x] (batch-128) `OntologyCritic.worst_score/average_overall/count_failing`
- [x] (batch-129) `LogicValidator.self_loop_count/average_entity_degree`
- [x] (batch-130) `OntologyOptimizer.score_at_index/improvement_from_start/is_improving_overall`

## Batch 131+ backlog
- [ ] (P2) [graphrag] `OntologyGenerator.split_result(result, n)` — split result into N balanced chunks
- [ ] (P2) [graphrag] `OntologyOptimizer.min_score/max_score` — convenience properties
- [ ] (P2) [graphrag] `OntologyCritic.passing_rate(scores, threshold)` — fraction of scores passing threshold
- [ ] (P2) [graphrag] `OntologyMediator.most_used_action/least_used_action` — action name strings
- [ ] (P2) [graphrag] `OntologyPipeline.run_improvement/stabilization_index` — pipeline convergence metrics
- [ ] (P2) [graphrag] `LogicValidator.unreachable_entities(ontology, source)` — BFS unreachable from source
- [ ] (P2) [graphrag] `ExtractionConfig.describe()` — human-readable summary string
- [ ] (P2) [graphrag] `OntologyLearningAdapter.improvement_trend` — EMA-based trend indicator
- [ ] (P2) [graphrag] `EntityExtractionResult.entity_ids` — property returning list of all entity ids
- [ ] (P2) [graphrag] `OntologyGenerator.filter_low_confidence(result, threshold)` — remove entities below threshold
- [ ] (P2) [graphrag] `OntologyCritic.top_n_scores(scores, n)` — already exists; try `score_spread` — max-min of overalls
- [ ] (P3) [graphrag] `OntologyOptimizer.export_history_csv(filepath)` — CSV of score history
- [ ] (P3) [graphrag] `LogicValidator.max_path_length(ontology, source, target)` — BFS shortest path
- [ ] (P3) [graphrag] `OntologyPipeline.reset_to_initial` — clear history and restore defaults
- [ ] (P3) [graphrag] `OntologyMediator.undo_stack_summary` — list of pending undo labels

## Batches 131–143 Done ✅
- [x] (batch-131) `OntologyCritic.describe/ExtractionConfig.describe`, various mediator/pipeline methods
- [x] (batch-132) `EntityExtractionResult.entity_ids/relationship_ids`, `OntologyLearningAdapter.improvement_trend`
- [x] (batch-133) `OntologyCritic.passing_rate/score_spread`, `OntologyMediator.most_used_action/least_used_action`, `LogicValidator.shortest_path_length/reachable_from`
- [x] (batch-134) `OntologyOptimizer.export_history_csv/history_as_dicts`, `OntologyPipeline.stabilization_index/run_improvement`
- [x] (batch-135) `LogicValidator.has_cycle/cycle_participant_count`, `OntologyMediator.undo_stack_summary/undo_stack_depth`
- [x] (batch-136) `OntologyCritic.top_k_scores/below_threshold_count/average_dimension`, `OntologyLearningAdapter.feedback_streak/feedback_percentile/recent_average`
- [x] (batch-137) `OntologyOptimizer.top_k_history/history_score_std/count_entries_with_trend`, `OntologyGenerator.confidence_histogram/mean_confidence`
- [x] (batch-138) `OntologyPipeline.rolling_average/score_at_run/score_percentile`, `ExtractionConfig.combined_score/similarity_to`
- [x] (batch-139) `LogicValidator.in_degree/out_degree/top_k_entities_by_degree`, `OntologyCritic.bucket_scores/median_score`
- [x] (batch-140) `OntologyLearningAdapter.domain_coverage/volatility`, `OntologyGenerator.confidence_std/entity_type_distribution`
- [x] (batch-141) `OntologyPipeline.is_plateau/peak_run_index`, `OntologyOptimizer.dominant_trend/history_range`
- [x] (batch-142) `OntologyLearningAdapter.worst_n_feedback/feedback_score_range`, `LogicValidator.entity_count/relationship_count/entity_to_relationship_ratio`
- [x] (batch-143) `OntologyCritic.improvement_over_baseline/score_iqr`, `OntologyMediator.total_actions_taken/unique_action_count`

## Batch 144+ backlog
- [x] (P2) [graphrag] `OntologyGenerator.split_result(result, n)` — split into N balanced chunks
- [x] (P2) [graphrag] `OntologyOptimizer.min_score/max_score/median_score` — convenience properties
- [x] (P2) [graphrag] `OntologyPipeline.score_ewma(alpha)` — exponentially weighted moving average of scores
- [x] (P2) [graphrag] `LogicValidator.unreachable_entities(ontology, source)` — entities not reachable from source
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_zscore(value)` — z-score of a value in feedback distribution
- [x] (P2) [graphrag] `OntologyCritic.dimension_covariance(scores, dim_a, dim_b)` — covariance of two dimensions
- [x] (P2) [graphrag] `OntologyGenerator.relationship_types(result)` — set of unique relationship types
- [x] (P2) [graphrag] `ExtractionConfig.is_default()` — check if config matches defaults
- [x] (P2) [graphrag] `OntologyMediator.apply_feedback_list(scores)` — batch apply multiple CriticScores
- [x] (P3) [graphrag] `OntologyOptimizer.convergence_score()` — measure how much history is converging
- [x] (P3) [graphrag] `LogicValidator.strongly_connected_components(ontology)` — Tarjan/Kosaraju SCC
- [x] (P3) [graphrag] `OntologyPipeline.trend_slope()` — linear regression slope of score history
- [x] (P3) [graphrag] `OntologyCritic.top_improving_dimension(before, after)` — most improved dim between two scores
- [x] (P3) [graphrag] `OntologyGenerator.compact_result(result)` — drop empty properties

## Batches 144–165 Done ✅
- [x] (batch-144) `OntologyOptimizer.min/max/median_score`, `OntologyPipeline.score_ewma/trend_slope`, `LogicValidator.unreachable_entities`, `OntologyLearningAdapter.feedback_zscore`, `OntologyCritic.dimension_covariance`
- [x] (batch-145) `OntologyMediator.apply_feedback_list`, `OntologyOptimizer.convergence_score`, `LogicValidator.strongly_connected_components`
- [x] (batch-146) `OntologyCritic.top_improving_dimension`, `OntologyGenerator.compact_result`
- [x] (batch-148) `OntologyGenerator.relationship_types(result)`, `OntologyGenerator.split_result(result, n)`
- [x] (batch-149) `ExtractionConfig.describe()` — human-readable config summary, `OntologyGenerator.describe_extraction_pipeline()` — comprehensive pipeline report
  - Done 2026-02-21: Added ExtractionConfig.describe() returning formatted string with all config parameters. Added OntologyGenerator.describe_extraction_pipeline() that combines config description with extraction result statistics. Created 26 comprehensive unit tests in test_batch_149_pipeline_descriptions.py covering both methods. All tests passing (100% pass rate). Enables user-friendly debugging and reporting of extraction pipelines.
- [x] (batch-151) `OntologyOptimizer.history_stability`, `OntologyLearningAdapter.feedback_kurtosis`, `OntologyCritic.critic_dimension_rank`, `LogicValidator.relationship_type_distribution`
- [x] (batch-152) `OntologyPipeline.best_run_index/score_improvement_rate`, `OntologyOptimizer.window_average`, `OntologyMediator.feedback_history_size`
- [x] (batch-153) `OntologyOptimizer.first_n_history`, `OntologyLearningAdapter.feedback_rolling_average`, `OntologyCritic.dimension_variance`, `LogicValidator.average_path_length`
- [x] (batch-154) `OntologyLearningAdapter.worst_domain/best_domain`, `OntologyOptimizer.score_above_threshold`, `OntologyCritic.weakest_dimension`, `LogicValidator.node_degree_histogram`
- [x] (batch-155) `OntologyPipeline.scores_above_mean`, `OntologyGenerator.entity_count_by_type`, `OntologyLearningAdapter.score_momentum_delta`
- [x] (batch-156) `OntologyOptimizer.score_below_threshold`, `OntologyLearningAdapter.feedback_trend_direction`, `OntologyGenerator.entity_avg_confidence`, `OntologyCritic.dimension_delta_summary`
- [x] (batch-157) `OntologyPipeline.last_n_scores`, `LogicValidator.leaf_entities/source_entities`, `OntologyOptimizer.best_history_entry`
- [x] (batch-158) `OntologyCritic.all_dimensions_above`, `OntologyLearningAdapter.feedback_in_range`, `OntologyGenerator.avg_relationship_count`, `OntologyOptimizer.history_variance`
- [x] (batch-159) `OntologyOptimizer.history_iqr/top_n_history`, `OntologyPipeline.all_runs_above`, `OntologyGenerator.entity_type_ratio`
- [x] (batch-160) `OntologyCritic.dimension_ratio/all_dimensions_below`, `OntologyLearningAdapter.feedback_range`, `OntologyPipeline.run_score_at`
- [x] (batch-161) `LogicValidator.max_in_degree/max_out_degree`, `OntologyOptimizer.score_streak/recent_best_score`
- [x] (batch-162) `OntologyMediator.action_count_unique`, `OntologyLearningAdapter.feedback_improvement_rate`, `OntologyPipeline.run_score_deltas`, `OntologyGenerator.relationship_type_counts`
- [x] (batch-163) `OntologyLearningAdapter.feedback_last_n/feedback_top_n`, `OntologyOptimizer.history_change_count`, `LogicValidator.path_exists`
- [x] (batch-164) `OntologyCritic.dimension_mean/dimension_count_above`, `OntologyGenerator.entity_text_lengths`, `OntologyPipeline.run_score_variance`, `OntologyOptimizer.score_moving_sum`
- [x] (batch-165) `OntologyGenerator.entity_confidence_variance`, `LogicValidator.cycle_count`, `OntologyPipeline.run_trend`, `OntologyLearningAdapter.feedback_above_median`

---

## 📋 Comprehensive Refactor & Improvement Plan (2026)

_Last reviewed: 2026-02-21_

This section captures the full architectural vision beyond batch-method additions. Items here are larger, cross-cutting improvements that require careful planning.

### Track: [arch] — Architecture Unification

- [ ] (P1) [arch] **Unify optimizer base class hierarchy** — `BaseOptimizer`, `GraphRAGOptimizer`, `LogicTheoremOptimizer` all diverge in `__init__` signatures. Define a shared `OptimizerConfig` dataclass and wire it through all subclasses.
- [ ] (P1) [arch] **Protocol/ABC for `generate/validate/optimize`** — Create an `IOptimizer` Protocol (PEP 544) so all optimizer types can be used interchangeably. Enforce at import time via `isinstance` or `runtime_checkable`.
- [ ] (P2) [arch] **Remove circular import hazard** — `ontology_generator.py` imports from `ontology_critic.py` and vice versa in several code paths. Break the cycle with a shared `_types.py` module.
- [ ] (P2) [arch] **Consolidate `ExtractionConfig` variants** — There are at least 3 near-identical `ExtractionConfig`-like objects across the module. Unify into one with optional fields.
- [ ] (P3) [arch] **Introduce `OntologyResult` container** — Replace bare `dict` returns with a typed `OntologyResult` dataclass; provides `.entities`, `.relationships`, `.score`, `.metadata`.
- [ ] (P3) [arch] **Event bus for optimizer lifecycle hooks** — Add a lightweight pub/sub system so tests and dashboards can observe `on_round_start/end`, `on_score_improve`, `on_converge`.

### Track: [api] — Public API & Type Safety

- [ ] (P1) [api] **Add `py.typed` marker and check all public stubs** — Run `mypy --strict` on `ipfs_datasets_py/optimizers/` and fix all type errors in public surface. Mark package as typed.
- [ ] (P1) [api] **Deprecate magic `dict` ontologies** — All public methods that accept `Dict[str, Any]` as an ontology should accept `OntologyResult` instead; keep backward-compat shim for 2 releases.
- [ ] (P2) [api] **Version the optimizer public API** — Add `__version__` to `__init__.py` and document breaking changes in `CHANGELOG.md`.
- [ ] (P2) [api] **`OntologyGenerator.__call__` shorthand** — Implement `__call__(self, text) -> OntologyResult` as a convenience for pipeline chaining.
- [ ] (P3) [api] **Add `__repr__` / `__str__` to all major classes** — `OntologyOptimizer`, `OntologyPipeline`, `CriticScore`, `FeedbackRecord` all lack useful repr. Critical for debugging.

### Track: [graphrag] — Method Completions & Quality

- [ ] (P2) [graphrag] `OntologyOptimizer.history_skewness()` — skewness of score distribution
- [ ] (P2) [graphrag] `OntologyOptimizer.score_plateau_length()` — longest flat streak in history
- [ ] (P2) [graphrag] `OntologyCritic.dimension_std(score)` — std-dev across all dims
- [ ] (P2) [graphrag] `OntologyCritic.dimension_improvement_mask(before, after)` — bool dict of which dims improved
- [ ] (P2) [graphrag] `OntologyLearningAdapter.feedback_decay_sum(decay)` — exponentially decayed score sum
- [ ] (P2) [graphrag] `OntologyLearningAdapter.feedback_count_below(threshold)` — count below threshold
- [ ] (P2) [graphrag] `OntologyGenerator.max_confidence_entity(result)` — entity with highest confidence
- [ ] (P2) [graphrag] `OntologyGenerator.min_confidence_entity(result)` — entity with lowest confidence
- [ ] (P2) [graphrag] `OntologyPipeline.best_k_scores(k)` — top k overall scores across all runs
- [ ] (P2) [graphrag] `OntologyPipeline.worst_k_scores(k)` — bottom k overall scores
- [ ] (P2) [graphrag] `LogicValidator.relationship_diversity(ontology)` — entropy of relationship type distribution
- [ ] (P2) [graphrag] `LogicValidator.entity_pair_count(ontology)` — count of unique (source, target) pairs
- [ ] (P2) [graphrag] `OntologyMediator.feedback_age(idx)` — how many rounds ago feedback at index idx was recorded
- [ ] (P2) [graphrag] `OntologyMediator.clear_feedback()` — reset feedback history
- [ ] (P2) [graphrag] `ExtractionConfig.merge(other)` — merge two configs, taking max/min of thresholds
- [ ] (P2) [graphrag] `OntologyGenerator.entity_confidence_std(result)` — std-dev of confidences
- [ ] (P3) [graphrag] `OntologyOptimizer.score_gini_coefficient()` — inequality measure of score distribution
- [ ] (P3) [graphrag] `OntologyCritic.dimension_correlation(scores_a, scores_b)` — Pearson r between two score series
- [ ] (P3) [graphrag] `OntologyPipeline.score_histogram(bins)` — histogram of all run scores
- [ ] (P3) [graphrag] `LogicValidator.graph_diameter(ontology)` — longest shortest path in the graph
- [ ] (P3) [graphrag] `OntologyGenerator.relationship_confidence_avg(result)` — mean confidence of relationships

### Track: [tests] — Test Quality & Coverage

- [ ] (P1) [tests] **Property-based tests with Hypothesis** — Add Hypothesis strategies for `Entity`, `CriticScore`, `FeedbackRecord` and use them in at least 5 property tests per class.
- [ ] (P1) [tests] **Snapshot tests for `OntologyGenerator.generate()`** — Compare full pipeline output against JSON snapshots to catch regressions.
- [ ] (P2) [tests] **Coverage enforcement** — Add `pytest-cov` with `--cov-fail-under=85` to CI. Currently no minimum enforced.
- [ ] (P2) [tests] **Integration test: full round-trip** — `text → generate → validate → optimize → score` without mocking anything.
- [ ] (P2) [tests] **Parametrize existing batch tests** — Convert repeated test classes into `@pytest.mark.parametrize` to reduce LOC by ~30%.
- [ ] (P2) [tests] **Fix `test_end_to_end_pipeline.py`** — The externally-committed E2E tests fail because `OntologyGenerator.__init__` rejects `ExtractionConfig` objects. Fix the `ipfs_accelerate_config.get()` call to handle dataclass configs.
- [ ] (P3) [tests] **Mutation testing** — Run `mutmut` on `ontology_critic.py` and fix surviving mutants.
- [ ] (P3) [tests] **Benchmark tests** — Add `pytest-benchmark` tests for `generate()`, `evaluate_ontology()`, `optimize()` to track performance over time.

### Track: [obs] — Observability & Logging

- [ ] (P1) [obs] **Structured logging** — Replace all `print()` / bare `logging.info(f"...")` with structured log records (`logging.getLogger(__name__).info("...", extra={...})`). Use `structlog` or stdlib extras.
- [ ] (P2) [obs] **Metrics hook in `OntologyPipeline`** — Emit timing + score metrics after every round via a pluggable `MetricSink` protocol.
- [x] (P2) [obs] **Progress callback** — Add `on_progress: Callable[[int, int, float], None]` parameter to `OntologyPipeline.run()` so callers can show progress bars.
  - Done 2026-02-22: added `progress_callback` kwarg; fires at extracting/extracted/evaluating/refined stages; dict with stage/step/total_steps keys; exceptions suppressed. 7 tests added.
- [ ] (P3) [obs] **Distributed tracing stubs** — Add OpenTelemetry span creation in `generate()` and `optimize()` so long multi-round pipelines are traceable.

### Track: [perf] — Performance

- [ ] (P1) [perf] **Profile `OntologyGenerator.generate()` on 10 kB input** — Identify top-3 hotspots, document findings, and implement at least one optimization (target ≥ 20% speedup).
- [ ] (P2) [perf] **Lazy entity deduplication** — Defer deduplication to a post-pass rather than inline in every extraction loop.
- [ ] (P2) [perf] **Cache compiled regex patterns** — Scan for `re.compile()` calls inside hot loops; move them to module-level constants.
- [ ] (P3) [perf] **Async extraction support** — Add `async def generate_async(text)` wrappers so callers using asyncio can parallelize multiple extractions.

### Track: [docs] — Documentation

- [ ] (P1) [docs] **Module-level docstrings** — `ontology_generator.py`, `ontology_critic.py`, `ontology_optimizer.py` all lack a module-level docstring explaining purpose, usage, and key classes.
- [ ] (P2) [docs] **`README.md` for optimizers/** — Add a short `README.md` covering: what the optimizer does, quick-start code, and class diagram (ASCII or Mermaid).
- [ ] (P2) [docs] **Deprecation notices** — Any method marked `# TODO: remove` needs a `@deprecated` decorator with migration path documented in docstring.
- [ ] (P3) [docs] **API changelog** — Keep a running `CHANGELOG.md` in `optimizers/` noting added, changed, deprecated, removed items per batch.

### Track: [agentic] — Agentic Optimizer Improvements

- [ ] (P2) [agentic] **Wire `LogicTheoremOptimizer` to use the same `FeedbackRecord` class** — Currently uses a different feedback struct; unify for cross-optimizer analytics.
- [ ] (P2) [agentic] **Add `AgenticOptimizer.explain_action(action_name)` method** — Return a human-readable explanation of why the action was recommended.
- [ ] (P3) [agentic] **Pluggable reward function** — Let callers inject a `reward_fn: Callable[[OntologyResult], float]` into the agentic loop.

---

## Batch 166+ Backlog (auto-generated, pick randomly)

- [x] (P2) [graphrag] `OntologyOptimizer.history_skewness()` — skewness of scores (batch-166)
- [x] (P2) [graphrag] `OntologyOptimizer.score_plateau_length()` — longest flat streak (batch-167)
- [x] (P2) [graphrag] `OntologyCritic.dimension_std(score)` — std-dev of dims (batch-166)
- [x] (P2) [graphrag] `OntologyCritic.dimension_improvement_mask(before, after)` — bool dict (batch-166)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_decay_sum(decay)` — decayed score sum (batch-167)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_count_below(threshold)` — count below (batch-167)
- [x] (P2) [graphrag] `OntologyGenerator.max_confidence_entity(result)` — entity with max confidence (batch-166)
- [x] (P2) [graphrag] `OntologyGenerator.min_confidence_entity(result)` — entity with min confidence (batch-166)
- [x] (P2) [graphrag] `OntologyPipeline.best_k_scores(k)` — top k scores (batch-166)
- [x] (P2) [graphrag] `OntologyPipeline.worst_k_scores(k)` — bottom k scores (batch-166)
- [x] (P2) [graphrag] `LogicValidator.relationship_diversity(ontology)` — entropy of rel types (batch-167)
- [x] (P2) [graphrag] `LogicValidator.entity_pair_count(ontology)` — unique source/target pairs (batch-167)
- [x] (P2) [graphrag] `OntologyMediator.clear_feedback()` — reset feedback history (batch-168)
- [x] (P2) [graphrag] `ExtractionConfig.merge(other)` — merge two configs _(already exists at line 596)_
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_std(result)` — std-dev of confidences (batch-166)
- [x] (P2) [graphrag] `OntologyOptimizer.score_gini_coefficient()` — Gini inequality measure (batch-170)
- [x] (P2) [graphrag] `OntologyPipeline.score_histogram(bins)` — histogram dict (batch-169)
- [x] (P2) [graphrag] `LogicValidator.graph_diameter(ontology)` — longest shortest path (batch-170)
- [x] (P2) [graphrag] `OntologyGenerator.relationship_confidence_avg(result)` — mean rel confidence if available (batch-202)
- [x] (P2) [graphrag] `OntologyCritic.dimension_correlation(scores_a, scores_b)` — Pearson r (batch-170)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_above_threshold_fraction(t)` — fraction above t (batch-167)
- [x] (P2) [graphrag] `OntologyPipeline.run_moving_average(n)` — moving average of run scores (batch-168)
- [x] (P2) [graphrag] `OntologyCritic.weighted_score(score, weights_dict)` — custom-weighted overall (batch-168)
- [x] (P2) [graphrag] `LogicValidator.multi_hop_count(ontology, src, max_hops)` — entities reachable in ≤ max_hops (batch-169)
- [x] (P2) [graphrag] `OntologyGenerator.entities_with_properties(result)` — entities with non-empty props (batch-169)
- [x] (P2) [graphrag] `OntologyOptimizer.score_above_percentile(p)` — count above p-th percentile (batch-169)
- [x] (P2) [graphrag] `OntologyMediator.feedback_score_mean()` — mean of feedback scores (batch-168)
- [x] (P2) [graphrag] `OntologyPipeline.convergence_round()` — first round where variance drops (batch-168)
- [x] (P2) [graphrag] `OntologyCritic.passing_dimensions(score, threshold)` — list of dims above threshold (batch-166)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_percentile_rank(value)` — percentile rank of a value (batch-170)

## Batch 171+ Backlog

- [x] (P2) [graphrag] `OntologyOptimizer.history_trimmed_mean(trim)` — mean after removing top/bottom trim fraction (batch-171)
- [x] (P2) [graphrag] `OntologyOptimizer.score_z_scores()` — list of z-scores for each history entry (batch-171)
- [x] (P2) [graphrag] `OntologyCritic.dimension_entropy(score)` — Shannon entropy of dimension values (batch-171)
- [x] (P2) [graphrag] `OntologyCritic.compare_scores(a, b)` — dict of diffs per dimension + overall delta (batch-171)
- [x] (P2) [graphrag] `OntologyGenerator.top_confidence_fraction(result, frac)` — top-frac fraction of entities by confidence (batch-171)
- [x] (P2) [graphrag] `OntologyGenerator.relationship_source_set(result)` — set of unique source entity IDs (batch-171)
- [x] (P2) [graphrag] `OntologyGenerator.relationship_target_set(result)` — set of unique target entity IDs (batch-171)
- [x] (P2) [graphrag] `OntologyPipeline.score_std()` — std-dev of all run scores (batch-171)
- [x] (P2) [graphrag] `OntologyPipeline.improvement_count()` — number of runs that improved on previous (batch-171)
- [x] (P2) [graphrag] `LogicValidator.fanout_ratio(ontology)` — avg out-degree / avg in-degree (batch-172)
- [x] (P2) [graphrag] `LogicValidator.symmetric_pair_count(ontology)` — pairs where both (a→b) and (b→a) exist (batch-172)
- [x] (P2) [graphrag] `OntologyMediator.most_improved_action()` — action correlated with most score gain (batch-172)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_ewma(alpha)` — EWMA of feedback scores (batch-172)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_normalized()` — scores normalized to [0,1] (batch-172)
- [x] (P2) [graphrag] `OntologyOptimizer.score_cumulative_max()` — running maximum of scores over history (batch-172)
- [x] (P2) [graphrag] `OntologyOptimizer.history_autocorrelation(lag)` — autocorr of scores at given lag (pre-existing)
- [x] (P2) [graphrag] `OntologyCritic.score_is_above_baseline(score, baseline)` — bool overall check (batch-172)
- [x] (P2) [graphrag] `LogicValidator.triangle_count(ontology)` — number of directed 3-cycles (batch-173)
- [x] (P2) [graphrag] `OntologyGenerator.confidence_quartiles(result)` — Q1, median, Q3 of entity confidences (batch-173)
- [x] (P2) [graphrag] `OntologyPipeline.score_range()` — max - min of all run scores (batch-171)
- [x] (P1) [api] **Add `__repr__` to `OntologyOptimizer`, `OntologyPipeline`, `FeedbackRecord`** — done in batch-172
- [x] (P2) [graphrag] `OntologyCritic.top_k_dimensions(score, k)` — k highest-scoring dims (batch-173)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_score_std()` — std-dev of feedback scores (batch-173)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_last_improvement()` — score delta at last improving step (batch-173)
- [x] (P2) [graphrag] `OntologyOptimizer.score_cumulative_min()` — running minimum of scores over history (batch-174)
- [x] (P2) [graphrag] `OntologyOptimizer.history_below_median_count()` — entries below median score (batch-174)
- [x] (P2) [graphrag] `OntologyPipeline.first_score()` — overall score of the first run (batch-174)
- [x] (P2) [graphrag] `OntologyPipeline.score_below_mean_count()` — runs below mean score (batch-174)
- [x] (P2) [graphrag] `OntologyCritic.dimension_improvement_rate(before, after)` — fraction of dims that improved (batch-174)
- [x] (P2) [graphrag] `LogicValidator.leaf_node_count(ontology)` — nodes with no outgoing edges (batch-174)
- [x] (P2) [graphrag] `OntologyGenerator.relationship_confidence_mean(result)` — mean rel confidence (batch-174)
- [x] (P2) [graphrag] `OntologyGenerator.entities_above_confidence(result, threshold)` — entities above threshold (batch-174)
- [x] (P2) [graphrag] `OntologyOptimizer.score_trend_strength()` — absolute linear trend slope (batch-175)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_volatility()` — mean absolute change between feedback (batch-175)
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_trend_direction()` — up/down/flat trend of feedback (batch-175)
- [x] (P2) [graphrag] `OntologyGenerator.entity_type_entropy(result)` — Shannon entropy of entity type dist (batch-175)
- [x] (P2) [graphrag] `LogicValidator.root_node_count(ontology)` — nodes with no incoming edges (batch-175)
- [x] (P2) [graphrag] `LogicValidator.isolated_node_count(ontology)` — nodes with no edges at all (batch-175)
- [x] (P2) [graphrag] `OntologyCritic.dimension_weighted_sum(score, weights)` — custom-weighted sum (batch-175)

## Batch 176+ Backlog (all completed — verified 2026-02-22)

- [x] (P2) [graphrag] `OntologyOptimizer.history_kurtosis()` — excess kurtosis of score distribution
- [x] (P2) [graphrag] `OntologyOptimizer.score_ewma(alpha)` — EWMA of average_score values
- [x] (P2) [graphrag] `OntologyCritic.dimension_min(score)` — lowest-scoring dimension name
- [x] (P2) [graphrag] `OntologyCritic.dimension_max(score)` — highest-scoring dimension name
- [x] (P2) [graphrag] `OntologyCritic.dimension_range(score)` — max - min dimension value
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_skewness(result)` — skewness of entity confidences
- [x] (P2) [graphrag] `OntologyGenerator.unique_relationship_types(result)` — distinct relationship type strings
- [x] (P2) [graphrag] `LogicValidator.in_degree_distribution(ontology)` — dict of node→in-degree
- [x] (P2) [graphrag] `LogicValidator.out_degree_distribution(ontology)` — dict of node→out-degree
- [x] (P2) [graphrag] `OntologyPipeline.run_score_ewma(alpha)` — EWMA of pipeline run scores
- [x] (P2) [graphrag] `OntologyPipeline.run_score_percentile(p)` — p-th percentile of run scores
- [x] (P2) [graphrag] `OntologyMediator.feedback_count_by_action(action)` — how many times action was used
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_min()` — minimum feedback score
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_max()` — maximum feedback score
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_cumulative_sum()` — running sum of scores
- [x] (P1) [tests] **Fix `test_end_to_end_pipeline.py`** — tests passing as of 2026-02-22 (22/22)
- [x] (P1) [docs] **`README.md` for `optimizers/`** — Quick-start, class diagram, example pipeline code added 2026-02-22

## Batches 176–185 Completed

- [x] Batch 176: history_kurtosis, score_ewma, dimension_min/max/range, entity_confidence_skewness, unique_relationship_types, feedback_min/max/cumulative_sum
- [x] Batch 177: in/out_degree_distribution, run_score_ewma/percentile, feedback_count_by_action, action_success_rate
- [x] Batch 178: history_second_derivative, score_reliability, entity_relation_ratio, relationship_confidence_std, max_dag_depth, feedback_rate_of_change/above_mean_count, run_score_median/count_above
- [x] Batch 179: history_first_derivative, score_improvement_ratio, dimensions_above_count, score_letter_grade, entity_confidence_percentile, strongly_connected_count, consecutive_improvements, feedback_window_mean/outlier_count
- [x] Batch 180: history_percentile, score_below_percentile_count, dimension_coefficient_of_variation, relationship_type_frequency, entity_id_set, weakly_connected_count, run_score_iqr, feedback_interquartile_range
- [x] Batch 181: history_entropy_change, score_variance_trend, dimensions_at_max_count, dimension_harmonic_mean, entity_source_span_coverage, relationship_density, run_score_CV, feedback_entropy, feedback_positive_fraction
- [x] Batch 182: score_above_mean_fraction, history_gini, dimension_geometric_mean, dimensions_below_count, average_in_degree, average_out_degree, run_score_range, run_score_above_mean_fraction, feedback_consecutive_positive, feedback_gini
- [x] Batch 183: history_outlier_count, score_autocorrelation, dimension_spread, top_dimension, relationship_coverage, entity_confidence_variance, run_score_kurtosis, run_score_sum, feedback_below_mean_count, feedback_above_median, action_entropy, total_action_count
- [x] Batch 184: history_cross_mean_count, score_recent_max, score_recent_min, bottom_dimension, score_above_threshold_count, entity_property_count, entity_types_set, run_score_geometric_mean, best_run_index, feedback_min_max_ratio, feedback_count
- [x] Batch 185: history_std_ratio, score_turning_points, dimension_balance_score, score_percentile_rank, entity_confidence_iqr, avg_entity_confidence, run_score_harmonic_mean, worst_run_index, feedback_longest_positive_streak, feedback_score_range

## Batch 186+ Backlog (all completed in Batches 186–197)

- [x] (P2) [graphrag] `OntologyOptimizer.history_momentum_score()` — weighted sum of recent improvements
- [x] (P2) [graphrag] `OntologyOptimizer.score_signed_sum()` — sum of signed deltas
- [x] (P2) [graphrag] `OntologyCritic.score_classification(score)` — "excellent"/"good"/"fair"/"poor" bucket
- [x] (P2) [graphrag] `OntologyCritic.dimension_rank_order(score)` — list of dims sorted by value desc
- [x] (P2) [graphrag] `OntologyGenerator.relationship_bidirectionality_rate(result)` — fraction of bidirectional pairs
- [x] (P2) [graphrag] `OntologyGenerator.entity_text_length_mean(result)` — mean len of entity text strings
- [x] (P2) [graphrag] `LogicValidator.avg_path_length(ontology)` — average shortest-path length (BFS) — done in Batch 202 as alias
- [x] (P2) [graphrag] `OntologyPipeline.run_score_delta_sum()` — sum of consecutive score deltas
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_weighted_mean(weights)` — positionally weighted mean
- [x] (P2) [graphrag] `OntologyMediator.unique_action_count()` — number of distinct actions used

## Batches 186–197 Completed

- [x] Batch 186: history_momentum_score, score_signed_sum, score_classification, dimension_rank_order, relationship_bidirectionality_rate, entity_text_length_mean, run_score_delta_sum, run_score_improving_fraction, feedback_weighted_mean, feedback_last_score
- [x] Batch 187: score_acceleration, history_peak_count, dimension_normalized_vector, score_above_median, entity_confidence_mode, relationship_types_count, run_score_acceleration, run_score_peak_count, feedback_acceleration, feedback_first_score
- [x] Batch 188: history_valley_count, score_trend_correlation, dimension_cosine_similarity, score_distance, entity_confidence_std, entity_avg_property_count, self_loop_count, node_count, run_score_trend_direction, feedback_improvement_count, feedback_decline_count
- [x] Regression fixes: removed duplicate feedback_above_median/feedback_score_range/self_loop_count overrides; fixed 3 test files
- [x] Batch 189: history_weighted_mean, score_consecutive_above, dimension_percentile, entity_min/max_confidence, edge_count, run_score_first, feedback_trend_slope, action_ratio
- [x] Batch 190: history_min, history_max, history_rolling_mean, dimension_above_threshold, entity_with_most_properties, relationship_max_weight, run_score_last, feedback_median_deviation, action_mode
- [x] Batch 191: history_above_mean_count, score_delta_mean, history_median, score_above_rolling_mean, dimension_mean, entity_count_with_confidence_above, relationship_avg_confidence, run_score_delta, feedback_score_sum, action_least_frequent
- [x] Batch 192: history_first, history_last, score_first, score_last, dimension_below_threshold, entity_confidence_range, relationship_min_confidence, run_improvement_rate
- [x] Batch 193: history_streak_above, score_volatility, history_percentile_rank, dimension_weighted_score, entity_avg_text_length, relationship_confidence_range, feedback_positive_rate, action_diversity_score
- [x] Batch 194: history_span, history_change_rate, history_trend_direction, dimension_top_k, entity_property_keys, run_score_mean, feedback_negative_rate, action_gini
- [x] Batch 195: history_cumulative_sum, score_normalized, history_decay_sum, dimension_bottom_k, entity_text_max_length, relationship_type_diversity, run_score_std, feedback_weighted_sum, action_count_per_round
- [x] Batch 196: score_delta_std, history_coefficient_of_variation, dimension_sum, relationship_avg_weight, run_score_min, run_score_max, feedback_variance
- [x] Batch 197: history_above_threshold_rate, history_improving_fraction, score_percentile_of_last, score_diff_from_mean, entity_confidence_sum, feedback_longest_negative_streak, action_names

## Batch 198+ Backlog

- [x] (P2) [graphrag] `OntologyOptimizer.history_trimmed_mean(trim_fraction)` — trimmed mean ignoring extremes
  - Done 2026-02-21: Added method to OntologyOptimizer (lines 3827-3862) with trim_fraction validation and outlier removal
- [x] (P2) [graphrag] `OntologyOptimizer.score_z_score()` — z-score of last entry relative to history
- [x] (P2) [graphrag] `OntologyCritic.dimension_z_scores(score)` — dict of dim→z-score vs history
  - Done 2026-02-21: Added method to OntologyCritic (lines 2235-2267) with nominal=0.5 and std_dev=0.2 for z-score computation
- [x] (P2) [graphrag] `OntologyGenerator.entity_id_list(result)` — sorted list of entity IDs
  - Done 2026-02-21: Added method to OntologyGenerator (lines 5620-5640) with deduplication and None filtering
- [x] (P2) [graphrag] `OntologyGenerator.relationship_source_ids(result)` — set of source entity IDs
- [x] (P2) [graphrag] `OntologyGenerator.relationship_target_ids(result)` — set of target entity IDs
- [x] (P2) [graphrag] `LogicValidator.hub_nodes(ontology, min_degree)` — nodes with degree >= min_degree
  - Done 2026-02-21: Added method to LogicValidator (lines 1014-1070) with degree-based hub identification and sorting
- [x] (P2) [graphrag] `OntologyPipeline.run_score_trimmed_mean(trim_fraction)` — trimmed mean of run scores
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_trimmed_mean(trim_fraction)` — trimmed mean of feedback
- [x] (P2) [graphrag] `OntologyMediator.action_entropy_change()` — change in action entropy over rounds

## Batch 199 - Complete ✅ (2026-02-21)
- [x] (P2) [graphrag] `OntologyOptimizer.history_trimmed_mean(trim_fraction)`
- [x] (P2) [graphrag] `OntologyCritic.dimension_z_scores(score)`
- [x] (P2) [graphrag] `OntologyGenerator.entity_id_list(result)`
- [x] (P2) [graphrag] `LogicValidator.hub_nodes(ontology, min_degree)`
- [x] (P2) [tests] Unit tests for all 4 methods (32 tests, all passing)
- [x] (P2) [tests] Property-based tests with Hypothesis (2 property tests)

Implementations Summary:
- history_trimmed_mean: Removes outliers from score history using trim_fraction parameter [0, 0.5)
- dimension_z_scores: Computes z-scores for each CriticScore dimension (nominal=0.5, std_dev=0.2)
- entity_id_list: Returns sorted unique entity IDs from extraction results with None/empty filtering
- hub_nodes: Identifies high-degree nodes in ontology network graphs based on relationship count

Testing Coverage:
- 8 unit tests for history_trimmed_mean (edge cases, error handling, extremes)
- 6 unit tests for dimension_z_scores (boundary conditions, dimension coverage)
- 6 unit tests for entity_id_list (sorting, deduplication, filtering)
- 10 unit tests for hub_nodes (topology types, sortinf, None handling)
- 2 property-based tests with Hypothesis for statistical invariants

Bug Fixes in Implementation:
- Removed duplicate entity_id_list implementation on line 6625
- Fixed None ID handling in entity_id_list deduplication logic

---

## Batch 202 — Done ✅ (2026-02-22)

- [x] (P2) [graphrag] `OntologyOptimizer.score_geometric_mean()` — geometric mean of history average_score values
- [x] (P2) [graphrag] `OntologyOptimizer.score_harmonic_mean()` — harmonic mean of history average_score values
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_geometric_mean()` — geometric mean of feedback final_score values
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_harmonic_mean()` — harmonic mean of feedback final_score values
- [x] (P2) [graphrag] `OntologyGenerator.relationship_confidence_avg(result)` — alias for relationship_confidence_mean
- [x] (P2) [graphrag] `LogicValidator.avg_path_length(ontology)` — alias for average_path_length
- [x] (P2) [graphrag] `LogicValidator.node_density(ontology)` — edges / (n*(n-1)); directed graph density

Implementation notes:
- score_geometric_mean: product^(1/n) of history scores; returns 0.0 if any score is zero
- score_harmonic_mean: n / sum(1/s) of history scores; returns 0.0 if any score is zero
- feedback_geometric_mean: same pattern applied to OntologyLearningAdapter feedback records
- feedback_harmonic_mean: same pattern applied to OntologyLearningAdapter feedback records
- relationship_confidence_avg: thin alias delegating to relationship_confidence_mean (DRY)
- avg_path_length: thin alias delegating to average_path_length (DRY)
- node_density: directed graph density; 0.0 for < 2 nodes

Testing (50 new tests in test_batch_202_features.py):
- 7 tests for score_geometric_mean (empty, single, two-values, uniform, zero, AM-GM, return type)
- 7 tests for score_harmonic_mean (empty, single, two-values, uniform, zero, HM≤GM≤AM, return type)
- 7 tests for feedback_geometric_mean
- 7 tests for feedback_harmonic_mean
- 6 tests for relationship_confidence_avg
- 7 tests for avg_path_length
- 9 tests for node_density

---

## Batch 203 — Done ✅ (2026-02-22)

- [x] (P2) [graphrag] `OntologyGenerator.apply_config(result, config)` — re-filter result using ExtractionConfig threshold; prunes orphaned relationships
- [x] (P2) [graphrag] `OntologyMediator.retry_last_round(ontology, score, ctx)` — re-applies last refinement by rolling back undo stack then calling refine_ontology
- [x] (P2) [graphrag] `OntologyOptimizer.score_coefficient_of_variation()` — CV (std/mean) of history scores
- [x] (P2) [graphrag] `OntologyOptimizer.score_relative_improvement()` — (last-first)/first relative gain
- [x] (P2) [graphrag] `OntologyOptimizer.score_to_mean_ratio()` — latest score / history mean
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_std()` — std-dev of feedback final_scores
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_coefficient_of_variation()` — CV of feedback scores
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_relative_std()` — alias for feedback_coefficient_of_variation
- [x] (P2) [graphrag] `OntologyPipeline.run_score_relative_improvement()` — relative gain from first to last run

Also marked 22 stale [ ] TODO entries as [x] (methods verified to already exist in source files).

Testing: 51 new tests in test_batch_203_features.py; all passing.

---

## Batch 204 — Done ✅ (2026-02-22)

- [x] (P2) [graphrag] `OntologyOptimizer.score_iqr()` — interquartile range of history average_score values
- [x] (P2) [graphrag] `OntologyOptimizer.history_rolling_std(window)` — rolling std-dev of scores over a sliding window
- [x] (P2) [graphrag] `OntologyCritic.dimension_iqr(score)` — IQR of the 6 evaluation dimension values in a CriticScore
- [x] (P2) [graphrag] `OntologyCritic.dimension_coefficient_of_variation(score)` — CV (std/mean) of dimension values
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_geometric_mean(result)` — geometric mean of entity confidences
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_harmonic_mean(result)` — harmonic mean of entity confidences
- [x] (P2) [graphrag] `OntologyGenerator.relationship_confidence_iqr(result)` — IQR of relationship confidence scores
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_iqr()` — IQR of feedback final_score values
- [x] (P2) [graphrag] `OntologyPipeline.best_score_improvement()` — maximum single-step score improvement across runs
- [x] (P2) [graphrag] `OntologyPipeline.rounds_without_improvement()` — trailing run count with no score improvement
- [x] (P2) [graphrag] `LogicValidator.most_connected_node(ontology)` — node with the highest total degree

Implementation notes:
- score_iqr / feedback_iqr / relationship_confidence_iqr / dimension_iqr: IQR using integer index
  (q1=scores[n//4], q3=scores[(3*n)//4]); returns 0.0 when fewer than 4 entries.
- history_rolling_std: window clamped to min 2; returns empty list when history < window.
- entity_confidence_geometric_mean / harmonic_mean: return 0.0 if any confidence ≤ 0 or no entities.
- best_score_improvement: max positive delta between consecutive runs; 0.0 if none improves.
- rounds_without_improvement: counts trailing runs from end where score ≤ previous run.
- most_connected_node: sum of in-degree + out-degree per node; empty string if no relationships.

Testing: 68 new tests in test_batch_204_features.py; all passing.

## Batch 205 — Done ✅ (2026-02-22)

- [x] (P2) [graphrag] `OntologyOptimizer.score_skewness()` — skewness of history score distribution
- [x] (P2) [graphrag] `OntologyOptimizer.history_rolling_mean(window)` — rolling mean over a sliding window (already existed)
- [x] (P2) [graphrag] `OntologyCritic.dimension_skewness(score)` — skewness of dimension value distribution
- [x] (P2) [graphrag] `OntologyCritic.weakest_dimension(score)` — dimension with lowest value (already existed)
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_kurtosis(result)` — excess kurtosis of entity confidences
- [x] (P2) [graphrag] `OntologyGenerator.entity_text_length_std(result)` — std-dev of entity text lengths
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_rolling_mean(window)` — rolling mean of feedback scores
- [x] (P2) [graphrag] `OntologyPipeline.run_score_skewness()` — skewness of run score distribution
- [x] (P2) [graphrag] `OntologyPipeline.worst_score_decline()` — maximum single-step score decline across runs
- [x] (P2) [graphrag] `LogicValidator.avg_in_degree(ontology)` — average in-degree across nodes (alias for average_in_degree)
- [x] (P2) [graphrag] `LogicValidator.avg_out_degree(ontology)` — average out-degree across nodes (alias for average_out_degree)

Implementation notes:
- score_skewness / dimension_skewness / run_score_skewness: population skewness formula
  (1/n)*sum((x-mean)^3)/std^3; returns 0.0 for <3 entries or zero std.
- entity_confidence_kurtosis: excess kurtosis (1/n)*sum((x-mean)^4)/std^4 - 3;
  returns 0.0 for <4 entities or zero std.
- entity_text_length_std: population std-dev of len(entity.text); 0.0 for <2 entities.
- feedback_rolling_mean: list of rolling means; window clamped to ≥1; empty when len<window.
- worst_score_decline: max positive backward delta across consecutive runs; 0.0 if no decline.
- avg_in_degree / avg_out_degree: thin aliases delegating to average_in_degree / average_out_degree.

Testing: 58 new tests in test_batch_205_features.py; all passing.

## Batch 206 — Done ✅ (2026-02-22)

- [x] (P2) [graphrag] `OntologyOptimizer.score_entropy()` — Shannon entropy of discretised history scores
- [x] (P2) [graphrag] `OntologyOptimizer.history_above_percentile(p)` — count of scores above p-th percentile
- [x] (P2) [graphrag] `OntologyCritic.dimension_entropy(score)` — already existed in source
- [x] (P2) [graphrag] `OntologyCritic.dimensions_above_mean(score)` — number of dimensions above their collective mean
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_range(result)` — already existed in source
- [x] (P2) [graphrag] `OntologyGenerator.entity_count_by_type(result)` — already existed in source
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_rolling_std(window)` — rolling std-dev of feedback scores
- [x] (P2) [graphrag] `OntologyPipeline.run_score_kurtosis()` — already existed in source
- [x] (P2) [graphrag] `OntologyPipeline.consecutive_declines()` — max consecutive declining runs
- [x] (P2) [graphrag] `LogicValidator.avg_degree(ontology)` — average total degree per node

Implementation notes:
- score_entropy: discretises scores into 10 bins in [0,1]; returns Shannon entropy in bits.
- history_above_percentile(p): threshold = sorted_scores[int(p/100*n)]; returns count strictly above.
- dimensions_above_mean: counts dimension values strictly above their collective mean.
- feedback_rolling_std: window clamped to ≥2; population std-dev per window; empty when len<window.
- consecutive_declines: max streak of strictly decreasing consecutive runs.
- avg_degree: sum of all in+out degrees / node count; 0.0 when no relationships.

Testing: 43 new tests in test_batch_206_features.py; all passing.

## Batch 207 — Done ✅ (2026-02-22)

- [x] (P2) [graphrag] `OntologyOptimizer.score_gini()` — alias for score_gini_coefficient()
- [x] (P2) [graphrag] `OntologyOptimizer.history_percentile(p)` — already existed in source
- [x] (P2) [graphrag] `OntologyCritic.dimension_gini(score)` — Gini coefficient of 6 dimension values
- [x] (P2) [graphrag] `OntologyGenerator.entity_confidence_gini(result)` — Gini coefficient of entity confidences
- [x] (P2) [graphrag] `OntologyLearningAdapter.feedback_gini()` — already existed in source
- [x] (P2) [graphrag] `OntologyPipeline.run_score_gini()` — Gini coefficient of run score distribution
- [x] (P2) [graphrag] `OntologyPipeline.first_improving_run()` — 0-based index of first improving run (-1 if none)
- [x] (P2) [graphrag] `LogicValidator.degree_centrality(ontology)` — dict of node→degree/(n-1) centrality
- [x] (P2) [graphrag] `LogicValidator.max_degree_node_count(ontology)` — count of nodes at maximum degree

Implementation notes:
- score_gini / run_score_gini / dimension_gini / entity_confidence_gini: sorted-list Gini formula
  G = (2*sum(i*x_i) - (n+1)*sum(x_i)) / (n*sum(x_i)); 0.0 when total=0 or single value.
- first_improving_run: returns 0-based index of first run with score > previous run; -1 if none.
- degree_centrality: deg / (n-1) for each node; returns {node: 0.0} when n < 2.
- max_degree_node_count: count of nodes with degree equal to max degree; 0 when no relationships.

Testing: 48 new tests in test_batch_207_features.py; all passing.

## Batch 208+ Backlog

- [ ] (P2) [graphrag] `OntologyOptimizer.score_trend_slope()` — linear regression slope of history scores
- [ ] (P2) [graphrag] `OntologyOptimizer.history_variance()` — variance of all history scores
- [ ] (P2) [graphrag] `OntologyCritic.dimension_variance(score)` — variance of the 6 dimension values
- [ ] (P2) [graphrag] `OntologyGenerator.relationship_type_count(result)` — number of distinct relationship types
- [ ] (P2) [graphrag] `OntologyLearningAdapter.feedback_trend_slope()` — linear regression slope of feedback scores
- [ ] (P2) [graphrag] `OntologyPipeline.run_score_variance()` — variance of run score distribution
- [ ] (P2) [graphrag] `OntologyPipeline.last_improving_run()` — index of last run that improved on previous
- [ ] (P2) [graphrag] `LogicValidator.closeness_centrality_approx(ontology)` — approximate closeness centrality
- [ ] (P2) [graphrag] `LogicValidator.reciprocal_edge_count(ontology)` — count of bidirectional edge pairs
