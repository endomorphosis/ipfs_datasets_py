# TODO List for logic/integration/

## Status: Phase 2 (Quality Improvements) - Active

### Recent Cleanup (2026-02-13)
- Archived old 7,180-line TODO.md to TODO_ARCHIVED.md
- Removed old_tests/ directory (4,366 LOC)
- Most functionality is already implemented and tested

## Current State
- **Test Coverage:** ~50% (483 tests in tests/unit_tests/logic/integration/)
- **Security:** Rate limiting and input validation integrated ✅
- **Bridge Pattern:** BaseProverBridge ABC implemented ✅
- **Code Quality:** In progress (Phase 2)

## Active Tasks (Phase 2)

### Refactoring (Priority: High)
- [ ] Split prover_core.py (2,884 LOC → <600 LOC)
- [ ] Refactor proof_execution_engine.py (949 LOC → <600 LOC)
- [ ] Refactor deontological_reasoning.py (911 LOC → <600 LOC)
- [ ] Refactor logic_verification.py (879 LOC → <600 LOC)
- [ ] Refactor interactive_fol_constructor.py (858 LOC → <600 LOC)

### Type System (Priority: High)
- [ ] Create logic/types/ directory for shared types
- [ ] Move DeonticFormula, DeonticOperator to types
- [ ] Move LogicTranslationTarget to types
- [ ] Move ProofResult, ProofStatus to types

### Code Quality (Priority: Medium)
- [ ] Remove unused imports (run autoflake)
- [ ] Standardize error handling
- [ ] Extract duplicate conversion logic
- [ ] Create LogicConverter base class

## Completed
- [x] Phase 1: Test coverage expansion (230 tests added)
- [x] Security module integration (rate limiting + validation)
- [x] Bridge pattern consolidation (BaseProverBridge ABC)
- [x] Archive old_tests/ directory
- [x] Clean up TODO.md file

## Notes
- See TODO_ARCHIVED.md for historical tasks
- See ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md for full roadmap
- All changes must maintain backward compatibility
