# Knowledge Graphs Comprehensive Refactoring, Integration & Improvement Plan

**Date:** 2026-02-16  
**Status:** Planning Phase  
**Scope:** Complete overhaul of `ipfs_datasets_py/knowledge_graphs/`  
**Duration:** ~240 hours (6 weeks)  
**Priority:** 🔴 HIGH - Critical for maintainability and future growth

---

## 🎯 Executive Summary

This document provides a comprehensive plan for refactoring, integrating, and improving the `knowledge_graphs` folder. The plan addresses code quality, duplication, organization, testing, documentation, and integration issues identified through detailed analysis.

### Current State (As of 2026-02-16)

**Folder Statistics:**
- **Files:** 54 Python files across 12 subdirectories
- **Lines of Code:** ~29,650 total lines
- **Documentation:** 25+ documentation files (~300KB)
- **Tests:** 26 test files (coverage unclear)
- **Size:** 1.2MB on disk

**Progress Status:**
- ✅ **Path A (Neo4j Compatibility):** 100% Complete - 381 tests passing
- ✅ **Path B (GraphRAG Consolidation):** 100% Complete - 58 tests passing, 82.6% code reduction
- ⏳ **Path C (Semantic Web):** Not started - 48h estimated

**Key Issues Identified:**
1. **Code Duplication:** Two lineage tracking modules with overlapping functionality
2. **Organization:** Inconsistent module structure and naming
3. **Legacy Code:** Multiple deprecated/legacy files still present
4. **Test Coverage:** Unknown coverage, tests scattered across locations
5. **Documentation:** Good quantity but needs consolidation and updating
6. **Integration:** Weak integration with other modules (processors, search, etc.)
7. **API Consistency:** Mixed API styles (new Neo4j-compatible vs legacy)
8. **Performance:** No performance benchmarks or optimization strategy

---

## 📊 Detailed Analysis

### 1. File Structure Analysis

```
ipfs_datasets_py/knowledge_graphs/
├── __init__.py (79 lines)              # Good: Migration warnings, new API exports
├── constraints/                         # ✅ Well organized
├── core/                                # ✅ Well organized
│   ├── query_executor.py (1,960 lines) # ⚠️ Very large, needs splitting
│   └── __init__.py
├── cypher/                              # ✅ Well organized
│   ├── lexer.py
│   ├── parser.py (852 lines)
│   ├── ast.py (544 lines)
│   ├── compiler.py (732 lines)
│   ├── functions.py (917 lines)
│   └── __init__.py
├── indexing/                            # ✅ Well organized
├── jsonld/                              # ✅ Well organized
│   ├── context.py
│   ├── rdf_serializer.py (528 lines)
│   ├── translator.py
│   ├── types.py
│   ├── validation.py
│   └── __init__.py
├── migration/                           # ✅ Well organized
├── neo4j_compat/                        # ✅ Well organized
├── query/                               # ✅ NEW: Path B unified engine
│   ├── unified_engine.py (535 lines)
│   ├── hybrid_search.py
│   ├── budget_manager.py
│   └── __init__.py
├── storage/                             # ✅ Well organized
├── transactions/                        # ✅ Well organized
├── cross_document_lineage.py (4,066 lines)          # 🔴 DUPLICATE #1
├── cross_document_lineage_enhanced.py (2,357 lines) # 🔴 DUPLICATE #2
├── cross_document_reasoning.py (812 lines)          # ⚠️ Unclear purpose
├── advanced_knowledge_extractor.py (751 lines)      # ⚠️ Legacy?
├── knowledge_graph_extraction.py (2,969 lines)      # ⚠️ Very large
├── finance_graphrag.py (18KB)                       # ⚠️ Domain-specific
├── ipld.py (1,425 lines)                            # ⚠️ Deprecated
├── query_knowledge_graph.py (8.7KB)                 # ⚠️ Duplicate functionality?
└── sparql_query_templates.py (567 lines)            # ⚠️ Limited usage
```

### 2. Code Duplication Analysis

#### Critical Duplication: Lineage Tracking (6,423 lines)

**Problem:** Two modules doing essentially the same thing

**cross_document_lineage.py (4,066 lines):**
- Classes: `LineageLink`, `LineageNode`, `LineageDomain`, `LineageBoundary`, `EnhancedLineageTracker`, `CrossDocumentLineageTracker`
- Features: Comprehensive lineage tracking with NetworkX graphs
- Dependencies: analytics.data_provenance, data_provenance_enhanced

**cross_document_lineage_enhanced.py (2,357 lines):**
- Classes: `CrossDocumentLineageEnhancer`, `DetailedLineageIntegrator`
- Features: Enhanced semantic relationships, boundary analysis
- Dependencies: Same as above

**Consolidation Potential:** 
- Merge into single `lineage/` subdirectory
- Create clear hierarchy: `lineage/core.py`, `lineage/enhanced.py`, `lineage/visualization.py`
- **Estimated Reduction:** 30-40% (~1,900-2,500 lines eliminated)

#### Moderate Duplication: Query Functionality

**Modules with overlapping query logic:**
- `query_knowledge_graph.py` (8.7KB)
- `query/unified_engine.py` (535 lines) - NEW from Path B
- `core/query_executor.py` (1,960 lines)

**Resolution:** 
- `query/unified_engine.py` should be the canonical entry point
- Move specialized logic from `query_executor.py` to `query/` subdirectory
- Deprecate or integrate `query_knowledge_graph.py`

### 3. Large File Issues

**Files > 1,000 lines requiring splitting:**

1. **cross_document_lineage.py** (4,066 lines)
   - Split into: core.py, visualization.py, metrics.py, boundaries.py
   - Target: 4 files of ~1,000 lines each

2. **knowledge_graph_extraction.py** (2,969 lines)
   - Split into: extractors.py, analyzers.py, graph_builders.py
   - Target: 3 files of ~1,000 lines each

3. **cross_document_lineage_enhanced.py** (2,357 lines)
   - Merge with above lineage refactoring

4. **core/query_executor.py** (1,960 lines)
   - Split into: executor.py, optimizers.py, planners.py
   - Target: 3 files of ~650 lines each

### 4. Test Coverage Analysis

**Current Testing Issues:**
- Tests scattered: `tests/unit/`, `tests/unit_tests/`, `tests/unit/test_stubs_from_gherkin/`
- Gherkin feature files exist but unclear if used
- No centralized `tests/unit/knowledge_graphs/` directory
- Unknown coverage percentage
- No integration tests for knowledge_graphs as a whole

**Test Files Found:**
- `test_ipld_knowledge_graph_traversal.py`
- `test_knowledge_graph_large_blocks.py`
- `test_advanced_knowledge_extractor.py` (stub)
- `test_knowledge_graph_extraction.py` (stub)
- `knowledge_graph_extraction.feature` (Gherkin)
- `advanced_knowledge_extractor.feature` (Gherkin)

### 5. Documentation Status

**Existing Documentation (25+ files, 300KB+):**

**Good:**
- ✅ Comprehensive roadmap documentation
- ✅ Path A, B, C implementation plans
- ✅ Migration guides
- ✅ API references

**Needs Improvement:**
- ⚠️ Too many overlapping status documents
- ⚠️ No single "getting started" guide
- ⚠️ No architecture diagrams
- ⚠️ No performance tuning guide
- ⚠️ Documentation not co-located with code

### 6. Integration Analysis

**Current Integration Points:**

**Strong Integration (Good):**
- ✅ `processors/graphrag/` - Via Path B adapters
- ✅ `search/graphrag_integration/` - Via Path B adapters
- ✅ `storage/` - IPLD backend used throughout
- ✅ `analytics/data_provenance/` - Used by lineage tracking

**Weak Integration (Needs Work):**
- ⚠️ `embeddings/` - No clear integration strategy
- ⚠️ `rag/` - Limited knowledge graph awareness
- ⚠️ `pdf_processing/` - Could benefit from knowledge extraction
- ⚠️ `llm/` - Should integrate with GraphRAG
- ⚠️ `search/` - Only GraphRAG integrated, not general KG search

**Missing Integration:**
- ❌ `multimedia/` - No media entity extraction to KG
- ❌ `logic_integration/` - No formal logic + KG integration
- ❌ `audit/` - No KG audit trail integration
- ❌ `optimizers/` - No KG query optimization

---

## 🎯 Improvement Plan Overview

### Phase 1: Code Consolidation & Organization (60 hours)
**Priority:** 🔴 CRITICAL  
**Goal:** Eliminate duplication, reorganize structure, split large files

### Phase 2: Testing & Quality (40 hours)
**Priority:** 🔴 HIGH  
**Goal:** Achieve 90%+ test coverage, establish quality gates

### Phase 3: Integration Enhancement (50 hours)
**Priority:** 🟡 MEDIUM  
**Goal:** Deep integration with other modules

### Phase 4: Path C Implementation (48 hours)
**Priority:** 🟡 MEDIUM  
**Goal:** Complete semantic web foundation

### Phase 5: Performance & Optimization (30 hours)
**Priority:** 🟢 LOW  
**Goal:** Establish benchmarks, optimize critical paths

### Phase 6: Documentation & Polish (12 hours)
**Priority:** 🟢 LOW  
**Goal:** Consolidate docs, create guides, polish APIs

**Total:** ~240 hours (6 weeks)

---

## 📋 Phase 1: Code Consolidation & Organization (60 hours)

### Task 1.1: Consolidate Lineage Tracking (20 hours)

**Problem:** Two modules with 6,423 lines of overlapping functionality

**Solution:** Create new `lineage/` subdirectory

**Structure:**
```
knowledge_graphs/lineage/
├── __init__.py                    # Public API exports
├── core.py (~1,000 lines)         # Core lineage tracking
│   ├── LineageTracker
│   ├── LineageGraph
│   ├── LineageNode
│   └── LineageLink
├── enhanced.py (~800 lines)       # Enhanced features
│   ├── SemanticAnalyzer
│   ├── BoundaryDetector
│   └── ConfidenceScorer
├── visualization.py (~600 lines)  # Visualization logic
│   ├── LineageVisualizer
│   ├── NetworkXRenderer
│   └── PlotlyRenderer
├── metrics.py (~400 lines)        # Metrics & analysis
│   ├── LineageMetrics
│   ├── ImpactAnalyzer
│   └── DependencyAnalyzer
└── types.py (~200 lines)          # Shared types
    ├── LineageNode (dataclass)
    ├── LineageLink (dataclass)
    └── LineageMetadata (dataclass)
```

**Migration Strategy:**
1. Extract common functionality to `core.py`
2. Move enhanced features to `enhanced.py`
3. Separate visualization to `visualization.py`
4. Extract metrics to `metrics.py`
5. Create deprecation shims in old locations
6. Update all imports

**Testing:**
- Migrate existing tests to `tests/unit/knowledge_graphs/lineage/`
- Achieve 90%+ coverage
- Add integration tests

**Expected Outcome:**
- 6,423 → ~3,000 lines (53% reduction)
- Clear module boundaries
- Better testability
- No breaking changes (via shims)

**Time Breakdown:**
- Code reorganization: 8 hours
- Testing: 6 hours
- Deprecation shims: 3 hours
- Documentation: 3 hours

---

### Task 1.2: Refactor Large Files (15 hours)

**Target Files:**
1. `knowledge_graph_extraction.py` (2,969 lines)
2. `core/query_executor.py` (1,960 lines)

#### 1.2a: Split knowledge_graph_extraction.py

**New Structure:**
```
knowledge_graphs/extraction/
├── __init__.py
├── extractors.py (~1,000 lines)   # Entity/relationship extraction
├── analyzers.py (~1,000 lines)    # Semantic analysis
└── builders.py (~1,000 lines)     # Graph construction
```

**Benefits:**
- Better separation of concerns
- Easier testing
- More maintainable
- Clearer APIs

#### 1.2b: Split core/query_executor.py

**New Structure:**
```
knowledge_graphs/core/
├── __init__.py
├── graph_engine.py (~unchanged)   # Keep existing
├── executor.py (~700 lines)       # Core execution logic
├── optimizer.py (~650 lines)      # Query optimization
└── planner.py (~610 lines)        # Query planning
```

**Time Breakdown:**
- Extraction module split: 6 hours
- Query executor split: 5 hours
- Testing: 3 hours
- Documentation: 1 hour

---

### Task 1.3: Deprecate Legacy Modules (10 hours)

**Modules to Deprecate:**

1. **ipld.py (1,425 lines)** - ⚠️ Already marked deprecated
   - Status: Already has deprecation warning
   - Action: Create adapter to new API
   - Timeline: 6-month deprecation period

2. **query_knowledge_graph.py (8.7KB)** - Superseded by query/unified_engine.py
   - Status: No deprecation warning yet
   - Action: Add deprecation, create adapter
   - Timeline: 6-month deprecation period

3. **advanced_knowledge_extractor.py (751 lines)** - Unclear usage
   - Status: Needs usage analysis
   - Action: Document or deprecate
   - Timeline: Based on usage analysis

**Deprecation Checklist:**
- [ ] Add DeprecationWarning to module __init__
- [ ] Create adapters/shims for backward compatibility
- [ ] Update all internal references to use new APIs
- [ ] Document migration path in docstrings
- [ ] Add migration guide to docs
- [ ] Create automated deprecation tracker

**Time Breakdown:**
- Usage analysis: 3 hours
- Adapter creation: 4 hours
- Documentation: 2 hours
- Testing: 1 hour

---

### Task 1.4: Organize Root-Level Files (8 hours)

**Problem:** Too many files in root directory

**Current Root Files:**
- cross_document_lineage.py → Move to lineage/
- cross_document_lineage_enhanced.py → Move to lineage/
- cross_document_reasoning.py → Move to reasoning/
- knowledge_graph_extraction.py → Move to extraction/
- advanced_knowledge_extractor.py → Move to extraction/ or deprecate
- finance_graphrag.py → Move to applications/
- ipld.py → Deprecate with adapter
- query_knowledge_graph.py → Deprecate with adapter
- sparql_query_templates.py → Move to query/

**New Structure:**
```
knowledge_graphs/
├── __init__.py
├── applications/          # Domain-specific applications
│   └── finance_graphrag.py
├── constraints/           # (existing)
├── core/                  # (existing, enhanced)
├── cypher/                # (existing)
├── extraction/            # Entity/relationship extraction
│   ├── extractors.py
│   ├── analyzers.py
│   └── builders.py
├── indexing/              # (existing)
├── jsonld/                # (existing)
├── lineage/               # Lineage tracking (NEW)
│   ├── core.py
│   ├── enhanced.py
│   ├── visualization.py
│   └── metrics.py
├── migration/             # (existing)
├── neo4j_compat/          # (existing)
├── query/                 # (existing, enhanced)
│   ├── unified_engine.py
│   ├── hybrid_search.py
│   ├── budget_manager.py
│   └── sparql_templates.py  # Moved here
├── reasoning/             # Cross-doc reasoning (NEW)
│   └── cross_document.py
├── storage/               # (existing)
└── transactions/          # (existing)

# Deprecated (with adapters)
deprecated/
├── ipld.py
├── query_knowledge_graph.py
└── advanced_knowledge_extractor.py
```

**Benefits:**
- Clearer organization
- Better discoverability
- Reduced root clutter
- Logical grouping

**Time Breakdown:**
- File moves: 3 hours
- Import updates: 2 hours
- Testing: 2 hours
- Documentation: 1 hour

---

### Task 1.5: API Consistency (7 hours)

**Problem:** Mixed API styles throughout codebase

**Issues:**
- Some modules use old procedural style
- Some use new class-based style
- Inconsistent naming conventions
- Inconsistent parameter ordering

**Solution:** Establish API guidelines and refactor

**API Guidelines:**
```python
# GOOD: New Neo4j-compatible style
from ipfs_datasets_py.knowledge_graphs import GraphDatabase

driver = GraphDatabase.driver("ipfs://localhost:5001")
with driver.session() as session:
    result = session.run("MATCH (n) RETURN n")
    
# GOOD: Unified query engine
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(backend=backend)
result = engine.execute_cypher(query, params, budgets)

# GOOD: Lineage tracking (new)
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

tracker = LineageTracker()
tracker.add_node(node_id, metadata)
tracker.add_link(source, target, relationship)
```

**Refactoring Targets:**
1. Update all module imports in `__init__.py`
2. Ensure consistent class initialization
3. Standardize method signatures
4. Add type hints everywhere
5. Use dataclasses for data structures

**Time Breakdown:**
- API audit: 2 hours
- Refactoring: 3 hours
- Testing: 1 hour
- Documentation: 1 hour

---

## 📋 Phase 2: Testing & Quality (40 hours)

### Task 2.1: Establish Test Infrastructure (10 hours)

**Goal:** Create comprehensive test framework

**Structure:**
```
tests/unit/knowledge_graphs/
├── __init__.py
├── conftest.py                      # Shared fixtures
├── test_core/
│   ├── test_graph_engine.py
│   ├── test_query_executor.py
│   └── test_budget_tracking.py
├── test_cypher/
│   ├── test_lexer.py
│   ├── test_parser.py
│   ├── test_compiler.py
│   └── test_functions.py
├── test_query/
│   ├── test_unified_engine.py
│   ├── test_hybrid_search.py
│   └── test_budget_manager.py
├── test_lineage/
│   ├── test_core.py
│   ├── test_enhanced.py
│   ├── test_visualization.py
│   └── test_metrics.py
├── test_extraction/
│   ├── test_extractors.py
│   ├── test_analyzers.py
│   └── test_builders.py
├── test_jsonld/
│   ├── test_context.py
│   ├── test_translator.py
│   └── test_validation.py
├── test_neo4j_compat/
│   ├── test_driver.py
│   ├── test_session.py
│   └── test_bookmarks.py
└── test_integration/
    ├── test_end_to_end_queries.py
    ├── test_graphrag_pipeline.py
    └── test_lineage_tracking.py
```

**Deliverables:**
- [ ] Comprehensive test structure
- [ ] Shared fixtures in conftest.py
- [ ] Test utilities and helpers
- [ ] Mock objects for IPFS/IPLD
- [ ] Performance test framework

**Time Breakdown:**
- Structure setup: 3 hours
- Fixtures & utilities: 4 hours
- Mock objects: 2 hours
- Documentation: 1 hour

---

### Task 2.2: Achieve 90% Test Coverage (20 hours)

**Current Coverage:** Unknown (likely <60%)  
**Target Coverage:** 90%+

**Priority Areas:**
1. **Critical (must have 95%+):**
   - core/graph_engine.py
   - core/query_executor.py
   - query/unified_engine.py
   - cypher/compiler.py
   - storage/ipld_backend.py

2. **Important (must have 90%+):**
   - All cypher/ modules
   - All query/ modules
   - neo4j_compat/ modules
   - lineage/core.py

3. **Nice-to-have (target 85%+):**
   - extraction/ modules
   - jsonld/ modules
   - visualization modules

**Approach:**
1. Run coverage analysis: `pytest --cov=knowledge_graphs --cov-report=html`
2. Identify gaps
3. Write tests to fill gaps
4. Prioritize by criticality
5. Establish coverage gates in CI

**Test Types:**
- Unit tests (fast, isolated)
- Integration tests (real IPFS backend)
- Property tests (hypothesis library)
- Performance tests (benchmarks)

**Time Breakdown:**
- Coverage analysis: 2 hours
- Writing unit tests: 10 hours
- Writing integration tests: 5 hours
- Performance tests: 2 hours
- Documentation: 1 hour

---

### Task 2.3: Quality Gates & CI Integration (5 hours)

**Goal:** Automated quality enforcement

**Quality Gates:**
1. **Test Coverage:** 90%+ required
2. **Type Checking:** mypy passing
3. **Linting:** flake8 passing
4. **Security:** No high/critical vulnerabilities
5. **Performance:** No regressions > 10%

**CI Integration:**
```yaml
# .github/workflows/knowledge-graphs-ci.yml
name: Knowledge Graphs CI

on:
  pull_request:
    paths:
      - 'ipfs_datasets_py/knowledge_graphs/**'
      - 'tests/unit/knowledge_graphs/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: |
          pip install -e ".[test]"
          
      - name: Run tests with coverage
        run: |
          pytest tests/unit/knowledge_graphs/ \
            --cov=ipfs_datasets_py.knowledge_graphs \
            --cov-report=xml \
            --cov-report=html \
            --cov-fail-under=90
            
      - name: Type checking
        run: mypy ipfs_datasets_py/knowledge_graphs/
        
      - name: Linting
        run: flake8 ipfs_datasets_py/knowledge_graphs/
        
      - name: Security scan
        run: bandit -r ipfs_datasets_py/knowledge_graphs/
        
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

**Deliverables:**
- [ ] CI workflow file
- [ ] Pre-commit hooks
- [ ] Coverage badges
- [ ] Quality dashboard

**Time Breakdown:**
- CI workflow: 2 hours
- Pre-commit hooks: 1 hour
- Quality dashboard: 1 hour
- Documentation: 1 hour

---

### Task 2.4: Code Quality Improvements (5 hours)

**Issues to Address:**
1. Missing type hints
2. Inconsistent docstrings
3. TODO/FIXME markers (3 files)
4. Complex functions (cyclomatic complexity > 15)
5. Long functions (> 50 lines)

**Tools:**
- mypy: Type checking
- flake8: Style checking
- radon: Complexity analysis
- pydocstyle: Docstring checking
- black: Auto-formatting

**Actions:**
1. Add type hints to all public APIs
2. Add docstrings following format in `docs/_example_docstring_format.md`
3. Resolve all TODO/FIXME markers
4. Split complex functions
5. Apply black formatting

**Time Breakdown:**
- Type hints: 2 hours
- Docstrings: 1 hour
- TODO resolution: 1 hour
- Refactoring: 1 hour

---

## 📋 Phase 3: Integration Enhancement (50 hours)

### Task 3.1: Embeddings Integration (12 hours)

**Goal:** Deep integration with embeddings module

**Current State:** Weak integration
- embeddings/ module exists but minimal KG awareness
- KG uses embeddings but no standard interface

**Improvements:**

**3.1a: Knowledge Graph Embeddings**
```python
# New: knowledge_graphs/embeddings/kg_embeddings.py

from ipfs_datasets_py.embeddings import EmbeddingManager

class KGEmbeddingManager:
    """Manages embeddings for knowledge graph entities."""
    
    def embed_entity(self, entity_id: str, entity_data: Dict) -> np.ndarray:
        """Generate embedding for entity."""
        pass
    
    def embed_relationship(self, rel_id: str, rel_data: Dict) -> np.ndarray:
        """Generate embedding for relationship."""
        pass
    
    def similarity_search(
        self, 
        query: str, 
        k: int = 10,
        entity_types: Optional[List[str]] = None
    ) -> List[Entity]:
        """Search entities by semantic similarity."""
        pass
```

**3.1b: Entity Linking**
```python
class EntityLinker:
    """Links text mentions to KG entities."""
    
    def link_entities(
        self, 
        text: str, 
        kg: KnowledgeGraph
    ) -> List[EntityMention]:
        """Identify and link entities in text."""
        pass
```

**Time Breakdown:**
- Design: 3 hours
- Implementation: 6 hours
- Testing: 2 hours
- Documentation: 1 hour

---

### Task 3.2: RAG Integration (10 hours)

**Goal:** Make RAG knowledge-graph-aware

**Current State:** rag/ module exists but no KG integration

**Improvements:**

**3.2a: KG-Augmented Retrieval**
```python
# rag/kg_retriever.py

class KnowledgeGraphRetriever:
    """RAG retriever backed by knowledge graph."""
    
    def retrieve(
        self,
        query: str,
        k: int = 5,
        expand_hops: int = 2
    ) -> List[Document]:
        """
        Retrieve documents using KG.
        
        1. Embed query
        2. Find similar entities in KG
        3. Expand to connected entities
        4. Retrieve associated documents
        5. Re-rank by relevance
        """
        pass
```

**3.2b: KG-Enhanced Context**
```python
class KGContextEnhancer:
    """Enriches RAG context with KG information."""
    
    def enhance_context(
        self,
        documents: List[Document],
        kg: KnowledgeGraph
    ) -> EnhancedContext:
        """Add KG context to retrieved documents."""
        pass
```

**Time Breakdown:**
- Design: 2 hours
- Implementation: 5 hours
- Testing: 2 hours
- Documentation: 1 hour

---

### Task 3.3: PDF Processing Integration (8 hours)

**Goal:** Extract knowledge from PDFs into KG

**Current State:** pdf_processing/ exists but no KG integration

**Improvements:**

**3.3a: PDF Entity Extraction**
```python
# pdf_processing/kg_extractor.py

class PDFKnowledgeExtractor:
    """Extract knowledge graph from PDFs."""
    
    def extract_from_pdf(
        self,
        pdf_path: str
    ) -> KnowledgeGraph:
        """
        Extract KG from PDF.
        
        1. Extract text
        2. Identify entities
        3. Extract relationships
        4. Build KG
        """
        pass
```

**3.3b: Citation Graph**
```python
class CitationGraphBuilder:
    """Build citation graph from academic PDFs."""
    
    def build_citation_graph(
        self,
        pdfs: List[str]
    ) -> KnowledgeGraph:
        """Build graph of citations between papers."""
        pass
```

**Time Breakdown:**
- Design: 2 hours
- Implementation: 4 hours
- Testing: 1 hour
- Documentation: 1 hour

---

### Task 3.4: LLM Integration (10 hours)

**Goal:** Enable LLM-powered KG operations

**Current State:** llm/ module exists but minimal KG awareness

**Improvements:**

**3.4a: LLM-Powered Extraction**
```python
# knowledge_graphs/llm/extractor.py

class LLMKnowledgeExtractor:
    """Use LLM to extract knowledge."""
    
    def extract_with_llm(
        self,
        text: str,
        schema: Optional[Schema] = None
    ) -> List[Triple]:
        """Use LLM to extract structured knowledge."""
        pass
```

**3.4b: KG-to-Text Generation**
```python
class KGTextGenerator:
    """Generate natural language from KG."""
    
    def generate_description(
        self,
        entity: Entity,
        context_hops: int = 2
    ) -> str:
        """Generate text description of entity using KG context."""
        pass
    
    def generate_explanation(
        self,
        path: Path
    ) -> str:
        """Explain a path through the KG."""
        pass
```

**Time Breakdown:**
- Design: 2 hours
- Implementation: 5 hours
- Testing: 2 hours
- Documentation: 1 hour

---

### Task 3.5: Search Integration (10 hours)

**Goal:** Enhance general search with KG

**Current State:** search/ has GraphRAG integration only

**Improvements:**

**3.5a: KG-Augmented Search**
```python
# search/kg_search.py

class KGSearchEngine:
    """Search engine with KG augmentation."""
    
    def search(
        self,
        query: str,
        k: int = 10,
        use_kg: bool = True
    ) -> SearchResults:
        """
        Search with KG augmentation.
        
        1. Standard search
        2. Entity linking in results
        3. KG expansion
        4. Re-ranking
        """
        pass
```

**3.5b: Entity-Centric Search**
```python
class EntitySearch:
    """Search focused on entities."""
    
    def find_entities(
        self,
        query: str,
        entity_types: Optional[List[str]] = None
    ) -> List[Entity]:
        """Find entities matching query."""
        pass
    
    def find_relationships(
        self,
        entity1: str,
        entity2: str
    ) -> List[Path]:
        """Find relationship paths between entities."""
        pass
```

**Time Breakdown:**
- Design: 2 hours
- Implementation: 5 hours
- Testing: 2 hours
- Documentation: 1 hour

---

## 📋 Phase 4: Path C Implementation (48 hours)

**Status:** Not started (from existing roadmap)

### Task 4.1: Expand Vocabularies (15 hours)

**Goal:** Add 7 vocabularies with 500+ terms

**From existing roadmap (KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md):**

Create `jsonld/vocabularies/` subdirectory:

1. `schema_org.py` - Extended Schema.org (3 hours)
2. `foaf.py` - Extended FOAF (2 hours)
3. `dublin_core.py` - Complete DC Terms (2 hours)
4. `skos.py` - Extended SKOS (3 hours)
5. `geonames.py` - Geographic entities (2 hours)
6. `dbpedia.py` - Linked data ontology (2 hours)
7. `prov_o.py` - Provenance vocabulary (1 hour)

**Deliverables:**
- 7 vocabulary modules
- 500+ terms defined
- Context integration
- Documentation

---

### Task 4.2: SHACL Validation (20 hours)

**Goal:** Core SHACL constraint validation

**Implementation:**
- Cardinality constraints (3 hours)
- Value type constraints (4 hours)
- Value range constraints (4 hours)
- String constraints (3 hours)
- Property pair constraints (3 hours)
- Validation reporting (3 hours)

**Deliverables:**
- `jsonld/shacl_validator.py` (~600 lines)
- Comprehensive constraint checking
- Detailed validation reports

---

### Task 4.3: Turtle RDF Serialization (8 hours)

**Goal:** Export as Turtle RDF

**Implementation:**
- Prefix management (2 hours)
- Triple generation (3 hours)
- Pretty printing (2 hours)
- Round-trip validation (1 hour)

**Deliverables:**
- `jsonld/turtle_serializer.py` (~400 lines)
- Turtle RDF export
- Format validation

---

### Task 4.4: Testing & Documentation (5 hours)

- Write 40+ tests for Path C features
- Update documentation
- Create examples

---

## 📋 Phase 5: Performance & Optimization (30 hours)

### Task 5.1: Establish Benchmarks (10 hours)

**Goal:** Create performance baseline

**Benchmarks:**

```python
# tests/performance/knowledge_graphs/benchmark_queries.py

class QueryBenchmarks:
    """Performance benchmarks for query operations."""
    
    def test_simple_match_performance(self):
        """Benchmark: MATCH (n) RETURN n LIMIT 100"""
        # Target: < 10ms
        pass
    
    def test_complex_match_performance(self):
        """Benchmark: Multi-hop pattern matching"""
        # Target: < 100ms
        pass
    
    def test_hybrid_search_performance(self):
        """Benchmark: Hybrid vector+graph search"""
        # Target: < 200ms
        pass
    
    def test_large_graph_traversal(self):
        """Benchmark: BFS on 10K+ node graph"""
        # Target: < 500ms
        pass
```

**Metrics to Track:**
- Query execution time
- Memory usage
- IPFS operations count
- Cache hit rate
- Index usage

**Deliverables:**
- Benchmark suite
- Performance dashboard
- Regression detection

**Time Breakdown:**
- Benchmark design: 3 hours
- Implementation: 4 hours
- Dashboard: 2 hours
- Documentation: 1 hour

---

### Task 5.2: Query Optimization (12 hours)

**Optimization Areas:**

**5.2a: Query Planning**
- Cost-based optimization
- Index selection
- Join ordering

**5.2b: Caching Strategy**
- Query result caching
- Parsed query caching
- Entity caching

**5.2c: Index Optimization**
- Automatic index selection
- Composite index creation
- Index usage statistics

**Implementation:**
```python
# core/optimizer.py (enhanced)

class QueryOptimizer:
    """Optimizes query execution plans."""
    
    def optimize(self, query_plan: QueryPlan) -> OptimizedPlan:
        """
        Optimize query plan.
        
        - Reorder operations for efficiency
        - Select best indexes
        - Apply caching strategies
        - Estimate costs
        """
        pass
```

**Time Breakdown:**
- Query planning: 4 hours
- Caching: 4 hours
- Index optimization: 3 hours
- Documentation: 1 hour

---

### Task 5.3: Memory Optimization (8 hours)

**Issues to Address:**
- Large graphs in memory
- Graph traversal memory usage
- Result set memory

**Solutions:**

**5.3a: Streaming Results**
```python
def execute_query_streaming(query: str) -> Iterator[Result]:
    """Stream query results instead of loading all."""
    pass
```

**5.3b: Graph Paging**
```python
class PagedGraph:
    """Graph with paged node/edge storage."""
    
    def get_neighbors(self, node_id: str, page: int = 0) -> Page[Node]:
        """Get neighbors with pagination."""
        pass
```

**5.3c: Memory Profiling**
- Add memory tracking
- Identify memory leaks
- Optimize data structures

**Time Breakdown:**
- Streaming: 3 hours
- Paging: 3 hours
- Profiling: 1 hour
- Documentation: 1 hour

---

## 📋 Phase 6: Documentation & Polish (12 hours)

### Task 6.1: Consolidate Documentation (5 hours)

**Current Issues:**
- 25+ documentation files
- Overlapping content
- Outdated information
- No clear entry point

**Solution: Create Documentation Hub**

**New Structure:**
```
docs/knowledge_graphs/
├── README.md                        # Entry point, navigation
├── getting-started.md               # 30-min tutorial
├── architecture/
│   ├── overview.md
│   ├── components.md
│   └── data-flow.md
├── guides/
│   ├── querying.md
│   ├── lineage-tracking.md
│   ├── knowledge-extraction.md
│   └── performance-tuning.md
├── api/
│   ├── core-api.md
│   ├── query-api.md
│   ├── lineage-api.md
│   └── integration-api.md
├── migration/
│   ├── from-legacy.md
│   ├── from-neo4j.md
│   └── breaking-changes.md
└── reference/
    ├── implementation-status.md
    ├── roadmap.md
    ├── changelog.md
    └── faq.md
```

**Consolidation Strategy:**
1. Merge overlapping status documents
2. Archive historical documents
3. Update outdated content
4. Create clear navigation
5. Add cross-references

**Time Breakdown:**
- Content audit: 1 hour
- Consolidation: 2 hours
- Writing: 1 hour
- Review: 1 hour

---

### Task 6.2: Create Getting Started Guide (4 hours)

**Goal:** 30-minute tutorial for new users

**Content:**
```markdown
# Knowledge Graphs - Getting Started

## Installation
## Basic Concepts
## Your First Query
## Building a Knowledge Graph
## Querying the Graph
## Advanced Features
## Next Steps
```

**Examples:**
- Create nodes and relationships
- Execute Cypher queries
- Track lineage
- Extract knowledge from text
- Visualize graphs

**Time Breakdown:**
- Content writing: 2 hours
- Code examples: 1 hour
- Review: 1 hour

---

### Task 6.3: API Documentation (3 hours)

**Goal:** Complete API reference

**Approach:**
- Use sphinx-autodoc for automatic generation
- Add examples to all docstrings
- Create usage patterns guide
- Document common pitfalls

**Deliverables:**
- Auto-generated API docs
- Usage examples
- Best practices guide

**Time Breakdown:**
- Setup: 1 hour
- Docstring enhancement: 1 hour
- Examples: 1 hour

---

## 📊 Success Metrics

### Code Quality Metrics

| Metric | Current | Target | Phase |
|--------|---------|--------|-------|
| Lines of Code | ~29,650 | ~22,000 | Phase 1 |
| Test Coverage | Unknown | 90%+ | Phase 2 |
| Duplicate Code | High | <5% | Phase 1 |
| Files > 1,000 lines | 5 | 0 | Phase 1 |
| Type Hint Coverage | ~60% | 95%+ | Phase 2 |
| Docstring Coverage | ~70% | 95%+ | Phase 6 |
| CI Pass Rate | Unknown | 100% | Phase 2 |

### Performance Metrics

| Metric | Target | Phase |
|--------|--------|-------|
| Simple query | <10ms | Phase 5 |
| Complex query | <100ms | Phase 5 |
| Hybrid search | <200ms | Phase 5 |
| Large traversal | <500ms | Phase 5 |
| Memory usage | <2GB for 10K nodes | Phase 5 |

### Integration Metrics

| Integration | Current | Target | Phase |
|-------------|---------|--------|-------|
| Embeddings | Weak | Strong | Phase 3 |
| RAG | None | Strong | Phase 3 |
| PDF Processing | None | Moderate | Phase 3 |
| LLM | Weak | Strong | Phase 3 |
| Search | Partial | Strong | Phase 3 |

### Documentation Metrics

| Metric | Current | Target | Phase |
|--------|---------|--------|-------|
| Docs size | 300KB+ | 150KB | Phase 6 |
| Getting started | No | Yes | Phase 6 |
| API reference | Partial | Complete | Phase 6 |
| Examples | Few | Many | Phase 6 |

---

## 🎯 Implementation Timeline

### Week 1-2: Phase 1 (Code Consolidation)
- Days 1-4: Consolidate lineage tracking
- Days 5-7: Refactor large files
- Days 8-9: Deprecate legacy modules
- Days 10-11: Organize root files
- Days 11-12: API consistency

### Week 3: Phase 2 (Testing & Quality)
- Days 1-2: Test infrastructure
- Days 3-8: Achieve 90% coverage
- Days 9-10: Quality gates & CI
- Days 11-12: Code quality improvements

### Week 4: Phase 3 (Integration)
- Days 1-3: Embeddings integration
- Days 4-5: RAG integration
- Days 6-7: PDF processing integration
- Days 8-9: LLM integration
- Days 10-12: Search integration

### Week 5: Phase 4 (Path C)
- Days 1-3: Expand vocabularies
- Days 4-8: SHACL validation
- Days 9-10: Turtle RDF serialization
- Days 11-12: Testing & documentation

### Week 6: Phase 5 & 6 (Performance & Polish)
- Days 1-2: Establish benchmarks
- Days 3-5: Query optimization
- Days 6-7: Memory optimization
- Days 8-10: Consolidate documentation
- Days 11-12: Final polish & review

---

## 🔗 Dependencies

### Internal Dependencies
- ✅ processors/ - Path B adapters complete
- ✅ search/ - Path B adapters complete
- ⚠️ embeddings/ - Needs integration work
- ⚠️ rag/ - Needs integration work
- ⚠️ pdf_processing/ - Needs integration work
- ⚠️ llm/ - Needs integration work

### External Dependencies
- ✅ IPFS/IPLD - Working
- ✅ NetworkX - Used for graphs
- ⚠️ RDFLib - Needed for Path C
- ⚠️ PyShacl - Needed for SHACL validation

### Testing Dependencies
- pytest, pytest-cov, pytest-xdist
- hypothesis (property testing)
- mypy, flake8, bandit
- coverage

---

## 🚨 Risk Assessment

### High Risk Items

**1. Breaking Changes During Consolidation**
- **Risk:** Moving files may break external dependencies
- **Mitigation:** Use deprecation shims, maintain backward compatibility
- **Timeline:** 6-month deprecation period

**2. Test Coverage Gaps**
- **Risk:** Unknown current coverage could hide bugs
- **Mitigation:** Start with coverage analysis, prioritize critical paths
- **Fallback:** Accept lower coverage initially, improve iteratively

**3. Performance Regressions**
- **Risk:** Refactoring could introduce performance issues
- **Mitigation:** Establish benchmarks first, monitor continuously
- **Fallback:** Profile and optimize specific bottlenecks

### Medium Risk Items

**4. Integration Complexity**
- **Risk:** Deep integration with other modules may be complex
- **Mitigation:** Start with well-defined interfaces, iterate
- **Fallback:** Implement partial integration, complete later

**5. Path C Dependencies**
- **Risk:** RDFLib, PyShacl may have compatibility issues
- **Mitigation:** Test early, have alternatives ready
- **Fallback:** Defer Path C if blocking issues

### Low Risk Items

**6. Documentation Consolidation**
- **Risk:** Minimal - just content reorganization
- **Mitigation:** Keep originals as archive
- **Fallback:** Easy to revert

---

## 📝 Next Steps

### Immediate Actions (This Session)

1. **Review & Approval**
   - Review this plan with stakeholders
   - Prioritize phases based on needs
   - Adjust timeline if needed

2. **Setup**
   - Create tracking issue
   - Set up project board
   - Create feature branch

3. **Phase 1 Start**
   - Begin lineage consolidation (Task 1.1)
   - Create new lineage/ directory structure
   - Start extracting common functionality

### After This Session

1. **Continue Phase 1**
   - Complete all Phase 1 tasks
   - Achieve code consolidation goals

2. **Begin Phase 2**
   - Set up test infrastructure
   - Start coverage improvements

3. **Weekly Reviews**
   - Track progress against timeline
   - Adjust as needed
   - Report blockers

---

## 🤝 Success Criteria

### Phase 1 Complete When:
- [x] Lineage modules consolidated (6,423 → ~3,000 lines)
- [x] Large files split (no files > 1,000 lines)
- [x] Legacy modules deprecated with adapters
- [x] Root directory organized (max 2 files)
- [x] API consistency achieved

### Phase 2 Complete When:
- [x] Test coverage ≥ 90%
- [x] CI pipeline green
- [x] Quality gates enforced
- [x] Code quality score ≥ 90/100

### Phase 3 Complete When:
- [x] All 5 integrations implemented
- [x] Integration tests passing
- [x] Documentation complete

### Phase 4 Complete When:
- [x] 7 vocabularies added
- [x] SHACL validation working
- [x] Turtle RDF export working
- [x] 40+ tests passing

### Phase 5 Complete When:
- [x] Benchmarks established
- [x] Performance targets met
- [x] Memory optimization complete

### Phase 6 Complete When:
- [x] Documentation consolidated
- [x] Getting started guide complete
- [x] API reference complete

### Overall Success When:
- [x] All phases complete
- [x] 90%+ test coverage
- [x] Zero breaking changes
- [x] Performance targets met
- [x] Documentation complete
- [x] Code quality ≥ 90/100

---

## 📚 References

### Existing Documentation
- [KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md](./KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md)
- [KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md](./KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md)
- [PATH_A_IMPLEMENTATION_COMPLETE.md](./PATH_A_IMPLEMENTATION_COMPLETE.md)
- [PATH_B_FINAL_STATUS.md](./PATH_B_FINAL_STATUS.md)
- [KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md](./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md)

### External Resources
- Neo4j Cypher Documentation
- RDF/OWL Specifications
- SHACL Specification
- Turtle RDF Specification

---

**Document Version:** 1.0  
**Created:** 2026-02-16  
**Status:** READY FOR REVIEW  
**Estimated Duration:** 240 hours (6 weeks)  
**Estimated Code Reduction:** 25-30% (~7,500-9,000 lines)  
**Priority:** 🔴 HIGH

---

**Next Action:** Review plan and approve Phase 1 start
