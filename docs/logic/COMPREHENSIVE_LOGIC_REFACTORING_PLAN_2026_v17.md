# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v17

**Supersedes:** v16
**Date:** 2026-02-23
**Branch:** `copilot/create-refactoring-plan-again`
**Version:** v17 (session ES207–FB216)
**Total tests:** 3,510

---

## 1. Overview

This document supersedes v16 of the comprehensive logic refactoring plan for
`ipfs_datasets_py/logic/` and `ipfs_datasets_py/mcp_server/`.  All phases from
v1–v16 are complete (see §3).  This version records the v25 session additions
and defines the v26 evergreen backlog.

---

## 2. v25 Session Changes

### New / Modified Methods

| Symbol | Module | Session |
|--------|--------|---------|
| `ComplianceMergeResult.to_dict()` | `compliance_checker.py` | EU209 |
| `I18NConflictReport.least_conflicted_language()` | `logic/api.py` | EV210 |
| `compile_batch_with_explain(fail_fast=False)` | `nl_ucan_policy_compiler.py` | ET208/FB216 |

### Tests added

53 tests in `tests/mcp/unit/test_v25_sessions.py` (ES207–FB216)

---

## 3. Phase / Feature Status Table

| Phase | Feature | Status | Delivered |
|-------|---------|--------|-----------|
| GRAMMAR | GrammarNL stage 1b + fallback | ✅ Complete | v13/v15 |
| TDFOL | TDFOL NL pattern tests (skip-guarded) | ✅ Complete | v16/v17 |
| ZKP | ZKPBridge + Groth16 wired | ✅ Complete | v15/v16 |
| BRIDGE | UCANPolicyBridge + evaluate_with_manager + audited | ✅ Complete | v16→v18 |
| COMPILER | NLUCANPolicyCompiler + explain + iter + batch + with_explain + fail_fast | ✅ Complete | v19→v25 |
| CONFLICT | NL conflict detection + i18n (9 langs) | ✅ Complete | v15→v24 |
| DELEGATION | DelegationManager + merge + async + metrics + active_tokens + by_resource + wildcard | ✅ Complete | v15→v25 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult + to_dict | ✅ Complete | v14→v25 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence split + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| CHINESE | _ZH_DEONTIC_KEYWORDS + E2E | ✅ Complete | v24/v25 |
| BATCH | compile_batch() + fail_fast + with_explain + policy_ids shorter | ✅ Complete | v23→v25 |
| DENSITY | conflict_density() + all 9 langs | ✅ Complete | v24/v25 |
| LEAST_CONFLICTED | least_conflicted_language() | ✅ Complete | v25 |
| WILDCARD | active_tokens_by_resource("*") | ✅ Complete | v25 |
| MERGE_DICT | ComplianceMergeResult.to_dict() | ✅ Complete | v25 |

---

## 4. API Quick Reference (v25 additions)

```python
# EU209 – ComplianceMergeResult as dict
r = checker.merge(other)
d = r.to_dict()
# d = {"added": N, "skipped_protected": M, "skipped_duplicate": K, "total": T}

# EV210 – least conflicted language
report = detect_all_languages(text)
least = report.least_conflicted_language()  # str | None

# ET208/FB216 – compile_batch_with_explain with fail_fast
pairs = compiler.compile_batch_with_explain(batches, fail_fast=True)
# stops at first erroring batch; returns partial list of (result, explain_str)

# ES207 – wildcard tokens match any resource
for cid, tok in mgr.active_tokens_by_resource("anything"):
    ...
# Tokens with capability resource="*" are always returned

# EZ214 – Chinese detection
report = detect_all_languages("可以访问，不得删除")
print(report.by_language["zh"])  # list (possibly empty if zh parser unavailable)
```

---

## 5. Evergreen Backlog (v26 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| FC217 | `I18NConflictReport.languages_above_threshold(n)` | Low | 🟢 Low |
| FD218 | `DelegationManager.active_tokens_by_actor(actor)` | Low | 🟢 Low |
| FE219 | `ComplianceMergeResult.from_dict(d)` | Low | 🟢 Low |
| FF220 | `compile_batch_with_explain` + shorter policy_ids | Low | 🟡 Med |
| FG221 | `least_conflicted_language()` with real `detect_all_languages()` | Low | 🟢 Low |
| FH222 | `detect_i18n_clauses` all 9 languages round-trip | Med | 🔴 High |
| FI223 | `DelegationManager.merge()` + `active_tokens_by_resource()` combined | Low | 🟡 Med |
| FJ224 | `conflict_density()` + `least_conflicted_language()` combined | Low | 🟢 Low |
| FK225 | Korean (`"ko"`) keyword table → 10 languages | Med | 🟡 Med |
| FL226 | Arabic (`"ar"`) keyword table → 11 languages | Med | 🟡 Med |

---

## 6. Success Criteria (v17)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,510 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | 9 languages | ✅ v24 (fr/es/de/en/pt/nl/it/ja/zh) |
| Delegation merge | sync + async + event_type | ✅ CQ153/CY161/DK173/DQ179 |
| Compliance merge | ComplianceMergeResult + total + to_dict | ✅ DA163/DH170/DS181/EC191/EK199/EU209 |
| Audit JSONL I/O | round-trip with metadata, clear() | ✅ CS155/CZ162/DG169/DR180/EB190/ER206 |
| Compiler explain | eager + lazy + batch + with_explain + fail_fast | ✅ CW159/DB164/DI171/DT182/DZ188/EJ198/ET208/FB216 |
| Portuguese parser | sentence-level multi-clause + filter | ✅ DJ172/DP178/DY187 |
| Italian keywords | _IT_DEONTIC_KEYWORDS | ✅ DO177 |
| Japanese keywords | _JA_DEONTIC_KEYWORDS | ✅ ED192 |
| Chinese keywords | _ZH_DEONTIC_KEYWORDS + E2E | ✅ EM201/EZ214 |
| Active token count | property + generator + by_resource + wildcard | ✅ DV184/EA189/EF194/EI197/ES207/EY213 |
| Conflict report | most/least_conflicted + density | ✅ EG195/EL200/EV210/FA215 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
| ComplianceMergeResult | NamedTuple + to_dict | ✅ EC191/EK199/EU209 |
