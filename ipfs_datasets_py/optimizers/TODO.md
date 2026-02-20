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

- [ ] (P1) [tests] Add smoke tests for GraphRAG optimizer components that are currently large but lightly validated (imports + basic API invariants).

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

- [ ] (P2) [obs] Ensure all optimizers accept an optional logger and use consistent log keys.
- [ ] (P2) [obs] Add minimal metrics hooks for session durations, score deltas, and error counts.

### D. Testing strategy (incremental, practical)

- [ ] (P1) [tests] Add import/smoke tests for each optimizer package (`agentic`, `logic_theorem_optimizer`, `graphrag`).
- [ ] (P2) [tests] Add deterministic unit tests for “pure” helpers (parsers, score aggregators, query plan generation).
- [ ] (P2) [tests] Add golden-file tests for GraphRAG “ontology dict schema” (entities/relationships/metadata invariants).

---

## GraphRAG backlog (inline TODOs + completion plan)

### 1) `graphrag/query_optimizer.py`

- [x] (P0) [graphrag] Replace abusive TODO comment with a normal TODO.
- [ ] (P1) [graphrag] Implement/verify the “continue with original optimize_query” merge path (the file appears to contain multiple `optimize_query` definitions; deduplicate).
- [ ] (P2) [graphrag] Split the file into smaller modules if it’s extremely large (planner, traversal heuristics, learning adapter, serialization).
- [ ] (P2) [tests] Add unit tests for `get_execution_plan()` invariants.

### 2) `graphrag/logic_validator.py`

- [ ] (P2) [graphrag] Implement `ontology_to_tdfol()` conversion (even a minimal subset) — **DoD**: non-empty formulas for a trivial ontology.
- [ ] (P3) [graphrag] Implement “intelligent fix suggestion” once validation errors are structured.
- [ ] (P3) [graphrag] Implement full TDFOL proving (or clearly scope it to a specific prover/backend).

### 3) `graphrag/ontology_generator.py`

- [ ] (P2) [graphrag] Implement relationship inference (start with heuristics; keep deterministic options).
- [ ] (P2) [graphrag] Implement rule-based extraction for at least one domain.
- [ ] (P2) [graphrag] Implement smart ontology merging (dedupe by ID, merge properties, track provenance).
- [ ] (P3) [graphrag] Implement LLM-based extraction via `ipfs_accelerate_py` behind a feature flag.
- [ ] (P3) [graphrag] Implement hybrid/neural extraction strategies.

### 4) `graphrag/ontology_optimizer.py`

- [ ] (P3) [graphrag] Implement pattern identification across successful runs.
- [ ] (P3) [graphrag] Implement “intelligent recommendation generation”.

### 5) `graphrag/ontology_critic.py`

- [ ] (P2) [graphrag] Implement LLM backend integration (or explicitly disable it and remove placeholder code).
- [ ] (P3) [graphrag] Improve the dimension evaluators: completeness, consistency, clarity, granularity, domain-alignment.

### 6) CLI wrapper TODOs

- [x] (P2) [graphrag] Implement `cli_wrapper.py` “load ontology and optimize” (best-effort via `OntologySession`; JSON ontology inputs supported).
- [x] (P2) [graphrag] Implement `cli_wrapper.py` “load and validate ontology” (JSON ontology inputs supported).
- [ ] (P2) [graphrag] Implement `cli_wrapper.py` “query optimization”.

---

## Logic theorem optimizer backlog

- [ ] (P2) [logic] Implement `logic_theorem_optimizer/cli_wrapper.py` theorem proving entrypoint (even a minimal stub wired to an existing prover integration).
- [ ] (P2) [tests] Add a minimal end-to-end “theorem session” smoke test.

---

## Agentic optimizers backlog (alignment & hardening)

- [ ] (P2) [agentic] Reconcile docs claiming phases/tests exist with what’s actually present (e.g., referenced test paths).  
  **DoD**: docs don’t mention non-existent files; or missing files are added.
- [ ] (P2) [agentic] Ensure `agentic/llm_integration.py` is exercised by at least one test at the repository’s current test entrypoints.

---

## TODO inventory (seeded from inline markers)

This section is the “copy of record” of inline TODO markers currently found under `optimizers/`.

| Area | File | TODO summary |
|---|---|---|
| GraphRAG | `graphrag/query_optimizer.py` | Deduplicate `optimize_query`; refactor learning-hook section |
| GraphRAG | `graphrag/logic_validator.py` | Ontology→TDFOL conversion; fix suggestion; full proving |
| GraphRAG | `graphrag/prompt_generator.py` | Example database integration |
| GraphRAG | `graphrag/ontology_generator.py` | Relationship inference; rule-based; LLM-based; hybrid; neural; smart merging |
| GraphRAG | `graphrag/ontology_mediator.py` | Prompt generation; targeted refinement; refinement actions |
| GraphRAG | `graphrag/ontology_optimizer.py` | Pattern identification; recommendation generation |
| GraphRAG | `graphrag/ontology_critic.py` | LLM integration + evaluator depth |
| GraphRAG | `graphrag/cli_wrapper.py` | Load ontology; validate ontology; query optimization |
| Logic | `logic_theorem_optimizer/cli_wrapper.py` | Implement theorem proving |

_Refresh command (run from repo root):_  
`rg -n "TODO\\b|FIXME\\b|XXX\\b" ipfs_datasets_py/ipfs_datasets_py/optimizers/`

---

## Legacy notes (imported)

The prior committed version of this file (circa 2026-02-14) contained an implementation status report and a large TDD checklist. The key context worth preserving:

- Agentic optimizer work was reported as largely complete for:
  - Phase 2 (methods): adversarial / actor-critic / chaos
  - Phase 4 (validation framework)
  - Phase 5 (CLI)
  - Phase 7 (examples) partially
- Optimizer monitoring components were reported as implemented:
  - `optimizer_learning_metrics.py`
  - `optimizer_alert_system.py`
  - `optimizer_learning_metrics_integration.py`
  - `optimizer_visualization_integration.py`
- Remaining work emphasized **tests** for the monitoring/metrics/alerting pipeline (unit + workflow integration).

If you need the full historical text, retrieve it from git history (e.g., `git show HEAD:ipfs_datasets_py/optimizers/TODO.md`).

## Definition of Done (DoD) templates

Use these checklists to keep work “finishable”:

- **Refactor DoD**: no behavior change unless stated; type hints not worse; imports clean; unit tests added/updated; docs updated.
- **Feature DoD**: minimal happy-path implemented; deterministic fallback; errors are typed/structured; at least one unit test.
- **Docs DoD**: no references to non-existent files; example commands run successfully.
