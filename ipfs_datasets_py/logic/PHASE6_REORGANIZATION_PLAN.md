# Phase 6: Module Reorganization Plan

**Date:** 2026-02-14  
**Branch:** copilot/implement-refactoring-plan-again  
**Status:** IN PROGRESS 🔄

---

## Executive Summary

Phase 6 reorganizes the integration/ directory (44 files) into logical subdirectories for better maintainability and discoverability. This improves code organization without changing functionality.

**Current:** Flat structure with 44 files in single directory  
**Target:** 7 subdirectories with clear categorization  
**Estimated Time:** 12-16 hours  
**Risk:** Low (tests validate, backward compatibility maintained)

---

## Current Structure Analysis

### Integration Directory Contents (44 files)

```
integration/
├── __init__.py
├── CHANGELOG.md
├── TODO.md
├── neurosymbolic/ (subdirectory already exists)
└── 41 Python files (flat structure)
```

### File Categorization

After analyzing all 44 files, here's the proposed organization:

#### Category 1: Bridges (9 files)
**Purpose:** Bridge implementations between different systems

- `base_prover_bridge.py` - Base class for prover bridges
- `symbolic_fol_bridge.py` - SymbolicAI <-> FOL bridge
- `tdfol_cec_bridge.py` - TDFOL <-> CEC bridge
- `tdfol_grammar_bridge.py` - TDFOL <-> Grammar engine bridge
- `tdfol_shadowprover_bridge.py` - TDFOL <-> ShadowProver bridge
- `external_provers.py` - External prover integrations
- `prover_installer.py` - Prover installation utilities

**New Location:** `integration/bridges/`

#### Category 2: Caching (3 files)
**Purpose:** Caching and storage systems

- `proof_cache.py` - Core proof caching (LRU + TTL)
- `ipfs_proof_cache.py` - IPFS-backed proof cache
- `ipld_logic_storage.py` - IPLD logic storage

**New Location:** `integration/caching/`

#### Category 3: Reasoning Engines (4 files + utils)
**Purpose:** Core reasoning and proof execution

- `proof_execution_engine.py` - Main proof execution engine
- `proof_execution_engine_types.py` - Types for proof engine
- `proof_execution_engine_utils.py` - Utilities for proof engine
- `deontological_reasoning.py` - Deontic reasoning engine
- `deontological_reasoning_types.py` - Types for deontic reasoning
- `deontological_reasoning_utils.py` - Utilities for deontic reasoning
- `logic_verification.py` - Logic verification system
- `logic_verification_types.py` - Types for verification
- `logic_verification_utils.py` - Utilities for verification

**New Location:** `integration/reasoning/`

#### Category 4: Converters (4 files)
**Purpose:** Format conversion and translation

- `deontic_logic_converter.py` - Deontic logic converter
- `deontic_logic_core.py` - Core deontic logic
- `logic_translation_core.py` - Logic translation utilities
- `modal_logic_extension.py` - Modal logic extensions

**New Location:** `integration/converters/`

#### Category 5: Domain-Specific (8 files)
**Purpose:** Domain-specific integrations (legal, medical, contracts)

- `legal_domain_knowledge.py` - Legal domain knowledge base
- `legal_symbolic_analyzer.py` - Legal symbolic analysis
- `medical_theorem_framework.py` - Medical theorem proving
- `symbolic_contracts.py` - Symbolic contract verification
- `caselaw_bulk_processor.py` - Bulk caselaw processing
- `document_consistency_checker.py` - Document consistency
- `deontic_query_engine.py` - Deontic query interface
- `temporal_deontic_api.py` - Temporal deontic API
- `temporal_deontic_rag_store.py` - Temporal deontic RAG

**New Location:** `integration/domain/`

#### Category 6: Interactive Tools (3 files)
**Purpose:** Interactive construction and exploration

- `interactive_fol_constructor.py` - Interactive FOL builder
- `interactive_fol_types.py` - Types for interactive FOL
- `interactive_fol_utils.py` - Utilities for interactive FOL

**New Location:** `integration/interactive/`

#### Category 7: SymbolicAI Integration (3 files)
**Purpose:** SymbolicAI and neurosymbolic integration

- `symbolic_logic_primitives.py` - Symbolic logic primitives
- `neurosymbolic_api.py` - Neurosymbolic API
- `neurosymbolic_graphrag.py` - Neurosymbolic GraphRAG
- `neurosymbolic/` (existing subdirectory)

**New Location:** `integration/symbolic/`

#### Category 8: Demos and Docs (3 files)
**Purpose:** Documentation and demonstration files

- `demo_temporal_deontic_rag.py` - Demo script
- `CHANGELOG.md` - Change log
- `TODO.md` - TODO list

**New Location:** Keep in `integration/` root or move to `integration/demos/`

---

## Proposed New Structure

```
integration/
├── __init__.py                    # Main integration exports
├── CHANGELOG.md                   # Keep at root
├── TODO.md                        # Keep at root
│
├── bridges/                       # 9 files
│   ├── __init__.py
│   ├── base_prover_bridge.py
│   ├── symbolic_fol_bridge.py
│   ├── tdfol_cec_bridge.py
│   ├── tdfol_grammar_bridge.py
│   ├── tdfol_shadowprover_bridge.py
│   ├── external_provers.py
│   └── prover_installer.py
│
├── caching/                       # 3 files
│   ├── __init__.py
│   ├── proof_cache.py
│   ├── ipfs_proof_cache.py
│   └── ipld_logic_storage.py
│
├── reasoning/                     # 9 files
│   ├── __init__.py
│   ├── proof_execution_engine.py
│   ├── proof_execution_engine_types.py
│   ├── proof_execution_engine_utils.py
│   ├── deontological_reasoning.py
│   ├── deontological_reasoning_types.py
│   ├── deontological_reasoning_utils.py
│   ├── logic_verification.py
│   ├── logic_verification_types.py
│   └── logic_verification_utils.py
│
├── converters/                    # 4 files
│   ├── __init__.py
│   ├── deontic_logic_converter.py
│   ├── deontic_logic_core.py
│   ├── logic_translation_core.py
│   └── modal_logic_extension.py
│
├── domain/                        # 9 files
│   ├── __init__.py
│   ├── legal_domain_knowledge.py
│   ├── legal_symbolic_analyzer.py
│   ├── medical_theorem_framework.py
│   ├── symbolic_contracts.py
│   ├── caselaw_bulk_processor.py
│   ├── document_consistency_checker.py
│   ├── deontic_query_engine.py
│   ├── temporal_deontic_api.py
│   └── temporal_deontic_rag_store.py
│
├── interactive/                   # 3 files
│   ├── __init__.py
│   ├── interactive_fol_constructor.py
│   ├── interactive_fol_types.py
│   └── interactive_fol_utils.py
│
├── symbolic/                      # 4 files + subdirectory
│   ├── __init__.py
│   ├── symbolic_logic_primitives.py
│   ├── neurosymbolic_api.py
│   ├── neurosymbolic_graphrag.py
│   └── neurosymbolic/            # Existing subdirectory
│
└── demos/                         # 1 file (optional)
    ├── __init__.py
    └── demo_temporal_deontic_rag.py
```

---

## Implementation Plan

### Step 1: Create New Subdirectories (30 min)

```bash
# Create subdirectories
mkdir -p integration/bridges
mkdir -p integration/caching
mkdir -p integration/reasoning
mkdir -p integration/converters
mkdir -p integration/domain
mkdir -p integration/interactive
mkdir -p integration/symbolic
mkdir -p integration/demos

# Create __init__.py files
touch integration/bridges/__init__.py
touch integration/caching/__init__.py
touch integration/reasoning/__init__.py
touch integration/converters/__init__.py
touch integration/domain/__init__.py
touch integration/interactive/__init__.py
touch integration/symbolic/__init__.py
touch integration/demos/__init__.py
```

### Step 2: Move Files (1-2 hours)

Move files to appropriate subdirectories:

```bash
# Bridges
git mv integration/base_prover_bridge.py integration/bridges/
git mv integration/symbolic_fol_bridge.py integration/bridges/
git mv integration/tdfol_*_bridge.py integration/bridges/
git mv integration/external_provers.py integration/bridges/
git mv integration/prover_installer.py integration/bridges/

# Caching
git mv integration/proof_cache.py integration/caching/
git mv integration/ipfs_proof_cache.py integration/caching/
git mv integration/ipld_logic_storage.py integration/caching/

# Reasoning
git mv integration/proof_execution_engine*.py integration/reasoning/
git mv integration/deontological_reasoning*.py integration/reasoning/
git mv integration/logic_verification*.py integration/reasoning/

# Converters
git mv integration/deontic_logic_*.py integration/converters/
git mv integration/logic_translation_core.py integration/converters/
git mv integration/modal_logic_extension.py integration/converters/

# Domain
git mv integration/legal_*.py integration/domain/
git mv integration/medical_*.py integration/domain/
git mv integration/symbolic_contracts.py integration/domain/
git mv integration/caselaw_*.py integration/domain/
git mv integration/document_*.py integration/domain/
git mv integration/deontic_query_*.py integration/domain/
git mv integration/temporal_deontic_*.py integration/domain/

# Interactive
git mv integration/interactive_fol_*.py integration/interactive/

# Symbolic
git mv integration/symbolic_logic_primitives.py integration/symbolic/
git mv integration/neurosymbolic_*.py integration/symbolic/
git mv integration/neurosymbolic integration/symbolic/

# Demos
git mv integration/demo_*.py integration/demos/
```

### Step 3: Update Import Paths (4-6 hours)

Update imports in all affected files. Pattern:

**Old:**
```python
from ipfs_datasets_py.logic.integration.proof_cache import ProofCache
from ipfs_datasets_py.logic.integration import proof_execution_engine
```

**New:**
```python
from ipfs_datasets_py.logic.integration.caching.proof_cache import ProofCache
from ipfs_datasets_py.logic.integration.reasoning import proof_execution_engine
```

Files to update:
- All 44 files in integration/ (internal imports)
- Files in logic/fol/ that import from integration/
- Files in logic/deontic/ that import from integration/
- Files in logic/TDFOL/ that import from integration/
- Files in logic/external_provers/ that import from integration/
- Files in logic/CEC/ that import from integration/
- Test files in tests/unit_tests/logic/

**Estimated:** ~150+ import statements to update

### Step 4: Create Subdirectory __init__.py Files (2-3 hours)

Each subdirectory needs an __init__.py that exports key classes/functions:

**Example: integration/caching/__init__.py**
```python
"""
Caching subsystem for logic module.

Provides proof caching, IPFS-backed caching, and IPLD storage.
"""

from .proof_cache import ProofCache, get_global_cache
from .ipfs_proof_cache import IPFSProofCache, get_global_ipfs_cache
from .ipld_logic_storage import LogicIPLDStorage

__all__ = [
    'ProofCache',
    'get_global_cache',
    'IPFSProofCache',
    'get_global_ipfs_cache',
    'LogicIPLDStorage',
]
```

Create similar __init__.py for:
- bridges/__init__.py
- reasoning/__init__.py
- converters/__init__.py
- domain/__init__.py
- interactive/__init__.py
- symbolic/__init__.py
- demos/__init__.py

### Step 5: Update Main integration/__init__.py (1 hour)

Update main __init__.py to re-export from subdirectories:

```python
"""
Integration subsystem for logic module.

Organized into subdirectories:
- bridges/: Prover and system bridges
- caching/: Proof caching systems
- reasoning/: Core reasoning engines
- converters/: Format converters
- domain/: Domain-specific tools
- interactive/: Interactive construction
- symbolic/: SymbolicAI integration
- demos/: Demonstration scripts
"""

# Re-export commonly used classes for backward compatibility
from .caching import ProofCache, get_global_cache, IPFSProofCache
from .reasoning import ProofExecutionEngine, DeontologicalReasoning
from .bridges import (
    BaseProverBridge,
    SymbolicFOLBridge,
    TDFOLCECBridge,
    TDFOLGrammarBridge,
)
from .converters import DeonticLogicConverter, ModalLogicExtension

__all__ = [
    # Caching
    'ProofCache',
    'get_global_cache',
    'IPFSProofCache',
    
    # Reasoning
    'ProofExecutionEngine',
    'DeontologicalReasoning',
    
    # Bridges
    'BaseProverBridge',
    'SymbolicFOLBridge',
    'TDFOLCECBridge',
    'TDFOLGrammarBridge',
    
    # Converters
    'DeonticLogicConverter',
    'ModalLogicExtension',
]
```

### Step 6: Update Tests (2-3 hours)

Update test imports to use new paths:

```python
# Old
from ipfs_datasets_py.logic.integration.proof_cache import ProofCache

# New - but still works via __init__.py re-export
from ipfs_datasets_py.logic.integration import ProofCache

# Or direct import
from ipfs_datasets_py.logic.integration.caching import ProofCache
```

### Step 7: Run Full Test Suite (1 hour)

```bash
pytest tests/unit_tests/logic/ -v --tb=short
```

Validate:
- All imports work
- Tests pass
- No regressions

### Step 8: Update Documentation (1-2 hours)

Update documentation to reflect new structure:
- README.md
- FEATURES.md
- MIGRATION_GUIDE.md
- Individual module READMEs

---

## Backward Compatibility Strategy

### 1. Re-export from Main __init__.py

Keep commonly used classes available from `integration/` root:

```python
# These still work
from ipfs_datasets_py.logic.integration import ProofCache
from ipfs_datasets_py.logic.integration import ProofExecutionEngine
```

### 2. Deprecation Warnings (Optional)

For less common direct imports, consider deprecation warnings:

```python
# integration/__init__.py
import warnings

def __getattr__(name):
    """Handle imports of moved modules."""
    if name == 'proof_cache':
        warnings.warn(
            "Importing proof_cache directly from integration is deprecated. "
            "Use: from ipfs_datasets_py.logic.integration.caching import proof_cache",
            DeprecationWarning,
            stacklevel=2
        )
        from .caching import proof_cache
        return proof_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### 3. Update All Internal Imports

Ensure all internal code uses new paths immediately.

---

## Success Criteria

### Functionality ✅
- [ ] All 44 files moved to appropriate subdirectories
- [ ] All imports updated and working
- [ ] All tests passing (maintain 94% pass rate)
- [ ] No functionality broken

### Structure ✅
- [ ] 7 logical subdirectories created
- [ ] Clear categorization of files
- [ ] Each subdirectory has __init__.py
- [ ] Main integration/__init__.py updated

### Backward Compatibility ✅
- [ ] Common imports still work from integration/
- [ ] Deprecation warnings for moved modules (optional)
- [ ] No breaking changes for external users

### Documentation ✅
- [ ] README.md updated with new structure
- [ ] MIGRATION_GUIDE.md updated
- [ ] Each subdirectory has docstring
- [ ] Benefits documented

---

## Benefits

### For Developers 👨‍💻
- **Easier navigation:** Find files by category, not alphabetically
- **Clear purpose:** Each subdirectory has specific responsibility
- **Better IDE support:** Subdirectories show up as packages
- **Reduced cognitive load:** ~7 categories vs 44 files

### For Maintainers 🔧
- **Easier refactoring:** Changes contained to subdirectories
- **Clear dependencies:** See what depends on what
- **Better testing:** Can test subdirectories independently
- **Improved modularity:** Can extract subdirectories if needed

### For Users 📚
- **Better documentation:** Organized by feature
- **Clearer imports:** Purpose evident from path
- **Easier exploration:** Browse by category
- **Discoverable:** Can explore subdirectories

---

## Risks and Mitigation

### Risk 1: Breaking External Code
**Mitigation:** Re-export common classes from main __init__.py

### Risk 2: Import Cycles
**Mitigation:** Analyze dependencies first, break cycles if found

### Risk 3: Test Failures
**Mitigation:** Update all test imports, run full suite before commit

### Risk 4: Merge Conflicts
**Mitigation:** Do this in dedicated PR, coordinate with team

---

## Timeline

| Task | Duration | Cumulative |
|------|----------|------------|
| Create subdirectories | 30 min | 0.5h |
| Move files (git mv) | 1-2h | 2.5h |
| Update imports | 4-6h | 8.5h |
| Create __init__.py files | 2-3h | 11.5h |
| Update main __init__.py | 1h | 12.5h |
| Update tests | 2-3h | 15.5h |
| Run test suite | 1h | 16.5h |
| Update documentation | 1-2h | 18.5h |

**Total: 12-16 hours** (as estimated)

---

## Next Session Tasks

1. **Immediate: Create Subdirectories**
   - Create 7 subdirectories
   - Create __init__.py files
   - Plan file moves

2. **Phase 1: Move Core Files**
   - Start with caching/ (small, isolated)
   - Then bridges/ (well-defined)
   - Update their imports

3. **Phase 2: Move Reasoning**
   - Move reasoning engines
   - Update internal imports
   - Test reasoning functionality

4. **Phase 3: Move Converters & Domain**
   - Move converters/
   - Move domain/
   - Update imports

5. **Phase 4: Final Touches**
   - Move interactive/ and symbolic/
   - Update all documentation
   - Run full test suite

---

## Conclusion

Phase 6 reorganization will significantly improve code organization and maintainability. The work is straightforward but requires careful attention to imports. By maintaining backward compatibility through re-exports, we minimize risk while improving structure.

**Status:** Ready to implement  
**Risk Level:** Low  
**Expected Benefit:** High  
**Recommendation:** Proceed with implementation

---

**Created:** 2026-02-14  
**Author:** GitHub Copilot  
**Branch:** copilot/implement-refactoring-plan-again  
**Phase:** 6 (Module Reorganization)
