# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v18

**Supersedes:** v17
**Date:** 2026-02-23
**Branch:** `copilot/create-refactoring-plan-again`
**Version:** v18 (session FC217–FL226)
**Total tests:** 3,571

---

## 1. Overview

This document supersedes v17 of the comprehensive logic refactoring plan for
`ipfs_datasets_py/logic/` and `ipfs_datasets_py/mcp_server/`.  All phases from
v1–v17 are complete (see §3).  This version records the v26 session additions
and defines the v27 evergreen backlog.

---

## 2. v26 Session Changes

### New / Modified Methods

| Symbol | Module | Session |
|--------|--------|---------|
| `I18NConflictReport.languages_above_threshold(n)` | `logic/api.py` | FC217 |
| `DelegationManager.active_tokens_by_actor(actor)` | `ucan_delegation.py` | FD218 |
| `ComplianceMergeResult.from_dict(d)` | `compliance_checker.py` | FE219 |
| `_KO_DEONTIC_KEYWORDS` inline Korean table | `nl_policy_conflict_detector.py` | FK225 |
| `_AR_DEONTIC_KEYWORDS` inline Arabic table | `nl_policy_conflict_detector.py` | FL226 |
| `detect_all_languages()` extended to 11 languages | `logic/api.py` | FK225/FL226 |

### Tests added

61 tests in `tests/mcp/unit/test_v26_sessions.py` (FC217–FL226)

---

## 3. Phase / Feature Status Table

| Phase | Feature | Status | Delivered |
|-------|---------|--------|-----------|
| GRAMMAR | GrammarNL stage 1b + fallback | ✅ Complete | v13/v15 |
| TDFOL | TDFOL NL pattern tests (skip-guarded) | ✅ Complete | v16/v17 |
| ZKP | ZKPBridge + Groth16 wired | ✅ Complete | v15/v16 |
| BRIDGE | UCANPolicyBridge + evaluate_with_manager + audited | ✅ Complete | v16→v18 |
| COMPILER | NLUCANPolicyCompiler + explain + iter + batch + with_explain + fail_fast | ✅ Complete | v19→v25 |
| CONFLICT | NL conflict detection + i18n (11 langs) | ✅ Complete | v15→v26 |
| DELEGATION | DelegationManager + merge + async + metrics + active_tokens + by_resource + wildcard + by_actor | ✅ Complete | v15→v26 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult + to_dict + from_dict | ✅ Complete | v14→v26 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence split + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| CHINESE | _ZH_DEONTIC_KEYWORDS + E2E | ✅ Complete | v24/v25 |
| KOREAN | _KO_DEONTIC_KEYWORDS | ✅ Complete | v26 |
| ARABIC | _AR_DEONTIC_KEYWORDS | ✅ Complete | v26 |
| BATCH | compile_batch() + fail_fast + with_explain + policy_ids shorter | ✅ Complete | v23→v25 |
| DENSITY | conflict_density() + all 11 langs | ✅ Complete | v24→v26 |
| LEAST_CONFLICTED | least_conflicted_language() | ✅ Complete | v25 |
| WILDCARD | active_tokens_by_resource("*") | ✅ Complete | v25 |
| MERGE_DICT | ComplianceMergeResult.to_dict() + from_dict() | ✅ Complete | v25/v26 |
| ABOVE_THRESHOLD | languages_above_threshold(n) | ✅ Complete | v26 |
| BY_ACTOR | active_tokens_by_actor(actor) | ✅ Complete | v26 |

---

## 4. API Quick Reference (v26 additions)

```python
# FC217 – languages above a conflict threshold
report = detect_all_languages(text)
langs = report.languages_above_threshold(2)  # langs with > 2 conflicts

# FD218 – tokens for a specific actor (audience)
for cid, tok in mgr.active_tokens_by_actor("did:key:alice"):
    print(cid, tok.audience)

# FE219 – round-trip ComplianceMergeResult
r = checker.merge(other)
d = r.to_dict()
r2 = ComplianceMergeResult.from_dict(d)
assert r2.added == r.added

# FK225 – Korean detection
result = detect_i18n_clauses("할 수 있다", "ko")
# → list (possibly empty)

# FL226 – Arabic detection
result = detect_i18n_clauses("يجوز", "ar")
# → list (possibly empty)

# detect_all_languages now covers 11 languages
report = detect_all_languages(text)
assert set(report.by_language) >= {"fr","es","de","en","pt","nl","it","ja","zh","ko","ar"}
```

---

## 5. Evergreen Backlog (v27 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| FM227 | `languages_above_threshold(n)` + `conflict_density()` combined | Low | 🟢 Low |
| FN228 | `active_tokens_by_actor()` + `active_tokens_by_resource()` combined | Low | 🟢 Low |
| FO229 | `ComplianceMergeResult.from_dict()` + `to_dict()` round-trip property test | Low | 🟢 Low |
| FP230 | Korean text → `detect_all_languages()["ko"]` non-empty E2E | Low | 🟡 Med |
| FQ231 | Arabic text → `detect_all_languages()["ar"]` non-empty E2E | Low | 🟡 Med |
| FR232 | `detect_all_languages()` all 11 slots + `conflict_density()` over 11 langs | Low | 🟡 Med |
| FS233 | `languages_above_threshold(0)` == sorted `languages_with_conflicts` invariant | Low | 🟢 Low |
| FT234 | `active_tokens_by_actor()` + `merge_and_publish()` combined | Low | 🟡 Med |
| FU235 | Swedish (`"sv"`) keyword table → 12 languages | Med | 🟡 Med |
| FV236 | Russian (`"ru"`) keyword table → 13 languages | Med | 🟡 Med |

---

## 6. Success Criteria (v18)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,571 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | 11 languages | ✅ v26 (fr/es/de/en/pt/nl/it/ja/zh/ko/ar) |
| Delegation merge | sync + async + event_type + by_actor | ✅ CQ153/CY161/DK173/DQ179/FD218 |
| Compliance merge | ComplianceMergeResult + total + to_dict + from_dict | ✅ DA163/DH170/DS181/EC191/EK199/EU209/FE219 |
| Audit JSONL I/O | round-trip with metadata, clear() | ✅ CS155/CZ162/DG169/DR180/EB190/ER206 |
| Compiler explain | eager + lazy + batch + with_explain + fail_fast | ✅ CW159/DB164/DI171/DT182/DZ188/EJ198/ET208/FB216 |
| Portuguese parser | sentence-level multi-clause + filter | ✅ DJ172/DP178/DY187 |
| Italian keywords | _IT_DEONTIC_KEYWORDS | ✅ DO177 |
| Japanese keywords | _JA_DEONTIC_KEYWORDS | ✅ ED192 |
| Chinese keywords | _ZH_DEONTIC_KEYWORDS + E2E | ✅ EM201/EZ214 |
| Korean keywords | _KO_DEONTIC_KEYWORDS | ✅ FK225 |
| Arabic keywords | _AR_DEONTIC_KEYWORDS | ✅ FL226 |
| Active token count | property + generator + by_resource + wildcard + by_actor | ✅ DV184/EA189/EF194/EI197/ES207/EY213/FD218 |
| Conflict report | most/least_conflicted + density + above_threshold | ✅ EG195/EL200/EV210/FA215/FC217 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
| ComplianceMergeResult | NamedTuple + to_dict + from_dict | ✅ EC191/EK199/EU209/FE219 |
