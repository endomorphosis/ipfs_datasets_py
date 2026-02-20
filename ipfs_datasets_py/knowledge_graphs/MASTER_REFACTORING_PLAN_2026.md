# Knowledge Graphs Module – Master Refactoring Plan 2026

**Version:** 1.0  
**Status:** ✅ Active  
**Created:** 2026-02-19  
**Last Updated:** 2026-02-20  

---

## Purpose

This document is the **single authoritative planning reference** for refactoring and quality-improvement work on the `ipfs_datasets_py/knowledge_graphs/` module.  It complements:

- **`MASTER_STATUS.md`** – feature completeness and test-coverage status  
- **`IMPROVEMENT_TODO.md`** – living improvement backlog with per-item status  
- **`DEFERRED_FEATURES.md`** – intentional feature deferrals  
- **`CHANGELOG_KNOWLEDGE_GRAPHS.md`** – user-visible version history

---

## 1. Module Snapshot (2026-02-19)

| Dimension | Metric |
|-----------|--------|
| Python source files | 92 |
| Total source lines | ~34,163 |
| Test files | 64 |
| Total test lines | ~26,000 |
| Tests collected | 1,100+ |
| Tests passing | 1,075+ |
| Pre-existing skip/fail | ~25 (missing optional deps) |
| Overall test coverage | ~78% |
| Migration module coverage | 70%+ ✅ |
| Documentation files | 50+ markdown files |
| Archive files | 17+ markdown files |

### Files by Size (current largest — all at acceptable levels)

| File | Lines | Status |
|------|-------|--------|
| `ipld.py` | 1,440 | ✅ Root-level; docstring clarifies relationship to `storage/ipld_backend.py` |
| `cypher/parser.py` | 1,157 | ✅ Acceptable (all clause features implemented) |
| `cypher/compiler.py` | 1,129 | ✅ Acceptable (all clause features implemented) |
| `ontology/reasoning.py` | 1,120 | ✅ New subpackage; well-structured |
| `extraction/extractor.py` | 1,105 | ✅ Reduced from 1,624 (Wikipedia helpers extracted) |
| `migration/formats.py` | 999 | ✅ Acceptable (pluggable registry implemented) |
| `cypher/functions.py` | 917 | ✅ Acceptable (pure function library) |
| `query/distributed.py` | 916 | ✅ New module; well-structured |
| `reasoning/cross_document.py` | 874 | ✅ Reduced from 1,196 (moved from root, helpers extracted) |
| `extraction/srl.py` | 763 | ✅ New module; well-structured |
| `extraction/advanced.py` | 751 | ✅ Moved from root to `extraction/` |

---

## 2. Completed Work Summary

All work below was completed before this plan was written; it is recorded here to give future contributors a clear starting baseline.

### Phase 1 — Critical Fixes (Complete ✅)
- Replaced bare `except:` / `except Exception` handlers across all 33 affected tool files
- Removed backup files and merge conflict markers
- Fixed pytest `INTERNALERROR` from unsafe `builtins.__import__` mocking
- Fixed `CypherParser.parse()` to wrap lexer `SyntaxError` as `CypherParseError`

### Phase 2 — Public API and Deprecation Cleanup (Complete ✅)
- Defined stable import paths in `README.md`
- Reduced accidental API surface (`__all__` in `__init__.py` exports exceptions only)
- `knowledge_graph_extraction.py` converted to 120-line thin shim with `DeprecationWarning`
- Deprecation story centralized: all legacy modules point to `docs/knowledge_graphs/MIGRATION_GUIDE.md`

### Phase 3 — Error Handling and Observability (Complete ✅)
- All broad `except Exception` blocks now re-raise typed `KnowledgeGraphError` subclasses with `raise ... from e`
- Error messages include `operation`, `error_class`, `remediation` fields
- Replaced all `print()` calls with `logging.getLogger(__name__).warning()`
- Consistent `logging.getLogger(__name__)` usage across all subpackages

### Phase 4 — Correctness Improvements (Complete ✅)
- `cross_document_reasoning.py`: real semantic similarity (not placeholder)
- Configurable relation thresholds (`relation_similarity_threshold` etc.)
- "Golden query" fixtures for Cypher parsing/compilation (18 tests)

### Phase 5 — Testing and Quality Gates (Complete ✅)
- Suite completes without `INTERNALERROR`
- Migration module coverage raised from 40% → 70%+ (error handling + edge case tests)
- Format roundtrip tests (DAG-JSON, JSON-Lines, GraphML/GEXF/Pajek)
- Cypher fuzz tests (67 tests across 7 stress classes)
- WAL invariant tests (23 tests across 10 invariant categories)
- Optional-dependency matrix tests (11 tests)
- Benchmark harness (10 `@pytest.mark.slow` tests)

### Phase 6 — Performance and Memory (Complete ✅)
- `GraphData.iter_nodes_chunked()` / `iter_relationships_chunked()` (chunk_size=500)
- `GraphData.export_streaming()` with 64 KB write buffers
- CEC-style `@cache_formula_comparison` / `@memoize_can_apply` patterns available for future use

### Phase 7 — Dependency and Packaging (Complete ✅)
- `setup.py` `knowledge_graphs` extras include `numpy`, `openai`, `anthropic`, `networkx`
- `pytest-mock>=3.12.0` in `setup.py` `test` extras
- spaCy model install guidance improved in error messages

### Phase 8 — Architectural Improvements (Complete ✅)
- `core/types.py`: type aliases (`GraphProperties`, `NodeLabels`, `CID`), TypedDicts, structural Protocols
- `_FormatRegistry` + `register_format()` API in `migration/formats.py`
- CAR format: documented decision (defer until `ipld-car ≥ 1.0`) with plug-in example
- `extraction/_entity_helpers.py`: 4 helpers extracted from `extractor.py` (1760→1624 lines)
- `core/_legacy_graph_engine.py`: `_LegacyGraphEngine` extracted from `query_executor.py` (1189→545 lines)
- `cross_document_types.py`: 4 data types extracted from `cross_document_reasoning.py` (1244→1196 lines)
- Component role guide added to `query/__init__.py` docstring

### P1–P4 Feature Work (Complete ✅, PR #1085)
- P1: Cypher NOT operator + CREATE relationships
- P2: GraphML / GEXF / Pajek format support
- P3: Neural extraction + aggressive extraction + complex inference
- P4: Multi-hop traversal + LLM integration (OpenAI + Anthropic)

### CAR Format + Expression Evaluator (Complete ✅, 2026-02-19)
- Evaluated `libipld` (Option 1, Rust-backed) vs `ipld-car+ipld-dag-pb` (Option 2, pure Python)
- Implemented CAR save/load using `libipld` (DAG-CBOR) + `ipld-car` (CAR container)
- Fixed `evaluate_compiled_expression` to correctly handle NOT, AND, OR in complex WHERE clauses
- Added `libipld>=3.3.2`, `dag-cbor>=0.3.3` to `setup.py` `ipld` extras
- 18 new tests in `test_car_format.py` (all passing)

---

## 3. Remaining Work (Prioritized)

### 3.1 P0 — Nothing Critical Remaining ✅

All P0 items (broken code, test-blocking failures, INTERNALERROR) are resolved.

---

### 3.2 P1 — High Value, Low Risk

#### 3.2.1 Migration Module Test Coverage (40% → 70%+)

**Status:** ✅ DONE (2026-02-19) — coverage raised to 83%  
**File:** `migration/` package  
**Effort:** 8–12 hours  
**Risk:** Low

**What to add:**
- Concurrent-access tests (`threading.Thread` + multiple importers)
- Schema-mismatch error handling (wrong column names, missing mandatory fields)
- Large-graph streaming import/export tests (>500 nodes, using `export_streaming()`)
- Integrity verifier: checksum mismatch + missing node scenarios
- Schema checker: version-incompatibility path

**Acceptance criteria:** `coverage report --include='*/knowledge_graphs/migration/*'` shows ≥ 70%.

---

#### 3.2.2 `ipld.py` Module Relocation

**Status:** ✅ DONE (2026-02-19) — docstring updated with clear explanation of relationship to `storage/ipld_backend.py` (legacy primitive layer vs. recommended backend)  
**File:** `ipld.py` (1425 lines, root level — file content unchanged, docstring clarified)  
**Effort:** 4–6 hours  
**Risk:** Medium (import-path change)

`ipld.py` is a large IPLD implementation sitting at the package root, while `storage/ipld_backend.py` is the maintained storage backend.  The root-level file should either:

1. Be moved to `storage/ipld_legacy.py` and re-exported from the root for backward compat, OR
2. Be clearly marked as the low-level IPLD primitive layer with a comment explaining how it relates to `storage/ipld_backend.py`

**Acceptance criteria:** Zero import breakage; clear docstring explaining relationship to `storage/ipld_backend.py`.

---

#### 3.2.3 Wikipedia Extraction Methods — Extract from `extractor.py`

**Status:** ✅ DONE (2026-02-19) — created `extraction/_wikipedia_helpers.py` with `WikipediaExtractionMixin`; `extractor.py` 1624→988 lines  
**File:** `extraction/extractor.py` (now 988 lines)  
**Target:** `extraction/_wikipedia_helpers.py`  
**Effort:** 3–4 hours  
**Risk:** Low

Methods `validate_against_wikidata` (~225 lines, line 1174), `_get_wikidata_id` (~35 lines), `_get_wikidata_statements` (~75 lines), and `extract_from_wikipedia` (~190 lines) form a self-contained Wikipedia/Wikidata integration. Extracting them to `extraction/_wikipedia_helpers.py` would bring `extractor.py` to ~1100 lines.

**Acceptance criteria:**
- `extractor.py` ≤ 1200 lines
- Both import paths work (backward-compat re-export)
- All extraction tests continue to pass

---

### 3.3 P2 — Quality Improvements

#### 3.3.1 `advanced_knowledge_extractor.py` Relocation

**Status:** ✅ DONE (2026-02-19) — created `extraction/advanced.py`; root file replaced with deprecation shim  
**File:** `extraction/advanced.py` (canonical), `advanced_knowledge_extractor.py` (shim)  
**Effort:** 2–3 hours  
**Risk:** Low

This file contains `AdvancedKnowledgeExtractor` — logically part of the `extraction/` package. Moving it to `extraction/advanced.py` would keep the root namespace clean.

**Acceptance criteria:**
- Root-level import shim preserves backward compatibility
- Module tests pass from new location

---

#### 3.3.2 Extraction Validation Split

**Status:** 🟡 Deferred — `extraction/validator.py` (670 lines) contains a single class (`KnowledgeGraphExtractorWithValidation`) not clearly separable into SPARQL/schema/metrics concerns without substantial refactoring. Marked for future review when concerns become clearer.  
**File:** `extraction/validator.py` (670 lines)  
**Effort:** 3–4 hours  
**Risk:** Low

`validator.py` mixes three concerns: SPARQL validation, schema validation, and coverage metrics. Consider splitting into `validator_sparql.py`, `validator_schema.py`, and `validator_metrics.py` (or a `validation/` subpackage).

---

#### 3.3.3 Cypher Module Further Type Annotation

**Status:** ✅ DONE (2026-02-19) — added `-> None`, `-> Any` return annotations to all untyped `compiler.py` methods; `UnionClause` added to top-level imports  
**Files:** `cypher/parser.py`, `cypher/compiler.py`  
**Effort:** 4–6 hours  
**Risk:** Low

Several internal functions still use implicit `Any` where more specific types could be applied. Add type stubs or improve inline annotations to reduce mypy warnings.

---

#### 3.3.4 Lineage Module Optional-Dependency Guard

**Status:** ✅ DONE (2026-02-19) — added `pytest.importorskip("networkx")` to `test_core.py`, `test_enhanced.py`, `test_metrics.py`; 11 FAILED → 0 FAILED  
**Files:** `lineage/core.py`, `lineage/enhanced.py`, `lineage/metrics.py` (line 1 raises if NetworkX absent)  
**Effort:** 2–3 hours  
**Risk:** Low

Currently tests fail with `ImportError: NetworkX is required` instead of being skipped.  Add graceful `try/except ImportError` at the module level and convert hard-failure tests to `@pytest.mark.skip(reason="networkx not installed")`.

**Acceptance criteria:** Lineage tests skip cleanly when NetworkX is absent (no `FAILED`).

---

#### 3.3.5 `cross_document_reasoning.py` Further Reduction

**Status:** ✅ DONE (2026-02-19) — created `_reasoning_helpers.py` with `ReasoningHelpersMixin`; 1196→876 lines  
**File:** `cross_document_reasoning.py` (now 876 lines)  
**Effort:** 4–5 hours  
**Risk:** Low–Medium

The file is still large. Candidates for extraction:
- `_generate_traversal_paths()` + `_find_multi_hop_connections()` (~150 lines combined) → `_traversal_helpers.py`
- `_generate_llm_answer()` + `_get_llm_router()` (~120 lines combined) → `_llm_helpers.py`

**Acceptance criteria:** `cross_document_reasoning.py` ≤ 900 lines; backward-compat imports maintained.

---

### 3.4 P3 — Future / Nice-to-Have

#### 3.4.1 CAR Format Support

**Status:** ✅ DONE (2026-02-19)  
**Library decision:** `libipld` (Rust-backed, fast DAG-CBOR) + `ipld-car` (pure-Python CAR encode).  
**Files:** `migration/formats.py` (`_builtin_save_car`, `_builtin_load_car`), `setup.py` (`ipld` extras).  
**Tests:** `tests/unit/knowledge_graphs/test_car_format.py` (18 tests)  
**Install:** `pip install -e ".[ipld]"` adds `libipld>=3.3.2`, `ipld-car`, `dag-cbor>=0.3.3`.

---

#### 3.4.2 Distributed Query Execution

**Status:** ✅ DONE (2026-02-20, sessions 2–4)  
**Files:** `query/distributed.py` — `GraphPartitioner`, `DistributedGraph`, `FederatedQueryExecutor`  
**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (15 tests),
         `test_srl_ontology_distributed_cont.py` (7 tests),
         `test_deferred_session4.py` (13 tests)  
**Capabilities:** HASH/RANGE/ROUND_ROBIN partitioning, serial + parallel + async fan-out, cross-partition entity lookup, rebalancing, streaming, query plan explain.

---

#### 3.4.3 Additional Cypher Features

**Status:** ✅ DONE (2026-02-20) — UNWIND clause + WITH clause + MERGE + REMOVE + IS NULL/IS NOT NULL + XOR + FOREACH + CALL subquery
**Files:** `cypher/ast.py` (`UnwindClause`, `WithClause`, `MergeClause`, `RemoveClause`, `ForeachClause`, `CallSubquery`), `cypher/lexer.py` (`FOREACH` TokenType), `cypher/parser.py` (6 new `_parse_*` methods), `cypher/compiler.py` (6 new `_compile_*` methods), `core/ir_executor.py` (Unwind, WithProject, Merge, RemoveProperty, RemoveLabel, Foreach, CallSubquery ops), `core/expression_evaluator.py` (IS NULL, IS NOT NULL, XOR)
**Tests:**
- `tests/unit/knowledge_graphs/test_unwind_with_clauses.py` (19 tests — UNWIND + WITH + async)
- `tests/unit/knowledge_graphs/test_merge_remove_isnull_xor.py` (27 tests)
- `tests/unit/knowledge_graphs/test_foreach_call_mcp.py` (19 FOREACH+CALL tests)

Implemented:
- **UNWIND**: expands a list literal or node-property list into individual rows
- **WITH**: projects columns into the next query part; supports WHERE filtering on projected names
- **MERGE**: match-or-create / upsert; supports ON CREATE SET and ON MATCH SET
- **REMOVE**: removes a property (`REMOVE n.prop`) or a label (`REMOVE n:Label`)
- **IS NULL / IS NOT NULL**: null-check operators in WHERE
- **XOR**: exclusive-or boolean operator in WHERE
- **FOREACH**: iterates a list and applies mutation clauses to each element
- **CALL { ... }**: executes a subquery and merges its results; supports YIELD for column aliasing

All Cypher clause features are now complete.  No lower-priority items remain.

---

#### 3.4.4 Property-Based Tests for Migration Formats

**Status:** ✅ DONE (2026-02-20)  
**File:** `tests/unit/knowledge_graphs/test_property_based_formats.py` (32 tests across 5 formats + CAR)

Roundtrip tests with randomly generated graphs verify: node count, relationship count, node IDs, empty graph, single node, and 50-node stress cases.

---

#### 3.4.5 Async Query Execution Path

**Status:** ✅ DONE (2026-02-20)  
**File:** `query/unified_engine.py` — `execute_async()` method  
**Tests:** `tests/unit/knowledge_graphs/test_unwind_with_clauses.py::TestAsyncExecute` (3 tests)

`UnifiedQueryEngine.execute_async()` is a thin async wrapper around `execute_query()` that offloads work to `loop.run_in_executor()`, keeping the event loop unblocked for async web frameworks.

---

## 3.5 New Modules Added in v2.1.0

All items below are ✅ **DONE** (2026-02-20):

#### 3.5.1 Semantic Role Labeling (SRL)
**File:** `extraction/srl.py` — `SRLExtractor`, `SRLFrame`, `RoleArgument`  
**Tests:** 32 tests across 3 test files  
**Capabilities:** heuristic + spaCy backends, 10 role types, event-centric KG, batch extraction, temporal graph, round-trip serialization.

#### 3.5.2 OWL/RDFS Ontology Reasoning
**File:** `ontology/reasoning.py` — `OntologySchema`, `OntologyReasoner`, `InferenceTrace`  
**Tests:** 37 tests across 3 test files  
**Capabilities:** 9 OWL/RDFS axiom types, property chains, Turtle round-trip, equivalentClass, merge, explain_inferences (provenance trace).

#### 3.5.3 Reasoning Subpackage
**Files:** `reasoning/__init__.py`, `reasoning/cross_document.py`, `reasoning/helpers.py`, `reasoning/types.py`  
**Description:** Permanent canonical home for cross-document reasoning; root-level files now DeprecationWarning shims.

---

## 4. Implementation Order (Historical — All Complete)

All originally planned sprints are complete as of v2.1.0:

```
Sprint 1 ✅ (2026-02-19):  Lineage dep guard, migration coverage 40%→70%+
Sprint 2 ✅ (2026-02-19):  Wikipedia helpers extracted, advanced_knowledge_extractor.py moved
Sprint 3 ✅ (2026-02-19):  ipld.py docstring clarified, cross_document_reasoning.py reduced
Sprint 4 ✅ (2026-02-19):  Cypher type annotations added

v2.1.0 work ✅ (2026-02-20):
  - CAR format (3.4.1)
  - UNWIND/WITH/MERGE/REMOVE/IS NULL/XOR/FOREACH/CALL subquery (3.4.3)
  - Property-based format tests (3.4.4)
  - Async query execution (3.4.5)
  - Distributed query execution (3.4.2)
  - SRL extraction (3.5.1)
  - OWL/RDFS ontology reasoning (3.5.2)
  - Reasoning subpackage + folder refactoring (3.5.3)
```

---

## 5. Key Invariants to Maintain

When implementing any change from this plan:

1. **100% backward compatibility** — Never break existing import paths. Always provide a re-export shim when moving code.
2. **Test coverage non-regression** — PRs must not decrease overall coverage. Migration module must trend toward 70%+.
3. **Exception taxonomy** — All new exception raises must use specific `KnowledgeGraphError` subclasses with `raise ... from e`.
4. **Logging, not printing** — Use `logging.getLogger(__name__)` everywhere; no bare `print()` in library code.
5. **Type hints** — All new public functions must have complete type annotations.
6. **GIVEN-WHEN-THEN tests** — All new tests must follow repository test format.

---

## 6. Definition of Done (per item)

An improvement item is **Done** when:

- [ ] Code change is implemented
- [ ] All existing tests pass (or pre-existing failures unchanged)
- [ ] New tests added (≥ 1 test per changed public interface)
- [ ] `IMPROVEMENT_TODO.md` item marked `[x]` with status note
- [ ] `CHANGELOG_KNOWLEDGE_GRAPHS.md` updated (for user-visible changes)
- [ ] `MASTER_STATUS.md` updated (for coverage/feature changes)

---

## 7. Documentation Governance

### Canonical documents (keep updated):

| Document | Owner | Update Trigger |
|----------|-------|----------------|
| `MASTER_STATUS.md` | Module team | Any feature/coverage change |
| `IMPROVEMENT_TODO.md` | Module team | Any work item start/complete |
| `CHANGELOG_KNOWLEDGE_GRAPHS.md` | Module team | Any user-visible change |
| `DEFERRED_FEATURES.md` | Module team | Deferral decision changes |
| `MASTER_REFACTORING_PLAN_2026.md` (this file) | Module team | Plan updates |

### Archival policy:

- Session summary documents → `archive/refactoring_history/`  
- Superseded plans → `archive/superseded_plans/`  
- Never create new progress-report markdown files in the active directory; use git commit messages instead

---

## 8. Contact and Review

**Next scheduled review:** Q2 2026 (after v2.0.1 release)  
**Maintained by:** Knowledge Graphs Module Team  
**Questions:** Open a GitHub issue with label `knowledge-graphs`  

---

**Document Version:** 1.0  
**Created:** 2026-02-19  
**Status:** Active — supersedes no prior documents (this is the first consolidated plan)
