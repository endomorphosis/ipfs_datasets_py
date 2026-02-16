# Phase 2 Task 2.2: Usage Analysis Report

**Date:** 2026-02-16  
**Status:** Complete  
**Phase:** Knowledge Graphs Refactoring - Phase 2 (Lineage Migration)

---

## Executive Summary

This report documents the analysis of all internal imports of the legacy `cross_document_lineage` modules, providing a complete migration roadmap for updating these imports to the new `lineage` package.

**Key Findings:**
- **3 modules** contain imports from legacy lineage files
- **5 total import statements** found
- **3 different import patterns** identified
- **Low migration risk** - all changes are straightforward

---

## Import Locations Found

### 1. Audit Module
**File:** `ipfs_datasets_py/audit/audit_provenance_integration.py`  
**Line:** 58  
**Current Import:**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker
```

**New Import:**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
```

**Impact:** Low - Single import, straightforward replacement  
**Usage:** Used in audit-provenance integration for cross-document lineage tracking  
**Dependencies:** None - standalone import  

---

### 2. Analytics Module
**File:** `ipfs_datasets_py/analytics/data_provenance_enhanced.py`  
**Lines:** 4169, 5990  

**Import 1 (Line 4169):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker
```

**Import 2 (Line 5990):**
```python
from ipfs_datasets_py.cross_document_lineage_enhanced import CrossDocumentLineageEnhancer, DetailedLineageIntegrator
```

**New Imports:**
```python
# Line 4169
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker

# Line 5990
from ipfs_datasets_py.knowledge_graphs.lineage import CrossDocumentLineageEnhancer, DetailedLineageIntegrator
```

**Impact:** Medium - Two imports, one is in a try-except block  
**Usage:** Dynamic import in `create_cross_document_lineage()` method  
**Dependencies:** Both imports are within try-except blocks for graceful degradation  

---

### 3. Dashboard Module
**File:** `ipfs_datasets_py/dashboards/provenance_dashboard.py`  
**Lines:** 57, 1299  

**Import 1 (Line 57):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker
```

**Import 2 (Line 1299):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker
```

**New Imports:**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
```

**Impact:** Low - Two identical imports, both straightforward replacements  
**Usage:** One at module level, one dynamic import within method  
**Dependencies:** Second import is within try-except block  

---

## Migration Summary

### Import Patterns

| Pattern | Count | Modules |
|---------|-------|---------|
| `from ...cross_document_lineage import EnhancedLineageTracker` | 4 | audit, analytics (2x), dashboard (2x) |
| `from ...cross_document_lineage_enhanced import ...` | 1 | analytics |
| **Total** | **5** | **3 modules** |

### Classes Imported

| Class | Count | Source Module |
|-------|-------|---------------|
| `EnhancedLineageTracker` | 4 | cross_document_lineage.py |
| `CrossDocumentLineageEnhancer` | 1 | cross_document_lineage_enhanced.py |
| `DetailedLineageIntegrator` | 1 | cross_document_lineage_enhanced.py |

---

## Migration Strategy

### Phase 1: Update Imports ✅
1. Update audit module (1 import)
2. Update analytics module (2 imports)
3. Update dashboard module (2 imports)

### Phase 2: Testing
1. Run unit tests for each updated module
2. Verify deprecation warnings are triggered
3. Test integration with lineage package

### Phase 3: Validation
1. Verify no breaking changes
2. Check all affected functionality works
3. Confirm backward compatibility maintained

---

## Risk Assessment

### Risk Level: **LOW** ✅

**Reasons:**
1. ✅ All imports are straightforward replacements
2. ✅ New lineage package has full backward compatibility
3. ✅ Deprecation warnings provide safety net
4. ✅ Limited number of affected modules (3)
5. ✅ Most imports are in try-except blocks

### Potential Issues

**Issue 1: Dynamic Imports**
- **Description:** 3 of 5 imports are dynamic (within functions)
- **Mitigation:** Already in try-except blocks, graceful degradation
- **Status:** No action needed ✅

**Issue 2: Module Not Found**
- **Description:** If old modules removed before imports updated
- **Mitigation:** Deprecation wrappers provide backward compatibility
- **Status:** Protected ✅

---

## Testing Requirements

### Unit Tests
- [ ] Test audit module with new import
- [ ] Test analytics module with new imports
- [ ] Test dashboard module with new imports

### Integration Tests
- [ ] Test cross-document lineage tracking
- [ ] Test audit-provenance integration
- [ ] Test provenance dashboard visualization

### Regression Tests
- [ ] Verify no functionality breaks
- [ ] Check performance unchanged
- [ ] Validate error handling intact

---

## Implementation Timeline

**Estimated Time:** 1 hour

| Task | Duration | Status |
|------|----------|--------|
| Update audit import | 5 min | ⏳ Pending |
| Update analytics imports | 10 min | ⏳ Pending |
| Update dashboard imports | 10 min | ⏳ Pending |
| Run unit tests | 15 min | ⏳ Pending |
| Verify integration | 10 min | ⏳ Pending |
| Documentation | 10 min | ✅ Complete |

---

## Migration Checklist

### Pre-Migration
- [x] Identify all legacy imports (5 found)
- [x] Analyze import patterns
- [x] Assess risk level (LOW)
- [x] Document migration strategy

### Migration
- [ ] Update import in audit_provenance_integration.py (Line 58)
- [ ] Update import in data_provenance_enhanced.py (Line 4169)
- [ ] Update import in data_provenance_enhanced.py (Line 5990)
- [ ] Update import in provenance_dashboard.py (Line 57)
- [ ] Update import in provenance_dashboard.py (Line 1299)

### Post-Migration
- [ ] Run tests for audit module
- [ ] Run tests for analytics module
- [ ] Run tests for dashboard module
- [ ] Verify deprecation warnings work
- [ ] Update migration guide with results

---

## Conclusion

The migration from legacy `cross_document_lineage` modules to the new `lineage` package is straightforward and low-risk. All 5 imports can be updated with simple find-replace operations, and the deprecation wrappers provide a safety net for backward compatibility.

**Recommendation:** Proceed with migration in Session 8.

---

**Report prepared by:** GitHub Copilot Agent  
**Review status:** Ready for implementation  
**Next action:** Proceed to Phase 2 Task 2.3 (Update Imports)
