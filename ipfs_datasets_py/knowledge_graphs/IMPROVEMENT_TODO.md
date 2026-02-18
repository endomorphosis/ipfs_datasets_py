# Knowledge Graphs – Infinite Improvement Backlog (Living TODO)

**Scope:** This backlog applies to the module at `ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/`.

**Note on pathing:** Some older references mention `ipfs_datasets_py/ipfs_datasets_py/logic/knowledge_graphs`, but in this checkout the knowledge graphs subsystem lives in `.../knowledge_graphs/` (not under `logic/`).

**Status snapshot (2026-02-18):** The module is already **production-ready** (see `MASTER_STATUS.md` and `COMPREHENSIVE_ANALYSIS_2026_02_18.md`). This document is a *comprehensive, ongoing* list of refactors + polish + hardening tasks to keep improving quality over time.

---

## How to use this backlog

- Treat this file as the “infinite list”: keep adding tasks as you discover issues.
- Prefer small, reviewable PRs. For each task, add/track:
  - **Priority**: P0 (urgent) → P3 (nice-to-have)
  - **Risk**: low/med/high
  - **Acceptance criteria**: what “done” means
- When changing behavior or public API, update:
  - `MASTER_STATUS.md` (authoritative status)
  - `CHANGELOG_KNOWLEDGE_GRAPHS.md` (user-visible changes)
  - and any relevant docs in this module directory (see `INDEX.md`)

**Primary references (don’t duplicate these):**
- `MASTER_STATUS.md` (single source of truth)
- `DEFERRED_FEATURES.md` (intentional deferrals)
- `COMPREHENSIVE_ANALYSIS_2026_02_18.md` (review findings)
- `DOCUMENTATION_GUIDE.md` + `INDEX.md` (doc navigation)

---

## Quick findings (actionable deltas)

These are the highest-signal improvement opportunities found during a quick pass:

- **Docs drift / broken references**
  - Keep `README.md`, `ROADMAP.md`, `INDEX.md`, and `DOCUMENTATION_GUIDE.md` aligned to the canonical docs in this directory.
  - Periodically re-run a simple internal link audit across `knowledge_graphs/*.md` to catch drift early.
- **Exception specificity & observability**
  - There are many `except Exception as e:` blocks across the module. Most are probably fine as defensive coding, but many should be narrowed and/or re-raised as `KnowledgeGraphError` subclasses with consistent context.
- **Migration module remains the main quality gap**
  - `MASTER_STATUS.md` calls out migration coverage as the primary area to improve (40% → 70%+).
  - CAR support remains intentionally deferred (see `migration/formats.py`).
- **Test environment expectations**
  - Some unit tests use the `mocker` fixture (from `pytest-mock`). Ensure it remains part of the test/dev dependency set.
- **Recent suite stability fix**
  - A pytest `INTERNALERROR` was previously triggered by unsafe mocking of `builtins.__import__` (returning `mocker.DEFAULT` for non-target imports) in `tests/unit/knowledge_graphs/migration/test_neo4j_exporter.py`, which broke pytest internals during failure reporting.
  - The KG suite now completes cleanly.

---

## Workstream A — Documentation consistency & governance

### A1. Fix doc drift and broken references (P0)
- [x] **Align `README.md` “Module Structure” with actual files** (P0, low risk)
  - Acceptance: references point to files that exist; structure reflects current docs; no mention of missing plan docs.
- [x] **Reconcile `ROADMAP.md` with `MASTER_STATUS.md`** (P0, low risk)
  - Acceptance: P1–P4 sections reflect “completed early” (or clearly marked as historical), and timelines don’t contradict `MASTER_STATUS.md`.
- [x] **Run a simple internal link audit** across `knowledge_graphs/*.md` (P1, low risk)
  - Acceptance: zero broken intra-module markdown links.

### A2. Reduce “status doc” sprawl (P1)
- [x] **Define which status docs are authoritative vs. archival** (P1, low risk)
  - Acceptance: `MASTER_STATUS.md` states what is canonical; other summaries clearly labeled as informational.
- [x] **Add/update a short “Docs Map” section** in `DOCUMENTATION_GUIDE.md` (P2, low risk)
  - Acceptance: new contributors can find the right doc in <2 minutes.

### A3. Make deprecations obvious to users (P1)
- [x] **Centralize the deprecation story** (P1, low risk)
  - Acceptance: `__init__.py`, `ipld.py`, `knowledge_graph_extraction.py`, lineage legacy modules all refer to one migration guide path and consistent removal timeline.

---

## Workstream B — Public API surface & deprecation cleanup

### B1. Define the stable import paths (P1)
- [x] **Document “supported imports”** (P1, low risk)
  - Acceptance: docs explicitly recommend `ipfs_datasets_py.knowledge_graphs.extraction`, `...query`, `...neo4j_compat`, etc., and clarify what is legacy.
- [x] **Reduce accidental API surface area** created by re-exports (P2, medium risk)
  - Acceptance: `__all__` lists only intended public symbols; internal modules don’t become “public-by-accident”.

### B2. Finish “thin wrapper” migration where feasible (P2)
- [ ] **Minimize duplicated legacy code in `knowledge_graph_extraction.py`** (P2, medium risk)
  - Acceptance: legacy module becomes a lightweight shim importing from `extraction/` and raising deprecation warnings; no behavior divergence.

---

## Workstream C — Error handling, logging, and diagnosability

### C1. Exception taxonomy and wrapping (P1)
- [ ] **Replace broad `except Exception` with narrower exception types where realistic** (P1, medium risk)
  - Acceptance: fewer generic catches; when generic catches remain, they re-raise a `KnowledgeGraphError` subclass with original exception attached (`raise ... from e`).
- [ ] **Standardize error messages and context payload** (P2, low risk)
  - Acceptance: errors include the operation (“import”, “query”, “commit”), relevant IDs, and a short remediation hint.

### C2. Observability (P2)
- [ ] **Make logging consistent across subpackages** (P2, medium risk)
  - Acceptance: consistent logger names; no noisy warnings in normal operation; debug logs available for troubleshooting.

---

## Workstream D — Correctness improvements (targeted)

### D1. Replace placeholder relation heuristics (P1)
- [x] **Implement real semantic similarity** in `cross_document_reasoning.py` (P1, medium risk)
  - Acceptance: similarity is computed from document text/metadata; tests cover scenarios (e.g., supporting vs elaborating vs complementary).
- [ ] **Make relation classification deterministic and configurable** (P2, medium risk)
  - Acceptance: thresholds are parameters; results are stable for identical input.

### D2. Query engine correctness hardening (P2)
- [ ] **Add “golden query” fixtures** for Cypher parsing/compilation (P2, low risk)
  - Acceptance: key query patterns compile to expected IR and execute correctly.

---

## Workstream E — Testing & quality gates

### E0. Fix the current suite failures (P0)
- [x] **Triage and resolve the remaining failures in `tests/unit/knowledge_graphs/`** (P0, medium risk)
  - Acceptance: `pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/` completes without pytest INTERNALERROR; remaining failures are fixed or explicitly documented/xfail.
  - Status (2026-02-18): suite completes cleanly (`800 passed`).

### E1. Migration module coverage (P0)
- [x] **Raise migration coverage from ~40% → 70%+** (P0, low risk)
  - Acceptance: adds tests for error handling + edge cases; `pytest` passes; coverage target met.
- [ ] **Add format-specific “roundtrip” tests** (P1, medium risk)
  - Acceptance: export → import produces equivalent graph for CSV/JSON/RDF (and GraphML/GEXF/Pajek if enabled).

### E2. Fuzz / property-based tests (P2)
- [ ] **Fuzz test Cypher parser** with grammar-ish generators (P2, medium risk)
  - Acceptance: parser never crashes; invalid input yields `QueryParseError`.
- [ ] **Property tests for WAL** (P2, medium risk)
  - Acceptance: random sequences of operations preserve invariants; crash-recovery tests validate correctness.

### E3. Optional dependency test matrix (P2)
- [ ] **Explicitly test with/without optional deps** (P2, low risk)
  - Acceptance: CI (or local test scripts) can run “minimal” and “full” configs; skips are intentional and documented.

---

## Workstream F — Performance & memory

### F1. Profiling and benchmarks (P2)
- [ ] **Add a small benchmark harness** (P2, low risk)
  - Acceptance: benchmark scripts document baseline performance for extraction + query + migration.

### F2. Large-graph behavior (P2)
- [ ] **Memory optimization in batch operations** (P2, medium risk)
  - Acceptance: streaming/chunking paths exist for large imports/exports; no unbounded accumulation.

---

## Workstream G — Dependency management & packaging ergonomics

- [ ] **Verify extras (`ipfs_datasets_py[knowledge_graphs]`) actually install what the code expects** (P1, medium risk)
  - Acceptance: documented optional deps match reality; runtime error messages give exact install commands.
- [ ] **Keep core test plugins in the test dependency set** (P1, low risk)
  - Acceptance: `pytest-mock` stays present wherever test dependencies are declared; tests that rely on `mocker` never fail due to missing fixture.
- [ ] **Improve spaCy model guidance** (P3, low risk)
  - Acceptance: clearer install instructions and graceful fallback when model not present.

---

## Workstream H — Migration formats and extensibility

### H1. CAR support (deferred; keep as optional) (P3)
- [ ] **Decide on CAR library strategy** (P3, high risk)
  - Acceptance: documented recommendation; either implement or keep deferred with a clear rationale.

### H2. Format plugin architecture (optional) (P3)
- [ ] **Make import/export formats pluggable** (P3, medium risk)
  - Acceptance: adding a new format doesn’t require editing a large if/else chain; tests cover registry.

---

## Workstream I — Codebase hygiene (ongoing)

- [ ] **Reduce file sizes / “god modules”** by extracting focused helpers (P2, medium risk)
  - Candidates: `extraction/extractor.py`, `core/query_executor.py`, `cross_document_reasoning.py`.
- [ ] **Improve typing at boundaries** (P2, low risk)
  - Acceptance: fewer `Any` at public edges; core dataclasses or Protocols for key interfaces.
- [ ] **Normalize naming and terminology** across docs and code (P3, low risk)
  - Acceptance: “GraphEngine/QueryExecutor/UnifiedQueryEngine” roles are unambiguous.

---

## “First PRs” (suggested order)

If you want a high-value sequence that keeps risk low:

1. **Docs drift fixes** (A1) — update `README.md` + `ROADMAP.md` to match `MASTER_STATUS.md`.
2. **Migration coverage** (E1) — push coverage toward 70%+.
3. **Placeholder relation logic** (D1) — implement real similarity + tests.
4. **Exception narrowing** (C1) — start with a single subpackage (e.g., `migration/` or `storage/`).

---

## Completed (log)

- 2026-02-18: Replaced placeholder similarity usage in `cross_document_reasoning.py` with a real similarity computation path and added/validated unit tests.
- 2026-02-18: Added `pytest-mock` to test/dev dependencies to provide the `mocker` fixture for knowledge graph migration tests.
- 2026-02-18: Fixed pytest `INTERNALERROR` in KG suite by making `builtins.__import__` mocking delegate to the real importer for all modules except the targeted optional dependency.
- 2026-02-18: Restored LLM integration behavior in `cross_document_reasoning.py` (expose patchable `openai`/`anthropic`, prefer OpenAI/Anthropic paths when keys are set, and make `LLMRouter` initialization lazy).
- 2026-02-18: Fixed knowledge_graphs doc drift: removed merge conflict markers in `README.md`, reconciled `ROADMAP.md` with `MASTER_STATUS.md`, updated `INDEX.md`/`QUICKSTART.md`, and repaired intra-module doc links (link audit passes excluding `archive/`).
- 2026-02-18: Reduced “status doc” sprawl: clarified canonical vs archived docs in `MASTER_STATUS.md`, updated `DOCUMENTATION_GUIDE.md` maintenance guidance, and removed remaining references to archived status docs from active entry points.
- 2026-02-18: Centralized deprecation messaging: updated deprecated modules to point at `docs/knowledge_graphs/MIGRATION_GUIDE.md` and aligned legacy lineage removal wording (“future release”).
- 2026-02-18: Documented stable “supported imports” in `README.md` (prefer subpackages; legacy shims are explicitly deprecated).
- 2026-02-18: Reduced accidental public API surface at package root by limiting `knowledge_graphs/__init__.py` `__all__` to exceptions only, while keeping backward-compatible lazy root-level convenience imports with `DeprecationWarning`s (tests added to lock behavior).
- 2026-02-18: Increased migration test coverage (measured via `ipfs_datasets_py/.coveragerc`) and added edge-case tests for `IPFSImporter` init/connect/import_data paths; migration module coverage now exceeds the 70% target.
- 2026-02-18: Began C1 exception taxonomy/wrapping work in `migration/` by making `IPFSImporter`/`Neo4jExporter` wrap connection/load failures as `MigrationError` with `raise ... from e`, and updated unit tests to lock in the new behavior.

