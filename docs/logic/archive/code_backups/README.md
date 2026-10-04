# Code Backups Archive

This directory contains backup copies of source files that were replaced during refactoring but are preserved for historical reference.

## Contents

### FOL Module Backups
- `text_to_fol_original.py` - Original FOL text-to-logic converter before unified architecture
- `text_to_fol_legacy.py.bak` - Legacy backup of FOL converter

### Deontic Module Backups  
- `legal_text_to_deontic_original.py` - Original deontic converter before unified architecture

### Integration Module Backups
- `__init__.py.backup` - Backup of integration module init before Phase 6 reorganization

## Why Preserved

These files are kept for:
1. **Historical Reference** - Understanding how the code evolved
2. **Comparison** - Comparing old vs new implementations
3. **Recovery** - Fallback if critical issues discovered (though unlikely)

## Current Implementations

| Old File | Current File | Status |
|----------|-------------|---------|
| `text_to_fol_original.py` | `fol/converter.py` + `fol/text_to_fol.py` | ✅ Active, unified architecture |
| `legal_text_to_deontic_original.py` | `deontic/converter.py` + `deontic/legal_text_to_deontic.py` | ✅ Active, unified architecture |
| `integration/__init__.py.backup` | `integration/__init__.py` | ✅ Active, reorganized |

All current implementations:
- Extend unified `LogicConverter` base class
- Include caching, batch processing, ML confidence
- Have comprehensive tests (94% pass rate)
- Are production-ready

## Do Not Use

⚠️ **These files should NOT be imported or used in production code.** They are for reference only.

If you need to reference old behavior:
1. Check git history for detailed change logs
2. Review MIGRATION_GUIDE.md for API changes
3. See REFACTORING_COMPLETE.md for what was changed

## Archived Date

2026-02-14 - Phase 2 code organization cleanup
