# Processors Refactoring Quick Reference

**Last Updated:** 2026-02-15  
**Status:** PLANNING PHASE  

This is a quick reference for the comprehensive processors refactoring. For full details, see [PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md](./PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md).

---

## TL;DR

**Goal:** Consolidate 32 root-level processor files and improve organization of 633 files across the processors directory.

**Timeline:** 10 weeks, ~140 hours  
**Priority:** HIGH - Code Quality & Architecture  

---

## Current Problems

| Problem | Impact | Files Affected |
|---------|--------|----------------|
| **Duplicate implementations** | 30-40% code duplication | 20+ files |
| **Poor organization** | Hard to find processors | 32 root files |
| **GraphRAG fragmentation** | 10+ implementations of same functionality | 10 files |
| **Legacy artifacts** | Clutter, confusion | 150+ stub files |
| **Test gaps** | 84% pass rate (should be 95%+) | All processors |

---

## Major Consolidations

### 1. GraphRAG (10 files → 3-4 files)

**Current:**
- `graphrag_processor.py` (ROOT)
- `graphrag_integrator.py` (ROOT)
- `website_graphrag_processor.py` (ROOT)
- `advanced_graphrag_website_processor.py` (ROOT)
- `graphrag/unified_graphrag.py`
- `graphrag/integration.py`
- `graphrag/website_system.py`
- `graphrag/complete_advanced_graphrag.py`
- `graphrag/extract.py`
- `graphrag/query.py`

**Target:**
```
specialized/graphrag/
├── unified_processor.py  # Main processor (all features)
├── integration.py        # Integration utilities
├── website_system.py     # Website-specific
└── utils.py             # Shared utilities
```

### 2. PDF Processing (2 files → 1)

**Current:**
- `pdf_processor.py` (ROOT)
- `pdf_processing.py` (ROOT)

**Target:**
```
specialized/pdf/
└── processor.py  # Consolidated
```

### 3. Multimodal (2 files → 1)

**Current:**
- `multimodal_processor.py` (ROOT)
- `enhanced_multimodal_processor.py` (ROOT)

**Target:**
```
specialized/multimodal/
└── processor.py  # Use enhanced as base
```

### 4. Batch Processing (3+ files → 1)

**Current:**
- `batch_processor.py` (ROOT)
- `file_converter/batch_processor.py`
- `multimedia/omni_converter_mk2/batch_processor/`

**Target:**
```
specialized/batch/
├── processor.py
├── parallel_executor.py
└── queue_manager.py
```

### 5. Infrastructure (6 files)

**Move from ROOT to infrastructure/:**
- `caching.py`
- `monitoring.py`
- `error_handling.py`
- `profiling.py`
- `debug_tools.py`
- `cli.py`

### 6. Core Duplicates (Remove from ROOT)

**Duplicates to remove:**
- `protocol.py` → Use `core/protocol.py`
- `registry.py` → Use `core/processor_registry.py`

---

## Target Directory Structure

```
processors/
├── core/                    # Core protocol & routing ✅
├── adapters/                # Processor adapters ✅
├── specialized/             # NEW: Specialized processors
│   ├── pdf/
│   ├── graphrag/
│   ├── batch/
│   └── multimodal/
├── domains/                 # NEW: Domain-specific
│   ├── legal/              # Moved from legal_scrapers/
│   ├── patent/             # Patent processing
│   └── geospatial/         # Geospatial analysis
├── infrastructure/          # NEW: Cross-cutting concerns
│   ├── caching.py
│   ├── monitoring.py
│   ├── error_handling.py
│   ├── profiling.py
│   ├── debug_tools.py
│   └── cli.py
├── file_converter/          # ✅ Keep as-is
├── multimedia/              # Review (100+ files in subsystem)
├── storage/                 # ✅ IPLD storage
├── serialization/           # ✅ Data serialization
├── ipfs/                    # ✅ IPFS utilities
├── auth/                    # ✅ Authentication
└── wikipedia_x/             # ✅ Wikipedia integration
```

---

## Import Changes

### Old → New Mappings

```python
# Core
OLD: from processors.protocol import ProcessorProtocol
NEW: from processors.core.protocol import ProcessorProtocol

# GraphRAG
OLD: from processors.graphrag_processor import GraphRAGProcessor
NEW: from processors.specialized.graphrag import GraphRAGProcessor

# PDF
OLD: from processors.pdf_processor import PDFProcessor
NEW: from processors.specialized.pdf import PDFProcessor

# Multimodal
OLD: from processors.multimodal_processor import MultimodalProcessor
NEW: from processors.specialized.multimodal import MultimodalProcessor

# Batch
OLD: from processors.batch_processor import BatchProcessor
NEW: from processors.specialized.batch import BatchProcessor

# Infrastructure
OLD: from processors.caching import CacheManager
NEW: from processors.infrastructure.caching import CacheManager

# Domains
OLD: from processors.patent_dataset_api import PatentDatasetAPI
NEW: from processors.domains.patent import PatentDatasetAPI
```

---

## Implementation Phases

| Phase | Time | Focus | Status |
|-------|------|-------|--------|
| **1. Analysis** | 8h | Audit directory, identify duplicates | ✅ COMPLETE |
| **2. Core Consolidation** | 20h | GraphRAG, PDF, multimodal, protocol | ⏳ NEXT |
| **3. Infrastructure** | 16h | Move cross-cutting concerns | ⏳ PENDING |
| **4. Batch Processing** | 12h | Consolidate batch implementations | ⏳ PENDING |
| **5. Stub Cleanup** | 8h | Remove/archive 150+ stubs | ⏳ PENDING |
| **6. Domain Organization** | 12h | Move domain-specific code | ⏳ PENDING |
| **7. Multimedia Review** | 16h | Review/document large subsystem | ⏳ PENDING |
| **8. Testing** | 24h | Comprehensive testing | ⏳ PENDING |
| **9. Documentation** | 16h | Update all docs | ⏳ PENDING |
| **10. Final Cleanup** | 8h | Validation & release | ⏳ PENDING |
| **TOTAL** | **140h** | **10 weeks** | |

---

## Success Metrics

### Code Quality
- [ ] Root files: 32 → 1
- [ ] GraphRAG files: 10 → 3-4
- [ ] Stub files: 150+ → 0
- [ ] Test pass rate: 84% → 95%+
- [ ] Code coverage: → 90%+
- [ ] Code duplication: -30-40%

### Organization
- [ ] Clear directory structure
- [ ] All processors have adapters
- [ ] Domain-specific code separated
- [ ] Infrastructure code organized

### Documentation
- [ ] Architecture docs updated
- [ ] Migration guide created
- [ ] API docs updated
- [ ] Developer guide created

---

## Backward Compatibility

**Strategy:**
- 6-month deprecation period (until v2.0.0, August 2026)
- All old imports work with warnings
- Clear migration messages
- No breaking changes during grace period

**Example Warning:**
```
DeprecationWarning: processors.graphrag_processor is deprecated.
Use processors.specialized.graphrag instead.
This import will be removed in v2.0.0 (August 2026).
```

---

## Quick Start for Phase 2 (Next)

### Step 1: Remove Core Duplicates (4 hours)

```bash
# Create deprecation shims
echo "# DEPRECATED: Use processors.core.protocol" > processors/protocol.py
echo "# DEPRECATED: Use processors.core.processor_registry" > processors/registry.py

# Update imports across codebase
grep -r "from processors.protocol import" .
grep -r "from processors.registry import" .
```

### Step 2: Consolidate GraphRAG (10 hours)

```bash
# Create specialized directory
mkdir -p processors/specialized/graphrag

# Use unified_graphrag.py as base
cp processors/graphrag/unified_graphrag.py processors/specialized/graphrag/unified_processor.py

# Merge features from other implementations
# Create deprecation shims for old imports
```

### Step 3: Consolidate PDF (3 hours)

```bash
# Create specialized directory
mkdir -p processors/specialized/pdf

# Merge both implementations
# Create deprecation shims
```

### Step 4: Test Everything (3 hours)

```bash
# Run tests
pytest tests/unit/processors/
pytest tests/integration/

# Check deprecation warnings work
python -W default::DeprecationWarning -c "from processors.protocol import ProcessorProtocol"
```

---

## Key Files

### Documentation
- [COMPREHENSIVE PLAN](./PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md) - Full 36KB plan
- [QUICK REFERENCE](./PROCESSORS_REFACTORING_QUICK_REFERENCE.md) - This file
- [INTEGRATION PLAN](./PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md) - Data transformation migration (complete)

### Code
- `processors/core/` - Core protocol & routing
- `processors/adapters/` - Processor adapters
- `processors/graphrag/` - GraphRAG implementations (to consolidate)
- `processors/multimedia/` - Media processing (review needed)

---

## Next Actions

1. ✅ Complete analysis (Phase 1)
2. ⏳ Review and approve plan
3. ⏳ Start Phase 2: Core Consolidation
4. ⏳ Create tracking issues for each phase

---

## Questions?

- See full plan: [PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md](./PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md)
- Check CLAUDE.md for worker assignments
- Review existing documentation in `docs/`

---

**Status:** Ready for Phase 2 implementation  
**Updated:** 2026-02-15  
**Owner:** Development Team
