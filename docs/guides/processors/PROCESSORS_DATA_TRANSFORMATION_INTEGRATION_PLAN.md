# Comprehensive Processors & Data Transformation Integration Plan

**Created:** 2026-02-15  
**Updated:** 2026-02-15  
**Status:** Phase 3 Complete - Implementing Phase 4  
**Timeline:** 3-4 weeks (ahead of schedule)  
**Priority:** HIGH - Architectural consolidation

---

## Executive Summary

This document provides a comprehensive refactoring, improvement, and integration plan for:
1. The `ipfs_datasets_py/processors/*` directory
2. Merging/deprecating the `ipfs_datasets_py/data_transformation/` directory

**Goal:** Create a unified, well-organized processor architecture that consolidates all data processing, transformation, and multimedia handling under a single coherent system, while maintaining backward compatibility.

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Problems & Challenges](#problems--challenges)
3. [Integration Strategy](#integration-strategy)
4. [Architectural Vision](#architectural-vision)
5. [Migration Plan](#migration-plan)
6. [Implementation Phases](#implementation-phases)
7. [Backward Compatibility](#backward-compatibility)
8. [Testing Strategy](#testing-strategy)
9. [Success Metrics](#success-metrics)

---

## Current State Analysis

### Processors Directory (`ipfs_datasets_py/processors/`)

**Structure:**
```
processors/
├── core/                      # NEW: Protocol-based architecture (Week 1)
│   ├── protocol.py           # ProcessorProtocol interface
│   ├── input_detector.py     # Auto-classify inputs (7 types)
│   ├── processor_registry.py # Priority-based routing
│   └── universal_processor.py # Single entry point
├── adapters/                  # NEW: 8 operational adapters (PR #948)
│   ├── ipfs_adapter.py       # Priority 20
│   ├── batch_adapter.py      # Priority 15
│   ├── specialized_scraper_adapter.py # Priority 12
│   ├── pdf_adapter.py        # Priority 10
│   ├── graphrag_adapter.py   # Priority 10
│   ├── multimedia_adapter.py # Priority 10
│   ├── web_archive_adapter.py # Priority 8
│   └── file_converter_adapter.py # Priority 5
├── file_converter/            # Comprehensive file conversion (27 files)
├── graphrag/                  # GraphRAG implementations (6 files, 270KB)
├── legal_scrapers/            # Legal document processing
├── multimedia/                # NEW: Multimedia processing (MOVED from data_transformation)
├── error_handling.py          # Circuit breaker, retry logic (PR #948)
├── caching.py                # Smart caching (TTL/LRU/LFU/FIFO) (PR #948)
├── monitoring.py             # Health monitoring (PR #948)
├── profiling.py              # Performance profiling (Phase 7)
├── debug_tools.py            # Debugging utilities (Phase 7)
├── cli.py                    # CLI management (Phase 7)
└── [22+ specialized processors]
```

**Status:**
- ✅ Phase 1: Multimedia Migration - COMPLETE (5h)
- ✅ Phase 2: Serialization Organization - COMPLETE (1h)
- ✅ Phase 3: GraphRAG Analysis & Planning - COMPLETE (1.5h)
- 🔄 Phase 4: GraphRAG Implementation - IN PROGRESS
- ⏳ Phase 5: Documentation & Deprecation - PENDING
- ⏳ Phase 6: Testing & Validation - PENDING

**Progress:** 7.5h spent, 7/30 tasks complete (23%), 7x faster than estimated

**Stats:**
- **Files:** 138+ Python files
- **Code:** ~82KB production code
- **Tests:** 129+ tests (84% pass rate)
- **Performance:** 73K ops/sec routing, 861K ops/sec cache

### Data Transformation Directory (`ipfs_datasets_py/data_transformation/`)

**Structure:**
```
data_transformation/
├── ipld/                      # IPLD storage & knowledge graphs
│   ├── storage.py            # Core IPLDStorage class
│   ├── dag_pb.py             # DAG-PB format implementation
│   ├── optimized_codec.py    # High-performance encoding/decoding
│   ├── vector_store.py       # IPLD-based vector storage
│   └── knowledge_graph.py    # IPLD-based knowledge graph
├── multimedia/                # ⚠️ DEPRECATED → processors/multimedia (v2.0.0)
│   ├── ffmpeg_wrapper.py     # FFmpeg integration (79KB)
│   ├── ytdlp_wrapper.py      # yt-dlp integration (70KB)
│   ├── media_processor.py    # Media processing orchestration
│   ├── media_utils.py        # Media utilities
│   ├── email_processor.py    # Email processing
│   ├── discord_wrapper.py    # Discord integration
│   ├── omni_converter_mk2/   # Complex conversion system (453+ files)
│   └── convert_to_txt_based_on_mime_type/ # MIME-based conversion
├── ipfs_formats/              # Format-specific handlers
│   └── ipfs_multiformats.py
├── car_conversion.py          # DataInterchangeUtils: Arrow ↔ CAR
├── jsonl_to_parquet.py        # JSONL → Arrow/Parquet conversion
├── dataset_serialization.py   # Serialize datasets to/from IPLD
├── ipfs_parquet_to_car.py     # Parquet → CAR conversion
├── unixfs.py                  # UnixFS chunking & operations
└── ucan.py                    # UCAN authorization
```

**Status:**
- ✅ multimedia/ has active DeprecationWarning → processors/multimedia
- ❌ No deprecation warnings for other components
- 🔄 IPLD components heavily used across codebase
- 🔄 Serialization utilities are core functionality

**Stats:**
- **IPLD:** ~4,384 lines (storage, DAG-PB, codec, vector store, knowledge graph)
- **Multimedia:** ~5,894 lines + 2 large submodules (omni_converter_mk2, convert_to_txt)
- **Serialization:** ~1,500 lines (car_conversion, jsonl_to_parquet, dataset_serialization)
- **Total:** ~12,000+ lines of core transformation code

### Dependencies & Import Analysis

**Modules importing from data_transformation:**

1. **IPLD imports (25+ locations):**
   - `ipfs_datasets_py/__init__.py` - Core package exports
   - `ipfs_datasets_py/vector_stores/ipld.py` - Vector store integration
   - `ipfs_datasets_py/analytics/data_provenance_enhanced.py` - Provenance tracking
   - `ipfs_datasets_py/search/graph_query/` - Graph querying
   - `ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py` - ML embeddings
   - `ipfs_datasets_py/ml/llm/llm_graphrag.py` - LLM integration
   - `ipfs_datasets_py/processors/` - 3 files (query_engine, graphrag_integrator, pdf_processor)
   - `ipfs_datasets_py/logic/integration/` - Logic caching

2. **Serialization imports (5+ locations):**
   - `ipfs_datasets_py/__init__.py` - Core exports
   - `ipfs_datasets_py/utils/data_format_converter.py` - Format conversion
   - `ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py` - Dataset serialization

3. **Multimedia imports:**
   - Active deprecation shim in place
   - Users being redirected to `processors/multimedia`

---

## Problems & Challenges

### Architectural Issues

1. **Fragmented Organization**
   - Related functionality split between processors/ and data_transformation/
   - No clear separation of concerns
   - Difficult to discover capabilities

2. **Naming Confusion**
   - "data_transformation" vs "processors" - unclear distinction
   - Both directories contain transformation/processing logic
   - Users don't know where to look

3. **Import Complexity**
   - 30+ files import from data_transformation
   - Complex dependency graph
   - Circular dependency risks

4. **Duplication Risk**
   - Multimedia migration already in progress
   - Risk of parallel implementations
   - Inconsistent APIs

### Technical Debt

1. **Two Large Submodules in multimedia/**
   - `omni_converter_mk2/` - 453+ files, complex architecture
   - `convert_to_txt_based_on_mime_type/` - Large conversion system
   - Need careful migration strategy

2. **IPLD Spread**
   - IPLD is foundational storage layer
   - Used by 25+ files across the codebase
   - Cannot simply move without breaking everything

3. **Serialization Utilities**
   - Core infrastructure for dataset handling
   - Used by analytics, ML, search, utils
   - Need to maintain as stable API

### Migration Challenges

1. **Backward Compatibility**
   - Many external users likely depend on data_transformation imports
   - Need deprecation period (3-6 months minimum)
   - Must maintain import shims

2. **Testing Complexity**
   - 182+ existing tests
   - Need to ensure all still pass
   - Add integration tests for new structure

3. **Documentation Burden**
   - Update 20+ docs
   - Migration guides for users
   - Clear deprecation timeline

---

## Integration Strategy

### Core Principle: Logical Separation

**Keep in data_transformation/:**
- ✅ **IPLD infrastructure** - Foundational storage layer
- ✅ **Serialization utilities** - Core dataset conversion
- ✅ **Format-specific tools** - CAR, Parquet, JSONL utilities

**Move to processors/:**
- ✅ **Multimedia** (already in progress)
- ⚠️ **Content processors** (if any - mostly already moved)
- ⚠️ **High-level orchestration** (leave low-level utils in data_transformation)

**Rationale:**
- **data_transformation/** = Low-level utilities, format conversion, storage primitives
- **processors/** = High-level processors, adapters, orchestration, user-facing APIs

### Three-Tier Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Tier 1: User APIs                        │
│              processors/ - High-level processing            │
│   • UniversalProcessor, ProcessorRegistry, Adapters         │
│   • Multimedia, PDF, GraphRAG, Web scraping                 │
│   • User-facing CLI, monitoring, debugging                  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Tier 2: Transformation Layer                    │
│         data_transformation/ - Core utilities               │
│   • IPLD storage (storage, dag_pb, optimized_codec)         │
│   • Serialization (car_conversion, dataset_serialization)   │
│   • Format utilities (jsonl_to_parquet, unixfs)             │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 Tier 3: IPFS Backend                         │
│        ipfs_kit_py, ipfshttpclient, ipfs_accelerate_py      │
└─────────────────────────────────────────────────────────────┘
```

### Naming Clarification

| Module | Purpose | Public API |
|--------|---------|-----------|
| **processors/** | High-level data processing, ML pipelines, content extraction | ✅ Primary user-facing |
| **data_transformation/** | Low-level format conversion, IPLD storage, serialization | ⚠️ Internal/power users |
| **ipfs_datasets_py/** (root) | Package-level convenience imports | ✅ User-facing shortcuts |

---

## Architectural Vision

### Target State (Post-Integration)

```
ipfs_datasets_py/
├── processors/                    # PRIMARY USER API
│   ├── core/                      # Protocol & routing
│   │   ├── protocol.py
│   │   ├── input_detector.py
│   │   ├── processor_registry.py
│   │   └── universal_processor.py
│   ├── adapters/                  # 8+ adapters
│   ├── multimedia/                # Multimedia processing (FFmpeg, yt-dlp, etc.)
│   │   ├── ffmpeg_wrapper.py
│   │   ├── ytdlp_wrapper.py
│   │   ├── media_processor.py
│   │   ├── media_utils.py
│   │   ├── email_processor.py
│   │   ├── discord_wrapper.py
│   │   └── converters/            # Moved from data_transformation/multimedia/
│   │       ├── omni_converter/    # Simplified from omni_converter_mk2
│   │       └── mime_converter/    # Simplified from convert_to_txt_based_on_mime_type
│   ├── file_converter/            # File conversion
│   ├── graphrag/                  # GraphRAG
│   ├── legal_scrapers/            # Legal documents
│   ├── error_handling.py          # Error handling
│   ├── caching.py                 # Caching
│   ├── monitoring.py              # Monitoring
│   └── ... (other processors)
├── data_transformation/           # LOW-LEVEL UTILITIES (simplified)
│   ├── ipld/                      # ✅ KEEP - Foundational IPLD storage
│   │   ├── storage.py             # IPLDStorage class
│   │   ├── dag_pb.py              # DAG-PB format
│   │   ├── optimized_codec.py     # High-performance codec
│   │   ├── vector_store.py        # Vector storage
│   │   └── knowledge_graph.py     # Knowledge graph storage
│   ├── serialization/             # ✅ REORGANIZED - Serialization utilities
│   │   ├── car_conversion.py      # Arrow ↔ CAR
│   │   ├── jsonl_to_parquet.py    # JSONL → Parquet
│   │   ├── dataset_serialization.py # Dataset ↔ IPLD
│   │   └── ipfs_parquet_to_car.py # Parquet → CAR
│   ├── ipfs_formats/              # ✅ KEEP - Format handlers
│   ├── unixfs.py                  # ✅ KEEP - UnixFS operations
│   ├── ucan.py                    # ✅ KEEP - UCAN auth
│   ├── multimedia/                # ⚠️ DEPRECATED (shim only)
│   │   └── __init__.py            # Deprecation warning + re-exports
│   └── __init__.py                # Simplified exports
```

### Key Improvements

1. **Clear Separation:**
   - processors/ = User-facing, high-level processing
   - data_transformation/ = Infrastructure, low-level utilities

2. **Simplified multimedia:**
   - Core wrappers in processors/multimedia/
   - Complex converters in processors/multimedia/converters/
   - Simplified omni_converter (remove _mk2 complexity)

3. **Better Organization:**
   - Group serialization utilities in serialization/ subfolder
   - Keep IPLD as foundational layer
   - Clear import paths

4. **Backward Compatibility:**
   - Keep data_transformation/multimedia/ as deprecation shim
   - Maintain all IPLD exports
   - Add compatibility imports in __init__.py

---

## Migration Plan

### Phase 1: Complete Multimedia Migration (Week 1)

**Status:** ✅ COMPLETE (5h, 7x faster than estimate)

**Completed Tasks:**
1. ✅ Task 1.1: Audit multimedia state (2h)
2. ✅ Task 1.2: Complete core migration - removed 361KB duplicates (1h)
3. ✅ Task 1.5: Migration guide created (2h)
4. 🔄 Tasks 1.3-1.4: Simplification of omni_converter_mk2 and convert_to_txt - DEFERRED to future sprint

**Deliverables:**
- ✅ processors/multimedia/ complete with 6+ wrappers
- ✅ Deprecation warnings for all old imports
- ✅ Migration guide: `MULTIMEDIA_MIGRATION_GUIDE.md`
- ✅ Status reports: `TASK_1_1_MULTIMEDIA_AUDIT_REPORT.md`, `TASK_1_2_CLEANUP_COMPLETE_REPORT.md`

### Phase 2: Organize Serialization Utilities (Week 1-2)

**Status:** ✅ COMPLETE (1h, 7x faster than estimate)

**Completed Tasks:**
1. ✅ Created data_transformation/serialization/ subfolder
2. ✅ Moved 4 serialization files (9,448 lines total):
   - car_conversion.py (547 lines)
   - jsonl_to_parquet.py (531 lines)
   - dataset_serialization.py (8,263 lines)
   - ipfs_parquet_to_car.py (107 lines)
3. ✅ Updated imports across codebase (7 files, 26 imports)
4. ✅ Added backward compatibility shims in root
5. ✅ Deprecation warnings with helpful messages

**Deliverables:**
- ✅ data_transformation/serialization/ package
- ✅ Backward compatibility shims
- ✅ Updated imports in 7 files
- ✅ `TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md`
- ✅ `TASK_2_2_IMPORTS_UPDATE_COMPLETE.md`
- ✅ `PHASE_2_SERIALIZATION_COMPLETE.md`

### Phase 3: Enhance Processor Adapters (Week 2)

**Tasks:**
1. Create DataTransformationAdapter for processors/
   - Integrate IPLD storage operations
   - Integrate serialization utilities
   - Provide high-level API
2. Update existing adapters to use data_transformation utilities:
   - ipfs_adapter.py → use IPLDStorage
   - multimedia_adapter.py → use converters
   - batch_adapter.py → use dataset_serialization
3. Add integration tests

**Deliverables:**
- DataTransformationAdapter in processors/adapters/
- Updated 3+ existing adapters
- 10+ integration tests
- Performance benchmarks

### Phase 4: Consolidate GraphRAG (Week 2-3)

**Status:** ✅ Phase 3 Complete, 🔄 Phase 4 In Progress

**Completed Phase 3 Tasks:**
1. ✅ Reviewed all 7 GraphRAG implementations (4 deprecated, 3 specialized)
2. ✅ Analyzed code duplication (62-67% overlap identified)
3. ✅ Verified deprecation warnings in place
4. ✅ Created comprehensive consolidation plan (13KB)
5. ✅ Created detailed migration guide (20KB)

**In Progress Phase 4 Tasks:**
1. 🔄 Verify/update deprecated shims (0.5h)
2. ⏳ Update main package exports (0.5h)
3. ⏳ Update import references across codebase (1-2h)
4. ⏳ Consolidate supporting files (1h)
5. ⏳ Update tests (0.5-1h)
6. ⏳ Validation (0.5h)

**Deliverables:**
- ✅ UnifiedGraphRAGProcessor implementation (already exists)
- ✅ Deprecation warnings for old implementations (in place)
- ✅ `PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` (13KB)
- ✅ `GRAPHRAG_CONSOLIDATION_GUIDE.md` (20KB migration guide)
- 🔄 Integration with data_transformation/ipld/knowledge_graph.py (in progress)
- ⏳ Updated imports across codebase
- ⏳ Test updates and validation

### Phase 5: Documentation & Deprecation (Week 3-4)

**Tasks:**
1. Create comprehensive migration guides:
   - `PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md`
   - `MIGRATION_GUIDE_V2.md`
   - `DEPRECATION_TIMELINE.md`
2. Update all processor documentation
3. Add deprecation warnings with 6-month timeline
4. Update README.md and top-level docs
5. Create architecture diagrams

**Deliverables:**
- 5+ migration guides
- Updated 20+ existing docs
- Clear deprecation timeline (6 months)
- Architecture diagrams

### Phase 6: Testing & Validation (Week 4)

**Tasks:**
1. Run full test suite (182+ tests)
2. Add integration tests (20+ new tests)
3. Performance benchmarking
4. Backward compatibility validation
5. Documentation review
6. External user testing (if possible)

**Deliverables:**
- All 182+ tests passing
- 20+ new integration tests
- Performance report
- Compatibility report

---

## Implementation Phases

### Week 1: Multimedia & Serialization

| Task | Effort | Status |
|------|--------|--------|
| Complete multimedia migration | 2 days | 🔄 In Progress |
| Simplify omni_converter_mk2 | 1 day | ⏳ Pending |
| Simplify convert_to_txt | 1 day | ⏳ Pending |
| Organize serialization/ | 1 day | ⏳ Pending |
| Update imports | 0.5 days | ⏳ Pending |
| Write migration guides | 0.5 days | ⏳ Pending |

### Week 2: Adapters & GraphRAG

| Task | Effort | Status |
|------|--------|--------|
| Create DataTransformationAdapter | 1 day | ⏳ Pending |
| Update existing adapters | 1 day | ⏳ Pending |
| Integration tests | 1 day | ⏳ Pending |
| Start GraphRAG consolidation | 2 days | ⏳ Pending |

### Week 3: GraphRAG & Documentation

| Task | Effort | Status |
|------|--------|--------|
| Complete GraphRAG consolidation | 2 days | ⏳ Pending |
| Write comprehensive docs | 2 days | ⏳ Pending |
| Add deprecation warnings | 1 day | ⏳ Pending |

### Week 4: Testing & Validation

| Task | Effort | Status |
|------|--------|--------|
| Full test suite | 1 day | ⏳ Pending |
| Integration tests | 1 day | ⏳ Pending |
| Performance benchmarks | 1 day | ⏳ Pending |
| Documentation review | 1 day | ⏳ Pending |
| User validation | 1 day | ⏳ Pending |

**Total Estimated Effort:** 20 days (4 weeks)

---

## Backward Compatibility

### Deprecation Strategy

**Timeline:**
- **v1.x (current):** Active development, warnings added
- **v1.9:** Full deprecation warnings, migration guides
- **v2.0:** Remove deprecated imports (6 months after v1.9)

### Compatibility Shims

**Example: data_transformation/multimedia/__init__.py** (already implemented):
```python
import warnings

warnings.warn(
    "data_transformation.multimedia is deprecated. Use processors.multimedia instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.processors.multimedia import *
```

**To Add:**
1. data_transformation/car_conversion.py → shim to serialization/
2. data_transformation/jsonl_to_parquet.py → shim to serialization/
3. Maintain IPLD exports in data_transformation/ipld/ (no deprecation)

### Import Compatibility

**Phase 1 (v1.x - v1.9):**
```python
# Old imports still work with warnings
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper  # ⚠️ Warning
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage  # ✅ No warning
```

**Phase 2 (v2.0+):**
```python
# Multimedia must use new import
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper  # ✅
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage  # ✅ Still supported
```

---

## Testing Strategy

### Test Categories

1. **Unit Tests:**
   - Test each processor adapter independently
   - Test serialization utilities
   - Test IPLD operations
   - **Target:** 95% code coverage

2. **Integration Tests:**
   - Test processor → data_transformation flow
   - Test multimedia converters
   - Test serialization pipelines
   - **Target:** 20+ new integration tests

3. **Backward Compatibility Tests:**
   - Test old import paths (with warning suppression)
   - Validate shims work correctly
   - Test that existing code doesn't break
   - **Target:** 100% of deprecated paths tested

4. **Performance Tests:**
   - Benchmark routing overhead
   - Benchmark serialization performance
   - Benchmark multimedia processing
   - **Target:** No regression from baseline

### Test Plan

| Category | Current | Target | New Tests |
|----------|---------|--------|-----------|
| Unit Tests | 210+ | 230+ | 20+ |
| Integration Tests | 20+ | 40+ | 20+ |
| E2E Tests | 5+ | 10+ | 5+ |
| Performance Tests | 11 | 20+ | 9+ |
| **Total** | **246+** | **300+** | **54+** |

### CI/CD Integration

**Workflows to Update:**
1. `processor-tests.yml` - Add data_transformation tests
2. `integration-tests.yml` - Add cross-module tests
3. `deprecation-warnings.yml` - Track deprecation compliance
4. `performance-benchmarks.yml` - Track performance metrics

---

## Success Metrics

### Functional Metrics

- ✅ All 182+ existing tests pass
- ✅ 54+ new tests added and passing
- ✅ 100% backward compatibility maintained
- ✅ No performance regression (<5% difference)
- ✅ All deprecated imports have warnings

### Organizational Metrics

- ✅ Clear separation: processors/ vs data_transformation/
- ✅ Simplified data_transformation/ (remove multimedia/)
- ✅ Single unified multimedia API
- ✅ Consolidated GraphRAG implementation
- ✅ Organized serialization utilities

### Documentation Metrics

- ✅ 5+ migration guides created
- ✅ 20+ docs updated
- ✅ Clear deprecation timeline (6 months)
- ✅ Architecture diagrams created
- ✅ User migration checklist provided

### Code Quality Metrics

- ✅ Reduced code duplication (target: 20% reduction)
- ✅ Improved import structure (fewer cross-dependencies)
- ✅ Better modularity (clear interfaces)
- ✅ Enhanced testability (95% coverage)

---

## Risk Management

### High Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing user code | HIGH | Maintain backward compatibility shims for 6 months |
| Complex multimedia migration | MEDIUM | Simplify omni_converter_mk2, extensive testing |
| Performance regression | MEDIUM | Benchmark before/after, optimize hot paths |
| Import circular dependencies | MEDIUM | Careful dependency analysis, lazy imports |

### Medium Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Documentation gaps | MEDIUM | Comprehensive review, user feedback |
| Test coverage gaps | MEDIUM | Add 54+ new tests, aim for 95% coverage |
| GraphRAG consolidation | MEDIUM | Incremental approach, feature parity validation |

### Low Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Naming conflicts | LOW | Clear naming conventions |
| Version conflicts | LOW | Semantic versioning |

---

## Next Steps

### Immediate Actions (Week 1)

1. **Review this plan** with project stakeholders
2. **Prioritize tasks** based on user impact
3. **Start Phase 1:** Complete multimedia migration
4. **Create detailed task breakdown** for Week 1

### Questions to Answer

1. Should omni_converter_mk2 be fully migrated or just the core functionality?
2. What is the target date for v2.0 (deprecation removal)?
3. Are there external users we should notify before making changes?
4. Should we create a compatibility testing framework?

### Approval Needed

- [ ] Architecture review
- [ ] Timeline approval
- [ ] Resource allocation
- [ ] External communication plan

---

## Appendix

### Related Documentation

- `PROCESSORS_MASTER_PLAN.md` - Processors architecture overview
- `PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` - Previous refactoring plan
- `PROCESSORS_WEEK1_SUMMARY.md` - Week 1 implementation summary
- `WEEK_1_IMPLEMENTATION_COMPLETE.md` - PR #948 details
- `KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md` - Knowledge graph migration example

### Key Files to Track

**Processors:**
- `processors/core/protocol.py` (2,316 lines)
- `processors/core/universal_processor.py` (426 lines)
- `processors/multimedia/` (will grow significantly)

**Data Transformation:**
- `data_transformation/ipld/` (~4,384 lines) - KEEP
- `data_transformation/multimedia/` (~5,894 lines) - DEPRECATE
- `data_transformation/*_conversion.py` (~1,500 lines) - REORGANIZE

### Import Analysis Results

**Files importing from data_transformation:**
- IPLD: 25+ files across analytics, search, ML, vector_stores, logic, processors
- Serialization: 5+ files in utils, ML, main __init__.py
- Multimedia: Active deprecation, redirecting to processors

**Critical Dependencies:**
- pyarrow, ipfshttpclient, ipld_car, datasets - Widely used
- ffmpeg-python, yt-dlp - Multimedia only

---

**Document Status:** Planning Phase  
**Next Review:** After Week 1 completion  
**Owner:** @endomorphosis  
**Contributors:** GitHub Copilot, refactoring team  

---

*This is a living document. Updates will be made as the integration progresses.*
