# Changelog - Knowledge Graphs Module

All notable changes to the knowledge_graphs module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
