# TDFOL Refactoring Plan - Quick Reference
**Date**: 2026-02-19  
**Status**: ✅ Planning Complete

> **Full Plan**: See `REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` for comprehensive details

---

## At a Glance

| Metric | Current | Target | Change |
|--------|---------|--------|--------|
| Total LOC | 18,000 | ~16,500 | -1,149 LOC (-6.4%) |
| Files | 45 | 46-48 | Slight increase from splitting |
| Tests | 57 | 282+ | +225 tests (+395%) |
| Coverage | ~60% | 80%+ | +20 percentage points |
| Largest File | 1,748 LOC | <600 LOC | Split into 7 modules |

---

## Critical Issues (P0)

### Issue #1: Monolithic Inference Rules 🔴
- **File**: `tdfol_inference_rules.py` (1,748 LOC)
- **Problem**: 61+ rules in one file, hard to maintain
- **Solution**: Split into 7 modules (propositional, first_order, temporal, deontic, modal, conversion)
- **Effort**: 4 days
- **Impact**: Clear organization, +60 tests

### Issue #2: Duplicated Expansion Rules 🔴
- **Files**: `modal_tableaux.py`, `tdfol_inference_rules.py`
- **Problem**: ~100 LOC duplication in expansion logic
- **Solution**: Create `ExpansionRule` base class in `tdfol_core.py`
- **Effort**: 2 days
- **Impact**: -100 LOC, single implementation

---

## High Priority Issues (P1)

### Issue #3: Fragmented NL Processing 🟡
- **Files**: `nl/` directory (9 files, 3,169 LOC)
- **Problem**: Overlapping patterns, unclear pipeline
- **Solution**: Consolidate to 7 files (generator, parser, llm, utils)
- **Effort**: 5 days
- **Impact**: -569 LOC (-18%), clearer architecture

### Issue #4: Inconsistent Caching 🟡
- **Files**: `tdfol_proof_cache.py`, `tdfol_optimization.py`
- **Problem**: Two different caching implementations
- **Solution**: Unify under `IndexedKnowledgeBase`, deprecate old cache
- **Effort**: 2 days
- **Impact**: Single implementation, +15 tests

### Issue #5: Duplicated ProofResult 🟡
- **Files**: `tdfol_prover.py`, `strategies/base.py`
- **Problem**: ~80 LOC duplication, inconsistent fields
- **Solution**: Move to `tdfol_core.py` (single source of truth)
- **Effort**: 1 day
- **Impact**: -80 LOC, consistency

### Issue #6: Performance Metrics Duplication 🟡
- **Files**: `performance_profiler.py`, `performance_dashboard.py`
- **Problem**: ~200 LOC duplication in timing logic
- **Solution**: Extract `performance_metrics.py`
- **Effort**: 2 days
- **Impact**: -200 LOC, shared implementation

---

## 4-Phase Roadmap (8 Weeks)

### Phase 1: Code Consolidation (Weeks 1-2)
**Goal**: Eliminate duplication

| Task | Issue | Days | LOC | Tests |
|------|-------|------|-----|-------|
| Extract expansion rules | #2 | 2 | -100 | +10 |
| Unify ProofResult | #5 | 1 | -80 | 0 |
| Consolidate caching | #4 | 2 | 0 | +15 |
| Merge performance metrics | #6 | 2 | -200 | +10 |
| **Phase 1 Total** | | **7+3 buffer** | **-380** | **+35** |

### Phase 2: Architecture Improvements (Weeks 3-4)
**Goal**: Improve organization

| Task | Issue | Days | LOC | Tests |
|------|-------|------|-----|-------|
| Split inference rules | #1 | 4 | 0 | +60 |
| Consolidate NL modules | #3 | 5 | -569 | +20 |
| Unify error handling | #8 | 2 | 0 | +10 |
| **Phase 2 Total** | | **11+3 buffer** | **-569** | **+90** |

### Phase 3: Documentation & Testing (Weeks 5-6)
**Goal**: Improve docs and coverage

| Task | Days | Tests |
|------|------|-------|
| Document interfaces | 3 | 0 |
| Expand test coverage | 5 | +100 |
| Update documentation | 2 | 0 |
| **Phase 3 Total** | **10+4 buffer** | **+100** |

### Phase 4: Performance & Optimization (Weeks 7-8)
**Goal**: Polish and optimize

| Task | Issue | Days | LOC |
|------|-------|------|-----|
| Extract viz helpers | #9 | 2 | -200 |
| Standardize naming | #10 | 1 | 0 |
| Performance benchmarks | - | 3 | +200 |
| Final integration testing | - | 4 | 0 |
| **Phase 4 Total** | | **10+4 buffer** | **-200** |

---

## Expected Outcomes

### Quantitative
- ✅ **-1,149 LOC** (6.4% reduction)
- ✅ **+225 tests** (395% increase)
- ✅ **+20% coverage** (60% → 80%)
- ✅ **+30% documentation** (50% → 80%)
- ✅ **100% backward compatibility**

### Qualitative
- ✅ Smaller, focused modules (<600 LOC each)
- ✅ Clear logical organization
- ✅ Comprehensive documentation
- ✅ Easier to maintain and extend
- ✅ Better onboarding for new contributors

---

## Implementation Guidelines

### Before Starting
1. Read full plan in `REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md`
2. Create feature branch
3. Understand success criteria

### During Implementation
1. Make small, incremental changes
2. Run tests after each change
3. Maintain 100% pass rate
4. Commit frequently

### After Each Task
1. Run full test suite
2. Check backward compatibility
3. Update documentation
4. Report progress

---

## Risk Management

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Breaking changes | Low (10%) | Comprehensive testing, backward compat aliases |
| Test failures | Medium (30%) | Run tests after each change, rollback if needed |
| Import breakage | Medium (25%) | Update all imports, test import paths |
| Performance regression | Low (15%) | Benchmark before/after, optimize hot paths |
| Scope creep | High (60%) | Strict adherence to plan, defer nice-to-haves |

---

## Key Principles

1. **Backward Compatibility First**: All existing code must continue to work
2. **Incremental Changes**: Small, testable changes with frequent commits
3. **Test-Driven**: Run tests after every change, maintain 100% pass rate
4. **Documentation-Driven**: Update docs with code changes
5. **Zero Breaking Changes**: Use adapters, aliases, deprecation warnings

---

## Next Steps

1. ✅ Review and approve this plan
2. ⬜ Create GitHub issues for each task
3. ⬜ Set up tracking dashboard
4. ⬜ Begin Phase 1 implementation

---

## References

- **Full Plan**: `REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` (35,516 characters, comprehensive)
- **Current Architecture**: `README.md` (existing documentation)
- **Strategy Refactoring**: `PHASE3_TASK31_COMPLETION_SUMMARY.md` (completed work)
- **Tests**: `tests/unit_tests/logic/TDFOL/` (57 tests, 100% pass rate)

---

**Document Version**: 1.0  
**Last Updated**: 2026-02-19  
**Status**: ✅ Ready for Implementation
