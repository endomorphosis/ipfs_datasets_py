# Changelog - Knowledge Graphs Module

All notable changes to the knowledge_graphs module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-02-20

### Bug Fixes

#### `extraction/validator.py`
- **Fixed:** `KnowledgeGraphExtractorWithValidation.validate_during_extraction` now preserves the value passed by the caller instead of silently setting it to `False` when `SPARQLValidator` is not available. The runtime guard `if self.validate_during_extraction and self.validator:` already prevents validation when the validator is absent.
- **Added:** When `validate_during_extraction=True` but `SPARQLValidator` is not installed, `extract_knowledge_graph()` now adds a `validation_metrics` entry with `"skipped": True` and an install-hint `"reason"` field so callers can detect the no-op.

#### `extraction/extractor.py`
- **Fixed:** Removed unused `from transformers import pipeline` inside `_neural_relationship_extraction()`. The import was never used (both REBEL and classification branches call the already-loaded `self.re_model`), but when `transformers` was absent it raised `ImportError` which the broad except-handler caught — silently preventing the classification branch from executing and making mock-based tests unreachable.

#### `query/hybrid_search.py`
- **Fixed:** Replaced three `except anyio.get_cancelled_exc_class():` clauses (in `vector_search`, `_get_embedding`, `_get_neighbors`) with `except asyncio.CancelledError:`. `anyio.get_cancelled_exc_class()` requires an active event loop and raises `anyio.NoEventLoopError` when called from synchronous code (e.g. unit tests). Since these methods are synchronous, using `asyncio.CancelledError` provides identical behavior in asyncio-backed code and is safe in all contexts.
- **Added:** `import asyncio` to module imports.

### Test Results
- Tests: 977 passing, 0 failing, 3 intentional skips
- Previously: 973 passing, **4 failing**, 3 skips

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
