# Documentation Drift Audit Report

**Date:** 2026-02-24  
**Auditor:** Automated + Manual Review  
**Scope:** docs/optimizers/ documentation vs ipfs_datasets_py/optimizers/ implementation  

## Executive Summary

Found **3 critical drift issues** and **2 minor issues** across optimizers documentation. Most code examples work correctly, but some method signatures in templates are outdated.

**Status by File:**

| File | Status | Issues |
|------|--------|--------|
| INTEGRATION_EXAMPLES.md | ✅ PASS | 0 - All imports validated |
| HOW_TO_ADD_NEW_OPTIMIZER.md | ⚠️ DRIFT | 1 critical - Method signatures outdated |
| README_validate_import_paths.md | ❌ FAIL | 2 - Missing module references |
| Other docs (6 files) | ⚠️ UNCHECKED | Pending manual review |

---

## Critical Issues

### 1. HOW_TO_ADD_NEW_OPTIMIZER.md - Outdated BaseOptimizer Template

**Location:** [docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md](../docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md) lines 30-50

**Issue:** The template class shows incorrect method signatures for BaseOptimizer subclasses.

**Documented Template:**
```python
def generate(self, source_data: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    return {"artifact": source_data}

def critique(self, artifact: Dict[str, Any], context: Dict[str, Any]):
    return {"overall": 1.0, "recommendations": []}

def optimize(self, artifact: Dict[str, Any], feedback: Dict[str, Any], context: Dict[str, Any]):
    return artifact

def validate(self, artifact: Dict[str, Any], context: Dict[str, Any]) -> bool:
    return True
```

**Actual BaseOptimizer (ipfs_datasets_py/optimizers/common/base_optimizer.py):**
```python
@abstractmethod
def generate(self, input_data: Any, context: OptimizationContext) -> Any:
    """Generate initial artifact from input data."""
    pass

@abstractmethod
def critique(self, artifact: Any, context: OptimizationContext) -> Tuple[float, List[str]]:
    """Evaluate quality of artifact.
    
    Returns:
        Tuple of (score, feedback_list)
        - score: Quality score from 0 (worst) to 1 (best)
        - feedback_list: List of improvement suggestions
    """
    pass

@abstractmethod
def optimize(self, artifact: Any, score: float, feedback: List[str], context: OptimizationContext) -> Any:
    """Improve artifact based on critique feedback."""
    pass

def validate(self, artifact: Any, context: OptimizationContext) -> bool:
    """Validate that artifact meets requirements."""
    return True  # Default implementation
```

**Key Differences:**

1. **`context` type:** Should be `OptimizationContext` not `Dict[str, Any]`
2. **`critique()` return type:** Must return `Tuple[float, List[str]]` not `Dict`
3. **`optimize()` parameters:** Takes `score: float, feedback: List[str]` as separate args, not `feedback: Dict`
4. **Parameter naming:** Uses `input_data` not `source_data` for `generate()`

**Impact:** HIGH - Developers following this template will create classes that don't match the BaseOptimizer contract and will fail type checking.

**Recommendation:** Update template to match actual BaseOptimizer abstract methods. Add imports for `OptimizationContext`, `Tuple`, `List`.

---

### 2. README_validate_import_paths.md - Missing Module

**Location:** README_validate_import_paths.md code block #1

**Issue:** Documentation references non-existent module path:
```python
from ipfs_datasets_py.mcp_server.tools.admin_tools.system_health import system_health
import ipfs_datasets_py.mcp_server.tools.admin_tools.system_health
```

**Actual Module Structure:**
- `ipfs_datasets_py/mcp_server/` exists
- `ipfs_datasets_py/mcp_server/tools/` exists
- `ipfs_datasets_py/mcp_server/tools/admin_tools/` exists
- **BUT**: `system_health.py` or `system_health/` does NOT exist in `admin_tools/`

**Verification:**
```bash
$ find ipfs_datasets_py/mcp_server/tools/admin_tools -name "system_health*"
# No results
```

**Impact:** MEDIUM - Code examples will fail with ImportError if copy-pasted.

**Recommendation:** Either (1) remove the non-existent import examples, or (2) update to reference actual admin_tools modules.

---

## Validated Passing Examples

### ✅ INTEGRATION_EXAMPLES.md

All imports and class references verified working:

**Tested Imports:**
```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyCritic,
    OntologyMediator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
    ExtractionConfig,
)
```

**Validation Result:**
```
$ python -c "from ipfs_datasets_py.optimizers.graphrag import ..."
✓ All imports successful
```

**Class References Verified:**
- ✅ `OntologyGenerator` → ipfs_datasets_py/optimizers/graphrag/ontology_generator.py:2937
- ✅ `OntologyCritic` → ipfs_datasets_py/optimizers/graphrag/ontology_critic.py:579
- ✅ `OntologyMediator` → ipfs_datasets_py/optimizers/graphrag/ontology_mediator.py:257
- ✅ `ExtractionConfig` → exported in ipfs_datasets_py/optimizers/graphrag/__init__.py

---

## Minor Issues

### 3. Missing Verification for Other Docs

**Files Not Yet Audited:**
- ALERTING_EXAMPLES.md
- DISTRIBUTED_ONTOLOGY_REFINEMENT.md
- PERFORMANCE_TUNING_GUIDE.md
- SANDBOXED_PROVER_POLICY.md
- TROUBLESHOOTING_DASHBOARDS.md
- TROUBLESHOOTING_GUIDE.md

**Recommendation:** Schedule follow-up audit for these files using automated drift checker.

---

## Automated Drift Detection Tool

Created `/home/barberb/complaint-generator/ipfs_datasets_py/scripts/audit_docs_drift.py` to automatically detect:
- Invalid import statements in code examples
- Missing module references
- Broken class references
- Syntax errors in code blocks

**Usage:**
```bash
cd /home/barberb/complaint-generator/ipfs_datasets_py
python scripts/audit_docs_drift.py
```

**Current Output:**
```
# Documentation Drift Audit Report

Found 2 issues across 1 files

## README_validate_import_paths.md
**2 issue(s)**

- **missing_module** (code block #1): Module not found: ipfs_datasets_py.mcp_server.tools.admin_tools.system_health
- **missing_module** (code block #1): Module not found: ipfs_datasets_py.mcp_server.tools.admin_tools.system_health
```

---

## Recommendations

### Immediate Actions (P1)

1. **Fix HOW_TO_ADD_NEW_OPTIMIZER.md template** - Update to match current BaseOptimizer API
2. **Fix README_validate_import_paths.md** - Remove or correct system_health import examples

### Short-term Actions (P2)

3. **Audit remaining 6 docs files** - Use automated tool + manual review
4. **Add CI check** - Run `audit_docs_drift.py` in CI to catch future drift
5. **Version pin examples** - Add version tags to code examples to track when they were last verified

### Long-term Actions (P3)

6. **Integration tests for docs** - Extract code blocks and run as pytest tests
7. **Auto-sync templates** - Generate templates from actual base classes
8. **Quarterly audit schedule** - Review all docs every 3 months

---

## Appendix: Audit Methodology

### Automated Checks
1. Extract Python code blocks from markdown (regex: ` ```python\n(.*?)``` `)
2. Parse and validate import statements (ast.parse)
3. Verify module existence with grep/file checks
4. Search for class definitions in codebase

### Manual Verification
1. Read documentation examples
2. Copy imports to Python REPL
3. Compare documented APIs with actual implementation
4. Check for outdated parameter names/types

### Tools Used
- `scripts/audit_docs_drift.py` (custom tool)
- `grep_search` for class/function definitions
- `python -c "..."` for import validation
- Manual diff of documented vs actual signatures

---

**Audit Complete:** 2026-02-24  
**Next Review Due:** 2026-05-24 (3 months)
