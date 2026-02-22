# TODO List for logic/integration/

## Status: Phase 8 (Advanced Coverage) - Active

**Last Updated:** 2026-02-22

## Current State (2026-02-22)
- **Test Coverage:** 99% (7,899 lines; 55 uncovered = dead code + symai-gated paths)
- **Integration tests:** 2,907+ passing, 106 skipped (symai-dependent)
- **All 1,463 integration tests passing** (sessions 52–58 fixed remaining failures)
- **Security:** Rate limiting and input validation integrated ✅
- **Bridge Pattern:** BaseProverBridge ABC implemented ✅
- **God-module splits:** All 6 oversized files split ✅

## Completed Tasks

### Phase 5 — Code Reduction (All Done ✅)
- [x] Split `prover_core.py` (4,245 LOC → 649 + extended_rules 1,116 LOC)
- [x] Split `dcec_core.py` (1,399 LOC → 849 + dcec_types 379 LOC)
- [x] Split `proof_execution_engine.py` (968 LOC → 460 + _prover_backend_mixin 527 LOC)
- [x] Split `deontological_reasoning.py` (776 LOC → 482 + _deontic_conflict_mixin 304 LOC)
- [x] Split `interactive_fol_constructor.py` (787 LOC → 521 + _fol_constructor_io 299 LOC)
- [x] Split `logic_verification.py` (692 LOC → 435 + _logic_verifier_backends_mixin 290 LOC)

### Type System (Done ✅)
- [x] `logic/types/` directory for shared types (ProofResult, ProofStatus, etc.)
- [x] `DeonticFormula`, `DeonticOperator` in `CEC/native/dcec_core.py` (dcec_types.py split)
- [x] `LogicTranslationTarget` in `converters/logic_translation_core.py`
- [x] `ProofResult`, `ProofStatus` in `reasoning/proof_execution_engine_types.py`

### Coverage Milestones (All Done ✅)
- [x] 38% → 50% (session 5)
- [x] 50% → 60% (session 6)
- [x] 60% → 70% (session 8)
- [x] 70% → 80% (sessions 9–12)
- [x] 80% → 85% (session 13)
- [x] 85% → 86% (sessions 14–15)
- [x] 86% → 99% (sessions 16–27)
- [x] 99% maintained (sessions 28–58)

### Bug Fixes (All Done ✅)
- [x] `IPFSProofCache.__init__()` — removed invalid `cache_dir` kwarg
- [x] `IPFSProofCache.put()` — fixed arg order
- [x] `document_consistency_checker.py` — 2 broken relative imports fixed
- [x] `caselaw_bulk_processor.py` — broken relative import fixed
- [x] `temporal_deontic_api.py` — `query_similar_theorems()` → `retrieve_relevant_theorems()`
- [x] `reasoning_coordinator.py` + `hybrid_confidence.py` — `.valid` → `.is_proved()`
- [x] `_prover_backend_mixin.py` — `"sat"` matched `"unsat"` substring (reordered checks)
- [x] `deontological_reasoning_types.py` — `DeonticConflict` missing `id` field
- [x] `ProofExecutionEngine` — missing `prove`/`prove_with_all_available_provers`/`check_consistency` aliases
- [x] `prover_installer.py` — missing `import logging`
- [x] `batch_processing.py` — `_anyio_gather(tasks)` → `_anyio_gather(*tasks)`
- [x] `proof_cache.py` — full standalone backward-compat implementation (LRU/TTL/thread-safe)
- [x] `logic_verification.py` — `_validate_formula_syntax` returns `status=="valid"`
- [x] `cec_bridge.py` — `result.prover_used→result.best_prover`, `status.value` guard, `get_statistics→get_stats()`

## Active Tasks (Phase 8)

### TDFOL Strategy Coverage (Priority: High)
- [ ] `strategies/modal_tableaux.py` 74% → 95% (session target: `_prove_basic_modal`/`estimate_cost`/`_prove_with_shadowprover`)
- [ ] `strategies/cec_delegate.py` 88% → 98% (CEC=True paths + exception handling)
- [ ] `strategies/strategy_selector.py` 85% → 97% (fallback/`add_strategy`/`select_multiple`)

### CEC Coverage (Priority: High)
- [ ] `CEC/proof_strategies.py` 0% → 80%+ (baseline not yet tested)
- [ ] `CEC/nl/tdfol_nl_preprocessor.py` 60% → 75% (requires spaCy for remaining 25%)

### Integration Remaining (Priority: Low — dead code)
- [ ] `integration/` 55 uncovered lines — dead code (lines 79/397/474/529-530) and symai-gated paths; no action needed unless symai is added to CI

### CI / Infrastructure (Priority: Medium)
- [ ] Wire performance baselines into GitHub Actions (fail PR if >2x regression)
- [ ] Add `spaCy` to CI optional extras and rerun ~65 deferred TDFOL NL tests

## Notes
- See `MASTER_REFACTORING_PLAN_2026.md` for the authoritative plan (Phases 1–8)
- All changes maintain backward compatibility via shims
- symai-dependent code paths (~55 lines) cannot be covered without `pip install symbolicai`
