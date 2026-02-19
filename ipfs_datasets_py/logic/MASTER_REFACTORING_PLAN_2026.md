# Master Refactoring and Improvement Plan — Logic Module

**Date:** 2026-02-19  
**Version:** 3.0 (supersedes all previous plans)  
**Status:** Active — Ready for Implementation  
**Scope:** `ipfs_datasets_py/logic/` and `tests/unit_tests/logic/`

> **This document is the single authoritative plan** for refactoring and improving the logic module.  
> It synthesizes analysis of all 196 markdown files, 265 Python files, and 184+ test files.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Inventory](#2-current-state-inventory)
3. [Critical Issues](#3-critical-issues)
4. [Phase 1: Documentation Consolidation](#4-phase-1-documentation-consolidation)
5. [Phase 2: Code Quality and Test Coverage](#5-phase-2-code-quality-and-test-coverage)
6. [Phase 3: Feature Completions](#6-phase-3-feature-completions)
7. [Phase 4: Production Excellence](#7-phase-4-production-excellence)
8. [Timeline and Priorities](#8-timeline-and-priorities)
9. [Success Criteria](#9-success-criteria)
10. [Document Inventory and Disposition](#10-document-inventory-and-disposition)

---

## 1. Executive Summary

The `ipfs_datasets_py/logic/` folder contains a **production-ready neurosymbolic reasoning system** with solid foundations, but suffers from significant **documentation sprawl** accumulated across multiple parallel development sessions. The core code is excellent; the surrounding documentation has grown to 196 markdown files — approximately 3× the appropriate number.

### What Was Accomplished (2026-02-10 to 2026-02-19)

| Component | Status | LOC | Tests |
|-----------|--------|-----|-------|
| **TDFOL** (Temporal Deontic FOL) | ✅ Phases 1–12 Complete | 19,311 | 765+ |
| **CEC Native** (Cognitive Event Calculus) | 🔄 Phases 1–3 Complete | 8,547 | 418+ |
| **Integration Layer** | ✅ Complete | ~1,100 | 110+ |
| **ZKP Module** | ⚠️ Simulation Only | ~633 | 35+ |
| **Common Infrastructure** | ✅ Complete | ~2,000 | 50+ |
| **External Provers** | ✅ Integration Ready | ~800 | 40+ |
| **TOTAL** | 🟢 Production-Ready Core | ~32,391 | 1,418+ |

### What Needs Work

1. **Documentation Sprawl** (highest priority) — 196 markdown files; target: 65–70
2. **CEC Inference Rules** — modal, resolution, and specialized modules pending merge
3. **NL Accuracy** — TDFOL 80% → 90%+, CEC 60% → 75%+
4. **REST API** — not yet implemented (high user value)
5. **Test Failures** — 69 NL-related test failures in TDFOL need investigation

---

## 2. Current State Inventory

### 2.1 Python Files

| Directory | Files | LOC (approx) | Status |
|-----------|-------|-------------|--------|
| `logic/TDFOL/` | ~35 | 19,311 | ✅ Production |
| `logic/CEC/native/` | ~30 | 8,547 | ✅ Production |
| `logic/CEC/native/inference_rules/` | 6 | ~2,000 | 🔄 Expanding |
| `logic/integration/` | ~8 | ~1,100 | ✅ Complete |
| `logic/fol/` | ~15 | ~3,500 | ✅ Production |
| `logic/deontic/` | ~8 | ~2,000 | ✅ Production |
| `logic/common/` | ~5 | ~800 | ✅ Complete |
| `logic/zkp/` | ~8 | ~800 | ⚠️ Simulation |
| `logic/external_provers/` | ~10 | ~1,500 | ✅ Integration |
| `logic/types/` | ~3 | ~500 | ✅ Complete |
| `logic/*.py` (root) | ~10 | ~2,000 | ✅ Complete |
| **TOTAL** | **~138+** | **~42,000** | 🟢 Strong |

### 2.2 Test Files

| Test Directory | Files | Tests | Pass Rate |
|---------------|-------|-------|-----------|
| `tests/logic/TDFOL/` | ~20 | 765+ | ~91.5% |
| `tests/logic/CEC/native/` | ~13 | 418+ | ~80-85% |
| `tests/logic/integration/` | ~5 | 110+ | ~90% |
| `tests/logic/common/` | ~4 | 50+ | ~95% |
| `tests/logic/deontic/` | ~3 | ~40 | ~90% |
| `tests/logic/fol/` | ~2 | ~30 | ~90% |
| Other | ~8 | ~60 | ~85% |
| **TOTAL** | **~55** | **~1,473+** | **~87%** |

### 2.3 Markdown Files (The Core Problem)

| Directory | Current Count | Target Count | Action |
|-----------|--------------|-------------|--------|
| `logic/` (root) | 39 | 20 | Archive 19 files |
| `logic/TDFOL/` | 52 | 15 | Archive 37 files |
| `logic/CEC/` | 31 | 10 | Archive 21 files |
| `logic/CEC/native/` | 2 | 2 | Keep as-is |
| `logic/zkp/` | 22 | 8 | Archive 14 files |
| `logic/zkp/ARCHIVE/` | 10 | 10 | Already archived |
| `logic/docs/archive/` | ~25 | ~25 | Already archived |
| `logic/integration/` | 2 | 2 | Keep as-is |
| `logic/common/` | 2 | 2 | Keep as-is |
| Other | ~11 | ~8 | Minor cleanup |
| **TOTAL** | **196** | **~102** | **Archive ~94 files** |

> **Note:** "Archive" means moving to an appropriate `ARCHIVE/` or `docs/archive/` subdirectory, never deleting.

### 2.4 Parallel Development Branches (As of 2026-02-19)

The following work streams are in progress on separate branches and need to be coordinated:

| Branch | Focus | Status |
|--------|-------|--------|
| `copilot/refactor-improvement-plan-cec` | CEC inference rules Phase 1–3 | 🔄 Active |
| `copilot/finish-phase-2-and-3` | TDFOL Phase 3 (139 tests) | 🔄 Active |
| `copilot/refactor-and-improve-tdfol-folder` | TDFOL NL consolidation | 🔄 Active |
| `copilot/create-refactoring-plan-markdown` | This plan document | 🔄 Active |

---

## 3. Critical Issues

### Issue 1: Documentation Sprawl (P0 — Critical)

**Problem:** 196 markdown files across the logic folder. Previous refactoring reduced root level from 61→30, but parallel work sessions each added 5–20 new markdown files (progress reports, completion summaries, phase reports), causing documentation to balloon back to 196.

**Impact:** Developers cannot find relevant documentation; it's buried under progress reports.

**Root Cause:** Each AI session creates new documentation files but doesn't clean up old ones.

**Solution:** Systematic archiving policy (see Phase 1).

---

### Issue 2: CEC Inference Rules Fragmentation (P1 — High)

**Problem:** The CEC native refactoring extracted 88 inference rules into 9 modules on `copilot/refactor-improvement-plan-cec`, but only 5 modules are on the main/current branch (base, propositional, temporal, deontic, cognitive). Modules for modal, resolution, and specialized rules are pending merge.

**Impact:** Missing 43+ inference rules in the current codebase.

**Solution:** Merge the CEC refactoring branch (see Phase 2).

---

### Issue 3: NL Processing Accuracy Gaps (P1 — High)

**Problem:** Both TDFOL (80% accuracy, 69 test failures) and CEC (60% coverage) have natural language processing gaps.

**Impact:** Limits usability for real-world legal/technical text processing.

**Solution:** NL improvement sprints (see Phase 3).

---

### Issue 4: No REST API (P2 — Medium)

**Problem:** The logic module exposes Python APIs only. No HTTP interface for external consumers.

**Impact:** Cannot be consumed by non-Python services or web applications.

**Solution:** FastAPI-based REST API implementation (see Phase 3).

---

### Issue 5: ZKP Module Misleading Status (P1 — High)

**Problem:** ZKP module is simulation-only but README and some docs imply production-readiness.

**Impact:** Users may rely on it for security-critical applications.

**Solution:** Clear warning labels and a production upgrade roadmap (see Phase 2).

---

## 4. Phase 1: Documentation Consolidation

**Duration:** 1–2 weeks  
**Priority:** P0 — Do First  
**Goal:** Reduce 196 markdown files to ~102, create clear navigation, eliminate confusion

### 4.1 Root Logic Level (39 → 20 files)

**Keep (20 essential files):**

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

### 4.2 TDFOL Directory (52 → 15 files)

**Keep (15 essential files):**

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

### 4.3 CEC Directory (31 → 10 files)

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

### 4.4 ZKP Directory (22 → 8 files)

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

**Duration:** 2–4 weeks  
**Priority:** P1 — High  
**Goal:** Complete CEC Phase 3, fix test failures, improve code quality

### 5.1 CEC Inference Rules Completion

**Status:** Phases 1–2 complete on `copilot/refactor-improvement-plan-cec`, Phase 3 complete per latest status.

**Remaining Work:**

1. **Merge CEC refactoring branch** — adds modal, resolution, specialized modules (43+ rules)
2. **Verify 88 total rules** — ensure all rules from both native and submodule implementations are represented
3. **Update INFERENCE_RULES_INVENTORY.md** — reflect final count (target: 215+ total with TDFOL)
4. **Performance validation** — verify <0.1ms targets for all new rule modules

**Acceptance Criteria:**
- [ ] `CEC/native/inference_rules/` contains 9 modules (base + 8 rule modules)
- [ ] All 88 CEC inference rules implemented and tested
- [ ] Performance: rule instantiation <0.1ms, can_apply() <0.1ms
- [ ] Integration tests: rule chaining, cross-module combinations pass

### 5.2 TDFOL NL Accuracy Improvement

**Status:** 80% accuracy, 69 test failures (NL-related)

**Remaining Work:**

1. **Diagnose 69 NL test failures** — categorize by failure type
2. **Improve pattern matching** — add/refine patterns for common failure cases
3. **NL module consolidation** — merge 4 files → 2 (on `copilot/refactor-and-improve-tdfol-folder`)
4. **Target accuracy:** 90%+ on legal/deontic text

**Acceptance Criteria:**
- [ ] NL test failures reduced from 69 to <20
- [ ] NL conversion accuracy: 80% → 90%+
- [ ] `nl/llm.py` and `nl/utils.py` consolidated (from 4 files)
- [ ] 10+ new NL tests covering previously-failing cases

### 5.3 CEC NL Coverage Improvement

**Status:** 60% NL coverage, pattern-based approach

**Remaining Work:**

1. **Extend pattern library** — add 50+ new patterns for common DCEC statements
2. **Improve grammar engine** — enhance enhanced_grammar_parser.py
3. **Add context awareness** — pronoun resolution, cross-sentence references
4. **Target coverage:** 75%+

**Acceptance Criteria:**
- [ ] NL coverage: 60% → 75%+
- [ ] Added 50+ new conversion patterns
- [ ] Context resolution working for 2-sentence inputs
- [ ] 25+ new NL conversion tests

### 5.4 ZKP Module Status Clarification

**Status:** Simulation only — no cryptographic security

**Required Changes:**

1. **Add prominent warnings** to `zkp/README.md` and `zkp/SECURITY_CONSIDERATIONS.md`
2. **Update all docstrings** in `zkp_integration.py` to clarify simulation status
3. **Add runtime warnings** when ZKP modules are imported
4. **Create production upgrade path** document (if not exists)

**Acceptance Criteria:**
- [ ] `zkp/README.md` has clear ⚠️ warning at top: "NOT cryptographically secure"
- [ ] `ZKPProver` class docstring states simulation-only clearly
- [ ] Import warning added: `warnings.warn("ZKP is simulation-only...")`
- [ ] `PRODUCTION_UPGRADE_PATH.md` exists with concrete upgrade plan

### 5.5 Test Coverage Gaps

**Current:** ~87% overall pass rate, gaps in NL processing

**Target:** 90%+ pass rate, <20 skipped tests

**Actions:**
1. Fix 69 NL test failures (see 5.2)
2. Add 30+ tests for edge cases in CEC modal/resolution/specialized rules
3. Add 15+ integration tests for TDFOL↔CEC cross-module interactions
4. Add 10+ security tests for ZKP simulation boundary conditions

---

## 6. Phase 3: Feature Completions

**Duration:** 4–8 weeks  
**Priority:** P2 — Medium  
**Goal:** High-value feature additions

### 6.1 REST API Interface

**Priority:** High user value  
**Estimated Effort:** 2–3 weeks

**Design:**

```python
# FastAPI-based REST API at logic/api_server.py
# Endpoints:
POST /prove          # Submit theorem to prove
POST /convert/fol    # Convert text to FOL
POST /convert/dcec   # Convert text to DCEC
POST /parse          # Parse formula (auto-detect format)
GET  /capabilities   # List available provers/rules
GET  /health         # Health check
```

**Acceptance Criteria:**
- [ ] FastAPI server implementation (800+ LOC)
- [ ] OpenAPI documentation auto-generated
- [ ] Authentication (API key basic auth)
- [ ] Rate limiting (configurable per endpoint)
- [ ] Docker deployment support
- [ ] 100+ tests covering all endpoints
- [ ] Response time: simple proofs <100ms, complex <1s

### 6.2 TDFOL Phase 3 Week 2: Documentation Enhancement

**Status:** Phase 3 Week 1 complete (139 tests on `copilot/finish-phase-2-and-3`)

**Week 2 Goals:**
1. Generate comprehensive docstrings for all TDFOL modules
2. Create usage examples for each inference rule category
3. Update API reference to reflect Phase 3 Week 1 new tests
4. Create TDFOL tutorial notebook

**Acceptance Criteria:**
- [ ] 100% of public classes/methods have docstrings
- [ ] Usage examples in all major module docstrings
- [ ] API_REFERENCE.md updated with new test coverage
- [ ] Tutorial notebook: `examples/tdfol_tutorial.ipynb`

### 6.3 Multi-Language NL Support

**Priority:** Medium  
**Estimated Effort:** 4–6 weeks

**Target Languages:** Spanish, French, German (first round)

**Implementation:**
1. Extract language-specific patterns from grammar YAML
2. Add translation dictionaries for key logical terms
3. Implement language detection
4. Create language-specific test suites

**Acceptance Criteria:**
- [ ] Spanish NL → TDFOL/DCEC conversion (80%+ accuracy)
- [ ] French NL → TDFOL/DCEC conversion (80%+ accuracy)
- [ ] German NL → TDFOL/DCEC conversion (75%+ accuracy)
- [ ] 100+ tests per language
- [ ] Language detection: >95% accuracy

### 6.4 GraphRAG Deep Integration

**Priority:** High strategic value  
**Estimated Effort:** 4–5 weeks

**Goals:**
1. Logic-aware knowledge graph construction from text
2. Theorem-augmented RAG retrieval
3. Logical constraint verification in RAG outputs
4. Semantic search with logical preconditions

**Key Integration Points:**
- TDFOL prover as verifier for RAG outputs
- CEC knowledge base as graph store
- FOL converter as text → KG transformer
- IPFS as storage backend for verified proofs

**Acceptance Criteria:**
- [ ] `logic/graphrag_integration.py` (1,000+ LOC)
- [ ] Text → Knowledge Graph pipeline functional
- [ ] Theorem verification in RAG workflow
- [ ] 100+ integration tests
- [ ] Compatible with existing GraphRAG infrastructure

---

## 7. Phase 4: Production Excellence

**Duration:** Ongoing  
**Priority:** Continuous  
**Goal:** Maintain and improve production quality

### 7.1 Performance Monitoring

**Current State:** Monitoring infrastructure exists (monitoring.py)

**Improvements:**
1. Add automated performance regression tests (run in CI)
2. Alert when proof times exceed 2x baseline
3. Dashboard for production metrics (Prometheus/Grafana)
4. Cache hit rate monitoring

**Key Metrics to Track:**
- Simple proof: target <5ms (currently ~1-5ms ✅)
- Complex proof: target <50ms (currently ~5-20ms ✅)
- Cache hit rate: target >80%
- Memory usage: target <100MB idle
- NL conversion: target <100ms (currently ~10ms ✅)

### 7.2 Security Hardening

**Current State:** Security validator exists (753 LOC), basic protections in place

**Improvements:**
1. Formal security audit of ZKP module
2. Input validation for all REST API endpoints
3. DoS protection with circuit breakers
4. Audit logging for sensitive operations
5. Dependency vulnerability scanning

**Priority Items:**
- [ ] All REST API endpoints: input size limits (max 1MB)
- [ ] Proof timeout: configurable, default 30s
- [ ] Rate limiting: configurable, default 100 req/min
- [ ] ZKP: runtime warning when used (simulation-only)

### 7.3 Dependency Management

**Current State:** 70+ optional dependency graceful fallbacks

**Policy:**
1. Core module must work with zero optional deps
2. Optional deps categorized: `[logic]`, `[logic-full]`, `[logic-api]`
3. All optional deps behind lazy imports
4. Quarterly dependency updates

**Required Actions:**
- [ ] Audit all ImportError handlers — ensure all are tested
- [ ] Create `logic[api]` extras for FastAPI + uvicorn
- [ ] Document minimum vs recommended vs full dependency sets
- [ ] CI test matrix: bare Python 3.12 + core only

### 7.4 Documentation Maintenance Policy

To prevent future documentation sprawl:

**Rules:**
1. **Never create new markdown files in active directories** for progress reports
2. **Use git commit messages** for progress tracking (not markdown files)
3. **Archive immediately** any completion report after the work is merged
4. **One status document** per subsystem, updated in place (don't create new ones)
5. **Quarterly review** — archive any document not referenced in 90 days

**Naming Convention:**
- Current plans: `PLAN_*.md` or `ROADMAP_*.md`
- Status: `STATUS.md` (single file, updated in place)
- Archived: `ARCHIVE/[YYYY-MM-DD]_*.md` (with date prefix)

---

## 8. Timeline and Priorities

### Week 1–2: Documentation Consolidation (Phase 1)

| Task | Owner | Effort |
|------|-------|--------|
| Archive 19 root-level historical files | Agent | 2h |
| Archive 37 TDFOL historical files | Agent | 2h |
| Archive 21 CEC historical files | Agent | 1h |
| Archive 14 ZKP historical files | Agent | 1h |
| Update DOCUMENTATION_INDEX.md | Agent | 1h |
| Fix broken cross-references | Agent | 2h |
| Update PROJECT_STATUS.md | Agent | 1h |
| **Total Phase 1** | | **~10h** |

### Week 2–4: Code Quality (Phase 2)

| Task | Owner | Effort |
|------|-------|--------|
| Merge CEC inference rules branch | Agent | 4h |
| Fix 69 TDFOL NL test failures | Agent | 8h |
| Improve CEC NL coverage (60%→75%) | Agent | 12h |
| ZKP status clarification/warnings | Agent | 2h |
| Add 30+ edge case tests | Agent | 6h |
| **Total Phase 2** | | **~32h** |

### Week 4–8: Feature Completions (Phase 3)

| Task | Owner | Effort |
|------|-------|--------|
| REST API implementation | Agent | 40h |
| TDFOL Phase 3 Week 2 docs | Agent | 8h |
| Multi-language NL (1 language) | Agent | 24h |
| GraphRAG integration | Agent | 40h |
| **Total Phase 3** | | **~112h** |

### Ongoing: Production Excellence (Phase 4)

| Task | Frequency |
|------|-----------|
| Performance regression testing | Per PR |
| Security audit | Quarterly |
| Documentation review | Monthly |
| Dependency updates | Quarterly |

---

## 9. Success Criteria

### Phase 1 Complete ✅ when:

- [ ] Total markdown files: 196 → ≤102
- [ ] No phase completion reports in active directories
- [ ] Single status document per subsystem
- [ ] All cross-references valid (no broken links)
- [ ] DOCUMENTATION_INDEX.md reflects current structure

### Phase 2 Complete ✅ when:

- [ ] CEC inference rules: 5 modules → 9 modules (88 total rules)
- [ ] TDFOL NL test failures: 69 → <20
- [ ] CEC NL coverage: 60% → 75%+
- [ ] ZKP module: clear simulation warnings in place
- [ ] Overall test pass rate: 87% → 90%+

### Phase 3 Complete ✅ when:

- [ ] REST API: `/prove`, `/convert/*`, `/capabilities` endpoints operational
- [ ] Multi-language NL: at least Spanish support (80%+ accuracy)
- [ ] GraphRAG integration: text → KG pipeline functional
- [ ] TDFOL documentation: 100% public methods have docstrings

### Phase 4 Ongoing ✅ when:

- [ ] Performance metrics: all targets met (see 7.1)
- [ ] Security: REST API endpoints protected
- [ ] Documentation: no accumulation of historical files in active dirs
- [ ] Dependencies: zero known vulnerabilities

---

## 10. Document Inventory and Disposition

### 10.1 Documents to Keep (Essential)

These files are current, authoritative, and should be maintained:

**Root Level:**
- `README.md` — Module overview ✅
- `MASTER_REFACTORING_PLAN_2026.md` — This document ✅ NEW
- `PROJECT_STATUS.md` — Current status (needs update) ✅
- `EVERGREEN_IMPROVEMENT_PLAN.md` — Ongoing backlog ✅
- `ARCHITECTURE.md`, `API_REFERENCE.md`, `FEATURES.md` ✅
- `QUICKSTART.md`, `UNIFIED_CONVERTER_GUIDE.md` ✅
- `DEPLOYMENT_GUIDE.md`, `SECURITY_GUIDE.md`, `PERFORMANCE_TUNING.md` ✅
- `CONTRIBUTING.md`, `TROUBLESHOOTING.md`, `ERROR_REFERENCE.md` ✅
- `KNOWN_LIMITATIONS.md`, `MIGRATION_GUIDE.md`, `API_VERSIONING.md` ✅
- `INFERENCE_RULES_INVENTORY.md`, `DOCUMENTATION_INDEX.md` ✅

**TDFOL (15):** STATUS_2026.md, README.md, INDEX.md, QUICK_REFERENCE.md, + 11 component docs

**CEC (10):** STATUS.md, README.md, QUICKSTART.md, CEC_SYSTEM_GUIDE.md, + 6 reference docs

**ZKP (8):** README.md, QUICKSTART.md, IMPLEMENTATION_GUIDE.md, INTEGRATION_GUIDE.md, + 4 docs

**Per subdirectory READMEs:** common, fol, deontic, types, tools, external_provers, integration

### 10.2 Documents to Archive (Historical)

See Sections 4.1–4.4 for complete archive lists.

**Archive Criteria:**
1. Progress reports / completion summaries → Archive after phase completion
2. Superseded planning documents → Archive when replaced
3. Session summaries → Archive after session completes
4. Phase tracking files → Archive after phase merges to main

### 10.3 Documents to Merge (Content Consolidation)

| Source | Merge Into |
|--------|-----------|
| `VERIFIED_STATUS_REPORT_2026.md` | `PROJECT_STATUS.md` |
| `TYPE_SYSTEM_STATUS.md` | `ARCHITECTURE.md` (type system section) |
| `CACHING_ARCHITECTURE.md` | `ARCHITECTURE.md` (caching section) |
| `FALLBACK_BEHAVIORS.md` | `KNOWN_LIMITATIONS.md` |
| `ADVANCED_FEATURES_ROADMAP.md` | `EVERGREEN_IMPROVEMENT_PLAN.md` |
| `CEC/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md` | `CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` |
| `TDFOL/COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | `TDFOL/COMPREHENSIVE_REFACTORING_PLAN_2026_02_19.md` |
| `ZKP/LEGAL_THEOREM_SEMANTICS.md` | `ZKP/INTEGRATION_GUIDE.md` |

---

## Appendix A: Inference Rules Summary

As of 2026-02-19 (current branch):

| Module | TDFOL Rules | CEC Rules (Merged) | Total |
|--------|------------|-------------------|-------|
| Propositional | 15 | 10 | 25 |
| First-Order | 10 | 5 | 15 |
| Temporal | 10 | 15 | 25 |
| Deontic | 8 | 7 | 15 |
| Temporal-Deontic | 7 | — | 7 |
| Cognitive | — | 26 | 26 |
| Modal | — | 2 (pending) | 2 |
| Resolution | — | 7 (pending) | 7 |
| Specialized | — | 21 (pending) | 21 |
| **TOTAL** | **50** | **93** | **143** |

> **Note:** CEC modal/resolution/specialized rules pending merge from `copilot/refactor-improvement-plan-cec`

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
**Status:** Simulation implemented; production upgrade path documented

---

## Appendix C: Test Coverage Targets

| Component | Current | Phase 2 Target | Phase 3 Target |
|-----------|---------|----------------|----------------|
| TDFOL Core | 91.5% pass | 95% pass | 97% pass |
| CEC Native | 80-85% pass | 90% pass | 93% pass |
| Integration | 90% pass | 92% pass | 95% pass |
| NL Processing | 75% pass | 85% pass | 90% pass |
| ZKP (simulation) | 80% pass | 85% pass | 85% pass |
| REST API | N/A | N/A | 90% pass |
| **Overall** | **~87%** | **~90%** | **~93%** |

---

**Document Status:** Active Plan — Ready for Implementation  
**Next Action:** Execute Phase 1 (Documentation Consolidation)  
**Review Schedule:** After each phase completion, update this document  
**Created:** 2026-02-19  
**Supersedes:** All previous refactoring plans (see docs/archive/planning/)
