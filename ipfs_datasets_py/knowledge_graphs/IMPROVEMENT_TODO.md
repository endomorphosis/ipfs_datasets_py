# Knowledge Graphs – Infinite Improvement Backlog (Living TODO)

**Scope:** This backlog applies to the module at `ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/`.

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
  - and any relevant docs under `docs/knowledge_graphs/`

**Primary references (don’t duplicate these):**
- `MASTER_STATUS.md` (single source of truth)
- `DEFERRED_FEATURES.md` (intentional deferrals)
- `COMPREHENSIVE_ANALYSIS_2026_02_18.md` (review findings)
- `DOCUMENTATION_GUIDE.md` + `INDEX.md` (doc navigation)

---

## Quick findings (actionable deltas)

These are the highest-signal improvement opportunities found during a quick pass:

- **Docs drift / broken references**
  - `README.md` references `NEW_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` in the module structure section, but the active directory currently contains `COMPREHENSIVE_ANALYSIS_2026_02_18.md` and other docs.
  - `ROADMAP.md` still lists features as “Planned” that `MASTER_STATUS.md` marks “Completed early / cancelled” (P1–P4).
- **Exception specificity & observability**
  - There are many `except Exception as e:` blocks across the module. Most are probably fine as defensive coding, but many should be narrowed and/or re-raised as `KnowledgeGraphError` subclasses with consistent context.
- **One “TODO” is actually a behavior placeholder**
  - `cross_document_reasoning.py` contains placeholder similarity logic (`doc_similarity = 0.7`) and a note about future LLM-based relation determination. This is not “broken”, but it’s a clear target for real implementation.
- **Migration module remains the main quality gap**
  - `MASTER_STATUS.md` calls out migration coverage as the primary area to improve (40% → 70%+).
  - CAR support remains intentionally deferred (see `migration/formats.py`).

---

## Workstream A — Documentation consistency & governance

### A1. Fix doc drift and broken references (P0)
- [ ] **Align `README.md` “Module Structure” with actual files** (P0, low risk)
  - Acceptance: references point to files that exist; structure reflects current docs; no mention of missing plan docs.
- [ ] **Reconcile `ROADMAP.md` with `MASTER_STATUS.md`** (P0, low risk)
  - Acceptance: P1–P4 sections reflect “completed early” (or clearly marked as historical), and timelines don’t contradict `MASTER_STATUS.md`.
- [ ] **Run a simple internal link audit** across `knowledge_graphs/*.md` (P1, low risk)
  - Acceptance: zero broken intra-module markdown links.

### A2. Reduce “status doc” sprawl (P1)
- [ ] **Define which status docs are authoritative vs. archival** (P1, low risk)
  - Acceptance: `MASTER_STATUS.md` states what is canonical; other summaries clearly labeled as informational.
- [ ] **Add/update a short “Docs Map” section** in `DOCUMENTATION_GUIDE.md` (P2, low risk)
  - Acceptance: new contributors can find the right doc in <2 minutes.

### A3. Make deprecations obvious to users (P1)
- [ ] **Centralize the deprecation story** (P1, low risk)
  - Acceptance: `__init__.py`, `ipld.py`, `knowledge_graph_extraction.py`, lineage legacy modules all refer to one migration guide path and consistent removal timeline.

---

## Workstream B — Public API surface & deprecation cleanup

### B1. Define the stable import paths (P1)
- [ ] **Document “supported imports”** (P1, low risk)
  - Acceptance: docs explicitly recommend `ipfs_datasets_py.knowledge_graphs.extraction`, `...query`, `...neo4j_compat`, etc., and clarify what is legacy.
- [ ] **Reduce accidental API surface area** created by re-exports (P2, medium risk)
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
- [ ] **Implement real semantic similarity** in `cross_document_reasoning.py` (P1, medium risk)
  - Options: simple TF-IDF cosine similarity, embedding-based similarity (if embeddings module exists), or reuse an existing similarity utility.
  - Acceptance: similarity is computed from document text/metadata; tests cover at least 3 scenarios (supporting vs contradicting vs unclear).
- [ ] **Make relation classification deterministic and configurable** (P2, medium risk)
  - Acceptance: thresholds are parameters; results are stable for identical input.

### D2. Query engine correctness hardening (P2)
- [ ] **Add “golden query” fixtures** for Cypher parsing/compilation (P2, low risk)
  - Acceptance: key query patterns compile to expected IR and execute correctly.

---

## Workstream E — Testing & quality gates

### E1. Migration module coverage (P0)
- [ ] **Raise migration coverage from ~40% → 70%+** (P0, low risk)
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

