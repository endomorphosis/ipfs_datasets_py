# Processors Archive Index

**Created:** February 16, 2026  
**Purpose:** Track archived processor files and their history  
**Location:** `docs/archive/processors/`

---

## Overview

This directory contains obsolete processor files that were part of previous implementation phases. These files are preserved for historical reference but are no longer part of the active codebase.

---

## Archived Files

### From processors/graphrag/ (February 16, 2026)

#### complete_advanced_graphrag.py (49,499 bytes)

**Original Purpose:**  
Complete advanced GraphRAG website processing system integrating all advanced components (web archiving, media processing, knowledge extraction, performance optimization).

**Why Archived:**
- Obsolete integration file from earlier development phases
- Functionality superseded by `processors/specialized/graphrag/` modules
- Was importing deprecated classes (ArchivingConfig, ArchiveCollection)
- Still referenced by `dashboards/advanced_analytics_dashboard.py` - needs migration

**Archived Date:** February 16, 2026  
**Phase:** Phase 8, Task 8.4 - Archive Obsolete Phase Files

**Original Location:** `ipfs_datasets_py/processors/graphrag/complete_advanced_graphrag.py`  
**Archived Location:** `docs/archive/processors/complete_advanced_graphrag.py`

**Dependencies Still Using:**
- `ipfs_datasets_py/dashboards/advanced_analytics_dashboard.py` (line 39)

**Migration Path:**
Replace imports with specialized/graphrag modules:
```python
# OLD:
from ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag import CompleteGraphRAGSystem

# NEW:
from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.processors.specialized.web_archive import AdvancedWebArchiver
from ipfs_datasets_py.processors.specialized.media import AdvancedMediaProcessor
```

---

#### enhanced_integration.py (33,412 bytes)

**Original Purpose:**  
Enhanced GraphRAG integration with advanced features and multi-pass processing.

**Why Archived:**
- Phase completion marker from earlier refactoring
- Functionality integrated into `processors/specialized/graphrag/integration.py`
- No longer needed as standalone file

**Archived Date:** February 16, 2026  
**Phase:** Phase 8, Task 8.4 - Archive Obsolete Phase Files

**Original Location:** `ipfs_datasets_py/processors/graphrag/enhanced_integration.py`  
**Archived Location:** `docs/archive/processors/enhanced_integration.py`

**Dependencies Still Using:**
- `ipfs_datasets_py/logic/integrations/enhanced_graphrag_integration.py` (compatibility shim)

**Migration Path:**
```python
# OLD:
from ipfs_datasets_py.processors.graphrag.enhanced_integration import *

# NEW:
from ipfs_datasets_py.processors.specialized.graphrag.integration import GraphRAGIntegration
```

---

#### phase7_complete_integration.py (46,219 bytes)

**Original Purpose:**  
Phase 7 complete integration marker - consolidated all processor components.

**Why Archived:**
- Phase completion marker file
- Part of processors refactoring Phases 1-7 (completed February 16, 2026)
- Contains integration code that has been superseded by final implementations
- Historical artifact documenting Phase 7 completion

**Archived Date:** February 16, 2026  
**Phase:** Phase 8, Task 8.4 - Archive Obsolete Phase Files

**Original Location:** `ipfs_datasets_py/processors/graphrag/phase7_complete_integration.py`  
**Archived Location:** `docs/archive/processors/phase7_complete_integration.py`

**Dependencies Still Using:**
- `ipfs_datasets_py/logic/integrations/phase7_complete_integration.py` (compatibility shim)

**Migration Path:**
```python
# OLD:
from ipfs_datasets_py.processors.graphrag.phase7_complete_integration import *

# NEW:
from ipfs_datasets_py.processors.specialized.graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGIntegration,
    WebsiteGraphRAGSystem
)
```

---

## Archive Statistics

| File | Size | Lines | Imports Still Using | Migration Priority |
|------|------|-------|---------------------|-------------------|
| complete_advanced_graphrag.py | 49.5 KB | ~1,200 | 1 (dashboard) | Medium |
| enhanced_integration.py | 33.4 KB | ~800 | 1 (logic shim) | Low |
| phase7_complete_integration.py | 46.2 KB | ~1,100 | 1 (logic shim) | Low |
| **TOTAL** | **129.1 KB** | **~3,100** | **3 files** | |

---

## Impact of Archiving

### Eliminated from Active Codebase
- **129 KB** of obsolete integration code
- **~3,100 lines** removed from processors/graphrag/
- **Complete removal** of processors/graphrag/ folder
- **Zero duplicate files** between old and new locations

### Backward Compatibility
- **3 compatibility shims** still reference archived files
- **Migration required** for:
  - `dashboards/advanced_analytics_dashboard.py`
  - `logic/integrations/enhanced_graphrag_integration.py` 
  - `logic/integrations/phase7_complete_integration.py`

### Next Steps
1. Update dashboard to use specialized/graphrag modules
2. Update logic/integrations shims to point to new locations
3. Verify no other code imports archived files
4. Document migration in PROCESSORS_MIGRATION_GUIDE.md

---

## Related Documentation

- **PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md** - Full refactoring plan
- **PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md** - Quick reference guide
- **PROCESSORS_ROOT_FILES_INVENTORY_2026.md** - Root files inventory
- **PROCESSORS_PHASES_6_7_COMPLETE.md** - Phase 7 completion documentation
- **PROCESSORS_STATUS_2026_02_16.md** - Overall status before Phase 8

---

## Accessing Archived Files

All archived files are available in the git history and in this archive directory for historical reference. To view or restore:

```bash
# View archived file
cat docs/archive/processors/complete_advanced_graphrag.py

# View git history
git log --all --full-history -- ipfs_datasets_py/processors/graphrag/complete_advanced_graphrag.py

# Restore if needed (not recommended)
git show HEAD~1:ipfs_datasets_py/processors/graphrag/complete_advanced_graphrag.py > temp_restore.py
```

---

## Archive Maintenance

This archive is **read-only**. Files in this directory should not be modified. For current processor code, see:
- `ipfs_datasets_py/processors/specialized/graphrag/`
- `ipfs_datasets_py/processors/specialized/pdf/`
- `ipfs_datasets_py/processors/specialized/multimodal/`
- `ipfs_datasets_py/processors/engines/`

**Last Updated:** February 16, 2026  
**Maintained By:** Processors Refactoring Team
