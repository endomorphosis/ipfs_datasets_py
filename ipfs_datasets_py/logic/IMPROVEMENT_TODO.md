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

---

## P0 — Correctness & Safety

- [ ] Ensure all public converters/provers validate inputs consistently (raise typed exceptions from `logic/common/errors.py`).
- [ ] Audit `__getattr__` deprecation shim behavior and ensure warnings are filtered in tests where appropriate.
- [ ] Make external prover integration robust to missing binaries (Z3/cvc5/Lean/Coq): deterministic “unavailable” result, not crash.
- [ ] Harden any file/network operations in caching (IPFS/IPLD) with explicit timeouts and input validation.
- [ ] Verify thread-safety of caches (RLock usage, mutable default args, shared global caches).
- [ ] Confirm “proof cache shims” are single-source-of-truth and cannot diverge.

## P0 — API Stability & Imports

- [ ] Define and document the **canonical public surface** (what’s supported vs internal):
  - `logic/fol`, `logic/deontic`, `logic/integration`, `logic/types`, `logic/common`.
- [ ] Add a top-level `logic/api.py` (or similar) exporting a stable subset (thin re-exports only).
- [ ] Keep `logic.tools` deprecation path working until v2.0 removal (per docs); add tests for the shim.

---

## P1 — Architecture / Boundaries

- [ ] Split “integration” responsibilities clearly:
  - bridges (translation), reasoning (coordination), caching (storage), domain (knowledge).
- [ ] Enforce dependency direction:
  - `common`/`types` should not import higher layers.
  - `integration` may import `fol`/`deontic`/`TDFOL`/`CEC`, not vice versa.
- [ ] Replace any ad-hoc cross-module imports with `types/` or `common/` interfaces.

## P1 — Error Model

- [ ] Standardize exceptions:
  - parsing errors, conversion errors, prover errors, timeout errors.
- [ ] Ensure all high-level APIs return a consistent result object (status + payload + diagnostics).
- [ ] Add “diagnostics payload” standard fields: `method`, `confidence`, `from_cache`, `timings`, `warnings`.

## P1 — Caching & Performance

- [ ] Document cache key strategy (hash vs CID) and collision expectations.
- [ ] Add tests for TTL eviction, LRU eviction, and concurrent access.
- [ ] Ensure batch processing APIs use bounded worker pools and respect timeouts.
- [ ] Add a micro-benchmark harness (already present) that can be run deterministically in CI.

## P1 — Typing / Mypy

- [ ] Keep “runtime-light” imports in `types/common_types.py` (TYPE_CHECKING only) to avoid heavyweight dependencies at import time.
- [ ] Add missing return annotations where trivial.
- [ ] Ensure Protocol forward refs resolve cleanly for static type checking.
- [ ] Consider a CI job running `mypy ipfs_datasets_py/logic --config-file ipfs_datasets_py/logic/mypy.ini`.

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

---

## P2 — Documentation & DX

- [ ] Consolidate overlapping docs:
  - ensure `DOCUMENTATION_INDEX.md` points to the canonical entry points.
- [ ] Add “How to extend” docs for:
  - new inference rules,
  - new external prover bridge,
  - new domain module.
- [ ] Add example notebooks/scripts that do not require network access.

## P2 — Cleanup

- [ ] Remove or quarantine unused benchmarks/scripts (keep reproducible ones).
- [ ] Normalize naming:
  - `integrations/` vs `integration/` usage.
- [ ] Reduce duplicated caches/utilities by routing through `common/`.

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
