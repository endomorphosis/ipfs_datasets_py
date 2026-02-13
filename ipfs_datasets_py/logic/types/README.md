# Logic Types Module

**Created:** 2026-02-13  
**Phase:** Phase 2 - Quality Improvements  
**Purpose:** Centralize shared type definitions to resolve circular dependencies

## Overview

The `logic/types/` module provides a centralized location for type definitions shared across the logic module. This prevents circular dependencies between `tools`, `integration`, `TDFOL`, and other submodules.

## Design Philosophy

### Backward Compatibility
- Types remain defined in their original locations
- This module re-exports them for internal use
- External APIs are unchanged
- No breaking changes to existing code

### Usage Patterns

**Internal use (within logic module):**
```python
# Preferred for new code within logic module
from ipfs_datasets_py.logic.types import DeonticOperator, ProofResult
```

**External use (outside logic module):**
```python
# Still supported for backward compatibility
from ipfs_datasets_py.logic.tools.deontic_logic_core import DeonticOperator
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
```

## Module Structure

```
logic/types/
├── __init__.py             # Main exports, imports all type modules
├── deontic_types.py        # Deontic logic types (DeonticOperator, DeonticFormula, etc.)
├── proof_types.py          # Proof types (ProofStatus, ProofResult, ProofStep)
├── translation_types.py    # Translation types (LogicTranslationTarget, TranslationResult)
└── README.md              # This file
```

## Available Types

### Deontic Types (`deontic_types.py`)
- `DeonticOperator` - Enum for deontic operators (OBLIGATION, PERMISSION, etc.)
- `DeonticFormula` - Dataclass for deontic logic formulas
- `DeonticRuleSet` - Collection of deontic rules
- `LegalAgent` - Dataclass for legal agents
- `LegalContext` - Dataclass for legal context
- `TemporalCondition` - Dataclass for temporal conditions
- `TemporalOperator` - Enum for temporal operators

### Proof Types (`proof_types.py`)
- `ProofStatus` - Enum for proof status (PROVED, DISPROVED, UNKNOWN, etc.)
- `ProofResult` - Dataclass for proof results
- `ProofStep` - Dataclass for individual proof steps

### Translation Types (`translation_types.py`)
- `LogicTranslationTarget` - Enum for translation targets (LEAN, COQ, SMT-LIB, etc.)
- `TranslationResult` - Dataclass for translation results
- `AbstractLogicFormula` - Platform-independent formula representation

## Benefits

1. **No Circular Dependencies:** Types can be imported without triggering circular imports
2. **Single Source of Truth:** One place to find all shared type definitions
3. **Backward Compatible:** Existing code continues to work without changes
4. **Future-Proof:** Easy to add new types or move existing ones
5. **Clear Separation:** Types vs. implementation logic

## Migration Strategy

The types module uses a gradual migration approach:

1. **Phase 1 (Current):** Types module created, re-exports from original locations
2. **Phase 2 (Future):** Internal logic module code updated to import from types
3. **Phase 3 (Future):** Consider moving actual type definitions to types module
4. **Phase 4 (Future):** Deprecate old import paths (with long deprecation period)

## Impact on Circular Dependencies

Before types module:
```
tools/deontic_logic_core.py
    ↓
integration/proof_execution_engine.py
    ↓
tools/logic_translation_core.py  ← Potential circular dependency
```

After types module:
```
types/deontic_types.py
    ↑
tools/deontic_logic_core.py    integration/proof_execution_engine.py
                                    ↓
                                types/translation_types.py
```

No circular dependencies - both tools and integration can import from types.

## Testing

Types are tested indirectly through the comprehensive test suite in `tests/unit_tests/logic/`:
- 483 tests cover functionality using these types
- Type safety validated through mypy (if configured)
- Import structure verified in CI/CD

## Future Enhancements

- Add more shared types as identified during refactoring
- Consider moving actual type definitions here (breaking change)
- Add type validation utilities
- Generate type documentation automatically

## References

- [ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md](../../ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md) - Full roadmap
- [Phase 2 Documentation](../../ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md#phase-2-quality-improvements-weeks-3-4---p1)
