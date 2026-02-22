# Knowledge Graphs - Development Roadmap

**Last Updated:** 2026-02-22  
**Current Version:** 3.22.14  
**Status:** Production Ready (99.99% test coverage)

---

## Overview

This roadmap outlines planned features and improvements for the knowledge_graphs module. All dates are estimates and subject to change based on community feedback and priorities.

**Note (2026-02-18):** This roadmap is aspirational. For the most accurate, current view of what’s implemented vs. missing (including known limitations and test coverage), see **[MASTER_STATUS.md](./MASTER_STATUS.md)**.

---

## Version 2.0.1 (Q2 2026) - Bug Fixes & Polish

**Target Release:** May 2026  
**Focus:** Production hardening and test coverage

### Planned Work
- [x] Increase migration module test coverage from 40% to 70%+ ✅ Done in v2.1.0
- [x] Add comprehensive error handling tests ✅ Done
- Performance profiling and optimization for large graphs (>100k nodes)
- Memory usage optimization for batch operations

---

## Version 2.1.0 (2026-02-20) - ✅ RELEASED

**Released:** 2026-02-20  
**Focus:** Cypher language completion + folder refactoring + advanced features

### Delivered Features

#### 1. Cypher Clause Completion ✅
All Cypher clauses now implemented: NOT, CREATE relationships, UNWIND, WITH, MERGE, REMOVE, IS NULL/IS NOT NULL, XOR, FOREACH, CALL subquery.

#### 2. Folder Refactoring ✅
All root-level modules moved to canonical subpackage locations. New `reasoning/` subpackage created. All old paths preserved as DeprecationWarning shims.

#### 3. SRL Extraction ✅
**Status:** ✅ Delivered in v2.1.0 (2026-02-20)  
`extraction/srl.py` — `SRLExtractor` with heuristic + spaCy backends, 10 semantic role types, event-centric KG construction, temporal graph, batch extraction.

#### 4. OWL/RDFS Ontology Reasoning ✅
**Status:** ✅ Delivered in v2.1.0 (2026-02-20)  
`ontology/reasoning.py` — `OntologySchema` + `OntologyReasoner` with 9 axiom types, property chains, Turtle round-trip, inference trace/provenance.

#### 5. Distributed Query Execution ✅
**Status:** ✅ Delivered in v2.1.0 (2026-02-20)  
`query/distributed.py` — `GraphPartitioner` + `FederatedQueryExecutor` with HASH/RANGE/ROUND_ROBIN, parallel + async fan-out, streaming, query plans.

#### 6. CAR Format ✅
**Status:** ✅ Delivered in v2.1.0 (2026-02-19)  
`migration/formats.py` — CAR save/load via `libipld` + `ipld-car`.

#### 7. New MCP Tools ✅
`graph_srl_extract`, `graph_ontology_materialize`, `graph_distributed_execute`

### Success Criteria — All Met ✅
- All Cypher clauses implemented
- SRL, OWL, distributed, CAR all implemented
- 1,075+ tests passing (~78% coverage)
- Complete documentation up to date

---

## Version 2.2.0 (Q3 2026) - Migration Enhancement (CANCELLED: delivered in v2.0.0)

**Target Release:** August 2026  
**Focus:** Additional data format support

### Planned Features

#### 1. GraphML Format Support
**Status:** ✅ Delivered in v2.0.0 (PR #1085)  
**Priority:** Medium  
**Description:** Import/export GraphML format

**Currently:** Raises NotImplementedError  
**Target:** Full read/write support

#### 2. GEXF Format Support
**Status:** ✅ Delivered in v2.0.0 (PR #1085)  
**Priority:** Medium  
**Description:** Import/export GEXF (Gephi) format

**Currently:** Raises NotImplementedError  
**Target:** Full read/write support

#### 3. Pajek Format Support
**Status:** ✅ Delivered in v2.0.0 (PR #1085)  
**Priority:** Low  
**Description:** Import/export Pajek format

**Currently:** Raises NotImplementedError  
**Target:** Basic read support

#### 4. Migration Performance
**Status:** Planned  
**Priority:** High  
**Description:** Optimize large graph migrations

**Improvements:**
- Streaming import/export (reduce memory usage)
- Parallel processing for large datasets
- Progress tracking and resumable migrations
- Validation and integrity checking

### Success Criteria
- GraphML, GEXF formats fully supported
- Pajek format read support
- Migration performance 2-3x faster
- Handles graphs with 1M+ nodes

---

## Version 2.5.0 (Q3-Q4 2026) - Advanced Extraction (CANCELLED: delivered in v2.0.0)

**Target Release:** November 2026  
**Focus:** Machine learning-powered entity/relationship extraction

### Planned Features

#### 1. Neural Relationship Extraction
**Status:** ✅ Delivered in v2.0.0 (PR #1085)  
**Priority:** Medium  
**Description:** Use neural networks for relationship extraction

**Approach:**
- Pre-trained transformer models (BERT, RoBERTa)
- Fine-tuning on domain-specific data
- Confidence scoring
- Fallback to rule-based extraction

**Benefits:**
- More accurate relationship detection
- Better handling of complex sentences
- Domain adaptation capability

#### 2. spaCy Dependency Parsing Integration
**Status:** Planned  
**Priority:** Medium  
**Description:** Leverage spaCy's dependency parser

**Note:** spaCy is already installed but not actively used

**Features:**
- Subject-verb-object extraction
- Compound noun handling
- Improved entity resolution
- Context-aware extraction

#### 3. Semantic Role Labeling (SRL)
**Status:** ✅ Delivered in v2.1.0 (2026-02-20)  
**Priority:** Low  
**Description:** Advanced semantic analysis for extraction

**Implementation (extraction/srl.py):**
- Heuristic SVO extraction (no external deps) + spaCy dependency-parse backend
- Frame-semantic parsing with 10 role types
- Event extraction and temporal graph construction
- No AllenNLP dependency required — pure-Python heuristic backend always available

#### 4. Confidence Scoring Improvements
**Status:** Planned  
**Priority:** High  
**Description:** Enhanced confidence metrics

**Features:**
- Multi-source confidence aggregation
- Probabilistic relationship scoring
- Quality metrics for extracted graphs
- Uncertainty quantification

### Success Criteria
- Neural extraction option available
- spaCy integration functional
- SRL experimental implementation
- Confidence scoring documented
- Performance benchmarks vs. rule-based

---

## Version 3.0.0 (Q1 2027) - Advanced Reasoning (CANCELLED: delivered in v2.0.0)

**Target Release:** February 2027  
**Focus:** Graph reasoning and AI integration

### Planned Features

#### 1. Multi-hop Graph Traversal
**Status:** ✅ Delivered in v2.0.0 (PR #1085)  
**Priority:** High  
**Description:** Advanced graph reasoning capabilities

**Currently:** Single-hop traversal only  
**Target:** N-hop traversal with path analysis

```cypher
// Example: Find indirect connections
MATCH path = (a:Person)-[*1..5]-(b:Person)
WHERE a.name = 'Alice' AND b.name = 'Charlie'
RETURN path, length(path)
```

**Features:**
- Shortest path algorithms
- All paths enumeration
- Path filtering and ranking
- Graph pattern matching

#### 2. LLM API Integration
**Status:** ✅ Delivered in v2.0.0 (PR #1085)  
**Priority:** High  
**Description:** Integration with large language models

**Supported Providers:**
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Local models (Llama, Mistral)

**Use Cases:**
- Natural language query translation
- Entity/relationship extraction enhancement
- Graph question answering
- Semantic similarity computation

#### 3. Advanced Inference Rules
**Status:** ✅ Delivered in v2.1.0 (2026-02-20)  
**Priority:** Medium  
**Description:** Automated reasoning over knowledge graphs via OWL/RDFS ontology reasoning

**Implementation (ontology/reasoning.py):**
- 9 axiom types: subClassOf, subPropertyOf, transitive, symmetric, inverseOf, domain, range, disjointWith, propertyChainAxiom
- Fixpoint materialize loop
- Consistency checking
- Inference trace/provenance (`explain_inferences`)

#### 4. Distributed Query Execution
**Status:** ✅ Delivered in v2.1.0 (2026-02-20)  
**Priority:** Low  
**Description:** Scale to large graphs with partitioned execution

**Implementation (query/distributed.py):**
- HASH, RANGE, ROUND_ROBIN partitioning
- Serial + thread-pool + async fan-out
- Cross-partition entity lookup
- Query plan explain + streaming results

### Success Criteria
- Multi-hop traversal implemented
- LLM integration functional
- Basic inference rules working
- Distributed execution prototype
- Comprehensive examples and docs

---

## Version 3.22.0 (2026-02-22) - ✅ RELEASED

**Released:** 2026-02-22  
**Focus:** Comprehensive coverage push, async bug fixes, and test quality hardening

### Delivered Features

#### 1. Comprehensive Coverage Push (Sessions 33–45) ✅
All modules at 99%+ coverage. 3,553 tests passing, 55 skipped, 0 failing.
- `transactions/wal.py` — asyncio.CancelledError re-raises now covered
- `extraction/extractor.py` — 73% → 98% with spaCy paths covered
- `extraction/entities.py` + `extraction/relationships.py` — `extraction_method` field added
- `ipld.py` — legacy IPLD module fully covered (73 new tests)
- All remaining single-line misses across 30+ modules resolved

#### 2. Async Context Bug Fixes ✅
`anyio.get_cancelled_exc_class()` called in synchronous methods without an event loop now handled gracefully in 4 modules:
- `query/unified_engine.py` — `_cancelled_exc_class()` helper
- `transactions/wal.py` — `_cancelled_exc_class()` helper
- `storage/ipld_backend.py` — `_cancelled_exc_class()` helper
- `query/hybrid_search.py` — `_cancelled_exc_class()` helper

#### 3. Optional Dependency Skip Guards ✅
All tests that require optional deps now have proper `@pytest.mark.skipif` guards:
- spaCy tests: `@_skip_no_spacy` (sessions 43, 44)
- matplotlib tests: `@_skip_no_matplotlib` (sessions 15, 37)
- libipld tests: `@_skip_no_libipld` (session 40)
- rdflib tests: `@pytest.mark.skipif(not _rdflib_available, ...)` (sessions 33, 37)

#### 4. Production Bug Fixes ✅
- `extraction/extractor.py` — spaCy v3 `ent._.get()` 1-arg API fixed
- `ipld.py` — `ipld_car = None` attribute added for patchability

### Success Criteria — All Met ✅
- 99%+ coverage across all modules (vs. target of 90%)
- 3,553 tests passing, 55 cleanly skipped, 0 failing
- All async cancellation bugs fixed
- All optional-dep tests properly guarded

---

## Version 3.22.2 (2026-02-22) - ✅ RELEASED

**Released:** 2026-02-22  
**Focus:** Production bug fixes (sessions 47–48) + final coverage push

### Delivered Features

#### 1. RDF Boolean Serialization Bug Fix (Session 47) ✅
`extraction/graph.py` `export_to_rdf()` now correctly serializes boolean values as `XSD.boolean` instead of `XSD.integer`. Root cause: Python's `bool` is a subclass of `int`, so `case int():` matched `True`/`False` before `case bool():` could. Fixed by reordering both the `match` block and the `elif` chain.

#### 2. Final Coverage Push (Sessions 47–48) ✅
- `extraction/graph.py`: 80% → **100%**
- `core/expression_evaluator.py`: 97% → **100%**
- `ontology/reasoning.py`: 99% → **100%**
- `migration/formats.py`: 98% → **100%** (via libipld+ipld-car+dag-cbor+multiformats)
- `cypher/compiler.py`: 3 → 2 missed lines
- **Overall: 99%, 141 missed lines** (108 spaCy-only, 33 dead code)

### Success Criteria — All Met ✅
- 3,626 tests passing, 7 skipped, 0 failing (with all optional deps)
- `extraction/graph.py` boolean serialization bug fixed
- All 100%-target modules achieved

---

## Version 3.22.3 (2026-02-22) - ✅ RELEASED

**Released:** 2026-02-22  
**Focus:** Test infrastructure hardening (session 49)

### Delivered

#### 1. numpy Skip Guards (Session 49) ✅
`test_master_status_session41.py` and `test_master_status_session42.py` had `import numpy as np` at module level, causing collection errors (not graceful skips) in environments without numpy. Fixed by replacing with `np = pytest.importorskip("numpy")`.

### Result
- Base env (without numpy/matplotlib/rdflib/etc): **3,569 passed, 64 skipped, 0 failed**
- Full env (all optional deps installed): **3,626 passed, 7 skipped, 0 failed**

---

## Long-Term Vision (v4.0+)

### Potential Features
- Real-time graph streaming
- Temporal graph databases
- Graph neural networks integration
- Advanced visualization tools
- GraphQL API support
- Blockchain integration for provenance
- Federated knowledge graphs
- Zero-knowledge proof support

### Research Areas
- Quantum algorithms for graph problems
- Neuromorphic computing for graph traversal
- Knowledge graph completion with AI
- Explainable AI over knowledge graphs

---

## Community Contributions

We welcome community contributions! Here's how you can help:

### Priority Areas
1. **Test Coverage** - ✅ 99%+ achieved — focus on optional-dep integration tests
2. **Documentation** - More examples and tutorials
3. **Performance** - Optimization and benchmarking for large graphs (>100k nodes)
4. **Features** - Implement long-term roadmap items (v4.0+)

### How to Contribute
See [CONTRIBUTING.md](../../docs/knowledge_graphs/CONTRIBUTING.md) for guidelines.

### Feature Requests
Open an issue on GitHub with:
- Use case description
- Expected behavior
- Code examples
- Priority justification

---

## Versioning Strategy

We follow [Semantic Versioning](https://semver.org/):

- **Major (X.0.0):** Breaking API changes
- **Minor (2.X.0):** New features, backwards compatible
- **Patch (2.0.X):** Bug fixes, performance improvements

### Deprecation Policy
- Features marked deprecated in version N
- Warnings issued in N and N+1
- Removed in N+2 (minimum 6 months notice)

---

## Release Schedule

| Version | Target Date | Status | Focus |
|---------|-------------|--------|-------|
| 2.0.0 | 2026-02-17 | ✅ Released | Documentation & Testing |
| 2.0.1 | May 2026 | ✅ Delivered in v2.1.0 | Bug Fixes & Coverage |
| 2.1.0 | 2026-02-20 | ✅ Released | Cypher completion, SRL, OWL, Distributed, CAR, Folder refactoring |
| 2.2.0 | August 2026 | ✅ Cancelled (delivered in 2.0.0) | Migration Enhancement |
| 2.5.0 | November 2026 | ✅ Cancelled (delivered in 2.0.0/2.1.0) | Advanced Extraction |
| 3.0.0 | February 2027 | ✅ Cancelled (delivered in 2.0.0/2.1.0) | Advanced Reasoning |
| 3.22.0 | 2026-02-22 | ✅ Released | Comprehensive coverage push: 3,553 tests passing, 55 skipped; 99%+ coverage across all modules; anyio async-context bug fixes; spaCy/matplotlib/rdflib optional-dep skip guards |
| 3.22.1 | 2026-02-22 | ✅ Released | rdflib optional-dep skip guards (session46); ROADMAP.md updated to v3.22.0 |
| 3.22.2 | 2026-02-22 | ✅ Released | Bug fix: RDF boolean serialization order (bool before int) in export_to_rdf (session47); extraction/graph.py 100% |
| 3.22.3 | 2026-02-22 | ✅ Released | Final coverage push: migration/formats.py 100%; expression_evaluator 100%; ontology/reasoning 100% (session48); 3,626 tests, 141 missed lines |
| 3.22.4 | 2026-02-22 | ✅ Released | numpy skip guards: importorskip in session41+42 (session49); 3,569 pass, 64 skip (base env) |
| 3.22.5 | 2026-02-22 | ✅ Released | numpy-via-networkx skip guards (session50): fixed 7 test failures when networkx installed but numpy absent |
| 3.22.6 | 2026-02-22 | ✅ Released | 13 new tests: hybrid_search.py 100%; CAR ImportError branches; entity_helpers dead code documented (session51) |
| 3.22.7 | 2026-02-22 | ✅ Released | 17 new tests: ImportError except branches in 5 modules (reasoning/types, lineage/core, neo4j_compat/driver, cross_document, ipld) (session52) |
| 3.22.8 | 2026-02-22 | ✅ Released | 14 lines dead code removed (compiler.py, ir_executor.py, ipld.py); 15 invariant tests (session53) |
| 3.22.9 | 2026-02-22 | ✅ Released | numpy skip guards for sessions 52+53 tests (session54); 3,490 pass, 77 skip |
| 3.22.10 | 2026-02-22 | ✅ Released | numpy promoted to default dep in setup.py + new pyproject.toml (session55) |
| 3.22.11 | 2026-02-22 | ✅ Released | 9 lines dead code removed (cross_document.py, ir_executor.py); both files now 100% (session56) |
| 3.22.12 | 2026-02-22 | ✅ Released | scipy/matplotlib/plotly/rdflib added to knowledge_graphs extras; visualization.py 100% + graph.py 100% (session57) |
| 3.22.13 | 2026-02-22 | ✅ Released | srl.py 2 dead lines removed → 100%; multiformats added to ipld extras; 1 missed line total (session58) |
| 3.22.14 | 2026-02-22 | ✅ Released | Doc consistency fixes: ROADMAP.md v3.22.14; missing CHANGELOG sections added; release table complete (session59) |
| 3.22.15 | 2026-02-22 | ✅ Released | MASTER_STATUS stale coverage table updated (99.99%); duplicate ROADMAP v2.0.1 section removed; sessions 47–59 added to session list; 15 doc integrity tests (session60) |
| 4.0 | 2027+ | 📋 Future | TBD based on feedback |

---

## Dependencies

### Current Dependencies
- Python 3.12+
- IPFS (optional, for storage)
- spaCy (optional, for NER)
- numpy, scipy (required)
- rdflib (optional, for RDF/SPARQL)

### Optional Dependencies (available in v2.1.0)
- transformers (neural extraction)
- libipld + ipld-car + dag-cbor (CAR format; `pip install -e ".[ipld]"`)
- OpenAI/Anthropic SDKs (LLM integration)

### Deprecation Notices
- Legacy IPLD API (deprecated in 2.0.0, removal in 3.0.0)

---

## Feedback

We value your feedback! Please share thoughts on:
- Feature priorities
- Use cases
- Pain points
- Performance requirements

**Contact:**
- GitHub Issues: [github.com/endomorphosis/ipfs_datasets_py](https://github.com/endomorphosis/ipfs_datasets_py)
- Discussions: GitHub Discussions tab

---

**Last Updated:** 2026-02-22  
**Next Review:** Q3 2026  
**Maintained By:** Knowledge Graphs Team
