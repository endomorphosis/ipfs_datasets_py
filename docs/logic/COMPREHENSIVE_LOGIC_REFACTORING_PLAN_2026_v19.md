# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v19

**Supersedes:** v18
**Date:** 2026-02-23
**Branch:** `copilot/create-refactoring-plan-again`
**Version:** v19 (session FM227–FV236)
**Total tests:** 3,633

---

## 1. Overview

This document supersedes v18 of the comprehensive logic refactoring plan for
`ipfs_datasets_py/logic/` and `ipfs_datasets_py/mcp_server/`.  All phases from
v1–v18 are complete (see §3).  This version records the v27 session additions
and defines the v28 evergreen backlog.

---

## 2. v27 Session Changes

### New / Modified Methods

| Symbol | Module | Session |
|--------|--------|---------|
| `_SV_DEONTIC_KEYWORDS` inline Swedish table | `nl_policy_conflict_detector.py` | FU235 |
| `_RU_DEONTIC_KEYWORDS` inline Russian table | `nl_policy_conflict_detector.py` | FV236 |
| `_load_i18n_keywords("sv")` | `nl_policy_conflict_detector.py` | FU235 |
| `_load_i18n_keywords("ru")` | `nl_policy_conflict_detector.py` | FV236 |
| `detect_all_languages()` extended to 13 languages | `logic/api.py` | FU235/FV236 |

### Tests added

62 tests in `tests/mcp/unit/test_v27_sessions.py` (FM227–FV236)

---

## 3. Phase / Feature Status Table

| Phase | Feature | Status | Delivered |
|-------|---------|--------|-----------|
| GRAMMAR | GrammarNL stage 1b + fallback | ✅ Complete | v13/v15 |
| TDFOL | TDFOL NL pattern tests (skip-guarded) | ✅ Complete | v16/v17 |
| ZKP | ZKPBridge + Groth16 wired | ✅ Complete | v15/v16 |
| BRIDGE | UCANPolicyBridge + evaluate_with_manager + audited | ✅ Complete | v16→v18 |
| COMPILER | NLUCANPolicyCompiler + explain + iter + batch + with_explain + fail_fast | ✅ Complete | v19→v25 |
| CONFLICT | NL conflict detection + i18n (13 langs) | ✅ Complete | v15→v27 |
| DELEGATION | DelegationManager + merge + async + metrics + active_tokens + by_resource + wildcard + by_actor | ✅ Complete | v15→v26 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult + to_dict + from_dict + round-trip | ✅ Complete | v14→v27 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence split + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| CHINESE | _ZH_DEONTIC_KEYWORDS + E2E | ✅ Complete | v24/v25 |
| KOREAN | _KO_DEONTIC_KEYWORDS + E2E | ✅ Complete | v26/v27 |
| ARABIC | _AR_DEONTIC_KEYWORDS + E2E | ✅ Complete | v26/v27 |
| SWEDISH | _SV_DEONTIC_KEYWORDS | ✅ Complete | v27 |
| RUSSIAN | _RU_DEONTIC_KEYWORDS | ✅ Complete | v27 |
| BATCH | compile_batch() + fail_fast + with_explain + policy_ids shorter | ✅ Complete | v23→v25 |
| DENSITY | conflict_density() + all 13 langs | ✅ Complete | v24→v27 |
| LEAST_CONFLICTED | least_conflicted_language() | ✅ Complete | v25 |
| WILDCARD | active_tokens_by_resource("*") | ✅ Complete | v25 |
| MERGE_DICT | ComplianceMergeResult.to_dict() + from_dict() + round-trip | ✅ Complete | v25/v26/v27 |
| ABOVE_THRESHOLD | languages_above_threshold(n) + invariant test | ✅ Complete | v26/v27 |
| BY_ACTOR | active_tokens_by_actor(actor) + combined with merge | ✅ Complete | v26/v27 |
| BY_ACTOR_RESOURCE | active_tokens_by_actor() ∩ active_tokens_by_resource() combined | ✅ Complete | v27 |
| THRESHOLD_DENSITY | languages_above_threshold + conflict_density combined | ✅ Complete | v27 |

---

## 4. API Quick Reference (v27 additions)

```python
# FU235 – Swedish detection
result = detect_i18n_clauses("får", "sv")  # → list

# FV236 – Russian detection
result = detect_i18n_clauses("должен", "ru")  # → list

# FR232 – 13-language report
report = detect_all_languages(text)
assert len(report.by_language) == 13
# includes "sv" and "ru" in addition to original 11

# FS233 – invariant
assert report.languages_above_threshold(0) == sorted(report.languages_with_conflicts)

# FO229 – round-trip
r = checker.merge(other)
r2 = ComplianceMergeResult.from_dict(r.to_dict())
assert r2.total == r.total

# FT234 – actor + merge_and_publish combined
dst.merge_and_publish(src, pubsub)
for cid, tok in dst.active_tokens_by_actor("did:key:alice"):
    print(cid, tok.audience)
```

---

## 5. Evergreen Backlog (v28 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| FW237 | Swedish text → `detect_i18n_clauses("sv")` E2E | Low | 🟢 Low |
| FX238 | Russian text → `detect_i18n_clauses("ru")` E2E | Low | 🟢 Low |
| FY239 | `detect_all_languages()` all 13 slots all `list` type | Low | 🟢 Low |
| FZ240 | `conflict_density()` with synthetic 13-lang populated report | Low | 🟡 Med |
| GA241 | Greek (`"el"`) keyword table → 14 languages | Med | 🟡 Med |
| GB242 | Turkish (`"tr"`) keyword table → 15 languages | Med | 🟡 Med |
| GC243 | Hindi (`"hi"`) keyword table → 16 languages | Med | 🟡 Med |
| GD244 | `languages_above_threshold(n)` with 13 slots | Low | 🟢 Low |
| GE245 | `active_tokens_by_actor()` + `revoke()` + `active_token_count` combined | Low | 🟡 Med |
| GF246 | Full pipeline E2E: `detect_all_languages()` → `compile_batch()` | Med | 🔴 High |

---

## 6. Success Criteria (v19)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,633 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | 13 languages | ✅ v27 (fr/es/de/en/pt/nl/it/ja/zh/ko/ar/sv/ru) |
| Delegation merge | sync + async + event_type + by_actor | ✅ CQ153/CY161/DK173/DQ179/FD218 |
| Compliance merge | ComplianceMergeResult + total + to_dict + from_dict + round-trip | ✅ DA163/DH170/DS181/EC191/EK199/EU209/FE219/FO229 |
| Audit JSONL I/O | round-trip with metadata, clear() | ✅ CS155/CZ162/DG169/DR180/EB190/ER206 |
| Compiler explain | eager + lazy + batch + with_explain + fail_fast | ✅ CW159/DB164/DI171/DT182/DZ188/EJ198/ET208/FB216 |
| Portuguese parser | sentence-level multi-clause + filter | ✅ DJ172/DP178/DY187 |
| Italian keywords | _IT_DEONTIC_KEYWORDS | ✅ DO177 |
| Japanese keywords | _JA_DEONTIC_KEYWORDS | ✅ ED192 |
| Chinese keywords | _ZH_DEONTIC_KEYWORDS + E2E | ✅ EM201/EZ214 |
| Korean keywords | _KO_DEONTIC_KEYWORDS + E2E | ✅ FK225/FP230 |
| Arabic keywords | _AR_DEONTIC_KEYWORDS + E2E | ✅ FL226/FQ231 |
| Swedish keywords | _SV_DEONTIC_KEYWORDS | ✅ FU235 |
| Russian keywords | _RU_DEONTIC_KEYWORDS | ✅ FV236 |
| Active token count | property + generator + by_resource + wildcard + by_actor + combined | ✅ DV184/EA189/EF194/EI197/ES207/EY213/FD218/FN228/FT234 |
| Conflict report | most/least_conflicted + density + above_threshold + invariant | ✅ EG195/EL200/EV210/FA215/FC217/FM227/FS233 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
| ComplianceMergeResult | NamedTuple + to_dict + from_dict + round-trip | ✅ EC191/EK199/EU209/FE219/FO229 |
