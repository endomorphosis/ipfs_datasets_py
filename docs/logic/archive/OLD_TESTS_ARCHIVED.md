# Old Tests Directory - Archived

## Summary

The `old_tests/` directory (4,366 LOC) has been archived and removed from the main codebase as part of Phase 2 quality improvements. These tests were disabled (prefixed with `_test_`) and have been superseded by the new test suite in `tests/unit_tests/logic/integration/`.

## Archived Files

- `_test_integration.py` (1,006 LOC) - 28 integration tests
- `_test_logic_primitives.py` (590 LOC) - 24 tests for LogicPrimitives
- `_test_logic_verification.py` (727 LOC) - 42 tests for LogicVerifier
- `_test_modal_logic_extension.py` (695 LOC) - 44 tests for modal logic
- `_test_symbolic_bridge.py` (695 LOC) - 26 tests for SymbolicFOLBridge
- `_test_symbolic_contracts.py` (695 LOC) - 32 tests for contract validation
- `__init__.py` (128 LOC) - Test utilities

**Total:** 196 tests, 4,366 LOC

## Why Archived

1. **Superseded:** New comprehensive test suite with 483+ tests added in Phase 1
2. **Disabled:** All files prefixed with `_test_` to prevent pytest discovery
3. **Dependency Issues:** Tests had unmet dependencies (anyio, etc.)
4. **Code Quality:** Tests used outdated patterns and imports

## New Test Coverage

The functionality covered by these old tests is now tested by:
- `tests/unit_tests/logic/integration/` (16 test files, 483 tests)
- Higher coverage (~50% vs <5%)
- Modern pytest patterns (GIVEN-WHEN-THEN format)
- Graceful dependency handling

## Recovery

If needed, these tests can be recovered from git history:
```bash
git log --all --full-history -- "ipfs_datasets_py/logic/integration/old_tests/*"
```

**Archived:** 2026-02-13  
**Phase:** Phase 2 - Quality Improvements  
**Branch:** copilot/complete-architecture-review-logic
