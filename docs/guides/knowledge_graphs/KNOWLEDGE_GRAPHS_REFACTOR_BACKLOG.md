# Knowledge Graphs Refactor & Improvement Backlog (Living Doc)

This document is intended to be an “infinite TODO list”: a continuously-extendable backlog for improving `ipfs_datasets_py.ipfs_datasets_py.knowledge_graphs`.

## Scope

In scope:
- `ipfs_datasets_py/knowledge_graphs/**` (core graph engine, query engine, cypher compiler/parser, storage/IPLD backend, indexing, constraints, transactions/WAL, json-ld serialization, migration tools, neo4j compatibility layer, lineage, cross-document reasoning)

Out of scope (unless explicitly pulled in by a task):
- Application-level callers (MCP tools, processors, dashboards) except where required to keep compatibility.

## Non-Negotiables

- **Backward compatibility**: do not break legacy imports without a deprecation window.
- **Layer boundaries**: clear separation between (1) storage, (2) graph primitives, (3) query execution, (4) higher-level pipelines (GraphRAG/hybrid), (5) adapters (Neo4j compat).
- **Deterministic behavior** where possible: same inputs yield same outputs (esp. in query execution and transaction semantics).

## Current Module Map (high level)

- `extraction/`: entity/relationship/graph container + extraction + validator (already modularized; keep migrating callers).
- `core/`: query execution + graph engine primitives (currently mixed in `core/query_executor.py`).
- `storage/`: IPLD storage backend via `ipfs_backend_router` + caching.
- `neo4j_compat/`: Neo4j-driver-like surface (`GraphDatabase.driver`, sessions, results, types).
- `cypher/`: lexer/parser/AST/compiler + function registry.
- `query/`: unified query engine + budget manager + hybrid search.
- `transactions/`: WAL + transaction manager + isolation levels.
- `indexing/`, `constraints/`, `jsonld/`, `migration/`, `lineage/`: supporting subsystems.

## Observed Hotspots (why this backlog exists)

- `core/query_executor.py` contains **both** `QueryExecutor` and `GraphEngine` plus a large amount of expression evaluation logic.
- `QueryExecutor` uses **dynamic instance state** (e.g. `_bindings`, `_union_parts`) created mid-execution. This complicates reentrancy, concurrency, and testability.
- Two different “graph engines” concepts appear:
  - `core/query_executor.GraphEngine` for node/relationship CRUD and traversal
  - `query/unified_engine.UnifiedQueryEngine.graph_engine` lazily constructing a graph engine but passing `backend=self.backend` (type mismatch risk vs `storage_backend` expectation).
- Storage layer (`storage/ipld_backend.py`) is fairly clean, but cache invalidation and namespaces are not consistently applied across the stack.
- There are multiple deprecated/legacy surfaces (e.g. `ipld.py`, import shims in `knowledge_graphs/__init__.py`, legacy files + `*.backup` copies) that need a **structured retirement plan**.

## How to Use This Backlog

- Each task is written as a checkbox with:
  - **Priority**: P0 (must), P1 (should), P2 (nice)
  - **Owner / area**
  - **Acceptance criteria** (what “done” means)
- Add tasks freely under “Backlog (unbounded)”. Keep the “Next Up” section small.

---

# Next Up (keep this short)

## P0 — Stabilize boundaries

- [ ] **P0 / core** Split `core/query_executor.py` into focused modules without changing public behavior.
  - Acceptance: imports unchanged; existing callers still pass; unit tests cover basic cypher → IR → execution path.

- [ ] **P0 / query** Fix `UnifiedQueryEngine.graph_engine` construction to use the correct dependency type.
  - Acceptance: type-consistent initialization; basic create/query roundtrip works using the unified engine.

- [ ] **P0 / transactions** Ensure `TransactionManager` depends on a stable `GraphEngine` interface (not a concrete module path).
  - Acceptance: `TransactionManager` can operate over a protocol/interface; import cycles reduced.

## P0 — Reliability

- [ ] **P0 / query** Make `QueryExecutor` execution **stateless per call** (no lingering `_bindings` / `_union_parts` across calls).
  - Acceptance: running two queries in the same executor instance can’t leak data between runs; concurrency-safe by design.

---

# Backlog (unbounded)

## 1) Public API & Packaging

- [ ] **P0** Define and document the *canonical* public API surface for knowledge graphs.
  - Acceptance: one page doc listing supported imports (new) + legacy mapping (old) + stability guarantees.

- [ ] **P1** Replace “star exports” and wide `__all__` with explicit exports per subpackage.
  - Acceptance: import-time reduced; `from ... import *` not required anywhere.

- [ ] **P1** Add `py.typed` and formalize typing for `knowledge_graphs` package.
  - Acceptance: mypy/pyright can type-check without pervasive `Any`.

## 2) Core Graph Model

- [ ] **P0** Introduce a single, authoritative `Node`/`Relationship`/`Path` data model boundary.
  - Acceptance: `neo4j_compat.types` and `core` agree on fields and access patterns.

- [ ] **P1** Normalize property access patterns (e.g., `node.get('x')` vs `node.properties['x']`).
  - Acceptance: one pattern is recommended, adapters provide compatibility.

- [ ] **P2** Add stable IDs strategy: separate *logical IDs* from *content IDs (CIDs)*.
  - Acceptance: docs + code clarifying mapping + persistence semantics.

## 3) Query Execution (`core/` + `cypher/`)

- [ ] **P0** Extract expression evaluation into a standalone evaluator module.
  - Acceptance: evaluator is unit-tested for property access, functions, CASE, comparisons, IN, CONTAINS, STARTS/ENDS.

- [ ] **P0** Make `QueryExecutor` return structured errors (exception types) instead of silently swallowing and returning empty results.
  - Acceptance: callers can distinguish syntax errors vs runtime errors vs empty results.

- [ ] **P1** Add query plan caching with explicit invalidation strategy.
  - Acceptance: cache keyed by query + schema version; can be disabled.

- [ ] **P1** Standardize Cypher detection and routing rules.
  - Acceptance: a unit test suite covers false positives (e.g., strings with `()` that aren’t cypher).

- [ ] **P2** Add minimal “EXPLAIN” / “PROFILE” style introspection.
  - Acceptance: returns compiled IR + counters without executing (or executes with tracing).

## 4) Unified Query Engine (`query/`)

- [ ] **P0** Ensure `UnifiedQueryEngine` has a strict contract for `backend` (protocol) rather than arbitrary `Any`.
  - Acceptance: protocol defines methods used by hybrid search / IR executor.

- [ ] **P1** Consolidate budget enforcement: every execution path increments counters consistently.
  - Acceptance: counters always populated; unit tests verify budget caps.

- [ ] **P1** Add caching policy: which steps can be cached (vector search, graph traversal, LLM reasoning) and how to invalidate.

- [ ] **P2** Add streaming / incremental results option for long GraphRAG runs.
  - Acceptance: optional generator interface; doesn’t change existing callers.

## 5) Transactions & WAL (`transactions/`)

- [ ] **P0** Formalize transaction semantics relative to the storage backend.
  - Acceptance: doc clarifies what durability and isolation mean given IPFS/IPLD constraints.

- [ ] **P0** Add crash-recovery tests for WAL replay.
  - Acceptance: simulate crash mid-commit; recovery yields consistent state.

- [ ] **P1** Implement read-set validation for SERIALIZABLE / REPEATABLE READ modes.
  - Acceptance: conflicting reads cause abort.

- [ ] **P2** Provide a bounded WAL compaction strategy.
  - Acceptance: older entries can be compacted while keeping recoverability.

## 6) Storage (`storage/`)

- [ ] **P0** Add explicit codec handling tests (`dag-json`, `dag-cbor`, `raw`).

- [ ] **P1** Cache invalidation hooks on `pin/unpin/store` and on mutation operations.

- [ ] **P2** Support pluggable cache backends (in-memory LRU vs disk vs none).

## 7) Indexing & Constraints

- [ ] **P1** Define index and constraint interfaces and make them backend-agnostic.

- [ ] **P1** Add “schema version” concept that coordinates:
  - node/relationship shapes
  - index definitions
  - constraint definitions
  - query planner cache keys

## 8) JSON-LD / RDF (`jsonld/`)

- [ ] **P1** Add roundtrip tests: graph → JSON-LD → RDF → JSON-LD → graph.

- [ ] **P2** Provide a mapping registry between internal labels/types and external vocabularies.

## 9) Migration & Deprecations

- [ ] **P0** Delete or quarantine `*.backup` files from runtime modules.
  - Acceptance: backups moved to docs/archive or removed; packaging does not ship them.

- [ ] **P0** Ensure `knowledge_graph_extraction.py` becomes a thin re-export wrapper (no duplicated implementations).
  - Acceptance: legacy imports still work; source of truth is `extraction/`.

- [ ] **P1** Deprecation timeline for `ipld.py` with a versioned schedule.

- [ ] **P2** Create an automated “import fixer” script to update legacy imports in downstream code.

## 10) Testing & Tooling

- [ ] **P0** Add a focused test suite for `knowledge_graphs` (unit + small integration).
  - Acceptance: tests cover: create node/rel; simple MATCH; Expand/OptionalExpand; functions; aggregates; ordering; WAL commit/rollback.

- [ ] **P1** Add property-based tests for query execution (small random graphs).

- [ ] **P1** Add deterministic fixtures for GraphRAG/hybrid search when vector store is absent.

- [ ] **P2** Add performance smoke benchmarks (tiny + medium graphs).

---

# Task Template (copy/paste)

- [ ] **P? / area** Short title
  - Motivation:
  - Proposed change:
  - Acceptance criteria:
  - Tests:
  - Docs:
  - Risks / rollout:
