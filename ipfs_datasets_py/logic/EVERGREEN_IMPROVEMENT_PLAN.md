# Logic Module — Evergreen Refactor & Improvement Plan (Infinite TODO List)

**Module:** `ipfs_datasets_py.logic`  
**Last updated:** 2026-02-17  
**Purpose:** A single, durable improvement plan + never-ending backlog that is safe to execute incrementally without breaking downstream imports.

This document is intentionally **never “done”**. It defines continuous loops (import hygiene, API stability, correctness, performance, and docs truth) and a queue of small refactor slices.

## How to Use This Plan

- If you’re planning work: start with **Top Priorities (P0/P1)** and pick the next **1–3 day slice**.
- If you’re refactoring code: obey **Guardrails** and ensure **Acceptance Criteria** per slice.
- If you’re debugging import/test issues: go to **Import & Optional Deps** and **Testing Strategy**.

## Canonical Sources (Don’t Duplicate)

This plan is an index + prioritization layer over existing detail documents:

- `IMPROVEMENT_TODO.md` — long-form backlog and acceptance criteria
- `COMPREHENSIVE_REFACTORING_PLAN.md` — narrative refactor program and doc consolidation strategy
- `PROJECT_STATUS.md` — current status snapshot (may need periodic verification)
- `ARCHITECTURE.md`, `FEATURES.md`, `KNOWN_LIMITATIONS.md`, `MIGRATION_GUIDE.md`

## Guardrails (Non-Negotiable)

1. **Import stability first**
   - Preserve `ipfs_datasets_py.logic.*` import paths.
   - When moving code, provide compatibility shims with `DeprecationWarning`.

2. **Import-quiet core**
   - Importing `ipfs_datasets_py.logic` and common subpackages must not:
     - touch network,
     - spawn threads,
     - mutate global environment,
     - require optional dependencies.

3. **Layering discipline**
   - `logic/common` + `logic/types` must stay dependency-light and should not import higher layers.

4. **Refactor in thin slices**
   - Each change should be PR-sized and ship with targeted tests.

5. **Determinism by default**
   - Under a fixed seed and without network, core reasoning should be deterministic.

## Continuous Quality Loops (Infinite)

These are always-on and never complete.

### Loop A — Import & Optional Dependencies

- Keep all optional deps behind lazy imports (`__getattr__`, factory functions, or explicit `init_*`).
- Ensure deprecation shims warn on access, not at import time (except explicit deprecated top-level imports).
- Maintain lightweight “import quiet” tests for the public surfaces.

**Exit criteria (per release):**
- Importing the core public surfaces produces no warnings/log spam.
- Missing optional deps yields deterministic, typed “unavailable” outcomes.

### Loop B — Public API Contract

- Make a small, explicit blessed API surface (prefer `logic/api.py` and documented entry points).
- For any public symbol: define signature stability, error types, and result schema.

**Exit criteria (per release):**
- Public API contract tests pass and `__all__` is stable.

### Loop C — Correctness & Safety

- Normalize error handling across converters/provers.
- Enforce timeouts for any external process calls.
- Validate file/path handling and cache size limits.

### Loop D — Performance & Memory

- Keep caches bounded by default.
- Ensure batch processing has backpressure and bounded worker pools.
- Maintain micro-benchmarks for hot paths and prevent regressions.

### Loop E — Documentation Truthfulness

- Docs should describe what exists today.
- Any “production-ready” claim needs a supporting test and a known limitations section.

## Top Priorities (P0/P1)

### P0 — Make import surfaces consistent and test-backed

- Establish a canonical public surface and keep it import-quiet.
- Maintain compatibility shims for legacy paths.

### P0 — Remove import-time side effects

- Audit `logic/integration` and other public modules for import-time configuration.
- Move any runtime initialization behind explicit functions.

### P1 — Unify errors and result objects

- Standardize exception hierarchy and normalization.
- Standardize result schemas (`ConversionResult`, `ProofResult`) and define the overlap policy.

### P1 — Clarify layering and ownership

- Define dependency direction rules and enforce with a static import graph check.

## Workstreams (Evergreen Backlog)

### 1) Public API + Namespacing

**Problems to solve:**
- Multiple overlapping entry points and duplicated symbol names (e.g., `ConversionResult`, `ConversionStatus`).

**Backlog:**
- Define “blessed” import targets (e.g., `logic/api.py`, `logic/fol`, `logic/deontic`).
- Keep `logic/__init__.py` `__all__` aligned with reality.
- Decide canonical definitions for overlapping symbols; keep aliases stable.

### 2) Import Hygiene + Shims

**Problems to solve:**
- Old import paths must keep working while code moves.

**Backlog:**
- Centralize shims in a dedicated compat namespace (e.g., `logic/_compat`).
- Ensure deprecation warnings are consistent and occur on access.

### 3) Layering & Dependency Inversion

**Problems to solve:**
- Cross-imports can create brittle coupling and optional-dep explosions.

**Backlog:**
- Maintain a layering map:
  - `common/types` (primitives) → engines (`TDFOL/CEC/fol/deontic`) → `integration` (orchestration).
- Replace ad-hoc imports with `types`/`common` interfaces.

### 4) Error Model & Results

**Problems to solve:**
- Inconsistent exception types and result payloads.

**Backlog:**
- Standardize exception types for parse/convert/prove/timeout/unavailable.
- Standardize diagnostics fields: `method`, `confidence`, `from_cache`, `timings`, `warnings`.

### 5) Performance, Caching, and OOM Avoidance

**Problems to solve:**
- Batch paths can grow memory; caches need consistent bounding.

**Backlog:**
- Enforce cache max sizes and TTL policy.
- Add concurrency/eviction tests.
- Make sure heavy tests remain gated to avoid accidental downloads.

### 6) Testing Strategy (Fast-by-default)

**Problems to solve:**
- Large test suites can OOM. Refactors must remain safe.

**Backlog:**
- Maintain a <30s “smoke suite” subset.
- Keep import-quiet and API contract micro-tests.
- Gate external prover tests with markers.

## Execution Model (Infinite Queue)

### The “Next Slice” Template (copy/paste)

For each slice:

- **Goal:**
- **Files touched:**
- **Behavior changes:** none / describe
- **Shims:** yes/no
- **Tests:** added/updated
- **Docs:** updated
- **Acceptance:**

### Suggested Small Slices (1–3 days each)

1. **Blessed API surface**
   - Create/confirm `logic/api.py` exports (thin re-exports only), and add contract tests.

2. **Import-time side effect removal**
   - Identify import-time runtime setup; move to explicit `init_*()`.

3. **Error normalization helper**
   - Add `normalize_exception()` and route top-level APIs through it.

4. **Result schema convergence**
   - Define canonical `ConversionResult` and alias existing types without breaking.

5. **Static dependency graph check**
   - Add a lightweight import graph script and ensure layering is obeyed.

6. **External prover availability API**
   - Standardize “unavailable” results and timeouts; add non-binary unit tests.

7. **Cache correctness tests**
   - TTL/LRU/concurrency tests, deterministic and low-memory.

8. **Doc truth sweep**
   - Remove stale claims and ensure `DOCUMENTATION_INDEX.md` points only to canonical docs.

## “Always Green” Definition (Per Release)

A release is considered stable when:

- Import-quiet tests for public surfaces pass.
- API contract tests pass.
- Optional deps missing do not break imports.
- No unbounded cache/memory growth in default paths.
- Documentation claims match tested reality.
