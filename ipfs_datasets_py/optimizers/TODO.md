# Optimizers: Infinite TODO / Improvement Plan

_Last updated: 2026-02-20_

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

## Now (P0/P1): highest leverage

- [x] (P0) [graphrag] Remove abusive/toxic inline TODO comment in `graphrag/query_optimizer.py` and replace with a professional TODO — **DoD**: comment removed; behavior unchanged; module imports.
  - Done 2026-02-20: replaced with actionable refactor TODO.
- [x] (P0) [docs] Ensure this file exists and is referenced consistently — **DoD**: `optimizers/TODO.md` present and discoverable.
  - Done 2026-02-20: confirmed present; keep as living backlog.

- [x] (P0) [graphrag] Fix GraphRAG CLI ontology contract mismatch (dict vs object) and implement real JSON load + validate — **DoD**: `generate`/`validate`/`optimize` don’t crash for JSON ontologies.
  - Done 2026-02-20: `graphrag/cli_wrapper.py` now treats ontologies as dicts; `validate` supports JSON.

- [x] (P1) [arch] Resolve “docs vs code” drift for the unified common layer (`optimizers/common/`) — pick one:
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

---

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
- [ ] (P2) [graphrag] Implement `_extract_with_llm_fallback()` in OntologyGenerator that wraps `_extract_rule_based()` + fallback
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
- [ ] (P2) [graphrag] Add `OntologyPipeline.run_async()` -- async coroutine wrapper around run()
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
- [ ] (P2) [graphrag] Add `OntologyCritic.calibrate_thresholds()` -- adjust dimension thresholds from history of scores
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
- [ ] (P2) [graphrag] Add `OntologyGenerator.extract_noun_phrases(text)` -- simple NP chunker
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
- [ ] (P2) [graphrag] Add `OntologyOptimizer.prune_history(n)` -- keep only last N history entries
- [x] (P3) [graphrag] Add `EntityExtractionResult.highest_confidence_entity()` -- return entity with max confidence
- [x] (P2) [graphrag] Add `Entity.to_text()` -- return human-readable single-line summary
- [x] (P3) [graphrag] Add `OntologyPipeline.summary()` -- one-line string with domain/rounds/stage-count
- [x] (P2) [graphrag] Add `ExtractionConfig.copy()` -- Done batch-77 -- shallow copy of the config
- [x] (P3) [graphrag] Add `OntologyLearningAdapter.feedback_summary()` -- Done batch-77: -- stats dict for feedback history
- [x] (P2) [graphrag] Add `OntologyMediator.get_round_count()` -- Done batch-77: -- number of refinement rounds performed
- [x] (P3) [graphrag] Add `OntologyCritic.score_delta(score_a, score_b)` -- Done batch-77: -- per-dim delta dict
- [x] (P2) [graphrag] Add `EntityExtractionResult.filter_by_span(start, end)` -- Done batch-77: -- keep entities with source_span in range
- [ ] (P3) [graphrag] Add `OntologyOptimizer.worst_ontology()` -- return ontology from lowest-scoring history entry
- [ ] (P2) [graphrag] Add `OntologyGenerator.dedup_by_text_prefix(result, prefix_len)` -- deduplicate entities with shared prefix
- [ ] (P3) [graphrag] Add `LogicValidator.is_consistent(ontology)` -- boolean shortcut for check_consistency
- [ ] (P2) [graphrag] Add `OntologyPipeline.history` property -- return list of PipelineResult from past runs
- [ ] (P3) [graphrag] Add `ExtractionConfig.apply_defaults_for_domain(domain)` -- mutate thresholds in-place for domain
- [ ] (P2) [graphrag] Add `OntologyCritic.critical_weaknesses(score)` -- return only weaknesses below 0.5 threshold
- [ ] (P3) [graphrag] Add `OntologyMediator.peek_undo()` -- return top of undo stack without popping
- [ ] (P2) [graphrag] Add `OntologyLearningAdapter.serialize_to_file(path)` and `from_file(path)` -- file-based persistence
- [ ] (P3) [graphrag] Add `EntityExtractionResult.random_sample(n)` -- return result with n random entities
