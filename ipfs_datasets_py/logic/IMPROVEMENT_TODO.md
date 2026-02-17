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
