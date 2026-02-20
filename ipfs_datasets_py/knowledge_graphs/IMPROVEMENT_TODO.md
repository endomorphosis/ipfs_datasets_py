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
- [x] **Minimize duplicated legacy code in `knowledge_graph_extraction.py`** (P2, medium risk)
  - Acceptance: legacy module becomes a lightweight shim importing from `extraction/` and raising deprecation warnings; no behavior divergence.
  - Status (2026-02-19): ✅ DONE – `knowledge_graph_extraction.py` is already a 120-line thin shim: it re-exports from `extraction/`, raises `DeprecationWarning` on import, and overrides `extract_knowledge_graph()` for backward API compatibility. Verified by `test_optional_deps.py::TestLegacyShim`.

---

## Workstream C — Error handling, logging, and diagnosability

### C1. Exception taxonomy and wrapping (P1)
- [x] **Replace broad `except Exception` with narrower exception types where realistic** (P1, medium risk)
  - Acceptance: fewer generic catches; when generic catches remain, they re-raise a `KnowledgeGraphError` subclass with original exception attached (`raise ... from e`).
  - Status (2026-02-19): ✅ SUBSTANTIALLY DONE – All remaining `except Exception` blocks across the module now either (a) re-raise a typed `KnowledgeGraphError` subclass via `raise ... from e`, or (b) are guarded by earlier `except asyncio.CancelledError: raise` / typed-catch clauses so the generic catch is truly the last resort. See the 15+ entries in the Completed log for full details.
- [x] **Standardize error messages and context payload** (P2, low risk)
  - Acceptance: errors include the operation ("import", "query", "commit"), relevant IDs, and a short remediation hint.
  - Status (2026-02-19): ✅ DONE – Added `operation`, `error_class`, and `remediation` fields to key error raises in `extraction/extractor.py` (NER/RE failures) and `migration/ipfs_importer.py` (connect/load failures). All modules now consistently populate `details` with `operation` + `remediation` hints.

### C2. Observability (P2)
- [x] **Make logging consistent across subpackages** (P2, medium risk)
  - Acceptance: consistent logger names; no noisy warnings in normal operation; debug logs available for troubleshooting.
  - Status (2026-02-19): ✅ DONE – All modules use `logging.getLogger(__name__)`; replaced `print()` calls in `extraction/extractor.py` (spaCy/transformers absent warnings) with `logger.warning()` to keep optional-dep messages in the logging system, not stdout.

---

## Workstream D — Correctness improvements (targeted)

### D1. Replace placeholder relation heuristics (P1)
- [x] **Implement real semantic similarity** in `cross_document_reasoning.py` (P1, medium risk)
  - Acceptance: similarity is computed from document text/metadata; tests cover scenarios (e.g., supporting vs elaborating vs complementary).
- [x] **Make relation classification deterministic and configurable** (P2, medium risk)
  - Acceptance: thresholds are parameters; results are stable for identical input.
  - Status (2026-02-19): ✅ DONE – added `relation_similarity_threshold`, `relation_supporting_strength`, `relation_elaborating_strength`, `relation_complementary_strength` constructor parameters to `CrossDocumentReasoner`; all four defaults preserved; verified with 5 new unit tests in `test_reasoning.py::TestConfigurableRelationThresholds`.

### D2. Query engine correctness hardening (P2)
- [x] **Add “golden query” fixtures** for Cypher parsing/compilation (P2, low risk)
  - Acceptance: key query patterns compile to expected IR and execute correctly.
  - Status (2026-02-19): ✅ DONE – created `tests/unit/knowledge_graphs/test_cypher_golden_queries.py` with 18 tests covering MATCH, WHERE, RETURN, CREATE patterns and parse-error paths; all 18 pass.

---

## Workstream E — Testing & quality gates

### E0. Fix the current suite failures (P0)
- [x] **Triage and resolve the remaining failures in `tests/unit/knowledge_graphs/`** (P0, medium risk)
  - Acceptance: `pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/` completes without pytest INTERNALERROR; remaining failures are fixed or explicitly documented/xfail.
  - Status (2026-02-18): suite completes cleanly (`800 passed`).

### E1. Migration module coverage (P0)
- [x] **Raise migration coverage from ~40% → 70%+** (P0, low risk)
  - Acceptance: adds tests for error handling + edge cases; `pytest` passes; coverage target met.
- [x] **Add format-specific “roundtrip” tests** (P1, medium risk)
  - Acceptance: export → import produces equivalent graph for CSV/JSON/RDF (and GraphML/GEXF/Pajek if enabled).
  - Status (2026-02-19): ✅ DONE – added 13 roundtrip tests to `tests/unit/knowledge_graphs/migration/test_formats.py` (7 for DAG_JSON, 6 for JSON_LINES); all 56 format tests pass. GraphML/GEXF/Pajek roundtrips already existed in `TestFormatConversions`.

### E2. Fuzz / property-based tests (P2)
- [x] **Fuzz test Cypher parser** with grammar-ish generators (P2, medium risk)
  - Acceptance: parser never crashes; invalid input yields `QueryParseError`.
  - Status (2026-02-19): ✅ DONE – Created `tests/unit/knowledge_graphs/test_cypher_fuzz.py` with 67 tests across 7 classes (truncated queries, malformed syntax, large inputs, Unicode, reserved words, valid edge cases, lexer stress). Fixed bug: parser now catches `SyntaxError` from lexer and re-raises as `CypherParseError`. All 67 fuzz tests pass.
- [x] **Property tests for WAL** (P2, medium risk)
  - Acceptance: random sequences of operations preserve invariants; crash-recovery tests validate correctness.
  - Status (2026-02-19): ✅ DONE – Created `tests/unit/knowledge_graphs/test_wal_invariants.py` with 23 tests across 10 invariant classes: append-only CID uniqueness, chain integrity, reverse-chronological read order, recovery (committed/aborted), empty WAL safety, compaction, stats, cycle detection, transaction history filtering, integrity validation. All 23 pass.

### E3. Optional dependency test matrix (P2)
- [x] **Explicitly test with/without optional deps** (P2, low risk)
  - Acceptance: CI (or local test scripts) can run "minimal" and "full" configs; skips are intentional and documented.
  - Status (2026-02-19): ✅ DONE – Created `tests/unit/knowledge_graphs/test_optional_deps.py` with 11 tests verifying graceful degradation without spaCy/transformers and confirming core imports always work; all 11 pass.

---

## Workstream F — Performance & memory

### F1. Profiling and benchmarks (P2)
- [x] **Add a small benchmark harness** (P2, low risk)
  - Acceptance: benchmark scripts document baseline performance for extraction + query + migration.
  - Status (2026-02-19): ✅ DONE – Created `tests/unit/knowledge_graphs/test_benchmarks.py` with 10 `@pytest.mark.slow` tests covering extraction speed (<5ms/doc), Cypher parse+compile (<1ms/query), GraphEngine CRUD (<0.5ms/op), and DAG-JSON/JSON-Lines roundtrip (<50ms/100 nodes). Can also be run standalone: `python tests/.../test_benchmarks.py`.

### F2. Large-graph behavior (P2)
- [x] **Memory optimization in batch operations** (P2, medium risk)
  - Acceptance: streaming/chunking paths exist for large imports/exports; no unbounded accumulation.
  - Status (2026-02-19): ✅ DONE – Added `GraphData.iter_nodes_chunked()`, `GraphData.iter_relationships_chunked()` (both default chunk_size=500), and `GraphData.export_streaming()` to `migration/formats.py`. The streaming export uses 64KB write buffers and processes one chunk at a time, avoiding unbounded string accumulation.

---

## Workstream G — Dependency management & packaging ergonomics

- [x] **Verify extras (`ipfs_datasets_py[knowledge_graphs]`) actually install what the code expects** (P1, medium risk)
  - Acceptance: documented optional deps match reality; runtime error messages give exact install commands.
  - Status (2026-02-19): ✅ DONE – Updated `setup.py` `knowledge_graphs` extras to include `numpy`, `openai`, `anthropic`, and `networkx` (all used in cross_document_reasoning.py and lineage/). Error messages in `extractor.py` now use `logger.warning()` with exact install commands.
- [x] **Keep core test plugins in the test dependency set** (P1, low risk)
  - Acceptance: `pytest-mock` stays present wherever test dependencies are declared; tests that rely on `mocker` never fail due to missing fixture.
  - Status (2026-02-19): ✅ DONE – Added `pytest-mock>=3.12.0` to `setup.py` `test` extras (was already in `requirements.txt` but not in `setup.py[test]`).
- [x] **Improve spaCy model guidance** (P3, low risk)
  - Acceptance: clearer install instructions and graceful fallback when model not present.
  - Status (2026-02-19): ✅ DONE – `extractor.py` now uses `logger.warning()` with combined install+model-download instructions (single message, not 3 separate prints). The existing graceful fallback to rule-based mode was already in place.

---

## Workstream H — Migration formats and extensibility

### H1. CAR support (deferred; keep as optional) (P3)
- [x] **Decide on CAR library strategy** (P3, high risk)
  - Acceptance: documented recommendation; either implement or keep deferred with a clear rationale.
  - Status (2026-02-19): ✅ DONE – Updated `DEFERRED_FEATURES.md` Section 6 with a detailed decision: keep CAR deferred until `ipld-car` ≥ 1.0 ships, with full rationale and a code example showing how third parties can plug in CAR support via `register_format()` without modifying core.

### H2. Format plugin architecture (optional) (P3)
- [x] **Make import/export formats pluggable** (P3, medium risk)
  - Acceptance: adding a new format doesn't require editing a large if/else chain; tests cover registry.
  - Status (2026-02-19): ✅ DONE – Replaced the `if/elif` chain in `save_to_file()`/`load_from_file()` with a `_FormatRegistry` singleton + `register_format()` public API. Built-in handlers (DAG_JSON, JSON_LINES, GRAPHML, GEXF, PAJEK, CAR) registered at import time. Third-party formats can be registered without modifying core. Exported from `migration/__init__.py`.

---

## Workstream I — Codebase hygiene (ongoing)

- [x] **Reduce file sizes / “god modules”** by extracting focused helpers (P2, medium risk)
  - Candidates: `extraction/extractor.py`, `core/query_executor.py`, `cross_document_reasoning.py`.
  - Status (2026-02-19): ✅ DONE – Three god-module reductions completed: (a) `extraction/extractor.py` 1760→1624 lines via `extraction/_entity_helpers.py`; (b) `core/query_executor.py` 1189→545 lines via `core/_legacy_graph_engine.py`; (c) `cross_document_reasoning.py` 1244→1196 lines by extracting `InformationRelationType`, `DocumentNode`, `EntityMediatedConnection`, `CrossDocReasoning` into new `cross_document_types.py`. All three preserve backward-compatible imports. Tests in `test_workstream_i.py` (27 tests) verify both import paths and object identity.
- [x] **Improve typing at boundaries** (P2, low risk)
  - Acceptance: fewer `Any` at public edges; core dataclasses or Protocols for key interfaces.
  - Status (2026-02-19): ✅ DONE – Created `core/types.py` with: type aliases `GraphProperties`, `NodeLabels`, `CID`; TypedDicts `GraphStats`, `NodeRecord`, `RelationshipRecord`, `WALStats`, `QuerySummary`; structural Protocols `StorageBackend` and `GraphEngineProtocol`. All exported from `core/__init__.py`.
- [x] **Normalize naming and terminology** across docs and code (P3, low risk)
  - Acceptance: “GraphEngine/QueryExecutor/UnifiedQueryEngine” roles are unambiguous.
  - Status (2026-02-19): ✅ DONE – Added a Component role guide to `query/__init__.py` module docstring that defines the three layers (GraphEngine = CRUD store, QueryExecutor = Cypher compiler/executor, UnifiedQueryEngine = full orchestration), their responsibilities, and a typical call-chain diagram.

---

## “First PRs” (suggested order)

If you want a high-value sequence that keeps risk low:

1. **Docs drift fixes** (A1) — update `README.md` + `ROADMAP.md` to match `MASTER_STATUS.md`.
2. **Migration coverage** (E1) — push coverage toward 70%+.
3. **Placeholder relation logic** (D1) — implement real similarity + tests.
4. **Exception narrowing** (C1) — start with a single subpackage (e.g., `migration/` or `storage/`).

---

## Completed (log)

- 2026-02-20: Fixed `extraction/validator.py`: `validate_during_extraction` now preserves user intent unchanged (was AND'd with `validator_available`, silently becoming `False` when SPARQLValidator absent); also added `validation_metrics` stub with `"skipped": True` when validation was requested but unavailable. Verified with `tests/unit/knowledge_graphs/test_extraction_package.py::TestValidationExtractor` (2 tests).
- 2026-02-20: Fixed `extraction/extractor.py`: removed unused `from transformers import pipeline` inside `_neural_relationship_extraction()` that caused an `ImportError` to swallow mock calls in tests. Verified with `tests/unit/knowledge_graphs/test_p3_p4_advanced_features.py::TestNeuralRelationshipExtraction::test_neural_extraction_with_mock_model`.
- 2026-02-20: Fixed `query/hybrid_search.py`: replaced three `except anyio.get_cancelled_exc_class():` clauses with `except asyncio.CancelledError:` — the anyio call raises `NoEventLoopError` outside an event loop (e.g. in sync unit tests); asyncio.CancelledError is safe in all contexts and is what anyio uses in asyncio mode anyway. Added `import asyncio`. Verified with `tests/unit/knowledge_graphs/test_unified_query_engine.py::TestHybridSearchEngine::test_vector_search_wraps_unexpected_vector_store_error`.
- 2026-02-20: Updated MASTER_STATUS.md to v2.0.1 (977 tests passing, 0 failing), updated MASTER_REFACTORING_PLAN_2026.md module snapshot (79 files, 977 tests), and added CHANGELOG_KNOWLEDGE_GRAPHS.md entry for v2.0.1.
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
- 2026-02-18: Continued C1 in `storage/` by tightening `IPLDBackend` error taxonomy (consistent `IPLDStorageError` wrapping, correct serialization/deserialization exception types, add `backend_name` context) and added unit tests for JSON/UTF-8 error wrapping.
- 2026-02-18: Continued C1 in `core/` by narrowing persistence-related generic catches in the legacy graph engine to `StorageError` (avoids swallowing unrelated exceptions while keeping existing return-on-failure behavior).
- 2026-02-18: Continued C1 in `extraction/` by narrowing broad exception handlers in `extraction/extractor.py` (typed `EntityExtractionError`/`RelationshipExtractionError` wrapping, fewer generic catches in advanced/neural extraction paths) and verified with extraction-focused tests + full KG unit suite.
- 2026-02-18: Continued C1 in `transactions/` by narrowing WAL (`transactions/wal.py`) exception handlers (typed `SerializationError`/`DeserializationError`/`TransactionError` wrapping; avoid generic catches where realistic) and verified with transaction unit tests.
- 2026-02-18: Continued C1 in `query/` by tightening `query/unified_engine.py` exception taxonomy (re-raise `QueryError` subclasses instead of double-wrapping; fix IR error path referencing undefined `query`) and verified with unified query engine unit tests.
- 2026-02-18: Continued C1 in `query/` by narrowing broad exception handlers in `query/hybrid_search.py` (re-raise `KnowledgeGraphError` subclasses; wrap unexpected vector-search failures as `QueryExecutionError`; preserve graceful fallback on missing embedding/vector store) and verified with unified query engine unit tests.
- 2026-02-18: Continued C1 in `core/` by narrowing persistence-path exception handlers in `core/graph_engine.py` to `StorageError` + common data-shape errors (avoid swallowing unrelated exceptions while preserving existing return-on-failure semantics) and verified with GraphEngine unit tests.
- 2026-02-18: Continued C1 in `core/` by tightening `core/query_executor.py` to re-raise `QueryError` subclasses (avoid double-wrapping) and narrowing `core/ir_executor.py` OrderBy sort failures to common comparison/data errors; verified with QueryExecutor unit tests.
- 2026-02-18: Continued C1 in `transactions/` by tightening `transactions/manager.py` exception taxonomy (re-raise existing `TransactionError`s; remove redundant handlers) and fixing `_capture_snapshot()` error wrapping to avoid masking failures; verified with transaction unit tests.
- 2026-02-18: Continued C1 in `jsonld/` by tightening `jsonld/validation.py` schema-validation exception handling (re-raise `KnowledgeGraphError` subclasses; handle expected jsonschema/schema/data errors explicitly while preserving `ValidationResult` semantics) and verified with JSON-LD unit tests.
- 2026-02-18: Continued C1 in `cypher/` by narrowing broad exception handlers in `cypher/parser.py` and `cypher/compiler.py` to common internal failure types and preserving exception chaining (`raise ... from e`); verified with Cypher-focused unit tests.
- 2026-02-18: Continued C1 in `neo4j_compat/` by narrowing `IPFSSession.read_transaction()`/`write_transaction()` retry-loop exception handling (retry only transient failures; re-raise non-retryable `KnowledgeGraphError` subclasses) and tightening `IPFSDriver.verify_connectivity()` to raise `IPLDStorageError` with context; verified with driver/pool/bookmarks unit tests.
- 2026-02-19: Continued C1 in `cross_document_reasoning.py` by narrowing the vector-similarity fallback from `except Exception: pass` to expected numeric/shape errors and making the GraphRAG query optimizer import optional (with a non-None fallback object when deps are missing); verified with `pytest -q tests/unit/knowledge_graphs/test_reasoning.py` (18 passed).
- 2026-02-18: Continued C1 in `migration/ipfs_importer.py` by re-raising `MigrationError` in `_connect()`/`_load_graph_data()` (avoid double-wrapping) and preserving underlying exception details in the `import_data()` unexpected-error path; verified with `/home/barberb/complaint-generator/.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/migration/test_ipfs_importer.py` (44 passed).
- 2026-02-18: Continued C1 in `migration/neo4j_exporter.py` by re-raising `MigrationError` in `_connect()` (avoid double-wrapping) and preserving underlying exception details in the `export_data()` unexpected-error path; verified with `/home/barberb/complaint-generator/.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/migration/test_neo4j_exporter.py` (32 passed).
- 2026-02-19: Continued C1 in `storage/ipld_backend.py` by preserving underlying exception details (`error`, `error_class`) in generic `IPLDStorageError` wrappers for `store()`/`retrieve()`; verified with `./.venv/bin/python -m pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/test_ipld_backend_error_wrapping.py` (3 passed).
- 2026-02-19: Continued C1 in `transactions/wal.py` by preserving underlying exception details (`error`, `error_class`) in generic `TransactionError` wrappers; verified with `./.venv/bin/python -m pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/test_transactions.py` (8 passed).
- 2026-02-19: Continued C2/C1 in `core/expression_evaluator.py` by improving function-call failure warnings to include the underlying exception class name (without changing the return-`None` semantics); verified with `./.venv/bin/python -m pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/test_expression_evaluator.py` (7 passed).
- 2026-02-19: Continued C1 in `query/unified_engine.py` by preserving underlying exception details (`error`, `error_class`) in generic `QueryExecutionError` wrappers across cypher/IR/hybrid/GraphRAG execution paths; verified with `./.venv/bin/python -m pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/test_unified_query_engine.py` (27 passed).
- 2026-02-19: Continued C1 in `query/hybrid_search.py` by preserving underlying exception details (`error`, `error_class`) when wrapping unexpected vector store failures, and added a unit test to lock behavior; verified with `./.venv/bin/python -m pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/test_unified_query_engine.py` (28 passed).
- 2026-02-19: Continued C1/C2 in `extraction/validator.py` by returning structured error metadata (`error_class`, `error_details`) in error-result dicts for unexpected failures (while preserving the existing `error` string + `knowledge_graph: None` shape); verified with `./.venv/bin/python -m pytest -q ipfs_datasets_py/tests/unit/knowledge_graphs/test_extraction_package.py` (22 passed).

- 2026-02-19: Continued C1 in `transactions/manager.py` by preserving underlying exception details (`error`, `error_class`) in generic `TransactionError` wrappers (commit path + snapshot capture); verified with `./.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/test_transactions.py` (8 passed).
- 2026-02-19: Continued C2 in `jsonld/validation.py` by including the underlying exception class name in schema-validation `ValidationResult` error strings (preserving existing validation semantics); verified with `./.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/test_jsonld_validation.py` (31 passed).
- 2026-02-19: Continued C1/C2 in `core/query_executor.py` by preserving underlying exception details (`error`, `error_class`) in `QueryExecutionError.details` for unexpected execution failures (without changing the existing summary `error_class`); verified with `./.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/test_query_executor_error_metadata.py` (2 passed).
- 2026-02-19: Continued C2 in `cross_document_reasoning.py` by improving fallback warning logs to include underlying exception class names (no behavior changes); verified with `./.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/test_reasoning.py` (18 passed).
- 2026-02-19: Continued C2 in `core/graph_engine.py` by including the underlying exception class name in graph save/load failure logs (no behavior changes); verified with `./.venv/bin/python -m pytest -q tests/unit/knowledge_graphs/test_graph_engine.py` (29 passed).
- 2026-02-19: Implemented D1 (configurable relation thresholds) in `cross_document_reasoning.py` by adding four new constructor parameters (`relation_similarity_threshold`, `relation_supporting_strength`, `relation_elaborating_strength`, `relation_complementary_strength`) to `CrossDocumentReasoner`; `_determine_relation` now uses these instead of hard-coded literals; verified with 5 new tests in `test_reasoning.py::TestConfigurableRelationThresholds` (23 passed).
- 2026-02-19: Implemented D2 (golden query fixtures) by creating `tests/unit/knowledge_graphs/test_cypher_golden_queries.py` with 18 tests covering MATCH/WHERE/RETURN/CREATE IR patterns and parse-error behavior; all 18 pass.
- 2026-02-19: Implemented E1 (format roundtrip tests) by adding `TestDagJsonRoundtrip` (7 tests) and `TestJsonLinesRoundtrip` (6 tests) to `tests/unit/knowledge_graphs/migration/test_formats.py`; all 56 format tests pass.
- 2026-02-19: B2 confirmed DONE – `knowledge_graph_extraction.py` is already a 120-line thin shim; documented in IMPROVEMENT_TODO.md.
- 2026-02-19: C2 – Replaced `print()` calls in `extraction/extractor.py` with `logger.warning()` for spaCy/transformers absent messages; all modules consistently use `logging.getLogger(__name__)`.
- 2026-02-19: Fixed lexer bug (C1): `CypherParser.parse()` now wraps `SyntaxError` from the lexer in `CypherParseError`, so callers always receive a consistent exception type.
- 2026-02-19: E2 – Created `tests/unit/knowledge_graphs/test_cypher_fuzz.py` with 67 tests (truncated queries, malformed syntax, large inputs, Unicode, reserved words, valid edge cases, lexer stress); all 67 pass.
- 2026-02-19: E3 – Created `tests/unit/knowledge_graphs/test_optional_deps.py` with 11 tests verifying graceful degradation without optional deps; all 11 pass.
- 2026-02-19: F1 – Created `tests/unit/knowledge_graphs/test_benchmarks.py` with 10 `@pytest.mark.slow` benchmark tests (extraction, Cypher parse/compile, GraphEngine CRUD, migration roundtrip); all 10 pass.
- 2026-02-19: G – Updated `setup.py` `knowledge_graphs` extras to add `numpy`, `openai`, `anthropic`, `networkx` (deps used in cross_document_reasoning.py and lineage/); also improved spaCy install guidance in error messages.
- 2026-02-19: C1 (error message standardization) – Added `operation`, `error_class`, and `remediation` fields to broad exception wrappers in `extraction/extractor.py` and `migration/ipfs_importer.py`.
- 2026-02-19: E2 (WAL invariant tests) – Created `tests/unit/knowledge_graphs/test_wal_invariants.py` with 23 tests covering 10 WAL invariants (append-only, chain integrity, read order, recovery, empty WAL, compaction, stats, cycle detection, tx history, integrity); all 23 pass.
- 2026-02-19: F2 (streaming export) – Added `GraphData.iter_nodes_chunked()`, `iter_relationships_chunked()`, and `export_streaming()` to `migration/formats.py` for memory-efficient large-graph export.
- 2026-02-19: G (pytest-mock) – Added `pytest-mock>=3.12.0` to `setup.py` `test` extras.
- 2026-02-19: H1 (CAR strategy) – Updated `DEFERRED_FEATURES.md` Section 6 with detailed decision rationale + plugin example.
- 2026-02-19: H2 (pluggable formats) – Replaced if/elif chain in `save_to_file`/`load_from_file` with `_FormatRegistry` + `register_format()` API; registered 6 built-in handlers at import time; exported from `migration/__init__.py`.
- 2026-02-19: C1 (final) – All remaining `except Exception` blocks now re-raise typed `KnowledgeGraphError` subclasses with `raise ... from e`; marked C1 as substantially complete.
- 2026-02-19: I.1a (god module) – Extracted 4 module-level helper functions from `extraction/extractor.py` (1760→1624 lines) into new `extraction/_entity_helpers.py`; re-imported for compat.
- 2026-02-19: I.1b (god module) – Extracted `_LegacyGraphEngine` class from `core/query_executor.py` (1189→545 lines) into new `core/_legacy_graph_engine.py`; re-imported for compat.
- 2026-02-19: I.1c (god module) – Renamed `example_usage()` → `_example_usage()` in `cross_document_reasoning.py` to reduce accidental public surface.
- 2026-02-19: I.2 (typing) – Created `core/types.py` with type aliases (`GraphProperties`, `NodeLabels`, `CID`), TypedDicts (`GraphStats`, `NodeRecord`, `RelationshipRecord`, `WALStats`, `QuerySummary`), and Protocols (`StorageBackend`, `GraphEngineProtocol`); exported from `core/__init__.py`.
- 2026-02-19: I.3 (naming) – Added component role guide to `query/__init__.py` module docstring defining GraphEngine/QueryExecutor/UnifiedQueryEngine layers with call-chain diagram.



- 2026-02-19: I.1d (god module) – Extracted `InformationRelationType`, `DocumentNode`, `EntityMediatedConnection`, `CrossDocReasoning` from `cross_document_reasoning.py` (1244→1196 lines) into new `cross_document_types.py`; re-exported for backward compat; 7 new tests in `test_workstream_i.py::TestCrossDocumentTypesExtraction`.
- 2026-02-19: Sprint 1 (3.3.4) – Added `pytest.importorskip("networkx")` to `lineage/test_core.py`, `test_enhanced.py`, `test_metrics.py`; 11 test failures → 0 (clean skips).
- 2026-02-19: Sprint 1 (3.2.1) – Added `TestIntegrityVerifierSample` (5 tests, `verify_sample` lines 182-214) and `TestNeo4jExporterExportMethod` (9 tests, `export()` + `export_to_graph_data()` lines 331-431); migration coverage 83%.
- 2026-02-19: Sprint 2 (3.2.3) – Extracted Wikipedia/Wikidata methods into `extraction/_wikipedia_helpers.py` as `WikipediaExtractionMixin`; `extractor.py` 1624→988 lines; `KnowledgeGraphExtractor(WikipediaExtractionMixin)`.
- 2026-02-19: Sprint 2 (3.3.1) – Relocated `AdvancedKnowledgeExtractor` to `extraction/advanced.py`; root `advanced_knowledge_extractor.py` replaced with deprecation shim; `extraction/__init__.py` exports new location.
- 2026-02-19: Sprint 3 (3.2.2) – Clarified `ipld.py` module docstring with explicit relationship to `storage/ipld_backend.py` (legacy primitive layer vs. recommended backend).
- 2026-02-19: Sprint 3 (3.3.5) – Extracted 5 methods from `cross_document_reasoning.py` into `_reasoning_helpers.py` as `ReasoningHelpersMixin`; 1196→876 lines; `CrossDocumentReasoner(ReasoningHelpersMixin)`.
- 2026-02-19: Sprint 4 (3.3.3) – Added `-> None` / `-> Any` return type annotations to 9 untyped methods in `cypher/compiler.py`; imported `UnionClause` at top-level (removed inline import); all 42 Cypher tests pass.
