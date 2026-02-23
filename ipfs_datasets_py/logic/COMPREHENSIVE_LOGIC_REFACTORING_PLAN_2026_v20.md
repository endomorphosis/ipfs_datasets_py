# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v20

**Supersedes:** v19
**Date:** 2026-02-23
**Branch:** `copilot/create-refactoring-plan-again`
**Version:** v20 (session FW237–GF246)
**Total tests:** 3,695

---

## 1. Overview

This document supersedes v19 of the comprehensive logic refactoring plan for
`ipfs_datasets_py/logic/` and `ipfs_datasets_py/mcp_server/`.  All phases from
v1–v19 are complete (see §3).  This version records the v28 session additions
and defines the v29 evergreen backlog.

---

## 2. v28 Session Changes

### New / Modified Methods

| Symbol | Module | Session |
|--------|--------|---------|
| `_EL_DEONTIC_KEYWORDS` inline Greek table | `nl_policy_conflict_detector.py` | GA241 |
| `_TR_DEONTIC_KEYWORDS` inline Turkish table | `nl_policy_conflict_detector.py` | GB242 |
| `_HI_DEONTIC_KEYWORDS` inline Hindi table | `nl_policy_conflict_detector.py` | GC243 |
| `_load_i18n_keywords("el")` | `nl_policy_conflict_detector.py` | GA241 |
| `_load_i18n_keywords("tr")` | `nl_policy_conflict_detector.py` | GB242 |
| `_load_i18n_keywords("hi")` | `nl_policy_conflict_detector.py` | GC243 |
| `detect_all_languages()` extended to 16 languages | `logic/api.py` | GA241/GB242/GC243 |

### Tests added

62 tests in `tests/mcp/unit/test_v28_sessions.py` (FW237–GF246)

### Compatibility fix

`tests/mcp/unit/test_v27_sessions.py`: Three `== 13` assertions relaxed to `>= 13`.

---

## 3. Phase / Feature Status Table

| Phase | Feature | Status | Delivered |
|-------|---------|--------|-----------|
| GRAMMAR | GrammarNL stage 1b + fallback | ✅ Complete | v13/v15 |
| TDFOL | TDFOL NL pattern tests (skip-guarded) | ✅ Complete | v16/v17 |
| ZKP | ZKPBridge + Groth16 wired | ✅ Complete | v15/v16 |
| BRIDGE | UCANPolicyBridge + evaluate_with_manager + audited | ✅ Complete | v16→v18 |
| COMPILER | NLUCANPolicyCompiler + explain + iter + batch + with_explain + fail_fast | ✅ Complete | v19→v25 |
| CONFLICT | NL conflict detection + i18n (16 langs) | ✅ Complete | v15→v28 |
| DELEGATION | DelegationManager + merge + async + metrics + active_tokens + by_resource + wildcard + by_actor + revoke combined | ✅ Complete | v15→v28 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult + to_dict + from_dict + round-trip | ✅ Complete | v14→v27 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence split + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| CHINESE | _ZH_DEONTIC_KEYWORDS + E2E | ✅ Complete | v24/v25 |
| KOREAN | _KO_DEONTIC_KEYWORDS + E2E | ✅ Complete | v26/v27 |
| ARABIC | _AR_DEONTIC_KEYWORDS + E2E | ✅ Complete | v26/v27 |
| SWEDISH | _SV_DEONTIC_KEYWORDS + E2E | ✅ Complete | v27/v28 |
| RUSSIAN | _RU_DEONTIC_KEYWORDS + E2E | ✅ Complete | v27/v28 |
| GREEK | _EL_DEONTIC_KEYWORDS | ✅ Complete | v28 |
| TURKISH | _TR_DEONTIC_KEYWORDS | ✅ Complete | v28 |
| HINDI | _HI_DEONTIC_KEYWORDS | ✅ Complete | v28 |
| BATCH | compile_batch() + fail_fast + with_explain + policy_ids shorter | ✅ Complete | v23→v25 |
| DENSITY | conflict_density() + all 16 langs | ✅ Complete | v24→v28 |
| LEAST_CONFLICTED | least_conflicted_language() | ✅ Complete | v25 |
| WILDCARD | active_tokens_by_resource("*") | ✅ Complete | v25 |
| MERGE_DICT | ComplianceMergeResult.to_dict() + from_dict() + round-trip | ✅ Complete | v25/v26/v27 |
| ABOVE_THRESHOLD | languages_above_threshold(n) + many-slot test | ✅ Complete | v26→v28 |
| BY_ACTOR | active_tokens_by_actor(actor) + revoke + combined | ✅ Complete | v26→v28 |
| FULL_PIPELINE | detect_all_languages() → compile_batch() E2E | ✅ Complete | v28 |

---

## 4. API Quick Reference (v28 additions)

```python
# GA241 – Greek detection
result = detect_i18n_clauses("απαγορεύεται", "el")  # → list

# GB242 – Turkish detection
result = detect_i18n_clauses("yasaktır", "tr")  # → list

# GC243 – Hindi detection
result = detect_i18n_clauses("अनिवार्य है", "hi")  # → list

# 16-language detect_all_languages
from ipfs_datasets_py.logic.api import detect_all_languages, I18NConflictReport
report: I18NConflictReport = detect_all_languages(text)
assert len(report.by_language) >= 16  # fr/es/de/en/pt/nl/it/ja/zh/ko/ar/sv/ru/el/tr/hi

# GF246 – full pipeline
from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import NLUCANPolicyCompiler
report = detect_all_languages(text)
results = NLUCANPolicyCompiler().compile_batch(
    [sentences] * len(report.by_language),
    policy_ids=list(report.by_language.keys()),
)
```

---

## 5. v29 Backlog

| Session | Target | Priority |
|---------|--------|----------|
| GG247 | Greek text E2E | 🟢 Low |
| GH248 | Turkish text E2E | 🟢 Low |
| GI249 | Hindi text E2E | 🟢 Low |
| GJ250 | All 16 slots non-None | 🟢 Low |
| GK251 | conflict_density() 16-lang | 🟡 Med |
| GL252 | Polish `"pl"` keywords → 17 langs | 🟡 Med |
| GM253 | Vietnamese `"vi"` keywords → 18 langs | 🟡 Med |
| GN254 | merge() + active_tokens_by_actor() E2E | 🔴 High |
| GO255 | compile_batch_with_explain + I18NConflictReport pipeline | 🔴 High |
| GP256 | PolicyAuditLog.export_jsonl + detect_all_languages full E2E | 🔴 High |

---

## 6. Security Notes (v28)

- All three new keyword tables (`_EL_`, `_TR_`, `_HI_`) are inline constants — no network access, no filesystem access.
- `detect_all_languages()` continues the existing loop-per-language pattern; adding 3 more iterations has no security impact.
- The `active_tokens_by_actor()` + `revoke()` combination test verifies that revocation is respected in the by-actor filter — no regression.
