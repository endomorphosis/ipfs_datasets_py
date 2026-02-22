# Changelog - Knowledge Graphs Module

All notable changes to the knowledge_graphs module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.22.11] - 2026-02-22

### Removed — Dead Code in cross_document.py and ir_executor.py (Session 56)

**9 lines of provably unreachable code removed from 2 files.**

#### `reasoning/cross_document.py`

- Removed `if norm_src == 0.0 or norm_tgt == 0.0: return 0.0` guard (2 lines).
  This guard was unreachable: the preceding `if not src_tokens or not tgt_tokens`
  check ensures both token lists are non-empty, so `Counter` values are always ≥ 1
  and both L2 norms are always strictly positive.
- A clarifying comment was added in place of the removed guard.
- **`reasoning/cross_document.py` is now at 100% coverage.**

#### `core/ir_executor.py`

- Removed the `if "." in expr:` / `else:` branching inside `OrderBy make_sort_key`
  (7 lines total):
  - The `var_name, prop_name = expr.split(".", 1)` assignment — those variables were
    never used in the function body.
  - The `try: record.get(expr) / except (AttributeError, KeyError, TypeError): value = None`
    wrapper — `Record.get()` delegates to `dict.get()` and never raises.
  - Both branches performed exactly `value = record.get(expr)`, so they collapsed to
    a single statement.
- **`core/ir_executor.py` is now at 100% coverage.**

### Tests
- Added `tests/unit/knowledge_graphs/test_master_status_session56.py` with **13 invariant
  tests** (2 classes: `TestCrossDocumentZeroNormProof`, `TestIRExecutorOrderByStringExpr`).

## [3.22.10] - 2026-02-22

### Changed — numpy as Default Dependency (Session 55)

**numpy promoted from optional to default (always-installed) dependency.**

#### `setup.py`
- `install_requires`: replaced bare `'numpy'` with versioned markers matching
  `requirements.txt`:
  - `"numpy>=1.21.0,<2.0.0; python_version < '3.14'"`
  - `"numpy>=2.0.0; python_version >= '3.14'"`
- `extras_require['knowledge_graphs']`: removed duplicate `'numpy>=1.21.0'` entry
  (numpy is now in base `install_requires`).

#### `pyproject.toml` (new file)
- Created minimal PEP 517/518 build configuration:
  - `[build-system]`: setuptools>=68 + wheel
  - `[project] dependencies`: same numpy version markers as setup.py / requirements.txt
  - `[project.optional-dependencies] knowledge_graphs`: spacy, networkx, transformers
    (numpy omitted since it is in base deps)
  - `[tool.pytest.ini_options]`: asyncio_mode = "auto"

#### `requirements.txt`
- Already had correct versioned numpy entries — no change needed.

#### Tests
- `test_master_status_session55.py`: 13 verification tests in 4 classes
  - `TestSetupPyNumpyDep`: install_requires version bounds + no-dup in extras
  - `TestPyprojectTomlNumpyDep`: file exists, numpy version bounds, build-system
  - `TestRequirementsTxtNumpyDep`: numpy version bounds
  - `TestNumpyVersionConsistency`: all three files share the same lower bound; numpy importable

**Result: 3,627 pass, 64 skip, 0 fail** (env with networkx+numpy; same 207 missed lines).

---

## [3.22.9] - 2026-02-22

### Fixed — Numpy Skip Guards for Sessions 52/53 (Session 54)

**3 test failures fixed by adding `_skip_no_numpy` marks (no production code changed).**

**Root cause:** `ipld.py` imports `ipfs_datasets_py.vector_stores.ipld`, which has a
hard `import numpy as np` at module level. Tests that reloaded `ipld.py` or imported
`IPLDKnowledgeGraph` from it would fail in environments without numpy installed.

#### Tests updated:
- `test_master_status_session52.py::TestIpldCarAvailable::test_have_ipld_car_true_when_mock_available`
- `test_master_status_session52.py::TestIpldCarAvailable::test_ipld_car_attribute_set_when_available`
- `test_master_status_session53.py::TestGetConnectedEntitiesDepthInvariant::test_get_connected_entities_returns_correct_neighbors`

**Pattern used:** `_numpy_available = bool(importlib.util.find_spec("numpy"))` +
`_skip_no_numpy = pytest.mark.skipif(not _numpy_available, reason="numpy not installed")`
— consistent with sessions 40/41/50.

**Result: 3,490 pass, 77 skip, 0 fail** (base env without numpy).

---

## [3.22.8] - 2026-02-22

### Changed — Dead Code Cleanup + Invariant Tests (Session 53)

**Removed 14 lines of confirmed dead code from 3 files; 15 new invariant tests.**

**Coverage improvement: 213→207 missed lines (−6 dead code lines removed from coverage tracking)**

#### Dead code removed:

1. **`cypher/compiler.py:185-186, 212-213`** (4 lines removed)
   - `if not variable: variable = f"_anon{...}"` after `variable = element.variable or f"_n{i}"`
   - `f"_n{i}"` is always truthy → the guard could never fire

2. **`core/ir_executor.py:433-442`** (8 lines removed)
   - `if value is None and hasattr(record, "_values"): obj = record._values.get(var_name) ...`
   - `Record._values` is a `tuple` (not a dict), so `_values.get()` always raised `AttributeError`
   - The entire block was unreachable before the `except (AttributeError, …)` clause caught it

3. **`ipld.py:753-754`** (2 lines removed)
   - `if not source_result: continue` in `vector_augmented_query`
   - `source_result` is found by searching `graph_results` for an entity_id that was derived from
     the same `graph_results` list — it can never be `None`

4. **`ipld.py:1122-1123`** (2 lines removed)
   - `if depth > max_hops: continue` in `_get_connected_entities` BFS
   - Items are only enqueued when `depth < max_hops` → max queue depth = `max_hops` → guard unreachable

**Files changed:**
- `ipfs_datasets_py/knowledge_graphs/cypher/compiler.py` — removed 4 dead lines
- `ipfs_datasets_py/knowledge_graphs/core/ir_executor.py` — removed 8 dead lines
- `ipfs_datasets_py/knowledge_graphs/ipld.py` — removed 4 dead lines
- `tests/unit/knowledge_graphs/test_master_status_session53.py` — new file, 15 tests
- `ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md` — version 3.22.7→3.22.8
- `ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md` — session 53 log
- `ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` — this entry

**Result: 3,614 pass, 64 skip, 0 fail (base env); 207 missed lines**



### Tests — ImportError Except Branches (Session 52)

**17 new tests** in `test_master_status_session52.py`. No production code changes.

**Coverage improvement: 229→213 missed lines (16 new lines covered)**

- `reasoning/types.py:24-26` — `numpy` ImportError except: `np=None`, `_NpNdarray=None` (3 lines, now 100%)
- `lineage/core.py:18-20` — `networkx` ImportError except: `NETWORKX_AVAILABLE=False`, `nx=None` (3 lines, now 100%)
- `neo4j_compat/driver.py:35-38` — `router_deps` ImportError except: `HAVE_DEPS=False`, stubs set (4 lines, now 100%)
- `reasoning/cross_document.py:31-32` — numpy ImportError except: `np=None` (2 lines, now 99%)
- `reasoning/cross_document.py:64-66` — optimizer ImportError except: `UnifiedGraphRAGQueryOptimizer=None` (3 lines, now 99%)
- `ipld.py:98` — `HAVE_IPLD_CAR=True` when `ipld_car` mock available via `sys.modules` (1 line, now 99%)

**Key technique**: `_reload_with_absent_dep(module_name, absent_deps)` helper reloads a module
with specified deps blocked in `sys.modules` (set to `None`). Critically, also saves/restores the
**parent package attribute** (e.g., `reasoning.cross_document`) to prevent state leakage into
other tests that import the module via `import pkg.submod as m` pattern.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session52.py` — new file, 17 tests
- `ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md` — version 3.22.6→3.22.7
- `ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md` — session 52 log
- `ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` — this entry

## [3.22.6] - 2026-02-22

### Tests — BFS Guard + ImportError Exception Coverage (Session 51)

**13 new tests** in `test_master_status_session51.py`. No production code changes.

**Coverage improvement:**
- `query/hybrid_search.py:217` — BFS already-visited guard now covered; `hybrid_search.py` reaches **100%**. The guard fires when diamond-topology graph puts the same node in `current_level` for hop N+1 after it was already visited during hop N (A→B, A→C, B→C topology).
- `migration/formats.py:914, 921-930, 950-951` — `_builtin_save_car` / `_builtin_load_car` ImportError paths now exercised via `sys.modules` injection (simulating absent libipld/ipld-car).
- `extraction/_entity_helpers.py:117` — Filter logic documented; the actual regex patterns cannot produce <2-char groups in normal use (all use `[A-Z][a-z]+`), confirming line 117 is unreachable in standard execution.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session51.py` — new file, 13 tests
- `ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md` — version 3.22.5→3.22.6, test count updated
- `ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md` — session 51 log entry added
- `ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` — this entry

**Result: 3,582 pass, 64 skip, 0 fail** (base env); 229 missed lines (down from 230).



### Tests — numpy Skip Guards (Session 50)

**No new tests, no production code changes.** Fixed 7 test failures that appeared when networkx is installed (networkx imports numpy as a soft dependency that becomes importable) but numpy is not directly available.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session16.py`
- `tests/unit/knowledge_graphs/test_master_status_session21.py`
- `tests/unit/knowledge_graphs/test_master_status_session33.py`

**Problem 1 (session16, 3 tests):** `TestLineageVisualizerPlotly` tests mock `plotly.graph_objs` (go) but `render_plotly()` also calls `nx.spring_layout()` which requires numpy. The tests called the real `nx.spring_layout` and crashed.

**Fix:** Added `patch("networkx.spring_layout", return_value={node: (x, y)})` to `test_render_plotly_with_mocked_plotly`, `test_render_plotly_with_output_path`, and `test_visualize_lineage_plotly_renderer`.

**Problem 2 (session21, 3 tests):** `TestCrossDocumentReasonerUncoveredPaths` has 3 tests with `import numpy as np` inside the method body. These tests pass when numpy is available but crash with `ModuleNotFoundError` when numpy is absent.

**Fix:** Added `_numpy_available` flag and `_skip_no_numpy` mark at module level; applied `@_skip_no_numpy` to the 3 individual numpy-dependent methods only (9 other tests in the class still run without numpy).

**Problem 3 (session33, 1 test):** `test_numpy_available_flag` in `TestCrossDocumentReasonerMissedPaths` similarly uses `import numpy as np_real` inline.

**Fix:** Added `_numpy_available = bool(importlib.util.find_spec("numpy"))` to the module-level constants (alongside the existing `_rdflib_available`) and applied `@pytest.mark.skipif(not _numpy_available, reason="numpy not installed")` to that one method.

**Verification:**
- Without numpy: 7 previously-failing tests now skip cleanly
- With numpy: all 7 tests continue to pass
- Full suite (base env, networkx installed, numpy absent): **3,448 passed, 74 skipped, 0 failed**

---

## [3.22.4] - 2026-02-22

### Tests — numpy Skip Guards (Session 49)

**No new tests, no production code changes.** Fixed collection errors in two test files.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session41.py`
- `tests/unit/knowledge_graphs/test_master_status_session42.py`

**Problem:** Both files had `import numpy as np` at module level (before `import pytest`), which caused a `ModuleNotFoundError` collection error — not a graceful skip — in environments without numpy installed.

**Fix:** In both files:
1. Moved `import pytest` before the numpy import
2. Replaced `import numpy as np` with `np = pytest.importorskip("numpy")`

This is consistent with the `pytest.importorskip` pattern used throughout the KG test suite for other optional dependencies (`spacy`, `rdflib`, `matplotlib`, `libipld`).

**Verification:**
- With numpy installed: all 91 tests in sessions 41+42 still pass
- Without numpy: sessions 41+42 are skipped cleanly (no collection error)
- Full suite (base env): **3,569 passed, 64 skipped, 0 failed**
- Full suite (all optional deps): **3,626 passed, 7 skipped, 0 failed**

---

## [3.22.3] - 2026-02-22

### Tests — Final Coverage Push (Session 48)

**16 new tests** in `test_master_status_session48.py`. No production code changes.

**New optional deps installed (unlocks more coverage):** `libipld`, `ipld-car`, `dag-cbor`, `multiformats`
- `migration/formats.py` now **100%** — CAR format save/load paths now exercised by existing property-based tests.

**New test groups:**

1. **`cypher/compiler.py:261`** — `_compile_node_pattern` anonymous variable fallback (`_anon{N}`) when both `node.variable` and `default_var` are `None`/empty string (5 tests):
   - Anon variable is generated and registered in `compiler.variables`
   - `ScanLabel` op emitted with auto-generated variable
   - `ScanAll` op emitted when no labels provided
   - Multiple consecutive anon nodes get unique `_anon0`, `_anon1` variables
   - Empty-string `node.variable` also triggers anon generation

2. **`core/expression_evaluator.py:153-163`** — `reverse` and `size` fallback string handlers (8 tests):
   - These handlers run when the function names are temporarily absent from `FUNCTION_REGISTRY`
   - `reverse`: reverses string / returns `None` for non-string / returns `None` for empty args
   - `size`: returns `len()` for strings / lists / tuples; returns `None` for empty args; returns `None` for non-sequence types

3. **`ontology/reasoning.py:828`** — BFS transitive closure cycle guard `if mid in visited: continue` (3 tests):
   - Triggered by A→B→C→B cycle: B is popped from the BFS queue a second time; line 828 fires and skips it
   - BFS terminates cleanly for longer cycles (A→B→C→D→B)
   - No duplicate inferred relationships added despite cycle

**Coverage impact:** `expression_evaluator.py` 97%→**100%**; `ontology/reasoning.py` 99%→**100%**; `migration/formats.py` 98%→**100%**; `compiler.py` misses reduced from 3→2; overall **99%** (159→141 missed lines).

**Result:** 3,626 passing, 7 skipped, 0 failing (with all optional deps installed).

---

## [3.22.2] - 2026-02-22

### Bug Fix — RDF Boolean Serialization Order (Session 47)

**Production bug fixed in `extraction/graph.py`:**

- **Entity properties** (`export_to_rdf` match block, line ~622): `case bool():` was listed AFTER `case int():`. In Python, `bool` is a subclass of `int`, so `case int():` was matching `True`/`False` first, causing boolean properties to be serialized as `XSD.integer` instead of `XSD.boolean`. Fixed by moving `case bool():` before `case int():`.
  - Before: `True` → `"1"^^xsd:integer` (wrong)
  - After: `True` → `"true"^^xsd:boolean` (correct)

- **Relationship properties** (`export_to_rdf` elif block, line ~654): Same issue with `elif isinstance(value, int):` coming before `elif isinstance(value, bool):`. Fixed by moving `elif isinstance(value, bool):` before `elif isinstance(value, int):`.

**New tests** (`test_master_status_session47.py`, 9 tests):
- `TestExportToRdfEntityNonPrimitiveProperty` (4 tests) — list/None/dict/tuple entity properties hit `case _:` catch-all and use `str(value)` fallback
- `TestExportToRdfRelationshipNonPrimitiveProperty` (5 tests) — same for relationship properties + confirm bool correctly uses XSD.boolean

**Coverage impact:** `extraction/graph.py` 99%→**100%**; overall 98%→**99%** (203→159 missed lines)

**Result:** 3,591 passing, 26 skipped, 0 failing (with matplotlib+scipy+plotly+rdflib); 3,553/55/0 in base environment.

---

## [3.22.1] - 2026-02-22

### Bug Fixes — rdflib Optional Dependency Skip Guards (Session 46)

- **`test_master_status_session33.py`** — Added `_rdflib_available = bool(importlib.util.find_spec("rdflib"))` + `@pytest.mark.skipif(not _rdflib_available, reason="rdflib not installed")` guards to 2 tests that call `export_to_rdf()`: `test_export_to_rdf_entity_boolean_property_uses_xsd_boolean` and `test_export_to_rdf_relationship_boolean_property_uses_xsd_boolean`.
- **`test_master_status_session37.py`** — Added matching class-level `@pytest.mark.skipif` guard to `TestKnowledgeGraphExportBooleanProperty` class.
- **Result:** 3,553 passing, 55 skipped (intentional), 0 failing in base environment (no rdflib).

### Documentation Updates

- **`ROADMAP.md`** — Updated current version from 2.1.0 to v3.22.0; added v3.22.0 section; updated release table; updated community priority list to note 99%+ coverage achieved.
- **`MASTER_STATUS.md`** — Updated "Last Updated" to session 46; corrected test count to 3,553/55/0; added sessions 33-46 to test file list.
- **`IMPROVEMENT_TODO.md`** — Added sessions 33-46 detailed log entries.

---

## [3.22.0] - 2026-02-22

### Bug Fixes — Async Safety + Test Environment Hardening (Session 45)

This release fixes 95 pre-existing test failures across two categories: production async-safety bugs and test skip guards for optional dependencies.

#### Production Bug Fixes

- **`anyio.get_cancelled_exc_class()` outside async context** — Fixed in 4 modules:
  - `query/unified_engine.py`: added `_cancelled_exc_class()` helper that falls back to `asyncio.CancelledError` when no event loop is active; replaced 5 `except anyio.get_cancelled_exc_class():` calls.
  - `transactions/wal.py`: same helper added; replaced 6 calls.
  - `storage/ipld_backend.py`: same helper added; replaced 3 calls.
  - `query/hybrid_search.py`: same helper added; replaced 3 calls.
  - Root cause: newer anyio versions raise `anyio.NoEventLoopError` when `get_cancelled_exc_class()` is called outside an async event loop, breaking synchronous error-handling paths.

- **`ipld.py` missing `ipld_car` module attribute** — Added `ipld_car = None` to the `except ImportError` block so the module-level attribute is always defined (patchable) even when `ipld-car` is not installed. Tests patching `_IPLD.ipld_car` now work correctly.

#### Test Environment Fixes

- **`test_master_status_session43.py`** — Added `pytest.importorskip("spacy")` at module level; all 32 tests are properly skipped when spaCy is absent.
- **`test_master_status_session44.py`** — Added per-class `@_skip_no_spacy` marks for `TestExtractorSpacyModelOSError` and `TestExtractEntitiesLowConfidenceSkip`; non-spaCy tests continue running.
- **`test_master_status_session15.py`** — Added `@_skip_no_matplotlib` decorator to `TestLineageVisualizerRenderNetworkx` class and two methods in `TestVisualizeLinkageFunction`; non-matplotlib tests continue running.
- **`test_master_status_session37.py`** — Added `@pytest.mark.skipif` to `test_render_networkx_ghost_node_gets_lightgray`.
- **`test_master_status_session40.py`** — Added `@_skip_no_libipld` decorator to `TestBuiltinCarSaveLoad` class; non-libipld tests continue running.
- **`test_master_status_session21.py`** — Fixed `test_default_query_optimizer_is_missing_stub` to patch `UnifiedGraphRAGQueryOptimizer` to `None` before constructing `CrossDocumentReasoner`; test now works regardless of whether GraphRAG deps are installed.
- **`test_master_status_session42.py`** — Fixed `TestFromCarEmptyRoots` and `TestExportToCar` to also patch `HAVE_IPLD_CAR = True` alongside `ipld_car`; tests now reach the actual CAR logic instead of the early ImportError guard.

**Result:** 3,567 passing (in full-deps env), 41 skipped (all intentional), 0 failing. Base env without rdflib: 3,553 pass, 55 skip (rdflib skip guards added in v3.22.1).

---

## [2.1.0] - 2026-02-20

### Cypher Feature Completion + Folder Refactoring

This release completes all Cypher clause features, restructures the module folder to permanent canonical subpackage locations, and adds three new MCP tools.

### Added

#### Cypher Clauses (All Clauses Now Complete)
- **FOREACH clause**: `FOREACH (variable IN list | clause*)` — iterate a list and apply mutation clauses (CREATE, SET, MERGE, DELETE, REMOVE) to each element.
- **CALL subquery**: `CALL { inner_query } [YIELD ...]` — execute an inner query and merge its results into the outer query's bindings. Supports YIELD aliasing.
- Lexer: `FOREACH` added to `TokenType` enum and `KEYWORDS` dictionary
- AST: `ForeachClause(variable, expression, body)` and `CallSubquery(body, yield_items)` dataclasses
- Parser: `_parse_foreach()` and `_parse_call_subquery()` methods
- Compiler: `_compile_foreach()` and `_compile_call_subquery()` methods
- IR executor: `Foreach` and `CallSubquery` op handlers

#### New `reasoning/` Subpackage
- `reasoning/__init__.py` — re-exports all public names from sub-modules
- `reasoning/cross_document.py` — canonical home for `CrossDocumentReasoner`
- `reasoning/helpers.py` — canonical home for `ReasoningHelpersMixin`
- `reasoning/types.py` — canonical home for `InformationRelationType`, `DocumentNode`, etc.
- `reasoning/README.md` — subpackage documentation

#### New MCP Graph Tools
- `mcp_server/tools/graph_tools/graph_srl_extract.py` — SRL extraction tool
- `mcp_server/tools/graph_tools/graph_ontology_materialize.py` — OWL/RDFS inference tool
- `mcp_server/tools/graph_tools/graph_distributed_execute.py` — distributed Cypher tool

#### KnowledgeGraphManager Extensions
- `extract_srl(text, return_triples, return_temporal_graph)` — SRL extraction
- `ontology_materialize(graph_name, schema, check_consistency, explain)` — ontology inference
- `distributed_execute(query, num_partitions, partition_strategy, parallel, explain)` — distributed query

#### Folder Restructuring (Permanent Locations)
- `cross_document_reasoning.py` → `reasoning/cross_document.py`
- `_reasoning_helpers.py` → `reasoning/helpers.py`
- `cross_document_types.py` → `reasoning/types.py`
- `cross_document_lineage.py` → `lineage/cross_document.py`
- `cross_document_lineage_enhanced.py` → `lineage/cross_document_enhanced.py`
- `query_knowledge_graph.py` → `query/knowledge_graph.py`
- `sparql_query_templates.py` → `query/sparql_templates.py`
- `finance_graphrag.py` → `extraction/finance_graphrag.py`

### Changed
- All root-level moved files replaced with `DeprecationWarning` shims (100% backward compatible)
- `query/__init__.py` updated with `knowledge_graph` and `sparql_templates` exports
- `extraction/__init__.py` updated with `finance_graphrag` exports
- `lineage/__init__.py` updated with `cross_document` and `cross_document_enhanced` exports
- `graph_tools/__init__.py` updated with 3 new MCP tool exports
- All READMEs (module root, query/, extraction/, lineage/) updated for v2.1.0

### Tests
- 32 new tests in `tests/unit/knowledge_graphs/test_foreach_call_mcp.py`
- 26 pass, 6 skipped (anyio not installed in CI)
- Total: 1075+ passing (up from 1067)

---

## [2.0.0] - 2026-02-17

### Major Refactoring and Documentation Update

This release represents a comprehensive refactoring and documentation effort for the knowledge_graphs module, bringing it to production-ready status with extensive documentation, comprehensive testing, and clear roadmap.

### Added

#### Documentation (222KB Total)
- **USER_GUIDE.md** (30KB) - Comprehensive user guide with 10 sections and 40+ examples
  - Quick start, core concepts, extraction workflows
  - Query patterns, storage options, transaction management
  - Integration patterns, production best practices
  - Troubleshooting guide, examples gallery

- **API_REFERENCE.md** (35KB) - Complete API documentation
  - Extraction API (Entity, Relationship, KnowledgeGraph, Extractor)
  - Query API (UnifiedQueryEngine, QueryResult, GraphRAG, HybridSearch)
  - Storage API (IPLDBackend, IPFS integration)
  - Transaction API (TransactionManager, ACID transactions)
  - Cypher Language Reference with supported features
  - Utility and compatibility APIs
  - Error handling with exception types

- **ARCHITECTURE.md** (24KB) - Comprehensive architecture documentation
  - Module architecture (14 subdirectories, 4-layer design)
  - Design patterns (8 patterns with examples)
  - Component internals (extraction, query, storage, transactions)
  - Data flow diagrams, performance characteristics
  - Scalability patterns, extension points
  - Integration architecture, future enhancements

- **MIGRATION_GUIDE.md** (15KB) - Migration and compatibility guide
  - Known limitations with workarounds
  - Feature support matrix
  - Breaking changes documentation
  - Compatibility matrix (Python, dependencies, environment)
  - Neo4j to IPFS migration guide (4-step workflow)
  - Migration checklist, common issues with solutions
  - Deprecation timeline (v2.0 → v2.5 → v3.0)

- **CONTRIBUTING.md** (23KB) - Development guidelines
  - Advanced development patterns
  - Performance guidelines (temperature tuning, batch processing)
  - Security best practices (input validation, type safety)
  - Common pitfalls with solutions
  - Module-specific conventions
  - Debugging tips, release process
  - Maintenance guidelines

#### Subdirectory Documentation (81KB Total)
- **cypher/README.md** (8.5KB) - Cypher query language implementation
- **migration/README.md** (10.8KB) - Migration tools and workflows
- **core/README.md** (11.5KB) - Core graph database engine
- **neo4j_compat/README.md** (12KB) - Neo4j driver compatibility (~80%)
- **lineage/README.md** (11.9KB) - Cross-document entity tracking
- **indexing/README.md** (12.8KB) - Index management (20-100x speedup)
- **jsonld/README.md** (13.8KB) - W3C JSON-LD 1.1, RDF serialization

#### Code Documentation (14KB)
- **Future Roadmap** - Documented 7 planned features (v2.1 → v3.0)
  - v2.1.0 (Q2 2026): NOT operator, Relationship creation
  - v2.5.0 (Q3-Q4 2026): Neural extraction, spaCy parsing, SRL
  - v3.0.0 (Q1 2027): Multi-hop traversal, LLM integration

- **Enhanced Docstrings** - Comprehensive documentation for 5 complex methods
  - `_determine_relation()` in cross_document_reasoning.py
  - `_generate_traversal_paths()` in cross_document_reasoning.py
  - `_split_child()` in indexing/btree.py
  - `_calculate_score()` in indexing/specialized.py
  - `_detect_conflicts()` in transactions/manager.py

#### Testing (38KB Test Code)
- **Migration Module Tests** - 27 comprehensive tests for 70%+ coverage
  - Neo4j Export: 7 tests (basic, relationships, batching, errors, properties, deduplication)
  - IPFS Import: 7 tests (CID, file, relationships, errors, IPLD, metadata)
  - Format Conversion: 6 tests (JSON, CSV, unsupported formats)
  - Schema Checking: 4 tests (validation, migration detection/execution)
  - Integrity Verification: 3 tests (validation, broken references, repair)

- **Integration Tests** - 9 end-to-end workflow tests
  - Extract → Validate → Query Pipeline: 3 tests
  - Neo4j → IPFS Migration Workflow: 3 tests
  - Multi-document Reasoning Pipeline: 3 tests

### Changed

#### Documentation Improvements
- Documented 2 NotImplementedError instances as known limitations
- Added CSV/JSON workarounds for unsupported formats (GraphML, GEXF, Pajek)
- Enhanced future enhancements section with technical specifications
- Added roadmap section with version timeline and priorities

#### Code Quality
- Enhanced docstrings now include:
  - Algorithm explanations with complexity analysis
  - Usage examples with realistic scenarios
  - Production considerations and best practices
  - Visual aids (ASCII diagrams where applicable)
  
### Fixed
- Clarified Cypher language limitations (NOT operator, CREATE relationships)
- Documented extraction limitations with future solutions
- Added workarounds for all known limitations

### Performance
- Documented performance characteristics:
  - Extraction: 2-100x speedup with parallel processing
  - Query: <100ms hybrid search target
  - Indexing: 20-100x query speedup with proper indexes
  - Parallel Processing: 4-16x gains with multiprocessing

### Security
- Documented security best practices:
  - Input validation patterns
  - Type safety with type hints
  - Exception handling best practices
  - Resource cleanup patterns

### Compatibility
- **Python:** 3.8+ supported, 3.10+ recommended
- **Neo4j API:** ~80% compatibility
- **W3C Standards:** JSON-LD 1.1 compliant
- **RDF Formats:** 5 formats supported (Turtle, N-Triples, RDF/XML, JSON-LD, N-Quads)

## [1.0.0] - Previous Release

### Initial Release
- Basic knowledge graph extraction
- IPLD storage support
- Cross-document reasoning
- Legacy API

---

## Migration Notes

### From v1.x to v2.0

**Breaking Changes:**
- Legacy IPLD API deprecated (use Neo4j-compatible API)
- Some extraction parameters renamed for clarity
- Budget presets modified for better defaults

**Migration Steps:**
1. Update imports to use new API
2. Replace legacy IPLD calls with Neo4j-compatible API
3. Update budget configurations if using custom settings
4. Test extraction and query workflows
5. Update deployment configurations

See MIGRATION_GUIDE.md for detailed migration instructions.

---

## Statistics

### Documentation Coverage
- **Total:** 222KB production-ready documentation
- **Major Docs:** 5 comprehensive guides (127KB)
- **Module Docs:** 7 subdirectory READMEs (81KB)
- **Code Docs:** Enhanced docstrings and roadmap (14KB)

### Test Coverage
- **Migration Module:** 40% → 70%+ (27 new tests)
- **Integration Tests:** 9 end-to-end workflow tests
- **Total New Tests:** 36 comprehensive tests

### Quality Metrics
- **Code Examples:** 150+ working examples
- **Reference Tables:** 60+ comparison and feature tables
- **Standards Compliance:** W3C JSON-LD 1.1, Neo4j API ~80%
- **Breaking Changes:** Documented with migration paths

---

## Roadmap

### v2.1.0 (Q2 2026) - Query Language Enhancement
- NOT operator support in Cypher
- CREATE relationship statement support
- Enhanced query optimization

### v2.5.0 (Q3-Q4 2026) - Advanced Extraction
- Neural relationship extraction
- Aggressive extraction with spaCy dependency parsing
- Complex relationship inference with Semantic Role Labeling (SRL)

### v3.0.0 (Q1 2027) - Advanced Reasoning
- Multi-hop graph traversal for indirect connections
- LLM API integration (OpenAI, Anthropic, local models)
- Advanced temporal reasoning
- Federated query support

---

## Contributors

This refactoring effort involved comprehensive documentation, testing, and code quality improvements across the entire knowledge_graphs module.

**Refactoring Statistics:**
- Duration: 30 hours across 6 sessions
- Files Modified: 20+ documentation and code files
- New Content: 260KB (222KB docs + 38KB tests)
- Commits: 13 comprehensive commits

---

For detailed information about any feature or change, see the corresponding documentation files in the `docs/knowledge_graphs/` directory.
