# Logic Common Module

**Created:** 2026-02-13  
**Phase:** Phase 2 - Quality Improvements (Day 3)  
**Purpose:** Provide shared utilities and standardized patterns for logic module

## Overview

The `logic/common/` module contains utilities shared across the logic module to:
1. Reduce code duplication
2. Standardize common patterns
3. Improve error handling consistency
4. Simplify maintenance

## Components

### Error Hierarchy (`errors.py`)

Standardized exception hierarchy replacing inconsistent use of `ValueError`, `TypeError`, and `RuntimeError`:

**Base Exception:**
- `LogicError` - Base for all logic module errors with context support

**Domain-Specific Exceptions:**
- `ConversionError` - Logic conversion failures
- `ValidationError` - Validation failures
- `ProofError` - Proof execution failures
- `TranslationError` - Logic translation failures
- `BridgeError` - Prover bridge operation failures
- `ConfigurationError` - Configuration issues
- `DeonticError` - Deontic logic failures
- `ModalError` - Modal logic failures
- `TemporalError` - Temporal logic failures

**Usage:**

```python
from ipfs_datasets_py.logic.common import ConversionError

def convert_logic(formula):
    if not formula:
        raise ConversionError(
            "Empty formula provided",
            context={"function": "convert_logic", "formula": formula}
        )
    # ... conversion logic
```

**Context Support:**

All errors accept optional context dictionary for debugging:

```python
try:
    convert_formula(formula)
except Exception as e:
    raise ConversionError(
        "Failed to convert formula",
        context={
            "formula": formula,
            "source": "user_input",
            "line": 42
        }
    ) from e
```

## Benefits

1. **Consistent Error Handling:** All logic module exceptions follow same pattern
2. **Better Debugging:** Context dictionary captures error details
3. **Type Safety:** Specific exception types for different failure modes
4. **Backward Compatible:** Doesn't break existing code, used for new code
5. **Clear Intent:** Exception names communicate what went wrong

## Migration Strategy

**Phase 1 (Current):** 
- Common module created
- Available for use in new code
- Existing code continues using old errors

**Phase 2 (Future):**
- Gradually wrap legacy errors in new code paths
- Update new features to use common errors
- Add examples and patterns

**Phase 3 (Optional):**
- Consider migrating critical paths to new errors
- Maintain backward compatibility with wrappers

## Future Additions

The common module will grow to include:
- Conversion utilities (DRY up duplicate logic)
- Base converter classes
- Validation helpers
- Common decorators
- Logging utilities

## References

- [ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md](../../ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md) - Full roadmap
- [Phase 2 Task 7](../../ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md#phase-2-quality-improvements-weeks-3-4---p1) - Extract common logic
