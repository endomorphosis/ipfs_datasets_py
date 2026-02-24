# Optimizers: Infinite TODO / Improvement Plan

_Last updated: 2026-02-24_

This is the living backlog for `ipfs_datasets_py/optimizers`.
It is intentionally infinite: finish work, add new work, repeat.

## Mission
- Keep optimizer behavior correct and stable.
- Keep APIs typed and consistent across GraphRAG, logic, and agentic.
- Improve performance and observability without regressions.
- Always run one strategic item and one random item in parallel.

## Working Model (Infinite)
- Every cycle has two lanes:
  - `Strategic lane`: one P0/P1/P2 item aligned to roadmap.
  - `Random lane`: one P2/P3 item from a different track.
- WIP limits:
  - Max 1 in-progress item per lane.
  - Max 5 active random picks total.
- Completion rule:
  - Change `[ ]` to `[x]`.
  - Add one `Done YYYY-MM-DD` note with tests/docs touched.
  - Immediately pull a new random pick from a different track.

## Priorities
- `P0`: correctness/security/data-loss blockers.
- `P1`: architecture/API debt that slows all work.
- `P2`: quality/perf/observability improvements.
- `P3`: useful enhancements and tooling polish.

## Tracks
- `[arch]` architecture and modularization
- `[api]` public API and typing contracts
- `[graphrag]` ontology/query pipeline
- `[logic]` theorem/prover pipeline
- `[agentic]` autonomous optimizer workflow
- `[tests]` test quality and coverage
- `[perf]` profiling, caching, scale behavior
- `[obs]` logging, metrics, tracing
- `[docs]` docs and onboarding
- `[security]` safety hardening

## Current Strategic Queue

### P1/P2 Must-Do
- [ ] (P1) [arch] Split `graphrag/query_optimizer.py` into focused modules (`query_planner.py`, `traversal_heuristics.py`, `learning_adapter.py`, `serialization.py`) with behavior parity tests.
- [ ] (P1) [api] Add package typing marker (`py.typed`) and run strict type audit for optimizer public surface.
- [ ] (P2) [arch] Replace remaining broad `except Exception` catch-alls with typed exceptions in optimizer core paths.
- [ ] (P2) [agentic] Audit `agentic/` for `**kwargs`-heavy APIs and replace with typed optional parameters.
- [ ] (P2) [tests] Finish fixture-factory migration for ontology mocks in shared `conftest.py` and remove duplicate builders.

## Random Rotation Queue (Keep 5 Active)

Active random picks (different tracks):
- [x] (P2) [perf] Profile `OntologyCritic._evaluate_consistency()` on large ontologies (>500 entities) and document bottlenecks + top fix.
  - Done 2026-02-24: replaced recursive cycle detection with iterative Kahn-based detection, removed duplicate cycle pass, added deep-chain regression tests (`test_batch_270_consistency_cycle_scaling.py`), and documented results in `docs/optimizers/PERFORMANCE_TUNING_GUIDE.md`.
- [ ] (P2) [obs] Add OpenTelemetry span hooks behind `OTEL_ENABLED` feature flag for pipeline/session boundaries.
- [x] (P2) [docs] Write "How to add a new optimizer" guide covering config, base classes, tests, docs, and CLI wiring.
  - Done 2026-02-24: added `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` and linked it from `DOCUMENTATION_INDEX.md` and `docs/optimizers/INTEGRATION_EXAMPLES.md`.
- [ ] (P3) [logic] Add `--tdfol-output` flag in GraphRAG/logic CLI path to persist generated formulas for debugging.
- [ ] (P3) [security] Design sandboxed subprocess policy for untrusted prover calls (timeout, resource caps, allowlist).
- [x] (P2) [tests] Add serialization round-trip tests for refinement session state snapshots.
  - Done 2026-02-24: added `test_batch_271_mediator_state_serialization.py` covering `MediatorState.to_dict()/from_dict()` round-trip and minimal payload restoration.
- [x] (P2) [graphrag] Add confidence histogram/report helper for extraction results.
  - Done 2026-02-24: verified helper methods and added regression coverage in `test_batch_272_confidence_histogram_helpers.py` for both `EntityExtractionResult.confidence_histogram()` and `OntologyGenerator.confidence_histogram()`.
- [ ] (P2) [perf] Benchmark sentence-window impact on extraction quality vs runtime.
- [x] (P2) [api] Add package-level `py.typed` marker and basic mypy smoke check for optimizer public imports.
  - Done 2026-02-24: added `ipfs_datasets_py/py.typed`, packaged it via `pyproject.toml`, added `optimizers/tests/typecheck/mypy_public_imports_smoke.py`, and verified with `mypy --follow-imports=skip`.
- [ ] (P2) [arch] Replace remaining broad `except Exception` catch-alls with typed exceptions in optimizer core paths.

Rotation rules:
- When one item completes, add a new `[ ]` pick from a track not already active.
- Avoid replacing with the same track twice in a row.
- Keep at least one random item from `[tests]`, `[perf]`, or `[obs]` at all times.

## Comprehensive Improvement Roadmap

### 1) Architecture Refactor
- [ ] (P1) [arch] Complete query optimizer file split and remove duplicated logic paths.
- [ ] (P2) [arch] Enforce single source of truth for shared optimizer abstractions in `optimizers/common/`.
- [ ] (P2) [arch] Remove circular dependencies by pushing shared types/helpers into common modules.
- [ ] (P3) [arch] Add lifecycle event bus hooks (`on_round_start/end`, `on_score_change`) without coupling core logic.

### 2) API and Type Safety
- [ ] (P1) [api] Finalize typed return contracts for all optimizer entrypoints (no ambiguous raw dicts for public methods).
- [ ] (P2) [api] Version optimizer API surface and document compatibility policy in `CHANGELOG.md`.
- [ ] (P2) [api] Standardize context/config dataclasses across GraphRAG/logic/agentic constructors.
- [ ] (P3) [api] Improve class `__repr__` output for debugging-heavy objects (`CriticScore`, session state, pipeline runs).

### 3) GraphRAG Quality
- [ ] (P2) [graphrag] Add semantic-similarity entity deduplication path behind feature flag and benchmark quality impact.
- [ ] (P2) [graphrag] Add multilingual extraction support with language detection and test corpora.
- [x] (P2) [graphrag] Implement LLM-based relationship inference fallback and compare against heuristics.
  - Done 2026-02-24: low-confidence heuristic relationship types can be LLM-refined via backend JSON response; heuristics are retained on errors or lower-confidence LLM output.
- [ ] (P3) [graphrag] Add ambiguity resolver for low-confidence critic outputs (rule+LLM assist mode).

### 4) Testing Strategy
- [ ] (P1) [tests] Add parity tests before/after query optimizer split to prevent silent behavior drift.
- [ ] (P2) [tests] Expand property-based testing for ontology stats and config invariants.
- [x] (P2) [tests] Add regression corpus for mixed-domain extraction with frozen expected invariants.
  - Done 2026-02-24: added frozen corpus fixture + invariant test in `tests/fixtures/graphrag/mixed_domain_corpus_invariants.json` and `tests/unit/graphrag/test_mixed_domain_regression_corpus.py`.
- [ ] (P3) [tests] Run mutation testing against critic dimensions and close surviving mutants with targeted tests.

### 5) Performance and Scale
- [ ] (P2) [perf] Benchmark 10k-token+ extraction path and capture baseline in versioned perf snapshot.
- [ ] (P2) [perf] Profile query optimizer under load prior to split and track delta after split.
- [ ] (P3) [perf] Add cache strategy for expensive logic validation/prover round-trips keyed by formula hash.
- [ ] (P3) [perf] Parallelize safe batch paths where deterministic ordering can be preserved.

### 6) Observability and Operations
- [ ] (P2) [obs] Standardize structured JSON log schema across all optimizer pipelines.
- [x] (P2) [obs] Ensure metrics include run duration, score deltas, failure counts, and stage timings.
  - Done 2026-02-24: added `optimizer_score_delta` metric, wired duration/score-delta/validation-failure recording in `BaseOptimizer`, and stage timing histogram in pipeline metrics.
- [ ] (P3) [obs] Add tracing spans for cross-optimizer workflows with low overhead defaults.
- [ ] (P3) [obs] Add troubleshooting dashboard examples for performance and quality drift.

### 7) Documentation and Developer Experience
- [ ] (P2) [docs] Keep docs/code drift audit as a recurring task each cycle.
- [x] (P2) [docs] Add architecture diagram for generate -> critique -> optimize -> validate loop.
  - Done 2026-02-24: added `docs/OPTIMIZATION_LOOP_ARCHITECTURE.md` and linked it from `optimizers/README.md`.
- [ ] (P3) [docs] Add docs build configuration (Sphinx or MkDocs) with auto-generated API pages.
- [ ] (P3) [docs] Maintain one-page quick references for GraphRAG, logic, and agentic workflows.

### 8) Security and Reliability
- [ ] (P1) [security] Ensure all CLI file inputs are resolved/validated against traversal and unsafe paths.
- [ ] (P2) [security] Add strict timeout + retry + circuit-breaker policy for all external backend calls.
- [ ] (P2) [security] Add redaction checks in logs for credentials/tokens across optimizer modules.
- [ ] (P3) [security] Add hardened execution mode for prover subprocess calls.

## Candidate Pool for Future Random Picks

Pull from this pool when replacing completed random items.

- [ ] (P2) [tests] Add serialization round-trip tests for refinement session state snapshots.
- [x] (P2) [tests] Add fuzz tests for `OntologyMediator.run_refinement_cycle()` with random recommendation strings.
  - Done 2026-02-24: added Hypothesis fuzz coverage in `tests/unit/graphrag/test_ontology_mediator_fuzz_recommendations.py`.
- [ ] (P2) [perf] Benchmark sentence-window impact on extraction quality vs runtime.
- [ ] (P2) [perf] Benchmark `LogicValidator.validate_ontology()` on 100-entity synthetic ontologies.
- [ ] (P2) [graphrag] Add confidence histogram/report helper for extraction results.
- [ ] (P2) [graphrag] Add score summary helper for critic batch output.
- [ ] (P3) [docs] Add per-method doctest examples for public GraphRAG methods.
- [ ] (P3) [logic] Add REPL mode for theorem optimizer CLI.
- [ ] (P3) [agentic] Add chaos test hooks for CPU/memory pressure simulation.
- [ ] (P3) [obs] Add alerting examples for run-score regression and error-rate spikes.

## Execution Cadence
- Start of cycle:
  - Confirm 1 strategic + 1 random item in progress.
  - Verify active random picks are from different tracks.
- During cycle:
  - Deliver in small batches with tests.
  - Update this file immediately after each merged change.
- End of cycle:
  - Add completion notes for finished items.
  - Refill random queue back to 5 active picks.

## Batch Template (Use for every completed item)

```md
- [x] (P2) [track] Item title
  - Done 2026-02-24: <what changed>; tests: <files or counts>; docs: <files>.
```

## Definition of Done
- Code implemented and lint/type checks pass for touched files.
- Relevant unit/integration tests added or updated.
- Public behavior and migration notes documented when API changes.
- TODO entry updated (`[ ]` -> `[x]`) with concrete completion note.
