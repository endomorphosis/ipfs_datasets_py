# Knowledge Graphs: Master Refactoring, Integration & Improvement Plan
## Comprehensive Strategic Plan for ipfs_datasets_py/knowledge_graphs

**Document Version:** 1.0  
**Date Created:** February 16, 2026  
**Last Updated:** February 16, 2026  
**Status:** 📋 Planning - Ready for Implementation  
**Priority:** 🔴 HIGH - Critical for long-term maintainability  

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Critical Issues](#critical-issues)
4. [Strategic Goals](#strategic-goals)
5. [Implementation Phases](#implementation-phases)
6. [Detailed Task Breakdown](#detailed-task-breakdown)
7. [Success Metrics](#success-metrics)
8. [Risk Management](#risk-management)
9. [Timeline & Resources](#timeline--resources)
10. [Appendices](#appendices)

---

## 📊 Executive Summary

### Current State Overview

**Folder:** `ipfs_datasets_py/knowledge_graphs/`  
**Size:** 61 Python files, 31,716 lines of code, 1.2MB on disk  
**Health Status:** ⚠️ **YELLOW FLAG** - Active refactoring with incomplete testing  

### Key Statistics

| Metric | Current Value | Target Value | Priority |
|--------|---------------|--------------|----------|
| **Total Python Files** | 61 | 45-50 | Medium |
| **Lines of Code** | 31,716 | 22,000-25,000 | High |
| **Test Coverage** | ~40% (estimated) | 90%+ | **CRITICAL** |
| **Files >1000 lines** | 5 | 0-1 | High |
| **Duplicate Code** | 6,423 lines | 0 | **CRITICAL** |
| **Deprecated Files** | 3-4 | 0 | Medium |
| **Documentation Files** | 25+ | 10-12 (consolidated) | Low |

### Recent Progress (Sessions 1-8 Complete ✅)

- **Created:** New `lineage/` package (2,025 lines) consolidating 6,423 lines of duplicates
- **Achievement:** 68.5% code reduction in lineage tracking
- **Tests Added:** 67 comprehensive tests for lineage package
- **Status:** Production-ready lineage package with zero breaking changes

### Critical Gaps Identified

1. **❌ NO UNIT TESTS** in knowledge_graphs directory (except new lineage/ package)
2. **⚠️ Large Monolithic Files** (knowledge_graph_extraction.py: 2,969 lines)
3. **⚠️ Incomplete Refactoring** (extraction/ package planned but empty)
4. **⚠️ Deprecated Modules** still actively used (ipld.py, cross_document_lineage*.py)
5. **⚠️ Fragmented Architecture** (query engines, storage backends)

### Plan Overview

**Total Duration:** 16-20 weeks (320-400 hours)  
**Phases:** 7 major phases  
**Approach:** Incremental, test-driven, zero breaking changes  

---

## 🔍 Current State Analysis

### Directory Structure

```
knowledge_graphs/
├── 📦 Core Modules (9 files, 13,747 lines)
│   ├── knowledge_graph_extraction.py     # 2,969 lines ⚠️ TOO LARGE
│   ├── cross_document_lineage.py         # 4,066 lines 🔴 DUPLICATE
│   ├── cross_document_lineage_enhanced.py# 2,357 lines 🔴 DUPLICATE
│   ├── ipld.py                           # 1,425 lines 🔴 DEPRECATED
│   ├── cross_document_reasoning.py       # 812 lines
│   ├── advanced_knowledge_extractor.py   # 751 lines
│   ├── sparql_query_templates.py         # 567 lines
│   ├── finance_graphrag.py               # 509 lines ⚠️ DOMAIN-SPECIFIC
│   └── query_knowledge_graph.py          # 213 lines
│
├── 📁 Organized Packages (11 subdirectories)
│   ├── lineage/         # ✅ NEW - Production ready (2,025 lines, 67 tests)
│   ├── neo4j_compat/    # ✅ Modern Neo4j-compatible API
│   ├── cypher/          # ✅ Cypher query language support
│   ├── jsonld/          # ✅ JSON-LD and RDF support
│   ├── query/           # ✅ Unified query engine
│   ├── storage/         # ✅ IPLD backend
│   ├── indexing/        # ✅ B-tree and specialized indexes
│   ├── transactions/    # ✅ WAL and transaction management
│   ├── migration/       # ✅ Import/export utilities
│   ├── constraints/     # ⚠️ Purpose unclear
│   ├── core/            # ⚠️ Large query_executor.py (1,960 lines)
│   └── extraction/      # 📋 PLANNED - Empty directory
│
└── 🧪 Tests
    ├── tests/unit/knowledge_graphs/lineage/  # 67 tests ✅
    └── tests/integration/knowledge_graphs/   # Integration tests
```

### Code Distribution Analysis

**By Size Category:**
- **Super Large (>2000 lines):** 3 files (8,392 lines) 🔴
  - knowledge_graph_extraction.py: 2,969 lines
  - cross_document_lineage.py: 4,066 lines
  - cross_document_lineage_enhanced.py: 2,357 lines (being refactored)

- **Large (1000-2000 lines):** 2 files (3,385 lines) ⚠️
  - core/query_executor.py: 1,960 lines
  - ipld.py: 1,425 lines (deprecated)

- **Medium (500-1000 lines):** 4 files (~3,000 lines)
- **Small (<500 lines):** 52 files (~17,000 lines) ✅

### Integration Points

**Knowledge Graphs Dependencies:**
```
knowledge_graphs/
├── Depends On:
│   ├── ipfs_kit_py (IPFS operations)
│   ├── networkx (graph algorithms)
│   ├── transformers (NLP/embeddings)
│   ├── spacy (entity extraction)
│   └── analytics.data_provenance (lineage)
│
└── Used By:
    ├── processors/graphrag/ (heavy usage)
    ├── processors/specialized/graphrag/
    ├── processors/file_converter/
    ├── analytics/ (data_provenance, cross_website_analyzer)
    ├── dashboards/ (provenance_dashboard)
    └── search/ (graphrag_integration)
```

**External Importers:** 58 import statements across codebase

### Test Coverage Analysis

**Current State:**
- **lineage/ package:** ~85% coverage (67 tests) ✅
- **Legacy modules:** ~40% coverage (estimated) ⚠️
- **Overall:** ~60% coverage 🔴

**Test Distribution:**
- Unit tests (lineage): 67 tests ✅
- Integration tests: ~15 tests
- Feature tests (Gherkin): 3 feature files
- **CRITICAL GAP:** No unit tests for:
  - knowledge_graph_extraction.py
  - cross_document_reasoning.py
  - advanced_knowledge_extractor.py
  - Most subdirectory packages

### Documentation Analysis

**Total:** 25+ documentation files (~300KB)

**Categories:**
1. **Planning & Status** (8 files)
   - COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md (41KB)
   - STATUS_2026_02_16.md (7.5KB)
   - IMPLEMENTATION_ROADMAP_2026_02_16.md (23KB)
   - And 5 more...

2. **Implementation Guides** (7 files)
   - MIGRATION_GUIDE.md
   - NEO4J_API_MIGRATION.md
   - REFACTORING_PLAN.md
   - And 4 more...

3. **Reference Docs** (10 files)
   - FEATURE_MATRIX.md
   - QUICK_REFERENCE.md
   - DOCUMENTATION_INDEX.md
   - And 7 more...

**Issues:**
- ⚠️ Too many overlapping documents
- ⚠️ Unclear which docs are current
- ⚠️ Need consolidation into 10-12 authoritative docs

---

## 🚨 Critical Issues

### Priority 0: Immediate Action Required

#### Issue #1: No Test Coverage for Core Modules

**Severity:** 🔴 CRITICAL  
**Impact:** High risk for breaking changes during refactoring  

**Affected Modules:**
- knowledge_graph_extraction.py (2,969 lines, 0 tests)
- cross_document_lineage.py (4,066 lines, minimal tests)
- cross_document_reasoning.py (812 lines, 0 tests)
- advanced_knowledge_extractor.py (751 lines, 0 tests)

**Risk:**
- Cannot safely refactor without tests
- Production code at risk
- Technical debt accumulating

**Solution Required:** Create comprehensive test suite BEFORE any refactoring

---

#### Issue #2: Duplicate Lineage Code (6,423 lines)

**Severity:** 🔴 CRITICAL  
**Impact:** Code bloat, maintenance burden, inconsistency risk  

**Current State:**
- cross_document_lineage.py: 4,066 lines
- cross_document_lineage_enhanced.py: 2,357 lines
- **Total:** 6,423 lines with ~70% overlap

**Refactoring Progress:**
- ✅ lineage/ package created (2,025 lines)
- ✅ 68.5% code reduction achieved
- ⚠️ Legacy files still in production use
- ❌ No deprecation warnings active

**Solution Required:** Complete migration and deprecate legacy files

---

#### Issue #3: Monolithic Extraction Module

**Severity:** 🔴 HIGH  
**Impact:** Hard to maintain, test, and extend  

**Details:**
- File: knowledge_graph_extraction.py
- Size: 2,969 lines
- Classes: 5+ major classes
- Concerns: Extraction, validation, Wikipedia integration, acceleration
- TODOs: 8 unresolved items

**Problems:**
- Violates single responsibility principle
- Mixed abstraction levels
- Hard to test individual components
- Circular dependency risks

**Solution Required:** Split into extraction/ package with proper architecture

---

### Priority 1: High Priority Issues

#### Issue #4: Deprecated Module Still Active

**Severity:** 🟠 HIGH  
**Module:** ipld.py (1,425 lines)  

**Status:**
- Explicit deprecation notice at top of file
- Recommended migration: neo4j_compat API
- Still imported in __init__.py for compatibility
- Unknown number of external dependencies

**Solution Required:** Complete neo4j_compat migration, archive ipld.py

---

#### Issue #5: Incomplete Refactoring (extraction/ package)

**Severity:** 🟠 HIGH  
**Status:** Planning phase only (README.md exists, no code)  

**Planned Structure:**
```
extraction/
├── entities.py (~400 lines)   # Entity and Relationship classes
├── extractors.py (~1,000 lines)  # Extraction algorithms
├── analyzers.py (~800 lines)     # Semantic analysis
└── builders.py (~700 lines)      # Graph construction
```

**Current:** Empty except README.md with 6-month timeline

**Problem:** Blocks progress on other refactorings

**Solution Required:** Implement extraction/ package or abandon

---

#### Issue #6: Large Query Executor

**Severity:** 🟠 MEDIUM-HIGH  
**File:** core/query_executor.py (1,960 lines)  

**Should be split into:**
- executor.py (~600 lines) - Execution logic
- optimizer.py (~700 lines) - Query optimization
- planner.py (~400 lines) - Query planning
- analyzer.py (~260 lines) - Query analysis

**Solution Required:** Split when test coverage reaches 80%

---

### Priority 2: Medium Priority Issues

#### Issue #7: Fragmented Query Architecture

**Severity:** 🟡 MEDIUM  

**Current State:**
- query/ package (unified_engine.py, hybrid_search.py, budget_manager.py)
- core/query_executor.py
- query_knowledge_graph.py (root level)
- Unclear relationships and responsibilities

**Solution Required:** Consolidate query architecture

---

#### Issue #8: Documentation Sprawl

**Severity:** 🟡 MEDIUM  
**Count:** 25+ documentation files  

**Issues:**
- Overlapping content
- Outdated information
- No clear hierarchy
- Hard to find authoritative source

**Solution Required:** Consolidate to 10-12 authoritative docs

---

#### Issue #9: Unclear Module Purpose

**Severity:** 🟡 MEDIUM  

**Modules:**
- constraints/ package (minimal documentation)
- finance_graphrag.py (domain-specific, unclear why in core)
- sparql_query_templates.py (limited usage)

**Solution Required:** Document purpose or consolidate/remove

---

## 🎯 Strategic Goals

### Primary Objectives

#### Goal 1: Achieve 90%+ Test Coverage

**Current:** ~60% overall, ~40% legacy modules  
**Target:** 90%+ across all modules  

**Success Criteria:**
- ✅ Unit tests for all public APIs
- ✅ Integration tests for cross-module functionality
- ✅ Test coverage reports in CI/CD
- ✅ No module below 80% coverage

**Value:** Safe refactoring, regression prevention, confidence in changes

---

#### Goal 2: Eliminate Code Duplication

**Current:** 6,423 lines duplicate in lineage modules  
**Target:** <1% duplication (DRY principle)  

**Success Criteria:**
- ✅ Complete lineage/ package migration
- ✅ Deprecate cross_document_lineage*.py
- ✅ No overlapping class definitions
- ✅ Single source of truth for all functionality

**Value:** Reduced maintenance, consistency, smaller codebase

---

#### Goal 3: Refactor Monolithic Files

**Current:** 5 files >1000 lines  
**Target:** 0-1 files >1000 lines  

**Success Criteria:**
- ✅ knowledge_graph_extraction.py → extraction/ package
- ✅ core/query_executor.py split into 4 modules
- ✅ All modules follow single responsibility
- ✅ Clear module boundaries

**Value:** Improved maintainability, easier testing, better organization

---

#### Goal 4: Complete Deprecation Cycle

**Current:** 3-4 deprecated but active modules  
**Target:** 0 deprecated modules in production  

**Success Criteria:**
- ✅ ipld.py archived
- ✅ cross_document_lineage*.py archived
- ✅ All imports migrated to new APIs
- ✅ Backward compatibility maintained

**Value:** Clean codebase, clear API surface, reduced confusion

---

#### Goal 5: Consolidate Documentation

**Current:** 25+ docs, overlapping content  
**Target:** 10-12 authoritative documents  

**Success Criteria:**
- ✅ Single source of truth for each topic
- ✅ Clear documentation hierarchy
- ✅ Up-to-date API references
- ✅ Comprehensive migration guides

**Value:** Easier onboarding, reduced confusion, better discoverability

---

### Secondary Objectives

#### Goal 6: Improve Integration Points

**Focus Areas:**
- Processors (GraphRAG)
- Analytics (Data provenance)
- Search (Recommendation engines)
- Dashboards (Provenance visualization)

**Success Criteria:**
- ✅ Clear integration APIs documented
- ✅ Example code for common integrations
- ✅ Integration tests for all major use cases
- ✅ Performance benchmarks

---

#### Goal 7: Enhance Code Quality

**Target Standards:**
- 95%+ type hints
- 100% docstrings for public APIs
- Zero linting errors
- <10 complexity per function

**Tools:**
- mypy (type checking)
- flake8 (linting)
- coverage (test coverage)
- radon (complexity analysis)

---

## 📅 Implementation Phases

### Phase 1: Test Infrastructure & Coverage (40-50 hours)

**Duration:** 2-3 weeks  
**Priority:** 🔴 CRITICAL  
**Dependencies:** None  

**Objectives:**
1. Create comprehensive test framework
2. Achieve 80%+ coverage on legacy modules
3. Establish CI/CD test requirements
4. Create test documentation

**Deliverables:**
- ✅ Test framework for knowledge_graphs
- ✅ 100+ new unit tests
- ✅ 20+ integration tests
- ✅ Test coverage reports
- ✅ Testing guidelines document

**Tasks:**
1.1. Set up test infrastructure (4 hours)
1.2. Unit tests for knowledge_graph_extraction.py (12 hours)
1.3. Unit tests for cross_document_lineage.py (8 hours)
1.4. Unit tests for cross_document_reasoning.py (6 hours)
1.5. Unit tests for advanced_knowledge_extractor.py (6 hours)
1.6. Integration tests (10 hours)
1.7. CI/CD integration (4 hours)

**Success Metrics:**
- Coverage: 40% → 80%+
- Test count: 67 → 200+
- CI/CD: Failing tests block merges

---

### Phase 2: Complete Lineage Migration (20-24 hours)

**Duration:** 1 week  
**Priority:** 🔴 HIGH  
**Dependencies:** Phase 1 (tests for legacy modules)  

**Objectives:**
1. Finalize lineage/ package
2. Add deprecation warnings to legacy files
3. Update all internal imports
4. Monitor external usage

**Deliverables:**
- ✅ Deprecation warnings active
- ✅ Migration script for external users
- ✅ Updated imports across codebase
- ✅ Usage monitoring dashboard

**Tasks:**
2.1. Add deprecation warnings (2 hours)
2.2. Usage analysis across codebase (4 hours)
2.3. Update internal imports (6 hours)
2.4. Create migration script (4 hours)
2.5. Documentation updates (4 hours)
2.6. Monitor usage for 2 weeks (tracked separately)

**Success Metrics:**
- Deprecation warnings: 100% coverage
- Internal imports migrated: 100%
- External usage tracked: Yes
- Breaking changes: 0

---

### Phase 3: Extract Knowledge Graph Extraction (40-50 hours)

**Duration:** 2-3 weeks  
**Priority:** 🔴 HIGH  
**Dependencies:** Phase 1 (test coverage for extraction module)  

**Objectives:**
1. Implement extraction/ package structure
2. Migrate classes with backward compatibility
3. Maintain 100% test coverage
4. Resolve TODOs

**Deliverables:**
- ✅ extraction/ package with 4-5 modules
- ✅ Backward compatibility shims
- ✅ Resolved TODOs (8 items)
- ✅ Migration guide

**Planned Structure:**
```python
extraction/
├── __init__.py              # Public API, backward compat
├── types.py                 # Entity, Relationship, KnowledgeGraph
├── extractors.py            # KnowledgeGraphExtractor base
├── validators.py            # KnowledgeGraphExtractorWithValidation
├── integrations.py          # Wikipedia, Accelerate integration
└── utils.py                 # Helper functions
```

**Tasks:**
3.1. Create extraction/types.py (8 hours)
3.2. Create extraction/extractors.py (12 hours)
3.3. Create extraction/validators.py (8 hours)
3.4. Create extraction/integrations.py (6 hours)
3.5. Create backward compatibility layer (4 hours)
3.6. Update tests (6 hours)
3.7. Documentation (6 hours)

**Success Metrics:**
- knowledge_graph_extraction.py: 2,969 → <100 lines (shim)
- extraction/ package: ~2,500 lines across 5 modules
- Test coverage: Maintained at 80%+
- Breaking changes: 0

---

### Phase 4: Split Query Executor (24-30 hours)

**Duration:** 1-2 weeks  
**Priority:** 🟠 MEDIUM-HIGH  
**Dependencies:** Phase 1 (test coverage for query_executor)  

**Objectives:**
1. Split core/query_executor.py into focused modules
2. Maintain backward compatibility
3. Improve testability

**Deliverables:**
- ✅ 4 focused modules (<500 lines each)
- ✅ Backward compatibility maintained
- ✅ Updated tests
- ✅ Performance benchmarks

**Planned Structure:**
```python
core/
├── __init__.py           # Public API
├── executor.py           # Query execution (~600 lines)
├── optimizer.py          # Query optimization (~700 lines)
├── planner.py            # Query planning (~400 lines)
└── analyzer.py           # Query analysis (~260 lines)
```

**Tasks:**
4.1. Analyze dependencies (4 hours)
4.2. Create core/executor.py (6 hours)
4.3. Create core/optimizer.py (6 hours)
4.4. Create core/planner.py (4 hours)
4.5. Create core/analyzer.py (4 hours)

**Success Metrics:**
- Modules: 1 → 4-5
- Largest module: 1,960 → <700 lines
- Test coverage: Maintained
- Performance: No regression

---

### Phase 5: Deprecation & Cleanup (20-24 hours)

**Duration:** 1 week  
**Priority:** 🟠 MEDIUM  
**Dependencies:** Phase 2, Phase 3  

**Objectives:**
1. Archive deprecated modules
2. Remove dead code
3. Consolidate query architecture
4. Clean up imports

**Deliverables:**
- ✅ Archived modules (ipld.py, cross_document_lineage*.py)
- ✅ Cleaned __init__.py
- ✅ Consolidated query modules
- ✅ Updated documentation

**Tasks:**
5.1. Archive ipld.py (4 hours)
5.2. Archive lineage legacy files (4 hours)
5.3. Consolidate query architecture (8 hours)
5.4. Clean up imports and __init__.py (4 hours)
5.5. Remove dead code (4 hours)

**Success Metrics:**
- Files removed/archived: 3-4
- Code reduction: ~8,000 lines
- Breaking changes: 0 (with shims)
- Deprecation timeline: 6 months

---

### Phase 6: Integration & Documentation (30-40 hours)

**Duration:** 2 weeks  
**Priority:** 🟡 MEDIUM  
**Dependencies:** Phase 3, Phase 4, Phase 5  

**Objectives:**
1. Update all integration points
2. Consolidate documentation
3. Create comprehensive examples
4. Performance benchmarks

**Deliverables:**
- ✅ Updated processor integrations
- ✅ Consolidated documentation (10-12 docs)
- ✅ Example gallery (10+ examples)
- ✅ Performance benchmarks
- ✅ Migration guides

**Tasks:**
6.1. Update processor/graphrag integration (8 hours)
6.2. Update analytics integration (4 hours)
6.3. Update search integration (4 hours)
6.4. Consolidate documentation (8 hours)
6.5. Create examples (6 hours)
6.6. Performance benchmarks (6 hours)
6.7. API reference (4 hours)

**Success Metrics:**
- Documentation: 25+ → 10-12 files
- Examples: 4 → 10+
- Integration points documented: 100%
- Performance baselines established

---

### Phase 7: Quality & Optimization (20-30 hours)

**Duration:** 1-2 weeks  
**Priority:** 🟡 LOW-MEDIUM  
**Dependencies:** All previous phases  

**Objectives:**
1. Code quality improvements
2. Performance optimization
3. Security review
4. Final validation

**Deliverables:**
- ✅ Zero linting errors
- ✅ 95%+ type hints
- ✅ Performance improvements (10-20%)
- ✅ Security scan clean
- ✅ Final test suite (90%+ coverage)

**Tasks:**
7.1. Type hint improvements (8 hours)
7.2. Linting and code style (4 hours)
7.3. Performance profiling (6 hours)
7.4. Performance optimization (6 hours)
7.5. Security review (4 hours)
7.6. Final testing and validation (4 hours)

**Success Metrics:**
- Type hints: 60% → 95%
- Linting errors: ? → 0
- Test coverage: 80% → 90%+
- Performance: 10-20% improvement
- Security issues: 0

---

## 📝 Detailed Task Breakdown

### Phase 1 Tasks (Test Infrastructure)

#### Task 1.1: Set Up Test Infrastructure (4 hours)

**Objective:** Create comprehensive test framework for knowledge_graphs

**Steps:**
1. Create test directory structure
2. Set up pytest configuration
3. Create test fixtures and utilities
4. Configure coverage reporting

**Files to Create:**
```
tests/unit/knowledge_graphs/
├── __init__.py
├── conftest.py               # Shared fixtures
├── test_extraction.py        # NEW
├── test_lineage_legacy.py    # NEW
├── test_reasoning.py         # NEW
└── test_advanced_extractor.py # NEW
```

**Deliverables:**
- pytest.ini configuration
- conftest.py with shared fixtures
- Coverage configuration (.coveragerc)
- Testing guidelines document

---

#### Task 1.2: Unit Tests for knowledge_graph_extraction.py (12 hours)

**Objective:** Achieve 80%+ coverage for extraction module

**Test Categories:**
1. Entity extraction tests (3 hours)
2. Relationship extraction tests (3 hours)
3. Knowledge graph construction tests (3 hours)
4. Validation tests (2 hours)
5. Integration tests (Wikipedia, Accelerate) (1 hour)

**Target:** 40-50 test cases

**Example Test Structure:**
```python
class TestKnowledgeGraphExtractor:
    def test_extract_entities_basic(self):
        """GIVEN a simple text, WHEN extracting entities, THEN returns expected entities"""
        pass
    
    def test_extract_relationships(self):
        """GIVEN entities, WHEN extracting relationships, THEN returns valid relationships"""
        pass
```

---

#### Task 1.3: Unit Tests for cross_document_lineage.py (8 hours)

**Objective:** Test legacy lineage module before migration

**Test Categories:**
1. LineageNode tests (2 hours)
2. LineageTracker tests (3 hours)
3. Graph operations tests (2 hours)
4. Serialization tests (1 hour)

**Target:** 30-40 test cases

---

#### Task 1.4-1.7: Additional Test Tasks

Similar structure for:
- cross_document_reasoning.py (6 hours, 20-25 tests)
- advanced_knowledge_extractor.py (6 hours, 20-25 tests)
- Integration tests (10 hours, 15-20 tests)
- CI/CD integration (4 hours)

---

### Phase 2 Tasks (Lineage Migration)

#### Task 2.1: Add Deprecation Warnings (2 hours)

**Objective:** Warn users about deprecated lineage modules

**Implementation:**
```python
# In cross_document_lineage.py, add at top:
import warnings

warnings.warn(
    "cross_document_lineage is deprecated. "
    "Use 'from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker' instead. "
    "This module will be removed in version 2.0 (6 months). "
    "See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration instructions.",
    DeprecationWarning,
    stacklevel=2
)
```

**Files to Update:**
- cross_document_lineage.py
- cross_document_lineage_enhanced.py

---

#### Task 2.2: Usage Analysis (4 hours)

**Objective:** Find all internal and external usage of deprecated modules

**Method:**
```bash
# Find all imports
grep -r "from.*cross_document_lineage" . --include="*.py"
grep -r "import.*cross_document_lineage" . --include="*.py"
```

**Deliverable:** Usage report with:
- List of all internal usages
- Estimated external usage (via package stats)
- Migration priority ranking

---

#### Task 2.3-2.6: Additional Migration Tasks

- Update internal imports (6 hours)
- Create migration script (4 hours)
- Documentation updates (4 hours)
- Monitor usage (ongoing)

---

### Phase 3 Tasks (Knowledge Graph Extraction)

#### Task 3.1: Create extraction/types.py (8 hours)

**Objective:** Extract Entity, Relationship, KnowledgeGraph classes

**Structure:**
```python
"""Core types for knowledge graph extraction."""

from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from enum import Enum

class EntityType(Enum):
    """Entity type enumeration."""
    PERSON = "PERSON"
    ORGANIZATION = "ORG"
    LOCATION = "LOC"
    # ... more types

@dataclass
class Entity:
    """Represents an entity in a knowledge graph."""
    id: str
    text: str
    type: EntityType
    metadata: Dict[str, Any]
    
@dataclass
class Relationship:
    """Represents a relationship between entities."""
    source: Entity
    target: Entity
    type: str
    confidence: float
    
class KnowledgeGraph:
    """Container for entities and relationships."""
    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
```

**Tests:** 20-25 unit tests

---

#### Task 3.2-3.7: Additional Extraction Tasks

- Create extractors.py (12 hours)
- Create validators.py (8 hours)
- Create integrations.py (6 hours)
- Backward compatibility layer (4 hours)
- Update tests (6 hours)
- Documentation (6 hours)

---

## 📊 Success Metrics

### Quantitative Metrics

| Metric | Baseline | Target | Measurement Method |
|--------|----------|--------|-------------------|
| **Test Coverage** | ~60% | 90%+ | pytest-cov |
| **Code Lines** | 31,716 | 22,000-25,000 | wc -l |
| **Duplicate Code** | 6,423 | <200 | manual analysis |
| **Files >1000 lines** | 5 | 0-1 | find + wc |
| **Test Count** | 67 | 250+ | pytest --collect-only |
| **Linting Errors** | Unknown | 0 | flake8 |
| **Type Coverage** | ~60% | 95%+ | mypy --html-report |
| **Documentation Files** | 25+ | 10-12 | ls docs/ |
| **Cyclomatic Complexity** | Unknown | <10 avg | radon |
| **Import Count** | 58 | 58 (unchanged) | grep analysis |

### Qualitative Metrics

| Aspect | Current State | Target State | Measurement |
|--------|---------------|--------------|-------------|
| **Code Organization** | Fragmented | Well-structured | Code review |
| **API Clarity** | Mixed (legacy + new) | Single clear API | API review |
| **Documentation Quality** | Good but scattered | Excellent + consolidated | User feedback |
| **Maintainability** | Medium | High | Developer survey |
| **Integration Ease** | Medium | Easy | Integration tests |
| **Migration Path** | Unclear | Clear + documented | Migration guide review |

### Success Criteria

**Phase Completion Criteria:**
- ✅ All tasks completed
- ✅ All tests passing
- ✅ Coverage targets met
- ✅ Documentation updated
- ✅ Zero breaking changes
- ✅ Code review approved

**Overall Project Success:**
- ✅ 90%+ test coverage achieved
- ✅ All duplicate code eliminated
- ✅ All monolithic files refactored
- ✅ All deprecated modules archived
- ✅ Documentation consolidated
- ✅ Performance maintained or improved
- ✅ Zero production issues during migration

---

## ⚠️ Risk Management

### High-Risk Areas

#### Risk 1: Breaking Production Code

**Probability:** Medium  
**Impact:** HIGH  
**Phase:** All phases  

**Mitigation Strategies:**
1. **Comprehensive Testing:** Achieve 80%+ coverage before refactoring
2. **Backward Compatibility:** Always provide compatibility shims
3. **Incremental Changes:** Small, reviewable changes
4. **Deprecation Period:** 6-month warning before removal
5. **Monitoring:** Track usage of deprecated APIs
6. **Rollback Plan:** Git tags for easy rollback

**Contingency:**
- If breaking changes detected, immediately rollback
- Extended deprecation period (12 months)
- Direct communication with affected users

---

#### Risk 2: Incomplete Migration

**Probability:** Medium  
**Impact:** MEDIUM-HIGH  
**Phase:** Phase 2, 3, 5  

**Mitigation Strategies:**
1. **Usage Analysis:** Comprehensive analysis before migration
2. **Migration Scripts:** Automated migration where possible
3. **Clear Documentation:** Step-by-step migration guides
4. **Examples:** Working examples for all scenarios
5. **Support:** Dedicated migration support period

**Contingency:**
- Extend migration period
- Provide direct migration assistance
- Keep legacy code longer if needed

---

#### Risk 3: Performance Regression

**Probability:** Low-Medium  
**Impact:** MEDIUM  
**Phase:** Phase 3, 4, 7  

**Mitigation Strategies:**
1. **Baseline Benchmarks:** Establish performance baselines
2. **Continuous Monitoring:** Performance tests in CI/CD
3. **Profiling:** Profile critical paths before/after
4. **Optimization:** Address regressions immediately
5. **Caching:** Leverage existing caching strategies

**Contingency:**
- If >10% regression, identify and optimize
- If >20% regression, reconsider approach
- Performance optimization sprint if needed

---

### Medium-Risk Areas

#### Risk 4: Test Maintenance Burden

**Probability:** Medium  
**Impact:** MEDIUM  
**Phase:** Phase 1, ongoing  

**Mitigation:**
- Use fixtures and utilities to reduce duplication
- Focus on critical paths
- Avoid brittle tests (implementation details)
- Regular test review and cleanup

---

#### Risk 5: Documentation Drift

**Probability:** Medium  
**Impact:** LOW-MEDIUM  
**Phase:** Phase 6, ongoing  

**Mitigation:**
- Documentation as part of every PR
- Automated documentation generation where possible
- Regular documentation reviews
- Clear ownership of documentation

---

### Low-Risk Areas

#### Risk 6: Over-Engineering

**Probability:** Low  
**Impact:** MEDIUM  
**Phase:** Phase 3, 4  

**Mitigation:**
- Follow YAGNI principle
- Start simple, iterate based on needs
- Code review focus on simplicity
- Avoid premature optimization

---

## ⏱️ Timeline & Resources

### Overall Timeline

**Total Duration:** 16-20 weeks (4-5 months)  
**Total Effort:** 320-400 hours  
**Recommended Team Size:** 1-2 developers  

### Phase Timeline

| Phase | Duration | Effort | Start Week | Dependencies |
|-------|----------|--------|------------|--------------|
| **Phase 1: Tests** | 2-3 weeks | 40-50h | Week 1 | None |
| **Phase 2: Lineage** | 1 week | 20-24h | Week 3 | Phase 1 |
| **Phase 3: Extraction** | 2-3 weeks | 40-50h | Week 4 | Phase 1 |
| **Phase 4: Query Executor** | 1-2 weeks | 24-30h | Week 7 | Phase 1 |
| **Phase 5: Cleanup** | 1 week | 20-24h | Week 9 | Phase 2, 3 |
| **Phase 6: Integration** | 2 weeks | 30-40h | Week 10 | Phase 3, 4, 5 |
| **Phase 7: Quality** | 1-2 weeks | 20-30h | Week 12 | All |
| **Buffer** | 2-4 weeks | - | Week 14+ | - |

### Gantt Chart (Text Format)

```
Week:     1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16
Phase 1:  [====Test Infrastructure====]
Phase 2:          [=Lineage=]
Phase 3:              [======Extraction======]
Phase 4:                          [=Query=]
Phase 5:                                  [Cleanup]
Phase 6:                                      [==Integration==]
Phase 7:                                              [=Quality=]
Buffer:                                                          [====]
```

### Resource Requirements

**Primary Developer:**
- Full-time dedication: 20-25 hours per week
- Skills: Python, testing, refactoring, graph databases
- Experience: 3+ years Python, familiar with codebase

**Code Reviewer:**
- Part-time: 5-10 hours per week
- Skills: Architecture, code quality, domain knowledge
- Experience: Senior developer familiar with project

**Tools & Infrastructure:**
- CI/CD pipeline (existing)
- Test coverage tools (pytest-cov)
- Code quality tools (mypy, flake8, radon)
- Performance profiling tools
- Git/GitHub

**Budget Estimate:**
- Developer time: 320-400 hours @ $80-150/hr = $25,600-$60,000
- Reviewer time: 80-100 hours @ $100-200/hr = $8,000-$20,000
- Tools: Minimal (existing infrastructure)
- **Total: $33,600-$80,000**

---

## 📚 Appendices

### Appendix A: File Inventory

**Complete listing of all 61 Python files with sizes and status**

```
knowledge_graphs/
├── __init__.py (78 lines) - ✅ Good
├── knowledge_graph_extraction.py (2,969 lines) - 🔴 TO REFACTOR
├── cross_document_lineage.py (4,066 lines) - 🔴 TO DEPRECATE
├── cross_document_lineage_enhanced.py (2,357 lines) - 🔴 TO DEPRECATE
├── ipld.py (1,425 lines) - 🔴 DEPRECATED
├── cross_document_reasoning.py (812 lines) - ✅ OK
├── advanced_knowledge_extractor.py (751 lines) - ✅ OK
├── sparql_query_templates.py (567 lines) - ⚠️ REVIEW USAGE
├── finance_graphrag.py (509 lines) - ⚠️ REVIEW PLACEMENT
├── query_knowledge_graph.py (213 lines) - ⚠️ MAY CONSOLIDATE
├── lineage/ (5 files, 2,025 lines) - ✅ PRODUCTION READY
│   ├── __init__.py (106 lines)
│   ├── types.py (278 lines)
│   ├── core.py (545 lines)
│   ├── enhanced.py (442 lines)
│   ├── visualization.py (297 lines)
│   └── metrics.py (357 lines)
├── neo4j_compat/ (7 files) - ✅ PRODUCTION READY
├── cypher/ (7 files) - ✅ PRODUCTION READY
├── jsonld/ (6 files) - ✅ PRODUCTION READY
├── query/ (4 files) - ✅ OK
├── storage/ (3 files) - ✅ OK
├── indexing/ (5 files) - ✅ OK
├── transactions/ (4 files) - ✅ OK
├── migration/ (6 files) - ✅ OK
├── constraints/ (1 file) - ⚠️ UNCLEAR PURPOSE
├── core/ (2 files) - ⚠️ query_executor.py TO SPLIT
└── extraction/ (1 file, README only) - 📋 PLANNED
```

---

### Appendix B: Test Coverage Details

**Current Test Distribution:**

```
tests/unit/knowledge_graphs/
└── lineage/
    ├── test_types.py (17 tests)
    ├── test_core.py (28 tests)
    ├── test_enhanced.py (13 tests)
    └── test_metrics.py (9 tests)

tests/integration/knowledge_graphs/
└── (few integration tests)

tests/unit/
├── test_ipld_knowledge_graph_traversal.py
├── test_knowledge_graph_large_blocks.py
└── test_stubs_from_gherkin/
    ├── test_cross_document_lineage.py
    ├── test_cross_document_lineage_enhanced.py
    └── test_knowledge_graph_extraction.py
```

**Target Test Structure:**

```
tests/unit/knowledge_graphs/
├── lineage/ (67 tests) ✅
├── test_extraction.py (40-50 tests) 🎯
├── test_reasoning.py (20-25 tests) 🎯
├── test_advanced_extractor.py (20-25 tests) 🎯
├── test_query_executor.py (30-40 tests) 🎯
├── neo4j_compat/ (existing tests) ✅
├── cypher/ (existing tests) ✅
└── ... (other packages)

tests/integration/knowledge_graphs/
├── test_graphrag_integration.py 🎯
├── test_processor_integration.py 🎯
├── test_analytics_integration.py 🎯
└── test_end_to_end.py 🎯
```

---

### Appendix C: Migration Scripts

**Script 1: Lineage Migration Helper**

```python
#!/usr/bin/env python3
"""
Migrate from legacy lineage modules to new lineage package.

Usage:
    python migrate_lineage.py --path /path/to/code --dry-run
    python migrate_lineage.py --path /path/to/code --execute
"""

import re
import sys
from pathlib import Path

OLD_IMPORTS = [
    r"from ipfs_datasets_py\.knowledge_graphs\.cross_document_lineage import",
    r"from ipfs_datasets_py\.knowledge_graphs\.cross_document_lineage_enhanced import",
]

NEW_IMPORT = "from ipfs_datasets_py.knowledge_graphs.lineage import"

def migrate_file(file_path: Path, dry_run: bool = True):
    """Migrate imports in a single file."""
    content = file_path.read_text()
    modified = content
    
    for old_pattern in OLD_IMPORTS:
        modified = re.sub(old_pattern, NEW_IMPORT, modified)
    
    if modified != content:
        if dry_run:
            print(f"Would modify: {file_path}")
        else:
            file_path.write_text(modified)
            print(f"Modified: {file_path}")
        return True
    return False

def main():
    # Implementation...
    pass

if __name__ == "__main__":
    main()
```

---

### Appendix D: Deprecation Timeline

**6-Month Deprecation Plan:**

| Month | Action | Status |
|-------|--------|--------|
| **Month 0 (Feb 2026)** | Add deprecation warnings | 🎯 |
| **Month 1 (Mar 2026)** | Monitor usage, update docs | 📋 |
| **Month 2 (Apr 2026)** | Update internal code | 📋 |
| **Month 3 (May 2026)** | Provide migration scripts | 📋 |
| **Month 4 (Jun 2026)** | Direct user support | 📋 |
| **Month 5 (Jul 2026)** | Final warnings | 📋 |
| **Month 6 (Aug 2026)** | Archive deprecated code | 📋 |

**Archived Files Location:**
```
docs/archive/knowledge_graphs/
├── ARCHIVE_INDEX.md
├── cross_document_lineage.py
├── cross_document_lineage_enhanced.py
└── ipld.py
```

---

### Appendix E: Integration Examples

**Example 1: GraphRAG Processor Integration**

```python
# OLD: Using legacy extraction
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    KnowledgeGraphExtractor
)

# NEW: Using extraction package
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor
)

# Usage remains the same
extractor = KnowledgeGraphExtractor()
kg = extractor.extract(text)
```

**Example 2: Lineage Tracking**

```python
# OLD: Legacy lineage tracking
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    CrossDocumentLineageTracker
)

# NEW: Modern lineage API
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker
)

# Usage
tracker = LineageTracker()
tracker.track_node(node_id, metadata)
```

---

### Appendix F: Performance Baselines

**Baseline Benchmarks (to be established in Phase 1):**

| Operation | Current Time | Target Time | Notes |
|-----------|--------------|-------------|-------|
| Extract entities (1000 words) | TBD | - | Baseline |
| Build knowledge graph (100 entities) | TBD | - | Baseline |
| Query graph (depth=3) | TBD | - | Baseline |
| Track lineage (1000 nodes) | TBD | - | Baseline |
| Serialize graph to IPLD | TBD | - | Baseline |

**Performance Goals:**
- No regression >5% for critical operations
- Optimization target: 10-20% improvement where possible
- Memory usage: No increase >10%

---

### Appendix G: Communication Plan

**Stakeholder Communication:**

1. **Internal Team:**
   - Weekly progress updates
   - PR reviews and discussions
   - Shared documentation

2. **External Users:**
   - Deprecation announcements (GitHub releases)
   - Migration guides (documentation)
   - Support period (6 months)

3. **Key Milestones to Announce:**
   - Phase 1 complete (test infrastructure)
   - Phase 2 complete (lineage migration)
   - Phase 3 complete (extraction refactoring)
   - Final release (all phases complete)

**Communication Channels:**
- GitHub releases
- Documentation updates
- CHANGELOG.md
- Migration guides
- Direct support (issues/discussions)

---

## 🎯 Conclusion

This comprehensive plan provides a clear roadmap for refactoring, integrating, and improving the `knowledge_graphs` folder over 16-20 weeks. The incremental, test-driven approach minimizes risk while delivering significant improvements:

- **Code Quality:** 90%+ test coverage, 95%+ type hints, zero linting errors
- **Maintainability:** Eliminate 6,423 lines of duplication, refactor monolithic files
- **Architecture:** Clear module boundaries, single source of truth
- **Documentation:** Consolidated, comprehensive, up-to-date
- **Migration:** Zero breaking changes, 6-month deprecation period

**Next Steps:**
1. Review and approve this plan
2. Begin Phase 1: Test Infrastructure
3. Execute phases incrementally with continuous validation
4. Monitor progress and adjust as needed

**Success Criteria:**
- All phases completed
- All metrics achieved
- Zero production issues
- User satisfaction with migration process

---

**Document Owner:** GitHub Copilot Agent  
**Last Review:** February 16, 2026  
**Next Review:** Start of Phase 2  
**Approval Status:** Pending stakeholder review  

---

**Related Documents:**
- KNOWLEDGE_GRAPHS_STATUS_2026_02_16.md
- KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md
- KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md
- KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md
