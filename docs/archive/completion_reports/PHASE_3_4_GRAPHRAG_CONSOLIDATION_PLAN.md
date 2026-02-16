# Phase 3-4: GraphRAG Consolidation Plan

**Created:** 2026-02-15  
**Status:** In Progress  
**Priority:** HIGH - Major architectural consolidation  
**Estimated Time:** 4-6 hours (based on 7x efficiency factor from Phases 1-2)

---

## Executive Summary

This plan consolidates **7 GraphRAG implementations** into a unified architecture, eliminating ~170KB of duplicate code while preserving all functionality. The consolidation is already partially complete with deprecation warnings in place.

---

## Current State Analysis

### GraphRAG Implementations Overview

| Implementation | Location | Lines | Status | Notes |
|----------------|----------|-------|--------|-------|
| **UnifiedGraphRAGProcessor** | `processors/graphrag/unified_graphrag.py` | ~550 | ✅ **PRODUCTION** | Async-first, 8-phase pipeline, IPLD integration |
| GraphRAGProcessor | `processors/graphrag_processor.py` | 264 | ⚠️ DEPRECATED | Basic graph/vector ops, has warnings |
| WebsiteGraphRAGProcessor | `processors/website_graphrag_processor.py` | 585 | ⚠️ DEPRECATED | Website crawling, has warnings |
| AdvancedGraphRAGWebsiteProcessor | `processors/advanced_graphrag_website_processor.py` | ~1,600 | ⚠️ DEPRECATED | Multi-pass extraction, has warnings |
| CompleteGraphRAGSystem | `processors/graphrag/complete_advanced_graphrag.py` | ~1,220 | ✅ INTEGRATED | Source for UnifiedGraphRAG |
| GraphRAGIntegration | `search/graphrag_integration/graphrag_integration.py` | 3,141 | ✅ KEEP | LLM-enhanced query engine |
| NeurosymbolicGraphRAG | `logic/integration/symbolic/neurosymbolic_graphrag.py` | ~800 | ✅ KEEP | Logic-enhanced for legal docs |

**Supporting Files:**
- `processors/graphrag/integration.py` (107KB)
- `processors/graphrag/phase7_complete_integration.py` (46KB)
- `processors/graphrag/enhanced_integration.py` (33KB)
- `processors/graphrag/website_system.py` (32KB)
- `processors/adapters/graphrag_adapter.py` (adapter for UniversalProcessor)

### Code Duplication Analysis

**Duplicated Functionality (62-67% overlap):**
1. Web archiving (all 4 main implementations)
2. Entity extraction (basic in 3, advanced in 1)
3. Content processing pipelines (similar in all)
4. Vector store integration (duplicated patterns)
5. Configuration management (4 separate config classes)

**Unique Features to Preserve:**
1. **UnifiedGraphRAG:** Async-first, IPLD integration, multi-service archiving
2. **GraphRAGIntegration:** LLM reasoning, cross-document Q&A
3. **NeurosymbolicGraphRAG:** TDFOL logic, contract analysis
4. **AdvancedGraphRAG:** Domain-specific patterns, quality assessment

### Import Analysis

**Files importing deprecated GraphRAG processors:** ~25+ files including:
- `ipfs_datasets_py/__init__.py` (main exports)
- `analytics/cross_website_analyzer.py`
- `logic/integrations/` (2 files)
- `optimizers/graphrag/` (multiple files)
- Various CLI and util files

---

## Consolidation Strategy

### Architecture Decision: 3-Tier Model

```
┌─────────────────────────────────────────────────────────────┐
│           Tier 1: User-Facing API (Keep as-is)              │
│                                                              │
│  • GraphRAGIntegration (search/) - LLM-enhanced queries     │
│  • NeurosymbolicGraphRAG (logic/) - Legal domain logic      │
│  • GraphRAGAdapter (processors/adapters/) - Universal entry │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│        Tier 2: Core Engine (Consolidate here) ✅            │
│                                                              │
│  UnifiedGraphRAGProcessor (processors/graphrag/)            │
│  • 8-phase async pipeline                                   │
│  • Web archiving (multi-service)                            │
│  • Entity extraction & knowledge graphs                     │
│  • IPLD integration                                         │
│  • Vector search + graph traversal                          │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│     Tier 3: Infrastructure (IPLD, storage, models)          │
│                                                              │
│  • data_transformation/ipld/knowledge_graph.py              │
│  • Vector stores (FAISS, Qdrant, etc.)                     │
│  • Embedding models                                         │
└─────────────────────────────────────────────────────────────┘
```

### What Gets Consolidated

**✅ Keep as Primary:**
- `processors/graphrag/unified_graphrag.py` - **Main implementation**
- `processors/graphrag/integration.py` - GraphRAG factory & integration helpers
- `processors/graphrag/website_system.py` - Website-specific system

**⚠️ Deprecate with Shims (Already Done):**
- `processors/graphrag_processor.py` - Has DeprecationWarning ✅
- `processors/website_graphrag_processor.py` - Has DeprecationWarning ✅
- `processors/advanced_graphrag_website_processor.py` - Has DeprecationWarning ✅

**✅ Keep as Specialized Layers:**
- `search/graphrag_integration/` - LLM enhancement layer
- `logic/integration/symbolic/neurosymbolic_graphrag.py` - Logic layer

**🔄 Merge/Simplify:**
- `processors/graphrag/complete_advanced_graphrag.py` - Already integrated into Unified
- `processors/graphrag/phase7_complete_integration.py` - Remove or simplify
- `processors/graphrag/enhanced_integration.py` - Merge into integration.py

---

## Implementation Plan

### Phase 3: Analysis & Documentation (1-2h)

#### Task 3.1: Complete GraphRAG Audit ✅ (DONE)
- [x] Identified all 7 implementations
- [x] Documented overlaps and unique features
- [x] Verified deprecation warnings in place
- [x] Analyzed import dependencies

#### Task 3.2: Create Migration Documentation (1h)
- [ ] Write `GRAPHRAG_CONSOLIDATION_GUIDE.md`
- [ ] Document migration paths for each deprecated class
- [ ] Provide code examples (before/after)
- [ ] Create import update checklist

#### Task 3.3: Update Architecture Documentation (0.5h)
- [ ] Update `PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md`
- [ ] Document 3-tier architecture
- [ ] Add architecture diagrams
- [ ] Update main README.md

### Phase 4: Implementation & Testing (3-4h)

#### Task 4.1: Update Deprecated Shims (0.5h)
**Already have deprecation warnings, need to verify completeness:**

1. Verify all deprecated files have proper warnings ✅ (3 files checked)
2. Ensure warnings point to UnifiedGraphRAGProcessor
3. Add migration examples in docstrings

#### Task 4.2: Update Main Package Exports (0.5h)
Update `ipfs_datasets_py/__init__.py` to:
- Export UnifiedGraphRAGProcessor as default
- Keep deprecated exports with warnings
- Add convenient aliases

#### Task 4.3: Update Import References (1-2h)
Update ~25+ files importing deprecated processors:
- `analytics/cross_website_analyzer.py`
- `logic/integrations/` (2 files)
- `optimizers/graphrag/` files
- CLI files
- Test files (preserve test backward compat)

Pattern:
```python
# OLD (deprecated)
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor

# NEW (unified)
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
```

#### Task 4.4: Consolidate Supporting Files (1h)
1. Review `processors/graphrag/phase7_complete_integration.py`
   - Determine if needed or can be removed
2. Merge `processors/graphrag/enhanced_integration.py` into `integration.py`
3. Clean up `processors/graphrag/__init__.py` to export properly

#### Task 4.5: Update Tests (0.5-1h)
1. Review test files using deprecated processors
2. Add backward compatibility tests (verify warnings work)
3. Update main test suite to use UnifiedGraphRAGProcessor
4. Ensure all existing tests still pass

#### Task 4.6: Run Test Suite & Validation (0.5h)
1. Run GraphRAG-specific tests
2. Run integration tests
3. Verify deprecation warnings appear correctly
4. Check no import errors

---

## Testing Strategy

### Test Categories

1. **Backward Compatibility Tests**
   - Import deprecated classes → verify DeprecationWarning
   - Use deprecated classes → verify functionality works
   - Ensure old code doesn't break

2. **Unified Processor Tests**
   - Test all 8 phases of pipeline
   - Async functionality
   - IPLD integration
   - Web archiving

3. **Integration Tests**
   - GraphRAGIntegration + UnifiedGraphRAG
   - NeurosymbolicGraphRAG + UnifiedGraphRAG
   - Adapter + UnifiedGraphRAG

4. **Import Update Tests**
   - Verify all updated imports work
   - No circular dependencies
   - Correct module resolution

### Test Files to Update

```
tests/unit/test_graphrag_*.py
tests/unit/processors/test_graphrag_consolidation.py
tests/unit/test_stubs_from_gherkin/test_graphrag_*.py
tests/finance_dashboard/test_graphrag_analysis.py
```

---

## Migration Guide Preview

### For Users

**If you're using GraphRAGProcessor:**
```python
# OLD - deprecated (still works with warning)
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
processor = GraphRAGProcessor(vector_store=vs, knowledge_graph=kg)
result = processor.query("search query")

# NEW - unified implementation
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.processors.graphrag.unified_graphrag import GraphRAGConfiguration

config = GraphRAGConfiguration(processing_mode="balanced")
processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_query("search query")
```

**If you're using WebsiteGraphRAGProcessor:**
```python
# OLD - deprecated (still works with warning)
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
processor = WebsiteGraphRAGProcessor()
result = await processor.process_website("https://example.com")

# NEW - unified implementation
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.processors.graphrag.unified_graphrag import GraphRAGConfiguration

config = GraphRAGConfiguration(enable_web_archiving=True)
processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_website("https://example.com")
```

### For Internal Code

Update imports in 25+ files:
```python
# OLD
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor

# NEW
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration,
    GraphRAGResult
)
```

---

## Success Metrics

### Code Reduction
- **Target:** Remove/deprecate ~2,100-2,300 duplicate lines (62-67% reduction)
- **Current:** Deprecation warnings in place for 3 main files
- **Goal:** Full consolidation with backward compatibility

### Functionality Preservation
- ✅ All features from 7 implementations available in unified processor
- ✅ Specialized layers (LLM, logic) remain functional
- ✅ Async-first architecture maintained
- ✅ IPLD integration preserved

### Quality Metrics
- [ ] All existing tests pass
- [ ] Deprecation warnings appear correctly
- [ ] No new import errors
- [ ] Documentation updated and complete

### User Impact
- [ ] Clear migration guide available
- [ ] Backward compatibility maintained (6-month deprecation period)
- [ ] No breaking changes in v1.x
- [ ] Improved API consistency

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking user code | HIGH | Maintain backward compatibility with warnings |
| Import circular dependencies | MEDIUM | Careful refactoring, lazy imports where needed |
| Test failures | MEDIUM | Incremental updates, run tests frequently |
| Missing functionality | LOW | Comprehensive audit already completed |

---

## Timeline

**Phase 3 (Analysis & Docs):** 1-2 hours
- ✅ Task 3.1: Audit complete (done)
- ⏳ Task 3.2: Migration guide (1h)
- ⏳ Task 3.3: Architecture docs (0.5h)

**Phase 4 (Implementation):** 3-4 hours
- Task 4.1: Verify/update shims (0.5h)
- Task 4.2: Package exports (0.5h)
- Task 4.3: Update imports (1-2h)
- Task 4.4: Consolidate files (1h)
- Task 4.5: Update tests (0.5-1h)
- Task 4.6: Validation (0.5h)

**Total Estimated:** 4-6 hours

---

## Next Steps

1. ✅ Complete Phase 3, Task 3.1 (GraphRAG Audit) - DONE
2. ⏳ Create migration documentation (Task 3.2)
3. ⏳ Update architecture documentation (Task 3.3)
4. ⏳ Begin Phase 4 implementation tasks

---

## Related Documents

- `PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md` - Overall integration plan
- `IMPLEMENTATION_ROADMAP_STATUS.md` - Phases 1-2 status
- `MULTIMEDIA_MIGRATION_GUIDE.md` - Similar migration example
- `PHASE_2_SERIALIZATION_COMPLETE.md` - Previous phase report

---

**Status:** Phase 3 in progress  
**Progress:** 3.1 complete, 3.2-3.3 pending  
**Overall Progress:** 5/30 tasks (17%), 6h/154h spent  
**Next Task:** Create GRAPHRAG_CONSOLIDATION_GUIDE.md
