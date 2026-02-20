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

- [ ] (P1) [arch] Resolve “docs vs code” drift for the unified common layer (`optimizers/common/`) — pick one:
  - implement minimal `BaseCritic`, `BaseSession`, `BaseHarness` scaffolding as documented, **or**
  - update architecture docs to match reality.
  - **DoD**: no misleading docs; no broken imports.

- [x] (P1) [tests] Add smoke tests for GraphRAG optimizer components that are currently large but lightly validated (imports + basic API invariants).
  - Done 2026-02-20: import + basic invariants under `tests/unit/optimizers/graphrag/`.

- [x] (P1) [perf] Consolidate duplicated resource monitoring in `performance_optimizer.py` (single source of truth via `ResourceMonitor`).
  - Done 2026-02-20: `WebsiteProcessingOptimizer.monitor_resources()` delegates to `ResourceMonitor.get_current_resources()`; schema covered by a unit test.


- [x] (P1) [obs] Make `OptimizerLearningMetricsCollector` persistence consistent across all `record_*` methods and enforce `max_history_size` for `learning_cycles`.
  - Done: 2026-02-20 (tests updated + timestamp handling fixed).

---

## Architecture & Refactor plan (comprehensive)

### A. Make the “unified architecture” real (or truthfully documented)

- [ ] (P1) [arch] Decide source-of-truth: code-first vs doc-first for `ARCHITECTURE_UNIFIED.md`.
- [ ] (P1) [arch] If code-first: shrink `ARCHITECTURE_UNIFIED.md` to match existing modules and add “future work” notes.
- [ ] (P2) [arch] If doc-first: add missing common primitives (thin, safe abstractions):
  - `optimizers/common/base_critic.py`
  - `optimizers/common/base_session.py`
  - `optimizers/common/base_harness.py`
  - (optional) `optimizers/common/llm_integration.py` that wraps `agentic/llm_integration.py`
  - **DoD**: abstractions are used by at least one concrete optimizer (or are explicitly marked experimental).

### B. Normalize configuration + dependency injection

- [ ] (P2) [api] Standardize “context” objects across GraphRAG / logic / agentic (dataclasses with typed fields; avoid `Dict[str, Any]` sprawl).
- [ ] (P2) [api] Centralize backend selection/config rules so GraphRAG and agentic don’t drift.

### C. Logging, metrics, and observability

- [x] (P2) [obs] Ensure all optimizers accept an optional logger and use consistent log keys. — Done 2026-02-20: OntologyGenerator, OntologyMediator, OntologyCritic all accept optional logger param; use self._log
- [x] (P2) [obs] Add minimal metrics hooks for session durations, score deltas, and error counts. — Done 2026-02-20: BaseOptimizer.run_session() + BaseSession.score_delta/avg_score/regression_count

### D. Testing strategy (incremental, practical)

- [x] (P1) [tests] Add import/smoke tests for each optimizer package (`agentic`, `logic_theorem_optimizer`, `graphrag`).
  - Done 2026-02-20: added unit smoke import test coverage.
- [ ] (P2) [tests] Add deterministic unit tests for “pure” helpers (parsers, score aggregators, query plan generation).
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
- [ ] (P3) [graphrag] Implement “intelligent recommendation generation”.

### 5) `graphrag/ontology_critic.py`

- [x] (P2) [graphrag] Implement LLM backend integration (or explicitly disable it and remove placeholder code).
  - Done 2026-02-20: LLM backend clearly gated on ipfs_accelerate availability; comment updated; rule-based fallback confirmed
- [ ] (P3) [graphrag] Improve the dimension evaluators: completeness, consistency, clarity, granularity, domain-alignment.

### 6) CLI wrapper TODOs

- [x] (P2) [graphrag] Implement `cli_wrapper.py` “load ontology and optimize” (best-effort via `OntologySession`; JSON ontology inputs supported).
- [x] (P2) [graphrag] Implement `cli_wrapper.py` “load and validate ontology” (JSON ontology inputs supported).
- [x] (P2) [graphrag] Implement `cli_wrapper.py` “query optimization”.
  - Done 2026-02-20: `query` now returns a plan via `UnifiedGraphRAGQueryOptimizer` and supports `--explain`/`--output`.

---

## Logic theorem optimizer backlog

- [x] (P2) [logic] Implement `logic_theorem_optimizer/cli_wrapper.py` theorem proving entrypoint (even a minimal stub wired to an existing prover integration). — Done: full 567-line CLI with extract/prove/validate/optimize commands
- [ ] (P2) [tests] Add a minimal end-to-end “theorem session” smoke test.

---

## Agentic optimizers backlog (alignment & hardening)

- [ ] (P2) [agentic] Reconcile docs claiming phases/tests exist with what’s actually present (e.g., referenced test paths).  
  **DoD**: docs don’t mention non-existent files; or missing files are added.
- [ ] (P2) [agentic] Ensure `agentic/llm_integration.py` is exercised by at least one test at the repository’s current test entrypoints.

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
- [ ] (P2) [arch] Wire `OntologySession` / `MediatorState` to extend `BaseSession`
- [ ] (P2) [arch] Wire `OntologyHarness` to extend `BaseHarness`
- [ ] (P2) [arch] Wire `LogicHarness` to extend `BaseHarness`
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
- [ ] (P3) [graphrag] Add confidence decay for distance-based co-occurrence (entities far apart = lower confidence)

### F3 — GraphRAG: Smart ontology merging

- [x] (P2) [graphrag] `_merge_ontologies()` — naïve list extend; implement dedup by `id`, merge `properties` dicts, track `provenance`
  - Done 2026-02-20: dedup by id, merge properties, add provenance metadata
- [x] (P2) [graphrag] Handle entity type conflicts on merge (e.g., same ID but different types) — emit a warning and pick the higher-confidence one — Done: warning logged + type override in _merge_ontologies()
- [x] (P2) [graphrag] Handle relationship dedup (same source_id + target_id + type = merge properties) — Done: _merge_ontologies() deduplicates by (source_id, target_id, type)
- [ ] (P3) [graphrag] Add merge provenance report (which entities came from which source)

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
- [ ] (P3) [graphrag] Add LLM-based fallback evaluator that rates quality when rule-based scores are ambiguous
- [ ] (P3) [graphrag] Add per-entity type completeness breakdown in `CriticScore.metadata`

### F5 — GraphRAG: Ontology mediator refinements

- [x] (P2) [graphrag] `refine_ontology()` — no-op copy; implement specific refinement actions driven by recommendations
  - Done 2026-02-20: implemented add-property, normalize-names, prune-orphans, and merge-duplicates actions
- [x] (P2) [graphrag] `generate_prompt()` — structured prompts with domain vocabulary, schema instructions, and feedback-driven refinement hints
  - Done 2026-02-20
- [x] (P2) [graphrag] Add `refine_ontology()` action: `add_missing_relationships` (links orphan entities via co-occurrence) — Done: add_missing_relationships action in ontology_mediator.py
- [ ] (P3) [graphrag] Add refinement action: `split_entity` (detect entities with multiple unrelated roles)

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
- [ ] (P3) [perf] Add pytest-benchmark harness to `tests/performance/optimizers/`

---

## Documentation Debt

- [ ] (P2) [docs] `ARCHITECTURE_UNIFIED.md` — update to match current code (remove references to non-existent modules)
- [x] (P2) [docs] `README.md` — add quick-start examples for each optimizer type — Done batch 30: GraphRAG + Logic API/CLI examples added
- [x] (P2) [docs] Add module-level docstrings to agentic/coordinator.py and production_hardening.py — Already present
- [x] (P2) [docs] Document the `BaseCritic` / `BaseSession` / `BaseHarness` extension pattern with examples — Done batch 30: BaseCritic module docstring expanded with full extension pattern + existing implementations list
- [ ] (P3) [docs] Add Sphinx/MkDocs configuration and auto-generate API reference
- [ ] (P3) [docs] Write a "How to add a new optimizer" guide covering all integration points
- [ ] (P3) [docs] Add architecture ASCII diagram to each sub-package `__init__.py`

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
- [ ] (P2) [perf] Parallelize OntologyOptimizer.analyze_batch() across sessions using concurrent.futures
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
- [ ] (P2) [arch] Wire MediatorState to extend BaseSession for unified session tracking
- [x] (P2) [tests] Fuzz tests for _extract_rule_based() — Done batch 28 (9 edge-case tests: Unicode, binary, very long, regex special chars)
- [ ] (P3) [perf] Benchmark _merge_ontologies() on 1000-entity ontologies
- [x] (P2) [graphrag] Add confidence decay for co-occurrence distance — Done batch 28 (steeper decay >100 chars, floor 0.2)
- [x] (P2) [tests] Property-based test: _merge_ontologies is idempotent — Done batch 23 (5 idempotency tests)
- [ ] (P2) [graphrag] LLM-based extraction fallback when rule-based confidence is too low (< threshold)
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
- [ ] (P3) [graphrag] Add `entity_to_tdfol()` helper that converts a single entity to a Formula object
- [ ] (P3) [graphrag] Cache ontology TDFOL output keyed on ontology hash (avoid re-conversion)
- [ ] (P2) [agentic] Wire `ChangeController.create_change()` to actually create GitHub PR draft
- [x] (P2) [arch] Add `__init__` test for graphrag/__init__ public symbols — Done batch 32: test_public_import_smoke.py (38 tests)
- [ ] (P2) [docs] Update common/README.md to include ExtractionConfig.custom_rules usage example

## Newly discovered items (batch 31+)

- [ ] (P2) [graphrag] Add `ExtractionConfig.llm_fallback_threshold: float = 0.5` — trigger LLM extraction when rule-based confidence < threshold
- [ ] (P2) [graphrag] Implement `_extract_with_llm_fallback()` in OntologyGenerator that wraps `_extract_rule_based()` + fallback
- [ ] (P2) [tests] Unit tests for LLM fallback: low confidence triggers fallback, high confidence skips fallback, fallback disabled when `llm_backend=None`
- [ ] (P2) [graphrag] `OntologyLearningAdapter.apply_feedback()` — accept list of mediator `Action` objects and update confidence weights
- [ ] (P2) [graphrag] `OntologyLearningAdapter.get_extraction_hint()` — return adjusted threshold based on historical accuracy
- [ ] (P2) [tests] Unit tests for `OntologyLearningAdapter` feedback loop (3+ scenarios)
- [x] (P2) [arch] Add `__init__` test for logic_theorem_optimizer public symbols — Done batch 32: test_public_import_smoke.py
- [ ] (P2) [tests] Parametrize domain-specific rule tests with all 4 domains (legal, medical, financial, technical) — use `pytest.mark.parametrize`
- [x] (P2) [graphrag] Add `OntologyCritic.evaluate_batch()` — Done batch 32: returns scores/mean_overall/min_overall/max_overall/count
- [x] (P2) [tests] Unit tests for `OntologyCritic.evaluate_batch()` — Done batch 32: 14 tests in test_ontology_critic_evaluate_batch.py
- [ ] (P2) [graphrag] Add `relationship_count`, `entity_type_diversity` fields to `OntologyGenerationResult` for richer reporting
- [ ] (P2) [docs] Update `ARCHITECTURE_UNIFIED.md` to document Relationship.direction field and co-occurrence confidence decay formula
- [ ] (P3) [graphrag] Add `ExtractionConfig.max_entities: int = 500` cap to prevent runaway extraction on large documents
- [ ] (P3) [graphrag] Add `ExtractionConfig.min_entity_length: int = 2` to filter single-character entities
- [ ] (P3) [tests] Fuzz test `OntologyMediator.run_refinement_cycle()` with Hypothesis-generated random documents
- [ ] (P3) [agentic] Add `ChaosOptimizer.inject_cpu_spike()` method for realistic CPU load testing
- [ ] (P3) [arch] Add `optimizers.__version__` string populated from `ipfs_datasets_py.__version__`
- [ ] (P3) [tests] Test that `_safe_resolve()` raises/returns 1 on path traversal `../../etc/passwd`
- [ ] (P2) [docs] Add `common/README.md` section documenting `CriticResult` fields and usage patterns
- [ ] (P2) [graphrag] Emit a structured log line (JSON) after each `analyze_batch()` call for observability (INFO level, no secrets)
- [ ] (P2) [logic] Add `--domain` flag to `validate` command (default: 'general', options: legal/medical/financial/technical)
- [ ] (P2) [logic] Apply domain-specific validation rules in `cmd_validate()` when `--domain` is specified
- [ ] (P2) [tests] Unit tests for `validate --domain legal` and `validate --domain medical`
- [ ] (P3) [graphrag] Add `OntologyOptimizer.export_to_rdf()` stub: serialize ontology to Turtle format using rdflib (optional dep)
- [ ] (P3) [graphrag] Add `OntologyOptimizer.export_to_graphml()` stub: serialize ontology to GraphML for visualization
