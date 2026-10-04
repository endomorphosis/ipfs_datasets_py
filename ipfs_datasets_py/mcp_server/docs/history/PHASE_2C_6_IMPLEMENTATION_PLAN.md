# Phase 2C-6 Implementation Plan

## Executive Summary

**Current Status:** 45% complete (Phases 1, 2A, 2B, and 3 done)  
**Remaining Work:** Phases 2C, 2D, 4, 5, 6  
**Estimated Time:** 30-42 hours  
**Next Action:** Phase 2C.1 - Refactor deontological_reasoning_tools.py

## Key Discovery

**Phase 3 (Enhanced Tool Nesting) is already complete!**
- HierarchicalToolManager exists (510 lines)
- 4 meta-tools provide 99% context window reduction
- Already integrated in server.py
- Production-ready and functional

## Phase 2C: Thick Tool Refactoring

### Tool 1: deontological_reasoning_tools.py ⭐ STARTING NEXT
- **Current:** 594 lines, 17 functions
- **Target:** <100 lines (83% reduction)
- **Extract to:** `ipfs_datasets_py/logic/deontic/analyzer.py`

### Tool 2: relationship_timeline_tools.py
- **Current:** 971 lines
- **Target:** <150 lines (85% reduction)
- **Extract to:** `ipfs_datasets_py/processors/relationships/`

### Tool 3: cache_tools.py
- **Current:** 709 lines
- **Target:** <150 lines (79% reduction)
- **Extract to:** `ipfs_datasets_py/caching/`

## Timeline

| Phase | Est. Time | Status |
|-------|-----------|--------|
| 1 | 6 hours | ✅ COMPLETE |
| 2A | 4 hours | ✅ COMPLETE |
| 2B | 3 hours | ✅ COMPLETE |
| 3 | - | ✅ ALREADY DONE |
| 2C | 11-15 hours | 🔄 NEXT |
| 2D | 4-6 hours | ⏳ PLANNED |
| 4 | 6-8 hours | ⏳ PLANNED |
| 5 | 3-4 hours | ⏳ PLANNED |
| 6 | 4-6 hours | ⏳ PLANNED |
| **TOTAL** | **41-52 hours** | **45% done** |

## Success Metrics

**Completed:**
- ✅ 85% root file reduction
- ✅ 188 stub files deleted
- ✅ Tool patterns documented
- ✅ Templates created
- ✅ Nested structure (99% context reduction)

**Remaining:**
- ⏳ 3 thick tools refactored
- ⏳ Testing infrastructure
- ⏳ CLI-MCP alignment
- ⏳ API documentation
- ⏳ Final validation

---
**Created:** 2026-02-18  
**Status:** Ready to execute
