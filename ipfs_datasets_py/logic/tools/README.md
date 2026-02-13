# tools/ Directory Status

## Current State

This directory contains files that were originally intended to be moved to `integration/`, but some files must remain due to dependencies from the `types/` module.

## Files and Status

### Must Remain (Type System Dependencies)

1. **deontic_logic_core.py** - MUST STAY
   - Imported by: `types/deontic_types.py`
   - Contains: `DeonticOperator`, `DeonticFormula`, `LegalAgent`, etc.
   - Action: Will be moved when types/ is refactored

### Duplicates (Can be removed when safe)

2. **symbolic_fol_bridge.py** - DUPLICATE
   - Also exists in: `integration/symbolic_fol_bridge.py`
   - Status: Kept for backward compatibility
   - Action: Remove after verifying no external imports

3. **symbolic_logic_primitives.py** - DUPLICATE
   - Also exists in: `integration/symbolic_logic_primitives.py`
   - Status: Kept for backward compatibility
   - Action: Remove after verifying no external imports

4. **modal_logic_extension.py** - DUPLICATE
   - Also exists in: `integration/modal_logic_extension.py`
   - Status: Kept for backward compatibility
   - Action: Remove after verifying no external imports

5. **logic_translation_core.py** - DUPLICATE
   - Also exists in: `integration/logic_translation_core.py`
   - Status: Kept for backward compatibility
   - Action: Remove after verifying no external imports

### Obsolete (Can be removed)

6. **legal_text_to_deontic.py** - OBSOLETE
   - Replaced by: `deontic/legal_text_to_deontic.py` (wrapper)
   - And: `deontic/converter.py` (new implementation)
   - Status: Can be removed
   - Action: Delete after final verification

7. **logic_utils/** - CHECK STATUS
   - May contain duplicates of fol/utils/ or deontic/utils/
   - Action: Analyze and consolidate

## Migration Plan

### Phase 1: Type System Refactoring (Future)
- Move `deontic_logic_core.py` contents directly into `types/deontic_types.py`
- Remove re-export pattern
- Update all imports

### Phase 2: Remove Duplicates
- Delete duplicate files once external imports verified
- Add deprecation warnings if needed
- Update documentation

### Phase 3: Complete Removal
- Delete entire tools/ directory
- Verify no broken imports
- Update all documentation

## Import Guidelines

**DO NOT** import from `logic.tools` in new code. Use:
- `from ipfs_datasets_py.logic.types import DeonticOperator, DeonticFormula`
- `from ipfs_datasets_py.logic.integration import symbolic_fol_bridge`
- `from ipfs_datasets_py.logic.fol.utils import predicate_extractor`
- `from ipfs_datasets_py.logic.deontic.utils import deontic_parser`

## Reason for Keeping tools/

The tools/ directory was supposed to be deleted as part of the Enhanced Refactoring Plan (Phase 2C). However, analysis revealed that `types/deontic_types.py` directly imports from `tools/deontic_logic_core.py`. This creates a hard dependency that cannot be removed without first refactoring the type system.

Rather than break the type system or create circular dependencies, we:
1. Keep tools/ for now with clear documentation
2. Add this to the refactoring plan as a separate phase
3. Focus on other high-value improvements

## Last Updated
2026-02-13 - Analysis during Enhanced Refactoring Plan implementation
