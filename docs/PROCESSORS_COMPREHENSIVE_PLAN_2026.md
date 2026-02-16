# Comprehensive Processors Refactoring/Improvement/Integration Plan 2026

**Document Version:** 2.0  
**Created:** February 16, 2026  
**Status:** PLANNING → IMPLEMENTATION  
**Priority:** HIGH - Code Quality, Architecture, Maintainability  
**Estimated Effort:** 92 hours over 3-4 weeks  

---

## Executive Summary

This document provides a comprehensive plan for completing the processors directory refactoring, addressing remaining technical debt, and establishing a production-ready architecture. While significant progress was made in Phase 1 (completed February 15, 2026), several critical areas require attention to achieve full consolidation and maintainability.

### Key Achievements to Date (Phase 1)
✅ **20 files consolidated** (702KB → 27.4KB, 96.1% reduction)  
✅ **123 stub files archived**  
✅ **~15,000 lines eliminated**  
✅ **Clear directory structure** established (specialized/, infrastructure/, domains/)  
✅ **Backward compatibility** maintained with deprecation shims  
✅ **Migration guide** created  

### Remaining Challenges
⚠️ **32 root-level files** still present (mix of shims and substantial code)  
⚠️ **Large monolithic files** not yet refactored (llm_optimizer.py: 3,377 lines, query_engine.py: 2,996 lines)  
⚠️ **Registry duplication** (registry.py vs core/processor_registry.py)  
⚠️ **Advanced processors** not yet organized (advanced_media_processing.py, advanced_web_archiving.py)  
⚠️ **Test coverage gaps** for refactored modules  
⚠️ **Documentation sprawl** (35+ processor-related docs)  

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Architecture Goals](#2-architecture-goals)
3. [Phase-by-Phase Implementation Plan](#3-phase-by-phase-implementation-plan)
4. [Testing Strategy](#4-testing-strategy)
5. [Migration & Compatibility](#5-migration--compatibility)
6. [Performance Optimization](#6-performance-optimization)
7. [Documentation Strategy](#7-documentation-strategy)
8. [Risk Management](#8-risk-management)
9. [Success Metrics](#9-success-metrics)
10. [Timeline & Resources](#10-timeline--resources)

---

## 1. Current State Analysis

### 1.1 Directory Structure

```
processors/
├── __init__.py                           # Main entry point (121 lines)
│
├── specialized/                          # ✅ Well-organized
│   ├── graphrag/                        # GraphRAG processing
│   │   ├── unified_graphrag.py
│   │   ├── integration.py
│   │   └── website_system.py
│   ├── pdf/                             # PDF processing
│   │   ├── pdf_processor.py
│   │   ├── pdf_processing.py
│   │   └── ocr_engine.py
│   ├── multimodal/                      # Multimodal content
│   │   ├── processor.py
│   │   └── multimodal_processor.py
│   └── batch/                           # Batch processing
│       ├── processor.py
│       └── file_converter_batch.py
│
├── infrastructure/                       # ✅ Well-organized
│   ├── caching.py
│   ├── monitoring.py
│   ├── error_handling.py
│   ├── profiling.py
│   ├── debug_tools.py
│   └── cli.py
│
├── domains/                              # ✅ Well-organized
│   ├── patent/                          # Patent processing
│   │   ├── patent_scraper.py
│   │   └── patent_dataset_api.py
│   ├── geospatial/                      # Geographic analysis
│   │   └── geospatial_analysis.py
│   └── ml/                              # ML classification
│       └── classify_with_llm.py
│
├── core/                                 # ⚠️ Needs review
│   ├── universal_processor.py           # 719 lines
│   ├── processor_registry.py            # Core registry
│   ├── protocol.py
│   └── input_detector.py
│
├── multimedia/                           # ✅ Large but organized
│   ├── omni_converter_mk2/              # 200+ files
│   └── ... (media processing tools)
│
├── [ROOT FILES - 32 TOTAL]              # ⚠️ NEEDS CLEANUP
│   ├── [DEPRECATION SHIMS - ~15 files] # ✅ Good
│   │   ├── batch_processor.py
│   │   ├── pdf_processor.py
│   │   ├── graphrag_processor.py
│   │   └── ... (properly delegating)
│   │
│   ├── [LARGE ACTIVE FILES - 6]         # ⚠️ REFACTOR NEEDED
│   │   ├── llm_optimizer.py             # 3,377 lines ❗
│   │   ├── query_engine.py              # 2,996 lines ❗
│   │   ├── advanced_web_archiving.py    # 971 lines
│   │   ├── universal_processor.py       # 719 lines
│   │   ├── advanced_media_processing.py # 639 lines
│   │   └── protocol.py                  # 481 lines
│   │
│   ├── [REGISTRY DUPLICATION]           # ❌ MUST FIX
│   │   ├── registry.py                  # 383 lines
│   │   └── core/processor_registry.py   # Duplicate functionality
│   │
│   └── [MISC ACTIVE FILES - 11]         # 📋 REVIEW
│       ├── input_detection.py           # 486 lines
│       ├── relationship_analyzer.py     # 260 lines
│       ├── relationship_analysis_api.py # 139 lines
│       ├── corpus_query_api.py          # 129 lines
│       ├── graphrag_integrator.py       # 94 lines
│       └── ... (6 more files)
```

### 1.2 File Size Analysis

| File | Size (lines) | Status | Recommended Action |
|------|--------------|--------|-------------------|
| llm_optimizer.py | 3,377 | ❌ Too large | Split into modules |
| query_engine.py | 2,996 | ❌ Too large | Refactor & modularize |
| advanced_web_archiving.py | 971 | ⚠️ Large | Move to specialized/ or split |
| universal_processor.py | 719 | ⚠️ Large | Keep in core/ but review |
| advanced_media_processing.py | 639 | ⚠️ Large | Move to multimedia/ |
| input_detection.py | 486 | ✅ OK | Move to core/ |
| protocol.py | 481 | ✅ OK | Keep in core/ |
| registry.py | 383 | ❌ Duplicate | Remove, use core/processor_registry.py |

### 1.3 Testing Coverage Analysis

**Current Test Files:**
- `tests/test_processors_refactoring.py` - Basic refactoring validation
- `tests/integration/test_processor_integration.py` - Integration tests
- `tests/integration/test_processor_refactoring.py` - Refactoring validation
- `tests/unit/test_batch_processor.py` - Batch processor tests
- `tests/unit/test_pdf_processor_unit.py` - PDF processor tests
- Various gherkin feature files

**Coverage Gaps:**
- ❌ No tests for infrastructure/ modules (caching, monitoring, profiling)
- ❌ No tests for domains/ processors (patent, geospatial, ml)
- ❌ Limited tests for specialized/graphrag/
- ❌ No tests for specialized/multimodal/
- ❌ No deprecation warning tests
- ❌ No migration path validation tests

**Estimated Current Coverage:** ~40-50%
**Target Coverage:** >90%

### 1.4 Documentation Analysis

**Current Documentation Files (35 total):**
- Multiple overlapping guides (COMPREHENSIVE_PLAN.md, REFACTORING_PLAN.md, etc.)
- Week-by-week progress reports (WEEK1_SUMMARY.md, WEEK2_PHASE2_SESSION_SUMMARY.md)
- Multiple implementation checklists
- Various architecture documents
- Migration guides

**Issues:**
- 📚 Information is scattered across 35+ files
- 🔄 Redundancy between similar documents
- 📅 Time-stamped documents that may be outdated
- 🎯 No clear "single source of truth"

---

## 2. Architecture Goals

### 2.1 Design Principles

1. **Separation of Concerns**
   - Specialized processors for domain-specific tasks
   - Infrastructure for cross-cutting concerns
   - Clear boundaries between modules

2. **Single Responsibility**
   - Each file has one clear purpose
   - Large files split into focused modules
   - No "god objects" or monolithic classes

3. **Open/Closed Principle**
   - Easy to add new processors
   - Registry-based discovery
   - Plugin architecture for extensions

4. **Dependency Inversion**
   - Depend on abstractions (ProcessorProtocol)
   - Not on concrete implementations
   - Clear interfaces

5. **DRY (Don't Repeat Yourself)**
   - No duplicate implementations
   - Shared utilities in infrastructure/
   - Reusable base classes

### 2.2 Target Architecture

```
processors/
├── specialized/        # Domain-specific processors (high-level)
│   ├── graphrag/      # Knowledge graph processing
│   ├── pdf/           # PDF document processing
│   ├── multimodal/    # Cross-modal content
│   ├── batch/         # Batch processing
│   ├── web_archive/   # Web archiving (NEW)
│   └── media/         # Advanced media (NEW)
│
├── infrastructure/     # Cross-cutting infrastructure
│   ├── caching/       # Caching subsystem (NEW - split from single file)
│   ├── monitoring/    # Metrics & monitoring (NEW - split from single file)
│   ├── optimization/  # Performance optimization (NEW)
│   ├── error_handling.py
│   ├── profiling.py
│   ├── debug_tools.py
│   └── cli.py
│
├── domains/           # Domain-specific business logic
│   ├── patent/       # Patent data processing
│   ├── geospatial/   # Geographic analysis
│   ├── ml/           # ML & classification
│   └── legal/        # Legal document processing (legal_scrapers/)
│
├── core/              # Core framework & protocols
│   ├── protocol.py   # ProcessorProtocol definition
│   ├── registry.py   # Unified processor registry
│   ├── routing.py    # Input-based routing
│   ├── universal.py  # Universal processor facade
│   └── input_detection.py
│
├── engines/           # Processing engines (NEW)
│   ├── query/        # Query engine (split from query_engine.py)
│   ├── llm/          # LLM optimization (split from llm_optimizer.py)
│   └── relationship/ # Relationship analysis
│
├── adapters/          # Adapter pattern implementations
├── auth/              # Authentication (UCAN)
├── file_converter/    # File format conversion
├── ipfs/              # IPFS utilities
├── multimedia/        # Media processing (large subsystem)
├── serialization/     # Serialization utilities
├── storage/           # Storage backends
└── wikipedia_x/       # Wikipedia integration
```

### 2.3 Module Responsibilities

| Module | Responsibility | Complexity | Size Target |
|--------|---------------|------------|-------------|
| specialized/ | High-level domain processors | Medium | <500 lines/file |
| infrastructure/ | Reusable cross-cutting tools | Low | <300 lines/file |
| domains/ | Business-specific logic | Medium | <500 lines/file |
| core/ | Framework & protocols | Low-Medium | <400 lines/file |
| engines/ | Complex processing engines | High | <800 lines/file |
| adapters/ | Interface adapters | Low | <200 lines/file |

---

## 3. Phase-by-Phase Implementation Plan

### Phase 1: Critical Consolidation (8 hours)

**Goal:** Eliminate duplication and clarify ownership

#### Task 1.1: Registry Consolidation (3 hours)
**Problem:** Two registry implementations causing confusion

**Actions:**
1. Compare `registry.py` vs `core/processor_registry.py`
2. Identify unique functionality in each
3. Merge into single `core/registry.py`
4. Create deprecation shim at `registry.py`
5. Update all imports throughout codebase
6. Test registry functionality

**Files Changed:**
- `/processors/core/registry.py` (consolidated)
- `/processors/registry.py` (deprecation shim)
- Update imports in ~10-15 files

**Success Criteria:**
- Single source of truth for registry
- All existing code still works
- Clear deprecation path

#### Task 1.2: Advanced Files Organization (3 hours)
**Problem:** "Advanced" processors not in proper locations

**Actions:**
1. Move `advanced_media_processing.py` → `specialized/media/`
2. Move `advanced_web_archiving.py` → `specialized/web_archive/`
3. Consolidate `advanced_graphrag_website_processor.py` into `specialized/graphrag/`
4. Create deprecation shims
5. Update imports

**Files Changed:**
- New: `/processors/specialized/media/advanced_processing.py`
- New: `/processors/specialized/web_archive/advanced_archiving.py`
- Update: `/processors/specialized/graphrag/website_system.py`
- Create: 3 deprecation shims

#### Task 1.3: Input Detection to Core (2 hours)
**Problem:** `input_detection.py` is at root but belongs in core/

**Actions:**
1. Move `input_detection.py` → `core/input_detection.py`
2. Create deprecation shim at root
3. Update imports

**Deliverables:**
- Clearer code organization
- 3 fewer root-level files
- Updated migration guide

---

### Phase 2: Large File Refactoring (16 hours)

**Goal:** Break down monolithic files into maintainable modules

#### Task 2.1: LLM Optimizer Refactoring (6 hours)
**Problem:** 3,377-line file is too large and complex

**Current Structure:**
```
llm_optimizer.py (3,377 lines)
├── Chunking strategies
├── Token optimization
├── Embedding generation
├── Context management
├── Summarization
└── Multi-modal handling
```

**Target Structure:**
```
engines/llm/
├── __init__.py
├── chunker.py          # Text chunking (400 lines)
├── tokenizer.py        # Token optimization (300 lines)
├── embeddings.py       # Embedding generation (500 lines)
├── context.py          # Context management (400 lines)
├── summarizer.py       # Summarization (500 lines)
├── multimodal.py       # Multi-modal content (600 lines)
└── optimizer.py        # Main orchestration (400 lines)
```

**Actions:**
1. Create `engines/llm/` directory
2. Extract chunking logic → `chunker.py`
3. Extract tokenization → `tokenizer.py`
4. Extract embedding logic → `embeddings.py`
5. Extract context management → `context.py`
6. Extract summarization → `summarizer.py`
7. Extract multi-modal handling → `multimodal.py`
8. Create facade class in `optimizer.py`
9. Create deprecation shim at root `llm_optimizer.py`
10. Update imports across codebase
11. Add tests for each module

**Success Criteria:**
- Each module <600 lines
- Clear separation of concerns
- All existing functionality preserved
- Backward compatibility maintained

#### Task 2.2: Query Engine Refactoring (6 hours)
**Problem:** 2,996-line file with mixed responsibilities

**Current Structure:**
```
query_engine.py (2,996 lines)
├── Query parsing
├── Query optimization
├── Execution engine
├── Result formatting
├── Caching
└── Error handling
```

**Target Structure:**
```
engines/query/
├── __init__.py
├── parser.py           # Query parsing (400 lines)
├── optimizer.py        # Query optimization (500 lines)
├── executor.py         # Execution engine (600 lines)
├── formatter.py        # Result formatting (400 lines)
├── cache.py            # Query caching (300 lines)
└── engine.py           # Main orchestration (500 lines)
```

**Actions:**
1. Create `engines/query/` directory
2. Extract parsing → `parser.py`
3. Extract optimization → `optimizer.py`
4. Extract execution → `executor.py`
5. Extract formatting → `formatter.py`
6. Extract caching → `cache.py`
7. Create main engine in `engine.py`
8. Create deprecation shim
9. Update imports
10. Add comprehensive tests

#### Task 2.3: Relationship Analyzer Consolidation (4 hours)
**Problem:** Multiple files for relationship analysis

**Current Files:**
- `relationship_analyzer.py` (260 lines)
- `relationship_analysis_api.py` (139 lines)
- `corpus_query_api.py` (129 lines)

**Target Structure:**
```
engines/relationship/
├── __init__.py
├── analyzer.py         # Core analysis (300 lines)
├── api.py             # API interface (200 lines)
└── corpus.py          # Corpus queries (200 lines)
```

**Actions:**
1. Create `engines/relationship/` directory
2. Consolidate analyzer logic
3. Merge API endpoints
4. Integrate corpus queries
5. Create deprecation shims
6. Add tests

---

### Phase 3: Integration & Testing (20 hours)

**Goal:** Ensure all modules work together seamlessly

#### Task 3.1: Integration Tests (8 hours)
**Scope:** End-to-end processor workflows

**Test Suites:**
1. **Specialized Processors Integration**
   - Test GraphRAG → LLM → Query pipeline
   - Test PDF → OCR → LLM → Storage
   - Test Multimodal → Media → Transcription
   - Test Batch → Parallel → Monitoring

2. **Cross-Module Integration**
   - Registry discovery → Routing → Execution
   - Caching → Monitoring → Profiling
   - Error handling across boundaries
   - Auth → Processing → Storage

3. **Backward Compatibility**
   - Test all old imports still work
   - Verify deprecation warnings fire
   - Test migration paths
   - Validate shim behavior

**Files Created:**
- `tests/integration/test_specialized_processors.py`
- `tests/integration/test_cross_module.py`
- `tests/integration/test_backward_compat.py`
- `tests/integration/test_migration_paths.py`

#### Task 3.2: Unit Tests (8 hours)
**Scope:** Individual module testing

**Test Coverage:**
1. **Infrastructure Tests**
   - `test_caching.py` - Cache operations
   - `test_monitoring.py` - Metrics collection
   - `test_profiling.py` - Performance profiling
   - `test_error_handling.py` - Error scenarios
   - `test_debug_tools.py` - Debug utilities

2. **Domain Tests**
   - `test_patent_processor.py` - Patent scraping
   - `test_geospatial.py` - Geographic analysis
   - `test_ml_classification.py` - ML operations

3. **Engine Tests**
   - `test_llm_optimizer.py` - LLM optimization
   - `test_query_engine.py` - Query execution
   - `test_relationship_analyzer.py` - Relationship analysis

4. **Core Tests**
   - `test_registry.py` - Registry operations
   - `test_protocol.py` - Protocol compliance
   - `test_routing.py` - Input routing

**Target:** 90%+ code coverage

#### Task 3.3: Deprecation Tests (4 hours)
**Scope:** Validate all deprecation paths

**Test Cases:**
1. Import from old location fires warning
2. Warning message is clear and helpful
3. Functionality identical to new location
4. Migration path documented
5. Removal date specified

---

### Phase 4: Performance Optimization (16 hours)

**Goal:** Improve processing speed and resource efficiency

#### Task 4.1: Profiling & Bottleneck Analysis (4 hours)
**Actions:**
1. Profile key workflows
2. Identify bottlenecks
3. Measure memory usage
4. Analyze I/O patterns
5. Document findings

#### Task 4.2: Caching Improvements (6 hours)
**Current:** Single-file caching utility
**Target:** Comprehensive caching subsystem

**Improvements:**
1. Multi-level caching (memory → disk → IPFS)
2. TTL and eviction policies
3. Cache warming strategies
4. Distributed caching support
5. Monitoring and metrics

**New Structure:**
```
infrastructure/caching/
├── __init__.py
├── memory_cache.py     # In-memory caching
├── disk_cache.py       # Persistent disk cache
├── ipfs_cache.py       # IPFS-backed cache
├── policy.py           # Eviction policies
└── distributed.py      # Distributed caching
```

#### Task 4.3: Parallel Processing (6 hours)
**Improvements:**
1. Batch processor parallelization
2. Pipeline processing optimization
3. Async/await patterns
4. Resource pooling
5. Load balancing

---

### Phase 5: Documentation Consolidation (12 hours)

**Goal:** Create clear, authoritative documentation

#### Task 5.1: Documentation Audit (3 hours)
**Actions:**
1. Review all 35 processor docs
2. Categorize by type (guide, reference, progress)
3. Identify redundancy
4. Mark for consolidation or archival

#### Task 5.2: Create Master Guide (5 hours)
**Content:**
1. **Introduction**
   - Project overview
   - Architecture philosophy
   - Quick start

2. **Architecture Guide**
   - Directory structure
   - Module responsibilities
   - Design patterns

3. **Developer Guide**
   - Adding new processors
   - Testing strategies
   - Best practices

4. **API Reference**
   - Core classes and protocols
   - Specialized processors
   - Infrastructure utilities

5. **Migration Guide**
   - Old → New mappings
   - Deprecation timeline
   - Breaking changes

6. **Performance Guide**
   - Optimization techniques
   - Caching strategies
   - Monitoring

**Output:** `PROCESSORS_MASTER_GUIDE.md` (comprehensive, ~5000 lines)

#### Task 5.3: Archive Old Documentation (2 hours)
**Actions:**
1. Move time-stamped docs to `docs/archived/processors/`
2. Keep only current guides
3. Update README references
4. Add deprecation notices

#### Task 5.4: Generate API Docs (2 hours)
**Actions:**
1. Ensure all modules have docstrings
2. Generate Sphinx/MkDocs documentation
3. Create interactive examples
4. Publish to documentation site

---

### Phase 6: Quality & Security (16 hours)

**Goal:** Production-ready code quality

#### Task 6.1: Code Review (4 hours)
**Review Areas:**
1. Adherence to Python best practices
2. Type hints completeness
3. Error handling robustness
4. Resource cleanup (context managers)
5. Security considerations

#### Task 6.2: Type Checking (4 hours)
**Actions:**
1. Add type hints to all public APIs
2. Run mypy strict mode
3. Fix type errors
4. Add py.typed marker
5. Validate with pyright

#### Task 6.3: Linting & Formatting (3 hours)
**Actions:**
1. Run flake8 on all files
2. Fix linting issues
3. Apply black formatting
4. Run isort for imports
5. Add pre-commit hooks

#### Task 6.4: Security Audit (5 hours)
**Review:**
1. Input validation
2. Path traversal prevention
3. Code injection risks
4. Dependency vulnerabilities
5. IPFS security considerations

---

### Phase 7: Final Polish (8 hours)

**Goal:** Production release preparation

#### Task 7.1: Changelog & Release Notes (2 hours)
**Content:**
1. What changed
2. Migration guide summary
3. Breaking changes (if any)
4. New features
5. Performance improvements

#### Task 7.2: Final Testing (4 hours)
**Activities:**
1. Full test suite run
2. Integration smoke tests
3. Performance regression tests
4. Documentation validation
5. Example code verification

#### Task 7.3: Cleanup & Polish (2 hours)
**Actions:**
1. Remove debug code
2. Clean up comments
3. Remove unused imports
4. Verify __all__ exports
5. Final code review

---

## 4. Testing Strategy

### 4.1 Testing Pyramid

```
           /\
          /  \         E2E Tests (10%)
         /____\        - Full workflow validation
        /      \       - Real data processing
       / Integr.\      
      /  ation   \     Integration Tests (30%)
     /____________\    - Multi-module interactions
    /              \   - Cross-boundary testing
   /   Unit Tests   \  
  /__________________\ Unit Tests (60%)
                      - Individual functions
                      - Module isolation
```

### 4.2 Test Categories

#### Unit Tests (60% of tests)
- **Focus:** Individual functions and classes
- **Isolation:** Mocked dependencies
- **Coverage Target:** >95%
- **Speed:** <5 seconds total

#### Integration Tests (30% of tests)
- **Focus:** Module interactions
- **Isolation:** Real dependencies where feasible
- **Coverage Target:** >80%
- **Speed:** <30 seconds total

#### E2E Tests (10% of tests)
- **Focus:** Complete workflows
- **Isolation:** Production-like environment
- **Coverage Target:** Critical paths only
- **Speed:** <2 minutes total

### 4.3 Test Infrastructure

#### Fixtures & Factories
```python
# tests/conftest.py
@pytest.fixture
def sample_pdf():
    """Provides sample PDF for testing."""
    return Path(__file__).parent / "data" / "sample.pdf"

@pytest.fixture
def mock_ipfs_client():
    """Mocked IPFS client for testing."""
    return MockIPFSClient()

@pytest.fixture
def processor_registry():
    """Clean processor registry for each test."""
    return ProcessorRegistry()
```

#### Test Data Management
- Sample files in `tests/data/`
- Synthetic data generators
- Mock responses for external APIs
- Cached test results for expensive operations

### 4.4 Coverage Requirements

| Module | Minimum Coverage | Target Coverage |
|--------|-----------------|-----------------|
| Core (protocol, registry) | 95% | 100% |
| Specialized processors | 85% | 95% |
| Infrastructure utilities | 90% | 95% |
| Domain processors | 80% | 90% |
| Engines | 85% | 95% |
| Adapters | 90% | 95% |

### 4.5 CI/CD Integration

**GitHub Actions Workflow:**
```yaml
test:
  - name: Unit Tests
    run: pytest tests/unit/ -v --cov=processors
  
  - name: Integration Tests
    run: pytest tests/integration/ -v
  
  - name: E2E Tests
    run: pytest tests/e2e/ -v --slow
  
  - name: Coverage Report
    run: coverage report --fail-under=90
```

---

## 5. Migration & Compatibility

### 5.1 Deprecation Policy

**Timeline:**
- **v1.9.0 (Current):** Introduce new structure, deprecation warnings
- **v1.10.0 → v1.15.0 (6 months):** Grace period, both work
- **v2.0.0 (August 2026):** Remove deprecated imports

**Deprecation Warning Format:**
```python
DeprecationWarning: 
    processors.{old_module} is deprecated. 
    Use processors.{new_location}.{Class} instead. 
    This import will be removed in v2.0.0 (August 2026).
    See docs/PROCESSORS_MASTER_GUIDE.md for migration help.
```

### 5.2 Migration Paths

#### GraphRAG Processors
```python
# OLD (deprecated, works until v2.0.0)
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
from ipfs_datasets_py.processors.graphrag_integrator import GraphRAGIntegrator
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor

# NEW (recommended)
from ipfs_datasets_py.processors.specialized.graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGIntegration,
    WebsiteGraphRAGSystem
)
```

#### PDF Processors
```python
# OLD
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
from ipfs_datasets_py.processors.pdf_processing import PDFProcessing

# NEW
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
```

#### LLM Optimizer
```python
# OLD
from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer

# NEW
from ipfs_datasets_py.processors.engines.llm import LLMOptimizer
# Or specific components:
from ipfs_datasets_py.processors.engines.llm import (
    Chunker, Tokenizer, EmbeddingGenerator, ContextManager
)
```

#### Registry
```python
# OLD
from ipfs_datasets_py.processors.registry import ProcessorRegistry

# NEW
from ipfs_datasets_py.processors.core.registry import ProcessorRegistry
```

### 5.3 Automated Migration Tool

**Script:** `scripts/migrate_processors_imports.py`

```python
#!/usr/bin/env python3
"""
Automated migration script for processors imports.

Usage:
    python scripts/migrate_processors_imports.py --path /path/to/code
    python scripts/migrate_processors_imports.py --file my_module.py
"""

import re
from pathlib import Path

# Migration mappings
MIGRATIONS = {
    'from ipfs_datasets_py.processors.graphrag_processor': 
        'from ipfs_datasets_py.processors.specialized.graphrag',
    'from ipfs_datasets_py.processors.pdf_processor':
        'from ipfs_datasets_py.processors.specialized.pdf',
    'from ipfs_datasets_py.processors.llm_optimizer':
        'from ipfs_datasets_py.processors.engines.llm',
    # ... more mappings
}

def migrate_file(filepath: Path) -> None:
    """Migrate imports in a single file."""
    content = filepath.read_text()
    modified = False
    
    for old, new in MIGRATIONS.items():
        if old in content:
            content = content.replace(old, new)
            modified = True
    
    if modified:
        filepath.write_text(content)
        print(f"✓ Migrated {filepath}")

# ... rest of implementation
```

---

## 6. Performance Optimization

### 6.1 Current Performance Baseline

**Benchmarks (as of Feb 2026):**
- PDF processing: ~2.5 seconds per page
- GraphRAG extraction: ~15 seconds per URL
- Batch processing: ~100 files/minute
- LLM optimization: ~1 second per 1000 tokens
- Query execution: ~200ms average

### 6.2 Optimization Targets

| Operation | Current | Target | Improvement |
|-----------|---------|--------|-------------|
| PDF processing | 2.5s/page | 1.5s/page | 40% faster |
| GraphRAG extraction | 15s/URL | 8s/URL | 47% faster |
| Batch processing | 100/min | 200/min | 2x throughput |
| LLM optimization | 1s/1k tokens | 0.5s/1k tokens | 2x faster |
| Query execution | 200ms | 100ms | 2x faster |

### 6.3 Optimization Strategies

#### 1. Caching
- Implement multi-tier caching (memory → disk → IPFS)
- Cache expensive operations (embeddings, OCR, LLM calls)
- Smart cache invalidation
- Pre-warming for common requests

#### 2. Parallelization
- Use `anyio` for async operations
- Parallel batch processing
- Concurrent I/O operations
- GPU acceleration where applicable

#### 3. Algorithm Optimization
- Better chunking strategies
- Efficient text processing
- Optimized vector operations
- Lazy evaluation patterns

#### 4. Resource Management
- Connection pooling
- Object reuse
- Memory profiling and optimization
- Efficient data structures

### 6.4 Performance Monitoring

**Metrics to Track:**
- Processing time per operation
- Memory usage patterns
- Cache hit rates
- Queue depths
- Error rates

**Tools:**
- `cProfile` for CPU profiling
- `memory_profiler` for memory analysis
- `py-spy` for production profiling
- Custom metrics in `infrastructure/monitoring/`

---

## 7. Documentation Strategy

### 7.1 Documentation Hierarchy

```
docs/processors/
├── README.md                    # Overview & getting started
├── MASTER_GUIDE.md              # Comprehensive guide (NEW)
├── API_REFERENCE.md             # Auto-generated API docs
├── MIGRATION_GUIDE.md           # Migration instructions
├── ARCHITECTURE.md              # System architecture
├── PERFORMANCE.md               # Performance optimization
├── TESTING.md                   # Testing guidelines
├── CONTRIBUTING.md              # Contribution guide
│
├── guides/                      # Task-specific guides
│   ├── adding_processor.md
│   ├── custom_adapters.md
│   ├── caching_strategies.md
│   └── troubleshooting.md
│
├── examples/                    # Code examples
│   ├── basic_processing.py
│   ├── custom_processor.py
│   ├── batch_pipeline.py
│   └── advanced_workflows.py
│
└── archived/                    # Historical documentation
    └── processors/
        ├── PHASES_1_7_COMPLETE.md
        ├── WEEK1_SUMMARY.md
        └── ... (time-stamped docs)
```

### 7.2 Documentation Consolidation Plan

**Keep (8 files):**
- `MASTER_GUIDE.md` (NEW - consolidates everything)
- `MIGRATION_GUIDE.md` (current)
- `ARCHITECTURE.md` (diagrams and structure)
- `API_REFERENCE.md` (auto-generated)
- `PERFORMANCE.md` (optimization guide)
- `TESTING.md` (testing strategy)
- `CONTRIBUTING.md` (development guide)
- `README.md` (quick start)

**Archive (27 files):**
- All time-stamped documents (WEEK1_, PHASE_X_, etc.)
- Multiple plan variations (PLAN_V1, PLAN_V2)
- Implementation checklists
- Session summaries
- Progress reports

**Rationale:**
- Single source of truth (MASTER_GUIDE.md)
- Clear, focused guides for specific tasks
- Historical documents preserved but not cluttering main docs
- Auto-generated API reference always current

### 7.3 Documentation Quality Standards

**Requirements:**
1. ✅ Every public class has docstring with examples
2. ✅ Every public function has clear parameter descriptions
3. ✅ All modules have purpose statement
4. ✅ Complex algorithms include inline comments
5. ✅ All examples are tested and working
6. ✅ Links are validated and current
7. ✅ Code snippets are syntax-highlighted
8. ✅ Diagrams for complex architectures

---

## 8. Risk Management

### 8.1 Identified Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Breaking existing code | Medium | High | Comprehensive testing, deprecation warnings |
| Performance regression | Low | High | Benchmarking, profiling before/after |
| Incomplete migration | Medium | Medium | Clear documentation, migration tools |
| Test coverage gaps | Medium | Medium | Coverage requirements, CI enforcement |
| Documentation drift | Low | Medium | Auto-generated docs, review process |
| Timeline overrun | Medium | Low | Phased approach, prioritization |

### 8.2 Mitigation Strategies

#### Risk: Breaking Existing Code
**Mitigation:**
1. Maintain all deprecation shims
2. Extensive backward compatibility tests
3. Beta period before v2.0.0
4. Clear communication to users

#### Risk: Performance Regression
**Mitigation:**
1. Baseline performance metrics
2. Benchmark suite in CI
3. Profile before and after changes
4. Performance alerts

#### Risk: Incomplete Migration
**Mitigation:**
1. Automated migration script
2. Clear documentation
3. Gradual deprecation timeline
4. Community support channels

### 8.3 Rollback Plan

**If major issues discovered:**
1. Keep old branch available
2. Document rollback procedure
3. Quick-fix strategy for critical bugs
4. Communication plan

---

## 9. Success Metrics

### 9.1 Quantitative Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Root-level files | 32 | <15 | File count |
| Largest file size | 3,377 lines | <800 lines | Line count |
| Test coverage | ~40% | >90% | pytest-cov |
| Documentation files | 35 | <10 | File count |
| CI test duration | N/A | <5 min | GitHub Actions |
| Code duplication | Unknown | <3% | SonarQube |
| Technical debt | Unknown | A-rating | SonarQube |

### 9.2 Qualitative Metrics

**Developer Experience:**
- ✅ Clear where to add new processors
- ✅ Easy to find relevant code
- ✅ Obvious how to test changes
- ✅ Good error messages
- ✅ Fast feedback loop

**Code Quality:**
- ✅ Single responsibility per module
- ✅ Clear interfaces and protocols
- ✅ Minimal coupling
- ✅ High cohesion
- ✅ Self-documenting code

**Maintainability:**
- ✅ New contributors can onboard quickly
- ✅ Changes are localized
- ✅ Refactoring is safe
- ✅ Dependencies are clear
- ✅ Technical debt is managed

### 9.3 Acceptance Criteria

**Phase 1 Complete When:**
- [ ] Registry consolidated to single implementation
- [ ] All "advanced" files moved to proper locations
- [ ] No duplicate functionality in root
- [ ] All tests passing

**Phase 2 Complete When:**
- [ ] No file exceeds 800 lines
- [ ] llm_optimizer split into modules
- [ ] query_engine refactored
- [ ] All functionality preserved

**Phase 3 Complete When:**
- [ ] >90% test coverage achieved
- [ ] All integration tests passing
- [ ] Deprecation warnings tested
- [ ] Migration paths validated

**Phase 4 Complete When:**
- [ ] Performance targets met or exceeded
- [ ] Caching subsystem implemented
- [ ] Profiling integrated
- [ ] Monitoring operational

**Phase 5 Complete When:**
- [ ] Single master guide published
- [ ] Old docs archived
- [ ] API reference generated
- [ ] Examples tested

**Phase 6 Complete When:**
- [ ] Type checking passes (mypy)
- [ ] Linting clean (flake8)
- [ ] Security audit complete
- [ ] Code review approved

**Phase 7 Complete When:**
- [ ] All tests passing
- [ ] Release notes published
- [ ] Changelog updated
- [ ] Ready for production

---

## 10. Timeline & Resources

### 10.1 Estimated Timeline

**Total Effort:** 92 hours

**Schedule (4 weeks):**
- **Week 1 (20h):** Phase 1 (8h) + Phase 2 (12h)
- **Week 2 (24h):** Phase 2 (4h) + Phase 3 (20h)
- **Week 3 (24h):** Phase 4 (16h) + Phase 5 (8h)
- **Week 4 (24h):** Phase 5 (4h) + Phase 6 (16h) + Phase 7 (4h)

**Contingency:** +10% (9 hours) for unexpected issues

### 10.2 Milestones

| Milestone | Date | Deliverables |
|-----------|------|--------------|
| M1: Critical Consolidation | Week 1 | Registry unified, files organized |
| M2: Large Files Refactored | Week 2 | llm_optimizer & query_engine split |
| M3: Tests Complete | Week 2 | >90% coverage, all tests passing |
| M4: Performance Optimized | Week 3 | Targets met, monitoring active |
| M5: Documentation Ready | Week 3 | Master guide, API docs |
| M6: Production Ready | Week 4 | All quality checks pass |
| M7: Release | Week 4 | v1.10.0 published |

### 10.3 Resource Requirements

**Team:**
- 1 Senior Engineer (full-time, 4 weeks)
- 1 Code Reviewer (10 hours total)
- 1 Technical Writer (5 hours for docs review)

**Infrastructure:**
- CI/CD pipeline access
- Test environment
- Documentation hosting
- Code quality tools (SonarQube, etc.)

### 10.4 Communication Plan

**Weekly Updates:**
- Progress report every Friday
- Blockers identified and escalated
- Metrics dashboard updated

**Stakeholder Communication:**
- Kickoff meeting (Week 0)
- Mid-point review (Week 2)
- Final review (Week 4)
- Release announcement (Week 4)

---

## 11. Next Steps

### 11.1 Immediate Actions (This Week)

1. **Review and approve this plan**
2. **Set up project tracking** (GitHub Issues, Project board)
3. **Create feature branch** for implementation
4. **Begin Phase 1, Task 1.1** (Registry consolidation)

### 11.2 First Session Goals

**Duration:** 4-6 hours

**Tasks:**
1. Registry consolidation (Task 1.1)
2. Move advanced files (Task 1.2)
3. Move input_detection to core (Task 1.3)
4. Update imports in affected files
5. Run tests to validate
6. Update documentation

**Deliverables:**
- 3 fewer root-level files
- Single registry implementation
- Clearer code organization
- All tests passing

### 11.3 Success Indicators

**After Week 1:**
- Phase 1 complete
- 50% of Phase 2 complete
- No test regressions
- Clear progress visible

**After Week 2:**
- Phases 1 & 2 complete
- Phase 3 80% complete
- Test coverage >80%
- Performance baseline established

**After Week 3:**
- Phases 1-4 complete
- Phase 5 in progress
- Performance targets met
- Documentation drafted

**After Week 4:**
- All phases complete
- Release candidate ready
- Documentation published
- Ready for v1.10.0 release

---

## Appendices

### Appendix A: File Movement Reference

| Old Location | New Location | Status |
|--------------|--------------|--------|
| `/registry.py` | `/core/registry.py` | Consolidate |
| `/advanced_media_processing.py` | `/specialized/media/` | Move |
| `/advanced_web_archiving.py` | `/specialized/web_archive/` | Move |
| `/input_detection.py` | `/core/input_detection.py` | Move |
| `/llm_optimizer.py` | `/engines/llm/` | Split |
| `/query_engine.py` | `/engines/query/` | Split |
| `/relationship_*.py` (3 files) | `/engines/relationship/` | Consolidate |

### Appendix B: Import Migration Map

```python
# Complete migration reference
OLD_TO_NEW = {
    'processors.registry': 'processors.core.registry',
    'processors.graphrag_processor': 'processors.specialized.graphrag',
    'processors.pdf_processor': 'processors.specialized.pdf',
    'processors.batch_processor': 'processors.specialized.batch',
    'processors.multimodal_processor': 'processors.specialized.multimodal',
    'processors.llm_optimizer': 'processors.engines.llm',
    'processors.query_engine': 'processors.engines.query',
    'processors.relationship_analyzer': 'processors.engines.relationship',
    'processors.advanced_media_processing': 'processors.specialized.media',
    'processors.advanced_web_archiving': 'processors.specialized.web_archive',
    'processors.caching': 'processors.infrastructure.caching',
    'processors.monitoring': 'processors.infrastructure.monitoring',
    'processors.patent_scraper': 'processors.domains.patent',
    'processors.geospatial_analysis': 'processors.domains.geospatial',
    'processors.classify_with_llm': 'processors.domains.ml',
}
```

### Appendix C: Testing Checklist

- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] Coverage >90% on all modules
- [ ] Deprecation warnings tested
- [ ] Migration paths validated
- [ ] Performance benchmarks pass
- [ ] No memory leaks detected
- [ ] Type checking passes (mypy)
- [ ] Linting passes (flake8)
- [ ] Security scan clean

### Appendix D: Release Checklist

- [ ] All phases complete
- [ ] All tests passing
- [ ] Documentation published
- [ ] Changelog updated
- [ ] Release notes written
- [ ] Migration guide updated
- [ ] Version bumped
- [ ] Git tags created
- [ ] PyPI package published
- [ ] Announcement sent

---

**Document Status:** DRAFT → REVIEW → APPROVED → IN PROGRESS

**Last Updated:** February 16, 2026  
**Next Review:** Weekly during implementation  
**Owner:** Engineering Team  
**Approver:** TBD  

---

