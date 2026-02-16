# Processors Refactoring Implementation Checklist

**Project:** IPFS Datasets Python - Processors Directory Refactoring  
**Date Started:** 2026-02-16  
**Target Completion:** ~12 weeks  
**Status:** Planning Complete → Ready for Implementation  

---

## Phase 1: Complete AnyIO Migration ⏳ (Weeks 1-3)

**Goal:** Replace all `asyncio` usage with `anyio` for framework consistency.

### 1.1 Infrastructure Layer Migration 🔴 CRITICAL
**Files:** 4 files in `infrastructure/`

- [ ] **profiling.py**
  - [ ] Replace `import asyncio` with `import anyio` (line 13)
  - [ ] Update async context managers
  - [ ] Replace `asyncio.sleep()` calls if any
  - [ ] Update tests
  - [ ] Verify profiling metrics still work
  - **Estimated:** 4 hours

- [ ] **error_handling.py**
  - [ ] Replace `import asyncio` with `import anyio` (line 10)
  - [ ] Replace `asyncio.sleep()` → `anyio.sleep()`
  - [ ] Replace `asyncio.gather()` → task groups
  - [ ] Update retry logic with task groups
  - [ ] Update tests
  - **Estimated:** 6 hours

- [ ] **debug_tools.py**
  - [ ] Audit for asyncio usage
  - [ ] Replace asyncio patterns with anyio
  - [ ] Update tests
  - **Estimated:** 3 hours

- [ ] **caching.py**
  - [ ] Audit for asyncio usage
  - [ ] Replace asyncio patterns with anyio if found
  - [ ] Update tests
  - **Estimated:** 2 hours

**Subtask:** Infrastructure Testing
- [ ] Run all infrastructure tests with anyio
- [ ] Add anyio-specific test cases
- [ ] Performance benchmarks (before/after)
- [ ] Document any API changes

**Estimated Time:** 3-4 days  
**Status:** ⏳ Not Started

---

### 1.2 Core Layer Migration 🔴 HIGH
**Files:** 1-2 files in `core/` and top-level

- [ ] **universal_processor.py** (top-level)
  - [ ] Replace `import asyncio` with `import anyio` (line 13)
  - [ ] Replace `asyncio.gather()` in `process_batch()` with task groups
  - [ ] Add `_process_and_collect()` helper method
  - [ ] Update error handling for task groups
  - [ ] Update tests
  - **Estimated:** 6 hours

- [ ] **core/universal_processor.py** (if exists)
  - [ ] Same changes as above
  - [ ] Ensure consistency between files
  - **Estimated:** 2 hours

**Subtask:** Core Testing
- [ ] Unit tests for UniversalProcessor
- [ ] Integration tests with various input types
- [ ] Performance tests (ensure no regression)

**Estimated Time:** 2-3 days  
**Status:** ⏳ Not Started

---

### 1.3 Specialized Processors Migration 🟡 MEDIUM
**Files:** Multiple files in `specialized/`

- [ ] **specialized/batch/processor.py**
  - [ ] Replace `asyncio.gather()` with task groups
  - [ ] Update concurrency control
  - [ ] Update tests
  - **Estimated:** 4 hours

- [ ] **specialized/batch/file_converter_batch.py**
  - [ ] Audit and migrate
  - **Estimated:** 2 hours

- [ ] **specialized/graphrag/** (all files)
  - [ ] Audit each file for asyncio usage
  - [ ] Migrate as needed
  - **Estimated:** 4 hours

- [ ] **specialized/media/advanced_processing.py**
  - [ ] Audit and migrate
  - **Estimated:** 3 hours

- [ ] **specialized/multimodal/multimodal_processor.py**
  - [ ] Audit and migrate
  - **Estimated:** 3 hours

- [ ] **specialized/web_archive/advanced_archiving.py**
  - [ ] Audit and migrate
  - **Estimated:** 3 hours

- [ ] **specialized/pdf/pdf_processor.py**
  - [ ] Audit and migrate
  - **Estimated:** 3 hours

**Estimated Time:** 3-4 days  
**Status:** ⏳ Not Started

---

### 1.4 Multimedia Subsystem Migration 🔴 HIGH - COMPLEX
**Files:** 40+ files across deep directory structure

#### Phase 1.4.1: Main Entry Points
- [ ] **multimedia/convert_to_txt_based_on_mime_type/main.py**
  - [ ] Replace `asyncio.run()` with `anyio.run()`
  - [ ] Remove event loop management
  - [ ] Update initialization
  - **Estimated:** 4 hours

#### Phase 1.4.2: Conversion Pipeline
- [ ] **converter_system/conversion_pipeline/functions/core.py**
  - [ ] Replace `asyncio.gather()` with task groups
  - [ ] Update error handling
  - **Estimated:** 3 hours

- [ ] **converter_system/conversion_pipeline/functions/pipeline.py**
  - [ ] Replace `asyncio.gather()` with task groups
  - **Estimated:** 3 hours

- [ ] **converter_system/conversion_pipeline/functions/optimize.py**
  - [ ] Replace asyncio patterns
  - **Estimated:** 2 hours

#### Phase 1.4.3: Queue and Resource Management
- [ ] **converter_system/file_path_queue/file_path_queue.py**
  - [ ] Replace `asyncio.Queue` with memory streams
  - [ ] Update producer/consumer pattern
  - [ ] Test thoroughly (queues are tricky!)
  - **Estimated:** 6 hours

- [ ] **converter_system/core_resource_manager/**
  - [ ] Audit and migrate resource management
  - **Estimated:** 4 hours

#### Phase 1.4.4: Pools System
- [ ] **pools/non_system_resources/core_functions_pool/core_functions_pool.py**
  - [ ] Replace `asyncio.gather()` with task groups
  - **Estimated:** 3 hours

- [ ] Other pool files
  - [ ] Audit and migrate as needed
  - **Estimated:** 3 hours

#### Phase 1.4.5: Utilities
- [ ] **utils/common/asyncio_coroutine.py**
  - [ ] Create new `anyio_coroutine.py` file
  - [ ] Migrate utilities
  - [ ] Update all callers
  - **Estimated:** 6 hours

- [ ] **utils/converter_system/monads/async_.py**
  - [ ] Replace asyncio in async monad
  - **Estimated:** 3 hours

- [ ] **utils/converter_system/run_in_parallel_with_concurrency_limiter.py**
  - [ ] Replace `asyncio.Semaphore` with `anyio.CapacityLimiter`
  - **Estimated:** 2 hours

- [ ] **utils/converter_system/run_in_thread_pool.py**
  - [ ] Replace `asyncio.run_in_executor()` with `anyio.to_thread.run_sync()`
  - **Estimated:** 2 hours

#### Phase 1.4.6: Omni Converter MK2
- [ ] **multimedia/omni_converter_mk2/interfaces/_gui.py**
  - [ ] Audit and migrate
  - **Estimated:** 3 hours

- [ ] Other omni_mk2 files with asyncio
  - [ ] Audit all files
  - [ ] Migrate as needed
  - **Estimated:** 4 hours

#### Phase 1.4.7: Testing
- [ ] Create integration tests for each conversion pipeline
- [ ] Test with various file formats (PDF, audio, video, images)
- [ ] Verify concurrency limits work correctly
- [ ] Test error handling and retries
- [ ] Performance benchmarks (anyio should be comparable)
- **Estimated:** 1 day

**Estimated Time:** 5-7 days  
**Status:** ⏳ Not Started

---

### 1.5 Documentation & Migration Guide
- [ ] Create `docs/ASYNCIO_TO_ANYIO_MIGRATION.md` (detailed guide)
- [ ] Document common patterns and pitfalls
- [ ] Create code examples
- [ ] Update README with anyio information
- [ ] Add migration checklist
- **Estimated:** 1 day  
**Status:** ⏳ Not Started

### Phase 1 Final Steps
- [ ] Run complete test suite
- [ ] Performance benchmarks
- [ ] Code review
- [ ] Update CHANGELOG.md
- [ ] Merge to main

**Phase 1 Total Estimated Time:** 2-3 weeks  
**Phase 1 Status:** ⏳ Not Started

---

## Phase 2: Consolidate Duplicate Functionality ⏳ (Weeks 4-7)

**Goal:** Merge 3 file conversion systems into 1 unified system.

### 2.1 Analysis & Planning (Week 4 Day 1-2)
- [ ] Document all features of each conversion system
- [ ] Identify unique features to preserve
- [ ] Create consolidated architecture design
- [ ] Get team approval on design
- **Estimated:** 2 days

### 2.2 Extract Valuable Components (Week 4 Day 3-5)
- [ ] From `convert_to_txt_based_on_mime_type/`:
  - [ ] Extract MIME detection logic (if better)
  - [ ] Extract format-specific extractors
  - [ ] Document what's being deprecated
- [ ] From `omni_converter_mk2/`:
  - [ ] Extract GUI interface → Move to `file_converter/gui/`
  - [ ] Extract content extraction enhancements
  - [ ] Extract file format detector logic
  - [ ] Extract batch processor enhancements
  - [ ] Extract monitoring tools
- **Estimated:** 3 days

### 2.3 Create Unified System (Week 5)
- [ ] Enhance `file_converter/backends/omni_backend.py`
- [ ] Create `file_converter/gui/` directory
- [ ] Merge MIME detection into `file_converter/detection/`
- [ ] Enhance `file_converter/batch_processor.py`
- [ ] Integrate monitoring with `infrastructure/monitoring.py`
- [ ] Create integration tests
- **Estimated:** 5 days

### 2.4 Deprecate Legacy Systems (Week 5-6)
- [ ] Add deprecation warnings to `convert_to_txt_based_on_mime_type/__init__.py`
- [ ] Add deprecation warnings to `omni_converter_mk2/__init__.py`
- [ ] Create backward compatibility adapters
- [ ] Update internal imports to use new system
- [ ] Document deprecation in CHANGELOG
- **Estimated:** 2 days

### 2.5 Consolidate Batch Processing (Week 6)
- [ ] Compare all 4 batch processing implementations
- [ ] Merge best features into `file_converter/batch_processor.py`
- [ ] Deprecate other implementations
- [ ] Update tests
- **Estimated:** 1 week

### 2.6 Consolidate PDF Processing (Week 6-7)
- [ ] Create `specialized/pdf/` structure
- [ ] Move logic from top-level files
- [ ] Integrate with `file_converter/` backends
- [ ] Remove top-level `pdf_processor.py` and `pdf_processing.py`
- [ ] Create deprecation wrappers
- [ ] Update tests
- **Estimated:** 3-4 days

### 2.7 Consolidate Multimodal Processing (Week 7)
- [ ] Create single `specialized/multimodal/processor.py`
- [ ] Merge logic from top-level files
- [ ] Deprecate `multimodal_processor.py`
- [ ] Deprecate `enhanced_multimodal_processor.py`
- [ ] Update tests
- **Estimated:** 2-3 days

### Phase 2 Final Steps
- [ ] Complete integration test suite
- [ ] Performance benchmarks (ensure no regression)
- [ ] Create migration guide for external users
- [ ] Code review
- [ ] Update CHANGELOG.md
- [ ] Merge to main

**Phase 2 Total Estimated Time:** 3-4 weeks  
**Phase 2 Status:** ⏳ Not Started

---

## Phase 3: Clean Up Legacy Top-Level Files ⏳ (Week 7-8)

**Goal:** Remove deprecated top-level files and enforce new directory structure.

### 3.1 Verify New Locations Exist
- [ ] Check all target directories exist
- [ ] Verify new implementations are production-ready
- [ ] Create any missing directories
- **Estimated:** 2 hours

### 3.2 Create Deprecation Wrappers (Week 7)
For each file to deprecate:
- [ ] `advanced_graphrag_website_processor.py` → `specialized/graphrag/`
- [ ] `advanced_media_processing.py` → `specialized/media/`
- [ ] `advanced_web_archiving.py` → `specialized/web_archive/`
- [ ] `batch_processor.py` → `specialized/batch/`
- [ ] `graphrag_processor.py` → `specialized/graphrag/`
- [ ] `graphrag_integrator.py` → `specialized/graphrag/`
- [ ] `multimodal_processor.py` → `specialized/multimodal/`
- [ ] `enhanced_multimodal_processor.py` → `specialized/multimodal/`
- [ ] `pdf_processor.py` → `specialized/pdf/`
- [ ] `pdf_processing.py` → `specialized/pdf/`
- [ ] `website_graphrag_processor.py` → `specialized/graphrag/`
- [ ] `patent_scraper.py` → `domains/patent/`
- [ ] `patent_dataset_api.py` → `domains/patent/`
- [ ] `geospatial_analysis.py` → `domains/geospatial/`
- [ ] `classify_with_llm.py` → `domains/ml/`
- [ ] `ocr_engine.py` → `specialized/ocr/`
- [ ] `query_engine.py` → `engines/query/`
- [ ] `relationship_analyzer.py` → `engines/relationship/`
- [ ] `llm_optimizer.py` → `engines/llm/`
- [ ] `caching.py` → `infrastructure/caching.py`
- [ ] `cli.py` → `infrastructure/cli.py`
- [ ] `debug_tools.py` → `infrastructure/debug_tools.py`
- [ ] `error_handling.py` → `infrastructure/error_handling.py`
- [ ] `monitoring.py` → `infrastructure/monitoring.py`
- [ ] `profiling.py` → `infrastructure/profiling.py`
- [ ] `protocol.py` → `core/protocol.py` (REMOVE DUPLICATE)
- [ ] `registry.py` → `core/registry.py` (REMOVE DUPLICATE)

**Estimated:** 3 days

### 3.3 Update __init__.py (Week 7-8)
- [ ] Update `ipfs_datasets_py/processors/__init__.py`
- [ ] Add new imports from subdirectories
- [ ] Keep deprecated imports with warnings (temporary)
- [ ] Document what's changing
- **Estimated:** 1 day

### 3.4 Update Internal References (Week 8)
- [ ] Find all imports of old locations
- [ ] Update to new locations
- [ ] Run tests after each batch of changes
- **Estimated:** 2 days

### 3.5 Create Automated Migration Script (Week 8)
- [ ] Create `scripts/migrate_imports.py`
- [ ] Test on a copy of the codebase
- [ ] Document usage
- **Estimated:** 1 day

### 3.6 Documentation Updates (Week 8)
- [ ] Update README.md with new import paths
- [ ] Create `docs/MIGRATION_GUIDE_V2_TO_V3.md`
- [ ] Update `docs/ARCHITECTURE.md`
- [ ] Add to DEPRECATION_SCHEDULE.md
- [ ] Update CHANGELOG.md
- **Estimated:** 1 day

### Phase 3 Final Steps
- [ ] Run complete test suite
- [ ] Verify all deprecation warnings work
- [ ] Code review
- [ ] Merge to main

**Phase 3 Total Estimated Time:** 1-2 weeks  
**Phase 3 Status:** ⏳ Not Started

---

## Phase 4: Flatten Multimedia Directory Structure ⏳ (Week 8-9)

**Goal:** Reduce deep nesting from 8+ levels to maximum 4 levels.

### 4.1 Run Code Coverage Analysis
- [ ] Determine what code is actually used
- [ ] Identify dead code for deletion
- [ ] Document findings
- **Estimated:** 0.5 day

### 4.2 Flatten or Deprecate (Week 8-9)
**Decision Point:** Keep simplified or fully deprecate?

**Option A: Full Deprecation** (RECOMMENDED)
- [ ] Create `multimedia/legacy_converter/` with deprecation wrapper
- [ ] Route all calls to `file_converter/`
- [ ] Document migration path
- **Estimated:** 1 day

**Option B: Simplify and Keep**
- [ ] Rename to `multimedia/txt_converter/`
- [ ] Merge small modules into larger ones
- [ ] Flatten to 3 levels maximum
- [ ] Update tests
- **Estimated:** 1 week

### 4.3 Fix Directory Naming
- [ ] Rename overly verbose directories
- [ ] Standardize snake_case
- [ ] Update all imports
- [ ] Update documentation
- **Estimated:** 1 day

### 4.4 Eliminate Over-Engineering
- [ ] Remove unnecessary abstractions (monads, pools if not needed)
- [ ] Simplify resource management
- [ ] Use standard libraries where possible
- **Estimated:** 2 days

### Phase 4 Final Steps
- [ ] Run complete test suite
- [ ] Verify directory structure
- [ ] Code review
- [ ] Update CHANGELOG.md
- [ ] Merge to main

**Phase 4 Total Estimated Time:** 1-2 weeks  
**Phase 4 Status:** ⏳ Not Started

---

## Phase 5: Standardize Architecture Patterns ⏳ (Week 9-11)

**Goal:** Establish and enforce clear architectural boundaries.

### 5.1 Define Architecture Tiers (Week 9 Day 1)
- [ ] Document 5 layers (core, adapters, specialized, domains, infrastructure)
- [ ] Define dependency rules
- [ ] Get team agreement
- **Estimated:** 0.5 day

### 5.2 Enforce Dependency Rules (Week 9 Day 2)
- [ ] Audit current dependencies
- [ ] Identify violations
- [ ] Create fix plan
- **Estimated:** 0.5 day

### 5.3 Create Architecture Tests (Week 9 Day 3-4)
- [ ] Create `tests/architecture/test_dependencies.py`
- [ ] Test core has no internal dependencies
- [ ] Test adapters only depend on core
- [ ] Test no circular dependencies
- [ ] Add to CI
- **Estimated:** 1 day

### 5.4 Create Standard Module Template (Week 9 Day 5)
- [ ] Document standard structure
- [ ] Create template file
- [ ] Add to development docs
- **Estimated:** 0.5 day

### 5.5 Standardize All Processors (Week 10-11)
For each processor:
- [ ] Implement `ProcessorProtocol`
- [ ] Use `anyio` exclusively
- [ ] Add comprehensive docstring
- [ ] Proper error handling with `ProcessorError`
- [ ] Return standardized `ProcessingResult`
- [ ] Add logging with module logger
- [ ] Add type hints on all methods
- [ ] Create config dataclass if needed

**Processors to Standardize:**
- [ ] `specialized/batch/processor.py`
- [ ] `specialized/pdf/pdf_processor.py`
- [ ] `specialized/graphrag/unified_graphrag.py`
- [ ] `specialized/media/advanced_processing.py`
- [ ] `specialized/multimodal/multimodal_processor.py`
- [ ] `specialized/web_archive/advanced_archiving.py`
- [ ] `domains/patent/patent_scraper.py`
- [ ] `domains/patent/patent_dataset_api.py`
- [ ] `domains/geospatial/geospatial_analysis.py`
- [ ] `domains/ml/classify_with_llm.py`
- [ ] All other domain processors

**Estimated:** 2 weeks

### Phase 5 Final Steps
- [ ] Run architecture tests
- [ ] Run complete test suite
- [ ] Code review
- [ ] Update CHANGELOG.md
- [ ] Merge to main

**Phase 5 Total Estimated Time:** 2-3 weeks  
**Phase 5 Status:** ⏳ Not Started

---

## Phase 6: Testing & Documentation ⏳ (Week 11-12)

**Goal:** Comprehensive testing and documentation.

### 6.1 Test Suite Updates (Week 11)
- [ ] Update all tests to use `@pytest.mark.anyio`
- [ ] Create integration tests for all processors
- [ ] Create architecture tests
- [ ] Performance benchmarks
- [ ] Test coverage report (target: 90%+)
- **Estimated:** 1 week

### 6.2 Documentation Creation (Week 12)
- [ ] Create `docs/ARCHITECTURE.md`
- [ ] Create `docs/PROCESSORS_GUIDE.md`
- [ ] Create `docs/ADDING_PROCESSORS.md`
- [ ] Create `docs/ASYNCIO_TO_ANYIO_MIGRATION.md` (if not done)
- [ ] Create `docs/MIGRATION_V2_TO_V3.md` (if not done)
- [ ] Update `CHANGELOG.md`
- [ ] Update `README.md`
- **Estimated:** 3 days

### 6.3 Code Examples (Week 12)
- [ ] Create `examples/processors/basic_usage.py`
- [ ] Create `examples/processors/batch_processing.py`
- [ ] Create `examples/processors/custom_processor.py`
- [ ] Create `examples/processors/anyio_patterns.py`
- [ ] Create `examples/processors/error_handling.py`
- **Estimated:** 2 days

### Phase 6 Final Steps
- [ ] Complete test suite passing
- [ ] All documentation reviewed
- [ ] Examples tested
- [ ] Final code review
- [ ] Update CHANGELOG.md
- [ ] Merge to main
- [ ] Create release

**Phase 6 Total Estimated Time:** 1-2 weeks  
**Phase 6 Status:** ⏳ Not Started

---

## Progress Summary

| Phase | Status | Estimated Time | Actual Time | Completion % |
|-------|--------|----------------|-------------|--------------|
| Phase 1: AnyIO Migration | ⏳ Not Started | 2-3 weeks | - | 0% |
| Phase 2: Consolidation | ⏳ Not Started | 3-4 weeks | - | 0% |
| Phase 3: Legacy Cleanup | ⏳ Not Started | 1-2 weeks | - | 0% |
| Phase 4: Flatten Structure | ⏳ Not Started | 1-2 weeks | - | 0% |
| Phase 5: Standardize Patterns | ⏳ Not Started | 2-3 weeks | - | 0% |
| Phase 6: Testing & Docs | ⏳ Not Started | 1-2 weeks | - | 0% |
| **TOTAL** | ⏳ Not Started | **8-12 weeks** | - | **0%** |

---

## Notes

- Each phase depends on the previous phase
- Phases can have some overlap (e.g., documentation started early)
- Testing should be continuous, not just in Phase 6
- Regular code reviews after each major milestone
- Keep backward compatibility until v3.0.0 release

---

## Risk Tracking

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Breaking external APIs | HIGH | Deprecation wrappers, migration guides | ⏳ Planned |
| Performance regression | MEDIUM | Benchmarks before/after each phase | ⏳ Planned |
| Complex async migration | HIGH | Integration tests, incremental approach | ⏳ Planned |
| Incomplete consolidation | MEDIUM | Thorough analysis, feature matrix | ⏳ Planned |

---

## Team Assignments

*To be filled in when work begins*

- Phase 1: TBD
- Phase 2: TBD
- Phase 3: TBD
- Phase 4: TBD
- Phase 5: TBD
- Phase 6: TBD

---

**Last Updated:** 2026-02-16  
**Next Review:** When Phase 1 starts  
**Maintained By:** Development Team
