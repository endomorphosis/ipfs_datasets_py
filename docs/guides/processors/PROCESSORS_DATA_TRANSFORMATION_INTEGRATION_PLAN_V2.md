# Comprehensive Processors & Data Transformation Integration Plan V2

**Created:** 2026-02-15  
**Status:** PLANNING  
**Priority:** HIGH - Architectural Consolidation  
**Timeline:** 4-6 weeks  
**Goal:** Merge `data_transformation/` into `processors/` and deprecate `data_transformation/`

---

## Executive Summary

This document provides a comprehensive refactoring, improvement, and integration plan to:
1. **Consolidate** all data transformation functionality into the `processors/` directory
2. **Deprecate** the `data_transformation/` directory with a 6-month migration window
3. **Maintain** 100% backward compatibility during migration
4. **Improve** code organization and reduce duplication

### Current State

**Processors Directory** (`ipfs_datasets_py/processors/`)
- 138+ Python files, ~82KB production code
- Unified ProcessorProtocol architecture
- 8 operational adapters with priority-based routing
- Specialized processors: PDF, GraphRAG, multimedia, file conversion, legal scrapers
- 129+ tests (84% pass rate)

**Data Transformation Directory** (`ipfs_datasets_py/data_transformation/`)
- IPLD storage and knowledge graphs (`ipld/`)
- Serialization utilities (`serialization/`)
- Multimedia processing (`multimedia/` - already migrated to processors)
- IPFS formats (`ipfs_formats/`)
- UCAN and UnixFS utilities
- **91 files across the codebase** import from this directory

### Key Findings

1. **Serialization already partially organized**: `data_transformation/serialization/` exists with 4 files
2. **Multimedia already migrated**: Core files moved to `processors/multimedia/`
3. **IPLD heavily used**: 4 processor files depend on IPLDStorage
4. **Duplication exists**: Some files exist in both root data_transformation/ and serialization/
5. **Clear migration path**: Most functionality fits naturally into processors/

---

## Table of Contents

1. [Architectural Vision](#architectural-vision)
2. [Migration Strategy](#migration-strategy)
3. [Detailed Implementation Plan](#detailed-implementation-plan)
4. [Backward Compatibility](#backward-compatibility)
5. [Testing Strategy](#testing-strategy)
6. [Timeline and Phases](#timeline-and-phases)
7. [Success Metrics](#success-metrics)
8. [Risk Mitigation](#risk-mitigation)

---

## Architectural Vision

### Target Directory Structure

```
processors/
├── core/                          # Core protocol & routing (existing)
├── adapters/                      # Processor adapters (existing)
├── file_converter/                # File conversion (existing)
├── graphrag/                      # GraphRAG (existing)
├── multimedia/                    # Multimedia processing (existing, migrated)
├── legal_scrapers/                # Legal document scraping (existing)
├── storage/                       # NEW: IPLD storage and knowledge graphs
│   ├── __init__.py
│   ├── ipld/                      # MOVED from data_transformation/ipld/
│   │   ├── storage.py            # IPLDStorage class
│   │   ├── dag_pb.py             # DAG-PB implementation
│   │   ├── optimized_codec.py    # High-performance encoding/decoding
│   │   ├── vector_store.py       # IPLD-based vector storage
│   │   └── knowledge_graph.py    # IPLD-based knowledge graph
├── serialization/                 # CONSOLIDATED: All serialization
│   ├── __init__.py
│   ├── car_conversion.py         # CAR file conversions
│   ├── dataset_serialization.py  # Dataset serialization
│   ├── ipfs_parquet_to_car.py    # Parquet → CAR conversion
│   └── jsonl_to_parquet.py       # JSONL → Parquet conversion
├── ipfs/                          # NEW: IPFS-specific utilities
│   ├── __init__.py
│   ├── formats/                   # MOVED from data_transformation/ipfs_formats/
│   │   └── multiformats.py       # Multiformats handling
│   └── unixfs.py                  # MOVED from data_transformation/unixfs.py
├── auth/                          # NEW: Authentication & authorization
│   ├── __init__.py
│   └── ucan.py                    # MOVED from data_transformation/ucan.py
└── [existing specialized processors]

data_transformation/               # DEPRECATED (removal in v2.0.0, Aug 2026)
├── __init__.py                    # Deprecation warnings + shims
├── ipld/ → processors/storage/ipld/    # Shim with warnings
├── serialization/ → processors/serialization/  # Shim with warnings
├── ipfs_formats/ → processors/ipfs/formats/    # Shim with warnings
├── ucan.py → processors/auth/ucan.py           # Shim with warnings
└── unixfs.py → processors/ipfs/unixfs.py       # Shim with warnings
```

### Design Principles

1. **Single Source of Truth**: All data processing in `processors/`
2. **Logical Organization**: Group by functionality (storage, serialization, auth, ipfs)
3. **Backward Compatibility**: 6-month deprecation window with working shims
4. **Zero Breaking Changes**: All existing imports continue to work
5. **Clear Migration Path**: Easy to update imports progressively

---

## Migration Strategy

### Phase-Based Approach

**Phase 1: IPLD Storage Integration** (Week 1, 8 hours)
- Move `data_transformation/ipld/` → `processors/storage/ipld/`
- Create backward compatibility shims in `data_transformation/ipld/`
- Update 4 processor files that import IPLDStorage
- Add deprecation warnings
- Test all IPLD functionality

**Phase 2: Serialization Consolidation** (Week 1-2, 10 hours)
- Consolidate `data_transformation/serialization/` into `processors/serialization/`
- Remove duplicate files from root `data_transformation/`
- Update imports across codebase
- Add deprecation warnings
- Test serialization functionality

**Phase 3: IPFS Utilities Integration** (Week 2, 6 hours)
- Move `data_transformation/ipfs_formats/` → `processors/ipfs/formats/`
- Move `data_transformation/unixfs.py` → `processors/ipfs/unixfs.py`
- Create backward compatibility shims
- Update imports in legal_scrapers
- Test IPFS functionality

**Phase 4: Authentication Integration** (Week 2, 4 hours)
- Move `data_transformation/ucan.py` → `processors/auth/ucan.py`
- Create backward compatibility shim
- Update imports if any
- Test UCAN functionality

**Phase 5: Multimedia Cleanup** (Week 3, 4 hours)
- Verify multimedia/ migration is complete
- Remove duplicate multimedia/ from data_transformation/
- Update any remaining references
- Clean up old deprecation shims

**Phase 6: Documentation** (Week 3, 8 hours)
- Create comprehensive migration guide
- Update README.md with new structure
- Create user migration checklist
- Update DEPRECATION_TIMELINE.md
- Add import examples

**Phase 7: Testing & Validation** (Week 4, 12 hours)
- Run full test suite (182+ tests)
- Verify all backward compatibility shims
- Test all import paths (new and deprecated)
- Validate processor functionality
- Performance testing
- Security scanning

**Phase 8: Final Cleanup** (Week 4, 6 hours)
- Mark data_transformation/ for deprecation in v2.0.0
- Update __init__.py exports
- Final validation
- Documentation review
- Release preparation

### Total Estimated Time: 58 hours over 4 weeks

---

## Detailed Implementation Plan

### Phase 1: IPLD Storage Integration

#### Tasks

**1.1 Create processors/storage/ Package** (1 hour)
```bash
mkdir -p ipfs_datasets_py/processors/storage/ipld
touch ipfs_datasets_py/processors/storage/__init__.py
touch ipfs_datasets_py/processors/storage/ipld/__init__.py
```

**1.2 Move IPLD Files** (2 hours)
```bash
# Move files
mv ipfs_datasets_py/data_transformation/ipld/*.py ipfs_datasets_py/processors/storage/ipld/
mv ipfs_datasets_py/data_transformation/ipld/*.md ipfs_datasets_py/processors/storage/ipld/

# Update imports within IPLD files
# Change: from ipfs_datasets_py.data_transformation.ipld import ...
# To: from ipfs_datasets_py.processors.storage.ipld import ...
```

**1.3 Create Backward Compatibility Shims** (1 hour)
```python
# ipfs_datasets_py/data_transformation/ipld/__init__.py
import warnings
from ipfs_datasets_py.processors.storage.ipld import (
    IPLDStorage,
    KnowledgeGraph,
    VectorStore,
    DAGPBCodec,
    OptimizedCodec
)

warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.ipld' is deprecated. "
    "Use 'ipfs_datasets_py.processors.storage.ipld' instead. "
    "This import path will be removed in v2.0.0 (August 2026).",
    DeprecationWarning,
    stacklevel=2
)

__all__ = ['IPLDStorage', 'KnowledgeGraph', 'VectorStore', 'DAGPBCodec', 'OptimizedCodec']
```

**1.4 Update Processor Imports** (2 hours)
```python
# Files to update:
# - ipfs_datasets_py/processors/batch_processor.py
# - ipfs_datasets_py/processors/pdf_processor.py
# - ipfs_datasets_py/processors/query_engine.py
# - ipfs_datasets_py/processors/graphrag_integrator.py

# Change:
# from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
# To:
# from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
```

**1.5 Update Main Package Exports** (1 hour)
```python
# ipfs_datasets_py/__init__.py
# Add new exports
from .processors.storage.ipld import IPLDStorage, KnowledgeGraph, VectorStore
```

**1.6 Testing** (1 hour)
- Test IPLDStorage functionality
- Test backward compatibility imports
- Verify deprecation warnings appear
- Run existing IPLD tests

---

### Phase 2: Serialization Consolidation

#### Tasks

**2.1 Analyze Current State** (1 hour)
- Identify duplicate files between root data_transformation/ and serialization/
- Map all imports of serialization functionality
- Document which files need updates

Current state:
```
data_transformation/
├── car_conversion.py           # DUPLICATE (19KB)
├── dataset_serialization.py    # DUPLICATE (351KB)
├── ipfs_parquet_to_car.py      # DUPLICATE (3.4KB)
├── jsonl_to_parquet.py         # DUPLICATE (23KB)
└── serialization/
    ├── car_conversion.py       # CANONICAL (should be used)
    ├── dataset_serialization.py # CANONICAL
    ├── ipfs_parquet_to_car.py  # CANONICAL
    └── jsonl_to_parquet.py     # CANONICAL
```

**2.2 Move Serialization to Processors** (2 hours)
```bash
# Create processors/serialization/
mkdir -p ipfs_datasets_py/processors/serialization

# Move canonical files from data_transformation/serialization/
mv ipfs_datasets_py/data_transformation/serialization/*.py ipfs_datasets_py/processors/serialization/
mv ipfs_datasets_py/data_transformation/serialization/__init__.py ipfs_datasets_py/processors/serialization/
```

**2.3 Create Backward Compatibility Shims** (2 hours)
```python
# ipfs_datasets_py/data_transformation/serialization/__init__.py
import warnings
from ipfs_datasets_py.processors.serialization import (
    DataInterchangeUtils,
    DatasetSerializer,
    convert_parquet_to_car,
    convert_jsonl_to_parquet
)

warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.serialization' is deprecated. "
    "Use 'ipfs_datasets_py.processors.serialization' instead. "
    "This import path will be removed in v2.0.0 (August 2026).",
    DeprecationWarning,
    stacklevel=2
)

__all__ = ['DataInterchangeUtils', 'DatasetSerializer', 'convert_parquet_to_car', 'convert_jsonl_to_parquet']

# Also create shims for root-level files
# ipfs_datasets_py/data_transformation/car_conversion.py
import warnings
warnings.warn(..., DeprecationWarning, stacklevel=2)
from ipfs_datasets_py.processors.serialization.car_conversion import *
```

**2.4 Remove Duplicate Files** (1 hour)
```bash
# Keep only shims in root data_transformation/
# Remove duplicate implementations
```

**2.5 Update Imports** (3 hours)
- Search for all imports of serialization modules
- Update to use new processor path
- Test each update

**2.6 Testing** (1 hour)
- Test all serialization functionality
- Verify backward compatibility
- Run existing serialization tests

---

### Phase 3: IPFS Utilities Integration

#### Tasks

**3.1 Create processors/ipfs/ Package** (1 hour)
```bash
mkdir -p ipfs_datasets_py/processors/ipfs/formats
touch ipfs_datasets_py/processors/ipfs/__init__.py
touch ipfs_datasets_py/processors/ipfs/formats/__init__.py
```

**3.2 Move IPFS Formats** (2 hours)
```bash
# Move multiformats
mv ipfs_datasets_py/data_transformation/ipfs_formats/*.py ipfs_datasets_py/processors/ipfs/formats/

# Move unixfs
mv ipfs_datasets_py/data_transformation/unixfs.py ipfs_datasets_py/processors/ipfs/
```

**3.3 Create Backward Compatibility Shims** (1 hour)
```python
# ipfs_datasets_py/data_transformation/ipfs_formats/__init__.py
import warnings
from ipfs_datasets_py.processors.ipfs.formats import get_cid, multiformats

warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.ipfs_formats' is deprecated. "
    "Use 'ipfs_datasets_py.processors.ipfs.formats' instead. "
    "This import path will be removed in v2.0.0 (August 2026).",
    DeprecationWarning,
    stacklevel=2
)
```

**3.4 Update Imports** (1 hour)
- Update legal_scrapers/ files
- Search for other imports

**3.5 Testing** (1 hour)
- Test multiformats functionality
- Test unixfs functionality
- Verify backward compatibility

---

### Phase 4: Authentication Integration

#### Tasks

**4.1 Create processors/auth/ Package** (30 minutes)
```bash
mkdir -p ipfs_datasets_py/processors/auth
touch ipfs_datasets_py/processors/auth/__init__.py
```

**4.2 Move UCAN** (1 hour)
```bash
mv ipfs_datasets_py/data_transformation/ucan.py ipfs_datasets_py/processors/auth/
```

**4.3 Create Backward Compatibility Shim** (30 minutes)
```python
# ipfs_datasets_py/data_transformation/ucan.py
import warnings
from ipfs_datasets_py.processors.auth.ucan import *

warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.ucan' is deprecated. "
    "Use 'ipfs_datasets_py.processors.auth.ucan' instead. "
    "This import path will be removed in v2.0.0 (August 2026).",
    DeprecationWarning,
    stacklevel=2
)
```

**4.4 Update Imports** (1 hour)
- Search for UCAN imports
- Update if any exist

**4.5 Testing** (1 hour)
- Test UCAN functionality
- Verify backward compatibility

---

### Phase 5: Multimedia Cleanup

#### Tasks

**5.1 Verify Migration Status** (1 hour)
- Confirm core multimedia files are in processors/multimedia/
- Check for remaining duplicates in data_transformation/multimedia/
- Verify all imports point to processors/multimedia/

**5.2 Remove Duplicates** (1 hour)
- Remove data_transformation/multimedia/ subdirectories if fully migrated
- Keep shim if needed for backward compatibility

**5.3 Update Documentation** (1 hour)
- Update multimedia migration status
- Document completed migration

**5.4 Testing** (1 hour)
- Test multimedia functionality
- Verify no broken imports

---

### Phase 6: Documentation

#### Tasks

**6.1 Create Migration Guide** (3 hours)
Create `docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md`:
- Overview of changes
- Import path mappings (old → new)
- Step-by-step migration instructions
- Code examples
- Common migration issues and solutions

**6.2 Update Architecture Documentation** (2 hours)
Update `docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md`:
- New directory structure
- Module organization
- Design patterns
- API reference

**6.3 Update README.md** (1 hour)
- Add migration notice
- Update import examples
- Link to migration guide

**6.4 Update Deprecation Timeline** (1 hour)
Update `docs/DEPRECATION_TIMELINE.md`:
- Add data_transformation/ deprecation schedule
- Migration milestones
- Support timeline

**6.5 Create Quick Reference** (1 hour)
Create import mapping quick reference:
```
OLD: from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
NEW: from ipfs_datasets_py.processors.storage.ipld import IPLDStorage

OLD: from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer
NEW: from ipfs_datasets_py.processors.serialization import DatasetSerializer

... etc
```

---

### Phase 7: Testing & Validation

#### Tasks

**7.1 Unit Tests** (3 hours)
- Run existing test suite (182+ tests)
- Fix any failing tests
- Add new tests for backward compatibility

**7.2 Integration Tests** (3 hours)
- Test processor workflows end-to-end
- Test IPLD storage integration
- Test serialization workflows
- Test multimedia processing

**7.3 Import Path Tests** (2 hours)
- Test all new import paths work
- Test all deprecated import paths work with warnings
- Verify deprecation warnings are raised

**7.4 Performance Tests** (2 hours)
- Benchmark processor routing
- Benchmark IPLD operations
- Ensure no performance regression

**7.5 Security Scanning** (2 hours)
- Run security tools
- Check for vulnerabilities
- Validate secure practices

---

### Phase 8: Final Cleanup

#### Tasks

**8.1 Update Main Package** (2 hours)
```python
# ipfs_datasets_py/__init__.py
# Add exports for new modules
from .processors.storage.ipld import IPLDStorage, KnowledgeGraph, VectorStore
from .processors.serialization import DatasetSerializer, DataInterchangeUtils
from .processors.ipfs.formats import get_cid
from .processors.auth.ucan import UCAN
```

**8.2 Deprecation Warnings** (1 hour)
- Ensure all shims have proper warnings
- Verify stacklevel is correct
- Test warning messages

**8.3 Final Validation** (2 hours)
- Full test suite run
- Manual testing of key workflows
- Documentation review

**8.4 Release Preparation** (1 hour)
- Update CHANGELOG.md
- Prepare release notes
- Tag version

---

## Backward Compatibility

### Strategy

1. **Working Shims**: All old import paths continue to work through Python imports
2. **Deprecation Warnings**: Clear warnings with migration instructions
3. **6-Month Window**: Support old paths until v2.0.0 (August 2026)
4. **Progressive Migration**: Users can migrate at their own pace
5. **Documentation**: Clear migration guide and examples

### Example Shim Pattern

```python
# ipfs_datasets_py/data_transformation/ipld/__init__.py
"""
DEPRECATED: This module has moved to processors.storage.ipld

This import path is deprecated and will be removed in v2.0.0 (August 2026).
Please update your imports:

OLD:
    from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

NEW:
    from ipfs_datasets_py.processors.storage.ipld import IPLDStorage

For more information, see:
    docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md
"""

import warnings

# Import from new location
from ipfs_datasets_py.processors.storage.ipld import (
    IPLDStorage,
    KnowledgeGraph,
    VectorStore,
    DAGPBCodec,
    OptimizedCodec
)

# Issue deprecation warning
warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.ipld' is deprecated. "
    "Use 'ipfs_datasets_py.processors.storage.ipld' instead. "
    "This import path will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md for details.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = ['IPLDStorage', 'KnowledgeGraph', 'VectorStore', 'DAGPBCodec', 'OptimizedCodec']
```

---

## Testing Strategy

### Test Coverage

1. **Unit Tests**: Test individual modules in isolation
2. **Integration Tests**: Test workflows using multiple modules
3. **Import Tests**: Test both old and new import paths
4. **Deprecation Tests**: Verify warnings are raised correctly
5. **Performance Tests**: Ensure no performance regression
6. **Security Tests**: Validate secure practices

### Test Matrix

| Module | Unit Tests | Integration Tests | Import Tests | Notes |
|--------|-----------|------------------|--------------|-------|
| IPLD Storage | ✓ | ✓ | ✓ | Test with processors |
| Serialization | ✓ | ✓ | ✓ | Test CAR, Parquet, JSONL |
| IPFS Formats | ✓ | ✓ | ✓ | Test multiformats |
| UCAN | ✓ | - | ✓ | Auth functionality |
| Multimedia | ✓ | ✓ | ✓ | Verify migration |

### Continuous Integration

- Run full test suite on every commit
- Test on Python 3.12+
- Test on multiple platforms (Linux, macOS, Windows if applicable)
- Test with and without optional dependencies

---

## Timeline and Phases

### Week 1 (16 hours)
- **Days 1-2**: Phase 1 - IPLD Storage Integration (8h)
- **Days 3-4**: Phase 2 - Serialization Consolidation (8h)

### Week 2 (14 hours)
- **Days 1-2**: Phase 2 continued (2h) + Phase 3 - IPFS Utilities (6h)
- **Days 3-4**: Phase 4 - Authentication (4h) + Phase 5 - Multimedia Cleanup (2h)

### Week 3 (12 hours)
- **Days 1-2**: Phase 5 continued (2h) + Phase 6 - Documentation (8h)
- **Days 3-4**: Phase 7 - Testing & Validation (2h)

### Week 4 (16 hours)
- **Days 1-3**: Phase 7 - Testing & Validation continued (10h)
- **Days 4-5**: Phase 8 - Final Cleanup (6h)

**Total: 58 hours over 4 weeks**

### Milestones

- **Week 1 End**: IPLD and Serialization migrated
- **Week 2 End**: All modules migrated with shims
- **Week 3 End**: Documentation complete
- **Week 4 End**: Testing complete, ready for release

---

## Success Metrics

### Code Quality
- [ ] All 182+ tests passing
- [ ] No new linting errors
- [ ] Code coverage maintained or improved
- [ ] No security vulnerabilities introduced

### Functionality
- [ ] All processor functionality works
- [ ] IPLD storage operations work
- [ ] Serialization operations work
- [ ] Multimedia processing works
- [ ] All import paths work (new and deprecated)

### Documentation
- [ ] Migration guide complete
- [ ] Architecture documentation updated
- [ ] README.md updated
- [ ] All code examples updated
- [ ] API documentation current

### User Experience
- [ ] Clear deprecation warnings
- [ ] Easy migration path
- [ ] No breaking changes
- [ ] Performance maintained or improved

### Timeline
- [ ] Complete in 4 weeks (58 hours)
- [ ] No major blockers or delays
- [ ] All phases completed successfully

---

## Risk Mitigation

### Identified Risks

1. **Breaking Existing Code**
   - **Risk**: Import path changes break user code
   - **Mitigation**: Backward compatibility shims for 6 months
   - **Impact**: Low (shims prevent breakage)

2. **Complex Dependencies**
   - **Risk**: Circular dependencies or complex import chains
   - **Mitigation**: Careful analysis before moving files
   - **Impact**: Medium (requires careful planning)

3. **Test Failures**
   - **Risk**: Tests fail after migration
   - **Mitigation**: Comprehensive testing at each phase
   - **Impact**: Medium (can delay progress)

4. **Performance Regression**
   - **Risk**: New structure impacts performance
   - **Mitigation**: Performance benchmarks before and after
   - **Impact**: Low (minimal structural changes)

5. **Documentation Debt**
   - **Risk**: Documentation becomes outdated
   - **Mitigation**: Update docs as part of each phase
   - **Impact**: Low (dedicated documentation phase)

6. **User Confusion**
   - **Risk**: Users unsure how to migrate
   - **Mitigation**: Clear migration guide and examples
   - **Impact**: Low (comprehensive documentation)

### Rollback Plan

If critical issues are discovered:
1. Revert commits to restore previous state
2. Analyze root cause
3. Fix issues
4. Re-attempt migration

---

## Dependencies

### Internal Dependencies
- Existing processor architecture must be stable
- Test infrastructure must be functional
- Documentation tooling must be available

### External Dependencies
- Python 3.12+
- All optional dependencies for testing
- CI/CD infrastructure

### Team Dependencies
- Code review availability
- Testing resources
- Documentation review

---

## Next Steps

1. **Review and Approve Plan** - Get stakeholder buy-in
2. **Begin Phase 1** - Start IPLD storage integration
3. **Regular Progress Updates** - Report after each phase
4. **Adjust as Needed** - Adapt plan based on discoveries

---

## Appendix: Import Path Mappings

### IPLD Storage
```python
# OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
from ipfs_datasets_py.data_transformation.ipld import KnowledgeGraph
from ipfs_datasets_py.data_transformation.ipld import VectorStore

# NEW (current)
from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
from ipfs_datasets_py.processors.storage.ipld import KnowledgeGraph
from ipfs_datasets_py.processors.storage.ipld import VectorStore
```

### Serialization
```python
# OLD (deprecated)
from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer
from ipfs_datasets_py.data_transformation.serialization import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.car_conversion import convert_to_car
from ipfs_datasets_py.data_transformation.jsonl_to_parquet import convert_jsonl

# NEW (current)
from ipfs_datasets_py.processors.serialization import DatasetSerializer
from ipfs_datasets_py.processors.serialization import DataInterchangeUtils
from ipfs_datasets_py.processors.serialization import convert_to_car
from ipfs_datasets_py.processors.serialization import convert_jsonl
```

### IPFS Formats
```python
# OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipfs_formats import get_cid
from ipfs_datasets_py.data_transformation.unixfs import UnixFS

# NEW (current)
from ipfs_datasets_py.processors.ipfs.formats import get_cid
from ipfs_datasets_py.processors.ipfs import UnixFS
```

### Authentication
```python
# OLD (deprecated)
from ipfs_datasets_py.data_transformation.ucan import UCAN

# NEW (current)
from ipfs_datasets_py.processors.auth.ucan import UCAN
```

---

**Document Status:** Draft - Awaiting Approval  
**Next Review:** Before Phase 1 implementation  
**Contacts:** See CLAUDE.md for worker assignments
