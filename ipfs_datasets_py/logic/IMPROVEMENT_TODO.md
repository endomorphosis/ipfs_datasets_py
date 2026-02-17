# Logic Module — Comprehensive Improvement TODO (Living List)

This is a **living** refactor & improvement backlog for `ipfs_datasets_py.logic/`.

Guiding principles:
- Prefer **behavior-preserving** refactors first (rename/move behind shims, typed wrappers, clearer APIs).
- Preserve **import stability** (`ipfs_datasets_py.logic.*`) and avoid breaking downstream projects.
- Add/expand tests **before** changing semantics.
- Keep changes **incremental**: small PR-sized slices, each with tests.

Legend:
- **P0**: correctness, security, broken UX / API footguns
- **P1**: maintainability, performance, DX
- **P2**: nice-to-have, cleanup

Operating principle for this list:
- This backlog is intentionally **open-ended**. Sections labeled **Ongoing** are never “done”; they define continuous quality loops.

---

## Always-On Acceptance Criteria (Definition of “No Gaps”)

Treat the logic module as “gapless” only when ALL of the following hold:

- **Import Surface**: every documented public import path exists and is stable (or has a compatibility shim with deprecation warning).
- **API Contracts**: all public entry points have deterministic input validation, deterministic error types, and consistent result objects.
- **Optional Deps**: optional integrations degrade gracefully (no import-time crashes).
- **Determinism**: core reasoning paths are deterministic under a fixed seed and do not require network.
- **Test Gating**: any test requiring LLM/network/heavy deps is gated by marker or auto-gating.
- **Doc Truthfulness**: docs match reality (no dead links, no stale claims).
- **Performance Baseline**: micro-benchmarks exist for the top hot paths and are stable within tolerance.

---

## P0 — Correctness & Safety

- [ ] Ensure all public converters/provers validate inputs consistently (raise typed exceptions from `logic/common/errors.py`).
- [ ] Audit `__getattr__` deprecation shim behavior and ensure warnings are filtered in tests where appropriate.
- [ ] Make external prover integration robust to missing binaries (Z3/cvc5/Lean/Coq): deterministic “unavailable” result, not crash.
- [ ] Harden any file/network operations in caching (IPFS/IPLD) with explicit timeouts and input validation.
- [ ] Verify thread-safety of caches (RLock usage, mutable default args, shared global caches).
- [ ] Confirm “proof cache shims” are single-source-of-truth and cannot diverge.

### P0 — Import-Time Side Effects

- [ ] Remove or quarantine any import-time mutations (global cache init, environment autoconfigure) from public modules; move to explicit `init_*()` entry points.
- [ ] Ensure all optional-dependency imports are guarded and never raise at import time for the core module.

## P0 — API Stability & Imports

- [ ] Define and document the **canonical public surface** (what’s supported vs internal):
  - `logic/fol`, `logic/deontic`, `logic/integration`, `logic/types`, `logic/common`.
- [ ] Add a top-level `logic/api.py` (or similar) exporting a stable subset (thin re-exports only).
- [ ] Keep `logic.tools` deprecation path working until v2.0 removal (per docs); add tests for the shim.

### P0 — Canonical “Core” Package Layout

- [ ] Define what “core” means inside `logic/` and enforce it:
  - `logic/common/` + `logic/types/` are dependency-free primitives.
  - `logic/TDFOL/` + `logic/CEC/` are core reasoning engines.
  - `logic/integration/` is orchestration, not foundational types.
- [ ] Introduce a thin `logic/core/` namespace ONLY if it reduces coupling (avoid churn otherwise).

---

## P0 — Gap Closure Audit (Per Subpackage)

Use this checklist as a systematic audit.

### `logic/common/`
- [ ] Single error hierarchy is used everywhere.
- [ ] Cache utils have timeouts, TTL/LRU tests, and concurrency tests.
- [ ] No module imports heavy optional deps at import time.

### `logic/types/`
- [ ] No runtime imports of heavy dependencies (only `TYPE_CHECKING`).
- [ ] Public protocols/types are documented in `types/README.md`.

### `logic/TDFOL/`
- [ ] Parser rejects invalid syntax deterministically.
- [ ] Inference rules have deterministic application strategy.
- [ ] Proof result object is consistent with integration-level proof results.

### `logic/CEC/`
- [ ] beartype usage is consistent and does not hide runtime exceptions.
- [ ] Modal prover APIs have a stable wrapper surface.

### `logic/fol/`
- [ ] Converter output schema is versioned.
- [ ] Batch conversion is bounded (worker pool + timeouts).

### `logic/deontic/`
- [ ] Domain knowledge extraction has deterministic fallback path when NLP stack missing.
- [ ] Conflict detection rules are covered by non-LLM unit tests.

### `logic/external_provers/`
- [ ] Each external prover integration has:
  - availability probe
  - deterministic “unavailable” result
  - timeout enforcement
  - unit tests that do not require installing the prover

### `logic/integration/`
- [ ] Bridges are pure translations (no IO, no caching).
- [ ] Caching is isolated to `integration/caching/*`.
- [ ] Reasoning orchestration has a stable `Reasoner`/`Prover` API.
- [ ] Backwards-compat shims exist for legacy import paths.

### `logic/security/`
- [ ] Input validation and sandboxing requirements are documented.
- [ ] Proof artifacts/caches have safe path handling and size limits.

### `logic/zkp/`
- [ ] ZKP APIs are stable and documented.
- [ ] Verification is deterministic and has golden tests.

---

## P1 — Architecture / Boundaries

- [ ] Split “integration” responsibilities clearly:
  - bridges (translation), reasoning (coordination), caching (storage), domain (knowledge).
- [ ] Enforce dependency direction:
  - `common`/`types` should not import higher layers.
  - `integration` may import `fol`/`deontic`/`TDFOL`/`CEC`, not vice versa.
- [ ] Replace any ad-hoc cross-module imports with `types/` or `common/` interfaces.

### P1 — Internal Layering Map

- [ ] Create and maintain a dependency graph (static import graph) for `logic/` and enforce layering.
- [ ] Establish “internal” modules (prefixed `_`) vs public modules; update `__all__` accordingly.

## P1 — Error Model

- [ ] Standardize exceptions:
  - parsing errors, conversion errors, prover errors, timeout errors.
- [ ] Ensure all high-level APIs return a consistent result object (status + payload + diagnostics).
- [ ] Add “diagnostics payload” standard fields: `method`, `confidence`, `from_cache`, `timings`, `warnings`.

### P1 — Result Objects

- [ ] Standardize all converter results to a single `ConversionResult[T]` style generic.
- [ ] Standardize all prover results to a single `ProofResult` schema.
- [ ] Add a `to_json()` method for result objects (no external deps).

## P1 — Caching & Performance

- [ ] Document cache key strategy (hash vs CID) and collision expectations.
- [ ] Add tests for TTL eviction, LRU eviction, and concurrent access.
- [ ] Ensure batch processing APIs use bounded worker pools and respect timeouts.
- [ ] Add a micro-benchmark harness (already present) that can be run deterministically in CI.

### P1 — Memory + OOM Avoidance

- [ ] Ensure batch processing uses explicit memory limits / backpressure.
- [ ] Remove unbounded caches or add max-size defaults.
- [ ] Ensure “heavy tests” gating prevents accidental large model downloads.

## P1 — Typing / Mypy

- [ ] Keep “runtime-light” imports in `types/common_types.py` (TYPE_CHECKING only) to avoid heavyweight dependencies at import time.
- [ ] Add missing return annotations where trivial.
- [ ] Ensure Protocol forward refs resolve cleanly for static type checking.
- [ ] Consider a CI job running `mypy ipfs_datasets_py/logic --config-file ipfs_datasets_py/logic/mypy.ini`.

### P1 — Type Audit (Continuous)

- [ ] Track mypy errors as a budget (must not regress).
- [ ] Add stub packages to extras (`types-PyYAML`, etc.) to reduce noise.

---

## P1 — Testing Strategy (Make Refactors Safe)

- [ ] Add a **public API contract** test suite:
  - import paths, deprecation shim behavior, stable “happy path” conversions.
- [ ] Add **golden tests** for:
  - simple FOL conversions,
  - simple deontic conversions,
  - a small theorem proof (modus ponens),
  - one bridge translation.
- [ ] Add **skip markers** for tests requiring external binaries (z3/cvc5/lean/coq).
- [ ] Add a minimal “smoke suite” runnable fast (<30s) for local development.

### P1 — LLM / Network / Heavy Test Gating (Audit)

- [ ] Ensure any test that:
  - calls an LLM provider,
  - downloads models,
  - hits the network,
  - spawns browsers/playwright,
  - or runs GPU paths
  is gated by marker (`llm`, `network`, `heavy`) OR is auto-gated in conftest.
- [ ] Provide a single documented way to opt-in:
  - `--run-llm`, `--run-network`, `--run-heavy`
  - or env vars `RUN_LLM_TESTS=1`, `RUN_NETWORK_TESTS=1`, `RUN_HEAVY_TESTS=1`

---

## P2 — Documentation & DX

- [ ] Consolidate overlapping docs:
  - ensure `DOCUMENTATION_INDEX.md` points to the canonical entry points.
- [ ] Add “How to extend” docs for:
  - new inference rules,
  - new external prover bridge,
  - new domain module.
- [ ] Add example notebooks/scripts that do not require network access.

### P2 — Developer Workflow

- [ ] Add a “fast dev loop” command set:
  - lint/types/smoke
  - deterministic unit subset
  - benchmark subset

## P2 — Cleanup

- [ ] Remove or quarantine unused benchmarks/scripts (keep reproducible ones).
- [ ] Normalize naming:
  - `integrations/` vs `integration/` usage.
- [ ] Reduce duplicated caches/utilities by routing through `common/`.

---

## Ongoing (Never Finishes)

- [ ] Each refactor slice must:
  - preserve imports or add shims
  - add/adjust tests
  - update docs
  - update benchmarks if hot path changes
- [ ] Monthly audit:
  - dependency graph check
  - public API import check
  - stale docs pruning
- [ ] Quarterly audit:
  - performance regressions
  - cache correctness (TTL/LRU + concurrency)
  - prover availability matrix

---

## Suggested Execution Order (Infinite Backlog → Iterative Milestones)

Milestone A (safe refactor foundation)
- [ ] Add/expand API contract tests
- [ ] Type-hint polish for shared types
- [ ] Fix low-risk import/deprecation shims tests

Milestone B (cache + batch hardening)
- [ ] Concurrency tests
- [ ] TTL/LRU behavior tests
- [ ] Timeouts and error normalization

Milestone C (integration robustness)
- [ ] External prover “unavailable” handling
- [ ] Deterministic integration tests and skips

Milestone D (semantic improvements)
- [ ] Only after A–C are stable and covered

Milestone E (ongoing hardening)
- [ ] Repeat A–D for any new feature/module

---

## Concrete Refactor Slices (1–3 Day Chunks)

These slices are designed to be executed incrementally without destabilizing downstream imports.
Each slice must ship with (a) import stability or shims, (b) minimal targeted tests (gated if heavy), and (c) doc updates.

### Slice 01 — Define the public surface explicitly
- [ ] Create `logic/api.py` as the only “blessed” import surface for external users (thin re-exports only).
- [ ] Update `logic/__init__.py` `__all__` to align with the blessed API.
- [ ] Add a fast “API contract” test file that imports everything in `logic/api.py`.

Acceptance criteria:
- [ ] `from ipfs_datasets_py.logic.api import *` succeeds without optional deps.
- [ ] No import-time side effects in `logic/api.py`.

### Slice 02 — Ban import-time side effects (core)
- [ ] Identify and quarantine import-time mutations in public modules.
- [ ] Introduce `logic/common/runtime.py` with explicit `init_runtime()` hooks (if needed).

Acceptance criteria:
- [ ] Importing `ipfs_datasets_py.logic` does not alter environment, spawn threads, or touch network/disk.

### Slice 03 — Error model unification
- [ ] Ensure converters/provers raise or wrap into `logic/common/errors.py` exceptions.
- [ ] Add a single top-level helper: `logic/common/errors.normalize_exception(e)`.

Acceptance criteria:
- [ ] All public APIs raise a bounded set of exception types.

### Slice 04 — Result object unification
- [ ] Standardize `ConversionResult` and `ProofResult` fields across modules.
- [ ] Add `to_json()` and `from_json()` (no extra deps) for both.

Acceptance criteria:
- [ ] All high-level APIs return results with `timings`, `warnings`, `from_cache` where applicable.

### Slice 05 — `common/` caching correctness baseline
- [ ] Add TTL/LRU/concurrency tests that are deterministic and low-memory.
- [ ] Enforce bounded cache sizes and safe defaults.

Acceptance criteria:
- [ ] No unbounded caches in the default path.

### Slice 06 — `types/` audit and import-light enforcement
- [ ] Ensure `types/common_types.py` only imports heavy deps under `TYPE_CHECKING`.
- [ ] Create a `types/public.py` to gather stable types/protocols.

Acceptance criteria:
- [ ] `python -c "import ipfs_datasets_py.logic.types"` succeeds without optional deps.

### Slice 07 — `TDFOL/` determinism and parser strictness
- [ ] Add golden parse tests for 10 canonical formulas.
- [ ] Add negative tests for invalid syntax.
- [ ] Ensure inference rule application order is deterministic (document strategy).

Acceptance criteria:
- [ ] Same inputs produce same proof trace under fixed seed.

### Slice 08 — `CEC/` wrapper stabilization
- [ ] Provide stable wrapper API around CEC provers for integration use.
- [ ] Ensure beartype exceptions are normalized.

Acceptance criteria:
- [ ] CEC can be used via wrapper without importing interactive/symai paths.

### Slice 09 — `external_provers/` availability matrix
- [ ] Add `availability.py` that probes Z3/cvc5/Lean/Coq and returns structured status.
- [ ] Add timeouts and deterministic “unavailable” result objects.

Acceptance criteria:
- [ ] No crashes when binaries are missing; results are explainable.

### Slice 10 — `fol/` converter contract
- [ ] Version converter output schema and document it.
- [ ] Ensure batch conversion uses bounded workers + timeouts.

Acceptance criteria:
- [ ] `convert_batch()` cannot exceed configured worker/memory defaults.

### Slice 11 — `deontic/` converter and domain fallback
- [ ] Ensure NLP stack is optional; provide regex fallback behavior.
- [ ] Add non-LLM unit tests for core deontic extraction.

Acceptance criteria:
- [ ] Deontic converter yields deterministic output without spaCy/symai.

### Slice 12 — `integration/` layering separation
- [ ] Move all translation-only code under `integration/bridges/` and keep it pure.
- [ ] Move caching-only code under `integration/caching/`.
- [ ] Move orchestration to `integration/reasoning/` and ensure it depends “down” only.

Acceptance criteria:
- [ ] No bridge module imports cache/storage or does IO.

### Slice 13 — Compatibility shims policy
- [ ] Create `logic/_compat/` and route all deprecated import paths through it.
- [ ] Add tests verifying warnings and import behavior.

Acceptance criteria:
- [ ] Downstream legacy imports keep working with deprecation warnings.

### Slice 14 — Documentation truth audit
- [ ] Run a doc-link audit (internal links) for `logic/*.md`.
- [ ] Remove/flag claims that are not test-backed.

Acceptance criteria:
- [ ] `DOCUMENTATION_INDEX.md` only points to existing paths.

### Slice 15 — Benchmarks that don’t OOM
- [ ] Ensure benchmark harnesses are bounded and can run on CPU-only.
- [ ] Add `--quick` mode for microbench.

Acceptance criteria:
- [ ] Quick benchmarks run in <30s without large downloads.

### Slice 16 — Test gating audit (LLM/network/heavy)
- [ ] Sweep all `ipfs_datasets_py/tests/**` for LLM/network/heavy usage.
- [ ] Add markers (preferred) or rely on auto-gating (fallback).
- [ ] Document the opt-in flags/env vars.

Acceptance criteria:
- [ ] Default `pytest` run does not download models or hit network.

---

## Stable Entrypoints to Protect (Do Not Break)

These are the “core business logic” entrypoints that must remain stable while refactoring:

- [ ] `ipfs_datasets_py.logic.integration` exports: `NeurosymbolicReasoner` and basic bridge/prover factory helpers.
- [ ] `ipfs_datasets_py.logic.fol` exports: `FOLConverter` (or equivalent) and `ConversionResult`.
- [ ] `ipfs_datasets_py.logic.deontic` exports: `DeonticConverter` (or equivalent) and `ConversionResult`.
- [ ] `ipfs_datasets_py.logic.common` exports: cache + error primitives.
- [ ] `ipfs_datasets_py.logic.types` exports: public protocols/types only.

For each entrypoint:
- [ ] Define a minimal contract (inputs/outputs/errors).
- [ ] Provide a single golden test.
- [ ] Provide a short doc snippet.

---

## Public API Inventory (Current Reality)

This section captures the **actual current exports** from key `logic/*` packages.
Refactors must preserve these paths or provide shims + deprecation warnings.

### `ipfs_datasets_py.logic.fol`

Exports (per `logic/fol/__init__.py`):
- [ ] `FOLConverter` (preferred)
- [ ] `convert_text_to_fol` (legacy)

### `ipfs_datasets_py.logic.deontic`

Exports (per `logic/deontic/__init__.py`):
- [ ] `DeonticConverter`
- [ ] `convert_legal_text_to_deontic`

### `ipfs_datasets_py.logic.common`

Exports (per `logic/common/__init__.py`):
- [ ] Errors: `LogicError`, `ConversionError`, `ValidationError`, `ProofError`, `TranslationError`, `BridgeError`, `ConfigurationError`, `DeonticError`, `ModalError`, `TemporalError`
- [ ] Converter base/types: `LogicConverter`, `ChainedConverter`, `ConversionResult`, `ConversionStatus`, `ValidationResult`
- [ ] Monitoring: `UtilityMonitor`, `track_performance`, `with_caching`, `get_global_stats`, `clear_global_cache`, `reset_global_stats`
- [ ] Caching: `BoundedCache`, `ProofCache`, `CachedProofResult`, `get_global_cache`

Risk notes:
- [ ] `ConversionResult` and `ConversionStatus` are also defined in other namespaces; unify semantics without breaking this export.

### `ipfs_datasets_py.logic.types`

Exports (per `logic/types/__init__.py`):
- [ ] Deontic: `DeonticOperator`, `DeonticFormula`, `DeonticRuleSet`, `LegalAgent`, `LegalContext`, `TemporalCondition`, `TemporalOperator`
- [ ] Proof: `ProofStatus`, `ProofResult`, `ProofStep`
- [ ] Translation: `LogicTranslationTarget`, `TranslationResult`, `AbstractLogicFormula`
- [ ] TDFOL compat helpers: `Formula`, `Predicate`, `Variable`, `Constant`, `And`, `Or`, `Not`, `Implies`, `Forall`, `Exists`
- [ ] Common types: `LogicOperator`, `Quantifier`, `FormulaType`, `ConfidenceScore`, `ComplexityScore`, `ComplexityMetrics`, `Prover`, `Converter`
- [ ] Bridge types: `BridgeCapability`, `ConversionStatus`, `BridgeMetadata`, `ConversionResult`, `BridgeConfig`, `ProverRecommendation`
- [ ] FOL types: `FOLOutputFormat`, `PredicateCategory`, `FOLFormula`, `FOLConversionResult`, `PredicateExtraction`

Risk notes:
- [ ] There is name overlap (`Formula`, `Predicate`, `ConversionResult`, `ConversionStatus`). Decide canonical sources and keep aliases stable.

### `ipfs_datasets_py.logic.integration`

Current behavior:
- [ ] This module exports a **large surface** (bridges, caching, domain, reasoning, symbolic, interactive), and it currently performs optional-dependency imports.

Integration subsystems with clear `__all__`:
- [ ] `logic.integration.bridges`: `BaseProverBridge`, `SymbolicFOLBridge`, `TDFOLCECBridge`, `TDFOLGrammarBridge`, `TDFOLShadowProverBridge`
- [ ] `logic.integration.caching`: `ProofCache`, `get_global_cache`, `IPFSProofCache`, `get_global_ipfs_cache`, `LogicIPLDStorage`
- [ ] `logic.integration.reasoning`: `ProofExecutionEngine`, `DeontologicalReasoningEngine`, `LogicVerifier`
- [ ] `logic.integration.symbolic`: `LogicPrimitives`, `NeurosymbolicAPI`, `NeurosymbolicGraphRAG`
- [ ] `logic.integration.symbolic.neurosymbolic`: `NeuralSymbolicCoordinator`, `EmbeddingEnhancedProver`, `HybridConfidenceScorer`

High-risk import-time side effect to eliminate:
- [ ] `autoconfigure_engine_env()` is called at import time in `logic.integration.__init__`.

Compatibility shims observed:
- [ ] `logic.integration.symbolic_fol_bridge` re-exports from `logic.integration.bridges.symbolic_fol_bridge`.

---

## Inventory Follow-Ups (Turn Inventory into Contracts)

- [ ] For each exported symbol above, define:
  - minimal docstring contract
  - stable signature (or stable adapter)
  - 1 golden test (non-LLM, non-network)
- [ ] For high-risk namespaces (`logic.integration`), carve out a small stable API and move the rest behind explicit submodules.
