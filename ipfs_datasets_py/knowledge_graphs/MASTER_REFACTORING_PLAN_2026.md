# Knowledge Graphs Module – Master Refactoring Plan 2026

**Version:** 1.0  
**Status:** ✅ Active  
**Created:** 2026-02-19  
**Last Updated:** 2026-02-19  

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
| Python source files | 76 |
| Total source lines | ~29,600 |
| Test files | 54 |
| Total test lines | ~18,950 |
| Tests collected | 958 |
| Tests passing | 919+ |
| Pre-existing skip/fail | 39 (missing optional deps) |
| Overall test coverage | ~75% |
| Migration module coverage | ~40% → target 70% |
| Documentation files | 30+ markdown files |
| Archive files | 17+ markdown files |

### Files by Size (top candidates for ongoing refactoring)

| File | Lines | Status |
|------|-------|--------|
| `extraction/extractor.py` | 1624 | ⚠️ Still large; Wikipedia methods extractable |
| `ipld.py` | 1425 | ⚠️ Root-level; consider moving to `storage/` |
| `cross_document_reasoning.py` | 1196 | ✅ Reduced (types extracted to `cross_document_types.py`) |
| `migration/formats.py` | 923 | ✅ Acceptable (pluggable registry implemented) |
| `cypher/functions.py` | 917 | ✅ Acceptable (pure function library) |
| `cypher/compiler.py` | 892 | ✅ Acceptable |
| `cypher/parser.py` | 855 | ✅ Acceptable |
| `advanced_knowledge_extractor.py` | 751 | ⚠️ Root-level; consider moving to `extraction/` |

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

---

## 3. Remaining Work (Prioritized)

### 3.1 P0 — Nothing Critical Remaining ✅

All P0 items (broken code, test-blocking failures, INTERNALERROR) are resolved.

---

### 3.2 P1 — High Value, Low Risk

#### 3.2.1 Migration Module Test Coverage (40% → 70%+)

**Status:** 🔄 In progress (partial gap already closed)  
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

**Status:** 🔴 Not started  
**File:** `ipld.py` (1425 lines, root level)  
**Effort:** 4–6 hours  
**Risk:** Medium (import-path change)

`ipld.py` is a large IPLD implementation sitting at the package root, while `storage/ipld_backend.py` is the maintained storage backend.  The root-level file should either:

1. Be moved to `storage/ipld_legacy.py` and re-exported from the root for backward compat, OR
2. Be clearly marked as the low-level IPLD primitive layer with a comment explaining how it relates to `storage/ipld_backend.py`

**Acceptance criteria:** Zero import breakage; clear docstring explaining relationship to `storage/ipld_backend.py`.

---

#### 3.2.3 Wikipedia Extraction Methods — Extract from `extractor.py`

**Status:** 🔴 Not started  
**File:** `extraction/extractor.py` (1624 lines)  
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

**Status:** 🔴 Not started  
**File:** `advanced_knowledge_extractor.py` (751 lines, root level)  
**Effort:** 2–3 hours  
**Risk:** Low

This file contains `AdvancedKnowledgeExtractor` — logically part of the `extraction/` package. Moving it to `extraction/advanced.py` would keep the root namespace clean.

**Acceptance criteria:**
- Root-level import shim preserves backward compatibility
- Module tests pass from new location

---

#### 3.3.2 Extraction Validation Split

**Status:** 🔴 Not started  
**File:** `extraction/validator.py` (670 lines)  
**Effort:** 3–4 hours  
**Risk:** Low

`validator.py` mixes three concerns: SPARQL validation, schema validation, and coverage metrics. Consider splitting into `validator_sparql.py`, `validator_schema.py`, and `validator_metrics.py` (or a `validation/` subpackage).

---

#### 3.3.3 Cypher Module Further Type Annotation

**Status:** 🔴 Not started  
**Files:** `cypher/parser.py`, `cypher/compiler.py`  
**Effort:** 4–6 hours  
**Risk:** Low

Several internal functions still use implicit `Any` where more specific types could be applied. Add type stubs or improve inline annotations to reduce mypy warnings.

---

#### 3.3.4 Lineage Module Optional-Dependency Guard

**Status:** 🔴 Not started  
**Files:** `lineage/core.py`, `lineage/enhanced.py`, `lineage/metrics.py` (line 1 raises if NetworkX absent)  
**Effort:** 2–3 hours  
**Risk:** Low

Currently tests fail with `ImportError: NetworkX is required` instead of being skipped.  Add graceful `try/except ImportError` at the module level and convert hard-failure tests to `@pytest.mark.skip(reason="networkx not installed")`.

**Acceptance criteria:** Lineage tests skip cleanly when NetworkX is absent (no `FAILED`).

---

#### 3.3.5 `cross_document_reasoning.py` Further Reduction

**Status:** 🔴 Not started  
**File:** `cross_document_reasoning.py` (1196 lines)  
**Effort:** 4–5 hours  
**Risk:** Low–Medium

The file is still large. Candidates for extraction:
- `_generate_traversal_paths()` + `_find_multi_hop_connections()` (~150 lines combined) → `_traversal_helpers.py`
- `_generate_llm_answer()` + `_get_llm_router()` (~120 lines combined) → `_llm_helpers.py`

**Acceptance criteria:** `cross_document_reasoning.py` ≤ 900 lines; backward-compat imports maintained.

---

### 3.4 P3 — Future / Nice-to-Have

#### 3.4.1 CAR Format Support

**Status:** Intentionally deferred (see `DEFERRED_FEATURES.md`)  
**Trigger:** When `ipld-car ≥ 1.0` ships a stable Python API  
**Effort:** 10–12 hours

See `DEFERRED_FEATURES.md` Section 6 for plug-in example showing how to add CAR support without modifying core.

---

#### 3.4.2 Distributed Query Execution

**Status:** Intentionally deferred  
**Trigger:** Only needed for graphs with > 100M nodes  
**Effort:** 40–60 hours

---

#### 3.4.3 Additional Cypher Features

**Status:** Backlog (low demand)

- `WITH` clause full support (currently partial)
- `UNWIND` operator
- `FOREACH` for mutations
- `CALL` subquery support

---

#### 3.4.4 Property-Based Tests for Migration Formats

**Status:** 🔴 Not started  
**Effort:** 3–4 hours

Extend `test_cypher_fuzz.py` style to migration formats: generate random `GraphData`, export, re-import, and assert graph equivalence.

---

#### 3.4.5 Async Query Execution Path

**Status:** 🔴 Not started  
**Effort:** 6–8 hours

`UnifiedQueryEngine` currently runs synchronously.  Adding `async def execute_async()` would allow integration with async web frameworks without blocking.

---

## 4. Implementation Order (Recommended)

The following sequence keeps risk low and delivers value incrementally:

```
Sprint 1 (4–6 hours):
  1. Lineage optional-dependency guard (3.3.4)  ← fixes 11 test failures immediately
  2. Migration coverage gap (3.2.1) — add concurrent + error-handling tests

Sprint 2 (6–8 hours):
  3. Wikipedia extraction helpers (3.2.3)  ← brings extractor.py to ≤1200 lines
  4. advanced_knowledge_extractor.py relocation (3.3.1)

Sprint 3 (8–10 hours):
  5. ipld.py clarification / relocation (3.2.2)
  6. cross_document_reasoning.py further reduction (3.3.5)

Sprint 4 (6–8 hours):
  7. Validator module split (3.3.2)
  8. Cypher type annotations (3.3.3)

Future (only if demand):
  9. CAR format support (3.4.1)
  10. Async query path (3.4.5)
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
