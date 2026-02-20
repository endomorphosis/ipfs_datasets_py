# Master Refactoring and Improvement Plan — Logic Module

**Date:** 2026-02-20 (last updated)  
**Version:** 5.0 (supersedes all previous plans)  
**Status:** Phase 1 ✅ COMPLETE · Phase 2 🔄 In Progress · Phase 3 ✅ COMPLETE · Phase 4 🔄 Ongoing · Phase 5 📋 Planned  
**Scope:** `ipfs_datasets_py/logic/` and `tests/unit_tests/logic/`  
**MCP Integration:** `ipfs_datasets_py/mcp_server/tools/logic_tools/`

> **This document is the single authoritative plan** for refactoring and improving the logic module.  
> It synthesizes analysis of all 195 markdown files (69 active, 126 archived), 270 Python files (~93K LOC), and 237+ test files.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Inventory](#2-current-state-inventory)
3. [Critical Issues](#3-critical-issues)
4. [Phase 1: Documentation Consolidation](#4-phase-1-documentation-consolidation) ✅ COMPLETE
5. [Phase 2: Code Quality and Test Coverage](#5-phase-2-code-quality-and-test-coverage) 🔄 In Progress
6. [Phase 3: Feature Completions](#6-phase-3-feature-completions) ✅ COMPLETE
7. [Phase 4: Production Excellence](#7-phase-4-production-excellence) 🔄 Ongoing
8. [Phase 5: Code Reduction — God-Module Splits](#8-phase-5-code-reduction--god-module-splits) 📋 Planned
9. [Timeline and Priorities](#9-timeline-and-priorities)
10. [Success Criteria](#10-success-criteria)
11. [Document Inventory and Disposition](#11-document-inventory-and-disposition)

---

## 1. Executive Summary

The `ipfs_datasets_py/logic/` folder contains a **production-ready neurosymbolic reasoning system** with solid foundations, but accumulated significant **documentation sprawl** and several **oversized Python modules** across multiple parallel development sessions.

### What Was Accomplished (2026-02-10 to 2026-02-20)

| Component | Status | LOC | Tests |
|-----------|--------|-----|-------|
| **TDFOL** (Temporal Deontic FOL) | ✅ Phases 1–12 Complete | 19,311 | 765+ |
| **CEC Native** (Cognitive Event Calculus) | ✅ Phases 1–3 Complete | 8,547 | 418+ |
| **CEC Inference Rules** | ✅ All 67 rules, 7 modules | ~3,200 | 120+ |
| **Integration Layer** | ✅ Complete | ~10,000 | 110+ |
| **ZKP Module** | ⚠️ Simulation Only (warnings added) | ~633 | 35+ |
| **Common Infrastructure** | ✅ Complete + validators | ~2,200 | 86+ |
| **External Provers** | ✅ Integration Ready | ~800 | 40+ |
| **MCP Server Tools** | ✅ 27 tools across 12 groups | ~4,500 | 167+ |
| **Documentation** | ✅ Consolidated (69 active, 126 archived) | — | — |
| **TOTAL** | 🟢 Production-Ready Core | ~93,431 | 1,739+ |

### What Needs Work (Phases 2, 4, 5 — Remaining)

1. **NL Accuracy** — TDFOL 80% → 90%+, CEC 60% → 75%+
2. **God-Module Splits** — 6 files over 700 LOC need decomposition (worst: `prover_core.py` 2,927 LOC)
3. **CI Integration** — performance baselines not yet wired into GitHub Actions
4. **Multi-language NL** — Spanish, French, German (medium priority)
5. **Dependency audit** — `logic[api]` extras group for pip install

---

## 2. Current State Inventory

### 2.1 Python Files (Updated 2026-02-20)

| Directory | Files | LOC (approx) | Status | Notes |
|-----------|-------|-------------|--------|-------|
| `logic/TDFOL/` | ~35 | 19,311 | ✅ Production | Large files: performance_profiler.py (1,407), performance_dashboard.py (1,314) |
| `logic/CEC/native/` | ~30 | 8,547 | ✅ Production | **prover_core.py (2,927 LOC) needs split** |
| `logic/CEC/native/inference_rules/` | 8 | ~3,200 | ✅ Complete | 67 rules across 7 modules |
| `logic/integration/` | ~30 | ~10,000 | ✅ Complete | Several >700 LOC files need splitting |
| `logic/fol/` | ~15 | ~3,500 | ✅ Production | — |
| `logic/deontic/` | ~8 | ~2,000 | ✅ Production | — |
| `logic/common/` | ~5 | ~800 | ✅ Complete | validators, converters |
| `logic/zkp/` | ~8 | ~800 | ⚠️ Simulation | Simulation warnings added |
| `logic/external_provers/` | ~10 | ~1,500 | ✅ Integration | — |
| `logic/types/` | ~3 | ~500 | ✅ Complete | Shared type definitions |
| `logic/*.py` (root) | ~10 | ~2,000 | ✅ Complete | api.py, cli.py, etc. |
| **TOTAL** | **~270** | **~93,431** | 🟢 Strong | — |

#### Files Requiring Decomposition (Phase 5)

| File | Current LOC | Target LOC | Priority |
|------|------------|-----------|---------|
| `CEC/native/prover_core.py` | 2,927 | <600 | 🔴 Critical |
| `CEC/native/dcec_core.py` | 1,399 | <600 | 🟠 High |
| `integration/reasoning/proof_execution_engine.py` | 968 | <600 | 🟠 High |
| `integration/interactive/interactive_fol_constructor.py` | 787 | <600 | 🟡 Medium |
| `integration/reasoning/deontological_reasoning.py` | 776 | <600 | 🟡 Medium |
| `integration/reasoning/logic_verification.py` | 692 | <600 | ✅ Done (435 + 290 mixin) |
| `TDFOL/performance_profiler.py` | 1,407 | <800 | 🟡 Medium |
| `TDFOL/performance_dashboard.py` | 1,314 | <800 | 🟡 Medium |

### 2.2 Test Files (Updated 2026-02-20)

| Test Directory | Files | Tests | Pass Rate |
|---------------|-------|-------|-----------|
| `tests/logic/TDFOL/` | ~20 | 765+ | ~91.5% |
| `tests/logic/CEC/native/` | ~13 | 418+ | ~80-85% |
| `tests/logic/integration/` | ~5 | 110+ | ~90% |
| `tests/logic/common/` | ~4 | 86+ | ~95% |
| `tests/logic/deontic/` | ~3 | ~40 | ~90% |
| `tests/logic/fol/` | ~2 | ~30 | ~90% |
| `tests/logic/zkp/` | ~20 | 35+ | ~80% |
| Other (MCP, integration) | ~170+ | ~260+ | ~85% |
| **TOTAL** | **~237+** | **~1,744+** | **~87%** |

### 2.3 Markdown Files (✅ RESOLVED)

| Directory | Before | After (2026-02-20) | Status |
|-----------|--------|-------------------|--------|
| `logic/` (root) | 39 | 20 | ✅ Done |
| `logic/TDFOL/` | 52 | 15 | ✅ Done |
| `logic/CEC/` (active) | 31 | 12 | ✅ Done |
| `logic/zkp/` (active) | 22 | 8 | ✅ Done |
| All ARCHIVE/ dirs | — | 126 | ✅ Archived |
| **TOTAL active** | **196** | **69** | ✅ **65% reduction** |

> **Documentation goal met:** 69 active files across all directories (well under the 102 target).

### 2.4 Current Branch

| Branch | Focus | Status |
|--------|-------|--------|
| `copilot/create-refactoring-plan-markdown-files` | This plan update | 🔄 Active |

---

## 3. Critical Issues (Updated 2026-02-20)

### Issue 1: Documentation Sprawl (P0) — ✅ RESOLVED

**Resolution:** Phase 1 complete. Reduced from 196 → 69 active files (65% reduction). All historical files moved to ARCHIVE/ subdirs. Documentation maintenance policy established (see Section 7.4).

---

### Issue 2: God Modules — Several Files > 700 LOC (P1 — High)

**Problem:** Several Python files have grown to 700–2,927 lines, violating the single-responsibility principle and making them hard to test, review, and maintain.

| File | LOC | Core Problem |
|------|-----|-------------|
| `CEC/native/prover_core.py` | 2,927 | Proof search, strategies, caching, API all in one |
| `CEC/native/dcec_core.py` | 1,399 | Formula building + parsing + inference in one |
| `integration/reasoning/proof_execution_engine.py` | 968 | Orchestration + execution + validation mixed |
| `integration/interactive/interactive_fol_constructor.py` | 787 | UI + logic + serialization mixed |

**Impact:** Hard to test individual components; PR reviews are unwieldy; type-checking is slower.

**Solution:** Phase 5 — God-Module Splits (see Section 8).

---

### Issue 3: NL Processing Accuracy Gaps (P1 — High)

**Problem:** Both TDFOL (80% accuracy, ~69 test failures) and CEC (60% coverage) have natural language processing gaps.

**Impact:** Limits usability for real-world legal/technical text processing.

**Solution:** NL improvement sprints (Phase 2.2 and 2.3 below).

---

### Issue 4: CI Performance Integration (P2 — Medium)

**Problem:** Performance baselines exist (14x cache speedup validated) but are not wired into GitHub Actions as regression gates.

**Impact:** Performance regressions can be introduced silently.

**Solution:** Add performance regression test workflow (Phase 4.1).

---

### Issue 5: ZKP Module Misleading Status (P1) — ✅ RESOLVED

**Resolution:** `warnings.warn()` added to `ZKPProver.__init__` and `ZKPVerifier.__init__`. Both classes state simulation-only status prominently in docstrings.

---

## 4. Phase 1: Documentation Consolidation ✅ COMPLETE

**Duration:** Completed 2026-02-19  
**Priority:** P0 — Done  
**Result:** Reduced from 196 → 69 active markdown files (65% reduction)

### 4.1 Root Logic Level — ✅ Done (20 files)

Active files maintained:

| File | Purpose |
|------|---------|
| `README.md` | Module entry point |
| `QUICKSTART.md` | 5-minute getting started |
| `ARCHITECTURE.md` | System architecture |
| `API_REFERENCE.md` | Complete API reference |
| `FEATURES.md` | Feature catalog |
| `MASTER_REFACTORING_PLAN_2026.md` | This document (active plan) |
| `PROJECT_STATUS.md` | Current status snapshot |
| `EVERGREEN_IMPROVEMENT_PLAN.md` | Ongoing improvement backlog |
| `DEPLOYMENT_GUIDE.md` | Production deployment |
| `SECURITY_GUIDE.md` | Security best practices |
| `PERFORMANCE_TUNING.md` | Optimization guide |
| `CONTRIBUTING.md` | Contribution guidelines |
| `TROUBLESHOOTING.md` | Common issues and solutions |
| `ERROR_REFERENCE.md` | Error catalog |
| `KNOWN_LIMITATIONS.md` | Limitations and workarounds |
| `MIGRATION_GUIDE.md` | Migration from legacy APIs |
| `API_VERSIONING.md` | Stability guarantees |
| `UNIFIED_CONVERTER_GUIDE.md` | Converter usage guide |
| `INFERENCE_RULES_INVENTORY.md` | All 128 inference rules |
| `DOCUMENTATION_INDEX.md` | Navigation hub |

**Archive to `docs/archive/planning/` (19 files):**

- `COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` (superseded by this doc)
- `COMPREHENSIVE_REFACTORING_PLAN.md` (superseded)
- `REFACTORING_IMPROVEMENT_PLAN.md` (superseded)
- `REFACTORING_ACTION_CHECKLIST.md` (historical)
- `REFACTORING_COMPLETION_REPORT.md` (historical)
- `REFACTORING_COMPLETION_SUMMARY_2026.md` (historical)
- `REFACTORING_EXECUTIVE_SUMMARY.md` (historical)
- `REFACTORING_VISUAL_SUMMARY.md` (historical)
- `IMPROVEMENT_TODO.md` (merged into EVERGREEN_IMPROVEMENT_PLAN.md)
- `IMPLEMENTATION_ROADMAP.md` (superseded)
- `PHASE3_P0_VERIFICATION_REPORT.md` (historical)
- `PHASE7_PERFORMANCE_OPTIMIZATION_PLAN.md` (historical)
- `PHASE8_FINAL_TESTING_PLAN.md` (historical)
- `PHASE_4_5_7_FINAL_SUMMARY.md` (historical)
- `VERIFIED_STATUS_REPORT.md` (superseded by 2026 version)
- `VERIFIED_STATUS_REPORT_2026.md` (merged into PROJECT_STATUS.md)
- `TYPE_SYSTEM_STATUS.md` (merge into ARCHITECTURE.md)
- `CACHING_ARCHITECTURE.md` (merge into ARCHITECTURE.md or PERFORMANCE_TUNING.md)
- `FALLBACK_BEHAVIORS.md` (merge into KNOWN_LIMITATIONS.md)
- `ADVANCED_FEATURES_ROADMAP.md` (merge into EVERGREEN_IMPROVEMENT_PLAN.md)

### 4.2 TDFOL Directory — ✅ Done (15 files, historical in TDFOL/ARCHIVE/)

Active files maintained (15):

| File | Purpose |
|------|---------|
| `README.md` | TDFOL module overview |
| `STATUS_2026.md` | Current implementation status |
| `INDEX.md` | TDFOL documentation index |
| `QUICK_REFERENCE.md` | API quick reference |
| `COMPREHENSIVE_REFACTORING_PLAN_2026_02_19.md` | Most recent refactoring plan |
| `proof_tree_visualizer_README.md` | Proof tree usage |
| `countermodel_visualizer_README.md` | Countermodel usage |
| `performance_dashboard_README.md` | Dashboard usage |
| `performance_profiler_README.md` | Profiler usage |
| `README_security_validator.md` | Security validator guide |
| `FORMULA_DEPENDENCY_GRAPH.md` | Dependency graph guide |
| `ZKP_INTEGRATION_STRATEGY.md` | ZKP integration |
| `TRACK3_PRODUCTION_READINESS.md` | Production readiness |
| `PHASE3_IMPLEMENTATION_PLAN.md` | Phase 3 plan (active) |
| `UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | Latest roadmap |

**Archive to `TDFOL/ARCHIVE/` (37 files):**

All other TDFOL markdown files including:
- All `PHASE*_COMPLETION_REPORT.md` files (10+ files)
- All `PHASE*_PROGRESS.md` files
- Superseded refactoring plans (`REFACTORING_PLAN_2026_02_18.md`, etc.)
- Session summaries (`SESSION_SUMMARY_2026_02_18.md`, etc.)
- `REVISION_SUMMARY.md`, `IPFS_CID_MIGRATION_SUMMARY.md`
- Multiple `REFACTORING_EXECUTIVE_SUMMARY_*.md` versions
- `PHASE_2_AND_3_SUMMARY.md`, `TASK_11.*_COMPLETE.md` files
- `IMPLEMENTATION_QUICK_START_2026.md` (merge into README.md)
- `PHASE_13_WEEK_1_COMPLETE.md` and all similar completion reports

### 4.3 CEC Directory — ✅ Done (12 active files, historical in CEC/ARCHIVE/)

**Keep (10 essential files):**

| File | Purpose |
|------|---------|
| `README.md` | CEC module overview |
| `STATUS.md` | Implementation status |
| `QUICKSTART.md` | Quick start guide |
| `CEC_SYSTEM_GUIDE.md` | Comprehensive guide |
| `API_REFERENCE.md` | CEC API reference |
| `DEVELOPER_GUIDE.md` | Development guide |
| `MIGRATION_GUIDE.md` | Migration from submodules |
| `CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | Current plan |
| `native/NATIVE_REFACTORING_PLAN_2026.md` | Native refactoring plan |
| `native/NATIVE_REFACTORING_QUICK_GUIDE.md` | Quick reference |

**Archive to `CEC/ARCHIVE/` (21 files):**

- All `WEEK_0_*.md` files (5 files — historical progress)
- All `PHASE_*.md` files (6 files — historical phases)
- `CEC_REFACTORING_EXECUTIVE_SUMMARY.md`, `CEC_REFACTORING_EXECUTIVE_SUMMARY_2026.md`
- `CEC_REFACTORING_QUICK_REFERENCE.md`, `CEC_REFACTORING_QUICK_REFERENCE_2026.md`
- `REFACTORING_QUICK_REFERENCE.md`, `IMPLEMENTATION_QUICK_START.md`
- `VISUAL_REFACTORING_ROADMAP_2026.md`, `UNIFIED_REFACTORING_ROADMAP_2026.md`
- `PHASES_4_8_IMPLEMENTATION_PLAN.md`, `CEC_PHASES_4_8_EXECUTION_GUIDE.md`
- `PHASE_3_COMPLETE_AND_PHASES_4_8_SUMMARY.md`, `PHASE_3_TRACKER.md`
- `COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md` (superseded by 2026 version)

### 4.4 ZKP Directory — ✅ Done (8 active files, historical in zkp/ARCHIVE/)

**Keep (8 essential files):**

| File | Purpose |
|------|---------|
| `README.md` | ZKP module overview |
| `QUICKSTART.md` | Quick start |
| `IMPLEMENTATION_GUIDE.md` | Implementation details |
| `INTEGRATION_GUIDE.md` | Integration with TDFOL/CEC |
| `SECURITY_CONSIDERATIONS.md` | Security warnings |
| `EXAMPLES.md` | Usage examples |
| `PRODUCTION_UPGRADE_PATH.md` | Road to production |
| `TODO_MASTER.md` | ZKP work backlog |

**Archive to `zkp/ARCHIVE/` (14 files):**

- `BEFORE_AFTER_ANALYSIS.md`, `FINDINGS_SUMMARY.md`
- `COMPREHENSIVE_REFACTORING_PLAN_2026_02_18_NEW.md`
- `REFACTORING_COMPLETE_2026_02_18.md`, `REFACTORING_EXECUTIVE_SUMMARY.md`
- `ANALYSIS_NAVIGATION.md`
- Various `PHASE3*` and `GROTH16*` planning files
- `IMPROVEMENT_TODO.md`, `SETUP_GUIDE.md`, `THREAT_MODEL.md`
- `LEGAL_THEOREM_SEMANTICS.md` (merge into INTEGRATION_GUIDE.md)

### 4.5 Implementation Steps

```bash
# Phase 1.1: Create archive directories (if not exist)
mkdir -p ipfs_datasets_py/logic/docs/archive/planning/
mkdir -p ipfs_datasets_py/logic/TDFOL/ARCHIVE/
mkdir -p ipfs_datasets_py/logic/zkp/ARCHIVE/

# Phase 1.2: Archive root-level files (see list above)
# Move with ARCHIVED_ prefix to docs/archive/planning/

# Phase 1.3: Archive TDFOL files
# Move to TDFOL/ARCHIVE/

# Phase 1.4: Archive CEC files
# CEC already has ARCHIVE/ directory - use it

# Phase 1.5: Archive ZKP files  
# zkp already has ARCHIVE/ directory - use it

# Phase 1.6: Update DOCUMENTATION_INDEX.md
# Remove references to archived files, add new structure

# Phase 1.7: Update cross-references
# Fix broken links after archiving
```

---

## 5. Phase 2: Code Quality and Test Coverage

**Duration:** 2026-02-19 (partial) → ongoing  
**Priority:** P1 — High  
**Status:** 🔄 In Progress (CEC inference rules + ZKP warnings COMPLETE; NL improvements pending)  
**Goal:** Complete NL accuracy improvements, fix test failures, improve code quality

### 5.1 CEC Inference Rules Completion — ✅ COMPLETE

**Completed:**

1. ✅ **Added modal.py** — 5 rules: NecessityElimination, PossibilityIntroduction, NecessityDistribution, PossibilityDuality, NecessityConjunction
2. ✅ **Added resolution.py** — 6 rules: ResolutionRule, UnitResolutionRule, FactoringRule, SubsumptionRule, CaseAnalysisRule, ProofByContradictionRule
3. ✅ **Added specialized.py** — 9 rules: BiconditionalIntroduction/Elimination, ConstructiveDilemma, DestructiveDilemma, ExportationRule, AbsorptionRule, AdditionRule, TautologyRule, CommutativityConjunction
4. ✅ **Updated `__init__.py`** — exports all 67 rules across 8 modules (base + 7 rule modules)

**Acceptance Criteria:**
- [x] `CEC/native/inference_rules/` contains 8 modules (base + 7 rule modules)
- [x] 67 CEC inference rules implemented and tested (60+ new tests passing)
- [x] Performance: rule instantiation <1ms, can_apply() <0.5ms

### 5.2 TDFOL NL Accuracy Improvement — 🔄 Pending

**Remaining Work:**

1. **Diagnose ~69 NL test failures** — categorize by failure type (pattern gap vs. parser error)
2. **Improve pattern matching** — add/refine patterns for obligation, prohibition, temporal constructs
3. **Target accuracy:** 90%+ on legal/deontic text (from current ~80%)

**Acceptance Criteria:**
- [ ] NL test failures reduced from ~69 to <20
- [ ] NL conversion accuracy: 80% → 90%+
- [ ] Coverage: `TDFOL/nl/tdfol_nl_patterns.py` (826 LOC) tested with 50+ new cases

### 5.3 CEC NL Coverage Improvement — 🔄 Pending

**Remaining Work:**

1. Expand grammar patterns in `CEC/native/grammar_rules.yaml`
2. Add multi-domain vocabulary in `CEC/nl/domain_vocabularies/`
3. Validate with real legal text samples

**Acceptance Criteria:**
- [ ] NL coverage: 60% → 75%+
- [ ] Added 50+ new conversion patterns across all rule modules
- [ ] `CEC/nl/` parsers (french_parser.py, german_parser.py) reach 70%+ accuracy

### 5.4 ZKP Module Status Clarification — ✅ COMPLETE

**Completed:**

1. ✅ `warnings.warn()` added to `ZKPProver.__init__`
2. ✅ `warnings.warn()` added to `ZKPVerifier.__init__`
3. ✅ Docstrings state simulation-only status prominently

### 5.5 Test Coverage Gaps — 🔄 Partial

**Completed:**
- [x] 60 new CEC inference rule tests added

**Remaining:**
- [ ] Integration tests for `integration/reasoning/` modules (currently ~50% coverage)
- [ ] E2E tests: legal text → formal proof pipeline
- [ ] Stress tests for proof search under timeout conditions
- [ ] Tests for `common/validators.py` edge cases (injection attack patterns)

**Completed:**
- [x] 60 new tests for CEC modal/resolution/specialized rules (all passing)
- [x] Package export tests covering all 67+ rules in `__all__`

**Remaining:**
- [ ] Fix 69 NL test failures (see 5.2)
- [ ] Add 15+ integration tests for TDFOL↔CEC cross-module interactions

---

## 6. Phase 3: Feature Completions ✅ COMPLETE

**Duration:** Completed 2026-02-19  
**Priority:** P2 — Done  
**Goal:** High-value feature additions

### 6.1 MCP Server Integration — ✅ COMPLETE

**27 MCP tools across 12 tool groups (updated from earlier count):**

| Tool Group | File | Tools | Description |
|------------|------|-------|-------------|
| Temporal Deontic | `temporal_deontic_logic_tools.py` | 4 | Document consistency, case-law, RAG |
| TDFOL Parse | `tdfol_parse_tool.py` | 1 | Symbolic + NL formula parsing |
| TDFOL Prove | `tdfol_prove_tool.py` | 1 | Theorem proving (forward/backward/tableaux) |
| TDFOL Convert | `tdfol_convert_tool.py` | 1 | TDFOL↔DCEC/FOL/TPTP/SMT-LIB |
| TDFOL Visualize | `tdfol_visualize_tool.py` | 2 | Proof trees, countermodels |
| TDFOL KB | `tdfol_kb_tool.py` | 2 | Knowledge base management |
| CEC Inference | `cec_inference_tool.py` | 4 | List/apply/check/info for 67 rules |
| CEC Prove | `cec_prove_tool.py` | 2 | DCEC theorem proving + tautology check |
| CEC Parse | `cec_parse_tool.py` | 2 | NL→DCEC + formula validation |
| CEC Analysis | `cec_analysis_tool.py` | 2 | Structural analysis + complexity |
| Capabilities | `logic_capabilities_tool.py` | 2 | Discovery + health check |
| GraphRAG | `logic_graphrag_tool.py` | 2 | KG construction + RAG verification |

**167+ MCP logic tool tests passing.**

### 6.2 TDFOL Documentation Enhancement — 🔄 Pending

**Acceptance Criteria:**
- [ ] 100% of public classes/methods have docstrings
- [ ] Usage examples in all major module docstrings
- [ ] API_REFERENCE.md updated with new test coverage

### 6.3 Multi-Language NL Support — 🔄 In Progress (FR/DE stubs exist)

**Status:** `CEC/nl/french_parser.py` and `german_parser.py` exist; Spanish stub pending

**Acceptance Criteria:**
- [ ] Spanish parser added (`CEC/nl/spanish_parser.py`)
- [ ] All three parsers reach 70%+ accuracy on legal text samples
- [ ] Language detection integrated into main NL pipeline

**Acceptance Criteria:**
- [ ] Spanish NL → TDFOL/DCEC conversion (80%+ accuracy)
- [ ] French NL → TDFOL/DCEC conversion (80%+ accuracy)
- [ ] German NL → TDFOL/DCEC conversion (75%+ accuracy)
- [ ] 100+ tests per language
- [ ] Language detection: >95% accuracy

### 6.4 GraphRAG Deep Integration

**Status:** ✅ COMPLETE — MCP tools implemented (2026-02-19)

**Completed:**

1. ✅ **`logic_build_knowledge_graph`** — Extracts logical entities (obligations, permissions,
   prohibitions) from text using TDFOL NL converter + regex fallback. Returns graph nodes
   and edges in a format compatible with `graph_create` / `graph_add_entity` tools.

2. ✅ **`logic_verify_rag_output`** — Verifies a RAG-generated claim against a list of
   logical constraints using the TDFOL prover. Returns `consistent` bool,
   `violations` list, and `verification_score` (0.0–1.0).

3. ✅ **20 GraphRAG tool tests** — all passing

**Remaining (future enhancements):**
- [ ] Deep IPFS storage integration for verified proof graphs
- [ ] Theorem-augmented retrieval (proof-as-evidence in RAG responses)
- [ ] Semantic search with logical preconditions

---

## 7. Phase 4: Production Excellence 🔄 Ongoing

**Duration:** Continuous  
**Priority:** P1/P2  
**Goal:** Maintain and improve production quality

### 7.1 Performance Monitoring

**Status:** ✅ Baseline tests added, CI integration pending

**Completed:**
- [x] `tests/unit_tests/logic/test_performance_baselines.py` — 13+ tests
- [x] CEC rule instantiation <1ms, can_apply() <0.5ms (validated)
- [x] Cache speedup: 14x (validated in proof cache)
- [x] Import time < 2s (validated)

**Remaining:**
- [ ] Wire performance baselines into GitHub Actions (fail PR if >2x regression)
- [ ] Alert on proof times exceeding 2x baseline

### 7.2 Security Hardening

**Status:** ✅ Core security complete

**Completed:**
- [x] `logic/common/validators.py` — 5 validators with injection detection
- [x] All 5 validators exported from `common/__init__.py`
- [x] ZKP runtime warnings (`warnings.warn()`)
- [x] 36 validator tests

**Remaining:**
- [ ] Rate limiting for MCP tool calls
- [ ] Formal ZKP security audit before production upgrade

### 7.3 Dependency Management

**Current State:** 70+ optional dependency graceful fallbacks

**Required Actions:**
- [ ] Audit all ImportError handlers — ensure all are tested
- [x] Create `logic[api]` extras group in `setup.py` for FastAPI + uvicorn (`logic-api` key)
- [ ] Document minimum vs recommended vs full dependency sets
- [ ] CI test matrix: bare Python 3.12 + core dependencies only

### 7.4 Documentation Maintenance Policy

**Rules (enforced from 2026-02-19 onward):**
1. **Never create new markdown files in active directories** for progress reports
2. **Use git commit messages** for progress tracking (not markdown files)
3. **Archive immediately** any completion report after the work is merged
4. **One status document** per subsystem, updated in place (don't create new ones)
5. **Quarterly review** — archive any document not referenced in 90 days

---

## 8. Phase 5: Code Reduction — God-Module Splits 📋 Planned

**Duration:** 3–5 weeks  
**Priority:** P1 — Important for maintainability  
**Goal:** Break up modules >700 LOC into focused, single-responsibility components

### 8.1 `CEC/native/prover_core.py` (2,927 → ~4 files × <600 LOC) 🔴 Critical

**Proposed Split:**

| New File | Responsibility | Est. LOC |
|----------|---------------|---------|
| `prover_core.py` | Core proof search entry points only | ~400 |
| `proof_strategies.py` | Strategy pattern implementations | ~500 |
| `proof_cache_manager.py` | Cache management and CID operations | ~350 |
| `proof_result_builder.py` | Result assembly, formatting, serialization | ~300 |

**Approach:**
1. Extract `ProofStrategy` subclasses to `proof_strategies.py`
2. Extract cache I/O methods to `proof_cache_manager.py`
3. Extract result building methods to `proof_result_builder.py`
4. Keep `prover_core.py` as thin orchestration layer
5. Add `__all__` and deprecation shims for any moved public names
6. Add tests for each new module

**Acceptance Criteria:**
- [ ] `prover_core.py` reduced to <600 LOC
- [ ] All existing `prover_core` tests still pass
- [ ] New tests added for split modules (20+ tests)
- [ ] Import compatibility shims in place for any moved symbols

### 8.2 `CEC/native/dcec_core.py` (1,399 → ~2 files × <700 LOC) 🟠 High

**Proposed Split:**

| New File | Responsibility | Est. LOC |
|----------|---------------|---------|
| `dcec_core.py` | Core DCEC data model and formula types | ~600 |
| `dcec_inference.py` | Inference engine and rule dispatch | ~600 |

**Approach:**
1. Separate pure data model (Formula, Term, Atom classes) from inference logic
2. Move rule application methods to `dcec_inference.py`
3. Keep shared types in `dcec_core.py`

**Acceptance Criteria:**
- [ ] `dcec_core.py` reduced to <700 LOC
- [ ] New `dcec_inference.py` module < 700 LOC
- [ ] All existing tests pass

### 8.3 `integration/reasoning/proof_execution_engine.py` (968 → ~2 files × <500 LOC) 🟠 High

**Proposed Split:**

| New File | Responsibility | Est. LOC |
|----------|---------------|---------|
| `proof_execution_engine.py` | Orchestration and public API | ~400 |
| `proof_step_executor.py` | Step-level execution logic | ~450 |

**Acceptance Criteria:**
- [ ] `proof_execution_engine.py` reduced to <500 LOC
- [ ] All existing tests pass

### 8.4 `integration/reasoning/deontological_reasoning.py` (776 → ~600 LOC) 🟡 Medium

**Approach:** Extract `DeonticConflictResolver` class to `deontic_conflict_resolver.py`

**Acceptance Criteria:**
- [ ] Main file reduced to <600 LOC
- [ ] Extracted class has unit tests (15+ tests)

### 8.5 `integration/interactive/interactive_fol_constructor.py` (787 → ~600 LOC) 🟡 Medium

**Approach:** Extract serialization/deserialization methods to `fol_constructor_io.py`

**Acceptance Criteria:**
- [ ] Main file reduced to <600 LOC

### 8.6 `integration/reasoning/logic_verification.py` (692 → 435 LOC) ✅ Done

**Completed:** Extracted backend methods to `_logic_verifier_backends_mixin.py` (290 LOC).
`LogicVerifier` now inherits from `LogicVerifierBackendsMixin`.

### 8.7 TDFOL Visualization Tools (performance_profiler 1,407 + performance_dashboard 1,314) 🟡 Medium

**Note:** These files are legitimately large (they implement complex visualization features).
Consider splitting only if test coverage or type checking becomes problematic.

**Provisional Approach:**
- `performance_profiler.py` → `profiler_core.py` + `profiler_reporters.py`
- `performance_dashboard.py` → `dashboard_core.py` + `dashboard_widgets.py`

---

## 9. Timeline and Priorities (Updated 2026-02-20)

### Completed ✅
| Phase | Completed | Result |
|-------|-----------|--------|
| Phase 1: Documentation Consolidation | 2026-02-19 | 196 → 69 active files |
| Phase 2.1: CEC Inference Rules | 2026-02-19 | 67 rules across 8 modules |
| Phase 2.4: ZKP Module Warnings | 2026-02-19 | `warnings.warn()` added |
| Phase 3: MCP Server Tools | 2026-02-19 | 27 tools across 12 groups |
| Phase 3: GraphRAG Integration | 2026-02-19 | 2 tools, 20 tests |

### Near Term (Next 2–4 weeks)
| Task | Phase | Effort | Priority |
|------|-------|--------|---------|
| Fix ~69 TDFOL NL test failures | 2.2 | 8h | 🔴 P1 |
| Improve CEC NL coverage (60%→75%) | 2.3 | 12h | 🟠 P1 |
| Split `prover_core.py` (2,927→4×<600 LOC) | 5.1 | 8h | 🟠 P1 |
| Add TDFOL docstrings (Phase 3.2) | 3.2 | 6h | 🟡 P2 |
| CI performance regression gates | 4.1 | 4h | 🟡 P2 |

### Medium Term (Weeks 4–8)
| Task | Phase | Effort | Priority |
|------|-------|--------|---------|
| Split `dcec_core.py` (1,399→2×<700) | 5.2 | 6h | 🟠 P1 |
| Split `proof_execution_engine.py` (968→2×<500) | 5.3 | 4h | 🟡 P2 |
| Split `deontological_reasoning.py` (776→<600) | 5.4 | 4h | 🟡 P2 |
| Spanish NL parser | 3.3 | 16h | 🟡 P2 |
| ~~`logic[api]` extras group~~ ✅ Done | 4.3 | 2h | 🟡 P2 |

### Ongoing (Per PR / Monthly / Quarterly)
| Task | Frequency |
|------|-----------|
| Performance regression testing (CI) | Per PR |
| Documentation archive review | Monthly |
| Security audit | Quarterly |
| Dependency vulnerability scan | Quarterly |

---

## 10. Success Criteria (Updated 2026-02-20)

### Phase 1 ✅ COMPLETE

- [x] Total active markdown files: 196 → 69 (target was ≤102)
- [x] No phase completion reports in active directories
- [x] Single status document per subsystem
- [x] DOCUMENTATION_INDEX.md reflects current structure

### Phase 2 ✅ Partial — Remaining Items

- [x] CEC inference rules: 8 modules, 67 rules total
- [x] ZKP module: simulation warnings in place
- [ ] TDFOL NL test failures: ~69 → <20
- [ ] CEC NL coverage: 60% → 75%+
- [ ] Overall test pass rate: 87% → 90%+

### Phase 3 ✅ COMPLETE

- [x] MCP tools: 27 tools replacing REST API
- [x] GraphRAG integration: text → KG pipeline functional
- [ ] TDFOL documentation: 100% public methods with docstrings (deferred)
- [ ] Spanish NL support: 80%+ accuracy (deferred)

### Phase 4 🔄 Ongoing

- [x] Input validation security module (36 tests)
- [x] ZKP simulation warnings
- [ ] CI performance gates (per PR)
- [x] `logic[api]` pip extras group (`logic-api` key in setup.py)
- [ ] Zero known vulnerabilities in dependencies

### Phase 5 📋 Planned

- [ ] `prover_core.py` < 600 LOC (currently 2,927)
- [ ] `dcec_core.py` < 700 LOC (currently 1,399)
- [ ] `proof_execution_engine.py` < 500 LOC (currently 968)
- [ ] `deontological_reasoning.py` < 600 LOC (currently 776)
- [ ] All split modules have dedicated unit tests

---

## 11. Document Inventory and Disposition (Updated 2026-02-20)

### 11.1 Active Documents (69 total)

**Root Level (20):**
- `README.md` — Module overview ✅
- `MASTER_REFACTORING_PLAN_2026.md` — This document ✅
- `PROJECT_STATUS.md` — Current status snapshot ✅
- `EVERGREEN_IMPROVEMENT_PLAN.md` — Ongoing backlog ✅
- `ARCHITECTURE.md`, `API_REFERENCE.md`, `FEATURES.md` ✅
- `QUICKSTART.md`, `UNIFIED_CONVERTER_GUIDE.md` ✅
- `DEPLOYMENT_GUIDE.md`, `SECURITY_GUIDE.md`, `PERFORMANCE_TUNING.md` ✅
- `CONTRIBUTING.md`, `TROUBLESHOOTING.md`, `ERROR_REFERENCE.md` ✅
- `KNOWN_LIMITATIONS.md`, `MIGRATION_GUIDE.md`, `API_VERSIONING.md` ✅
- `INFERENCE_RULES_INVENTORY.md`, `DOCUMENTATION_INDEX.md` ✅

**TDFOL (15):** STATUS_2026.md, README.md, INDEX.md, QUICK_REFERENCE.md, + 11 component docs

**CEC (12):** STATUS.md, README.md, QUICKSTART.md, CEC_SYSTEM_GUIDE.md, + 8 reference docs

**ZKP (8):** README.md, QUICKSTART.md, IMPLEMENTATION_GUIDE.md, INTEGRATION_GUIDE.md, + 4 docs

**Per-subdirectory READMEs (14):** common, fol, deontic, types, tools, external_provers, integration + subdirs

### 11.2 Archive Policy

**Archive Criteria:**
1. Progress reports / completion summaries → Archive after phase completion
2. Superseded planning documents → Archive when replaced
3. Session summaries → Archive after session completes
4. Phase tracking files → Archive after phase merges to main

**126 files already archived** in:
- `docs/archive/` (root-level historical docs)
- `TDFOL/ARCHIVE/` (TDFOL historical docs)
- `CEC/ARCHIVE/` (CEC historical docs)
- `zkp/ARCHIVE/` (ZKP historical docs)

---

## Appendix A: Inference Rules Summary (Updated 2026-02-20)

| Module | TDFOL Rules | CEC Rules | Total |
|--------|------------|-----------|-------|
| Propositional | 15 | 10 | 25 |
| First-Order | 10 | 5 | 15 |
| Temporal | 10 | 15 | 25 |
| Deontic | 8 | 7 | 15 |
| Temporal-Deontic | 7 | — | 7 |
| Cognitive | — | 13 | 13 |
| Modal | — | 5 | 5 |
| Resolution | — | 6 | 6 |
| Specialized | — | 9 | 9 |
| **TOTAL** | **50** | **70** | **120** |

> All 67 CEC inference rules are now implemented and tested (modal + resolution + specialized modules added 2026-02-19).

---

## Appendix B: Key Architecture Decisions

### Decision 1: Native vs Submodule CEC

**Decision:** Prioritize native Python implementation over Java/GF submodules  
**Rationale:** Zero external dependencies, 2–4x faster, modern Python 3.12+ type system  
**Status:** Native at 81% coverage of submodule features, production-ready

### Decision 2: Grammar YAML Externalization

**Decision:** Logic grammar rules stored in `grammar_rules.yaml`, loaded at runtime  
**Rationale:** Multi-language support, version control, no code changes for rule updates  
**Status:** Implemented for CEC (`CEC/native/grammar_rules.yaml`)

### Decision 3: CID-Based Proof Caching

**Decision:** Use IPFS Content IDs (CIDs) as cache keys for proofs  
**Rationale:** Distributed caching, content-addressable, reproducible  
**Status:** Implemented in both TDFOL (`tdfol_proof_cache.py`) and CEC (`cec_proof_cache.py`)

### Decision 4: ZKP as Simulation Only

**Decision:** Maintain ZKP module as educational simulation, not production cryptography  
**Rationale:** Real ZKP (Groth16) requires Rust/Go FFI; pure Python is simulation  
**Status:** Simulation implemented; production upgrade path documented in `zkp/PRODUCTION_UPGRADE_PATH.md`

### Decision 5: MCP Tools instead of REST API

**Decision:** Replace FastAPI REST API with MCP Server tool registration  
**Rationale:** Integrates directly with AI assistant workflows; no uvicorn dependency; 27 tools available through the existing MCP infrastructure  
**Status:** 27 MCP tools implemented; `api_server.py` deprecated

---

## Appendix C: Test Coverage Targets

| Component | Current | Phase 2 Target | Phase 5 Target |
|-----------|---------|----------------|----------------|
| TDFOL Core | 91.5% pass | 95% pass | 97% pass |
| CEC Native | 80-85% pass | 90% pass | 93% pass |
| Integration | ~50% pass | 80% pass | 90% pass |
| NL Processing | 75% pass | 85% pass | 90% pass |
| ZKP (simulation) | 80% pass | 85% pass | 85% pass |
| MCP Tools | 167+ tests | 200+ tests | 250+ tests |
| **Overall** | **~87%** | **~90%** | **~93%** |

---

**Document Status:** Active Plan — Being Implemented  
**Next Action:** Phase 2.2 TDFOL NL Accuracy; Phase 5 God-Module Splits  
**Review Schedule:** After each phase completion, update this document  
**Created:** 2026-02-19 | **Last Updated:** 2026-02-20  
**Supersedes:** All previous refactoring plans (see docs/archive/planning/)
