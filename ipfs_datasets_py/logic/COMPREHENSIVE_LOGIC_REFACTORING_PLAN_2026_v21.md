# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v21

**Supersedes:** v20
**Date:** 2026-02-23
**Branch:** `copilot/create-refactoring-plan-again`
**Version:** v21 (session GG247–GP256)
**Total tests:** 3,758

---

## 1. Overview

This document supersedes v20 of the comprehensive logic refactoring plan for
`ipfs_datasets_py/logic/` and `ipfs_datasets_py/mcp_server/`.  All phases from
v1–v20 are complete (see §3).  This version records the v29 session additions
and defines the v30 evergreen backlog.

---

## 2. v29 Session Changes

### New / Modified Methods

| Symbol | Module | Session |
|--------|--------|---------|
| `_PL_DEONTIC_KEYWORDS` inline Polish table | `nl_policy_conflict_detector.py` | GL252 |
| `_VI_DEONTIC_KEYWORDS` inline Vietnamese table | `nl_policy_conflict_detector.py` | GM253 |
| `_load_i18n_keywords("pl")` | `nl_policy_conflict_detector.py` | GL252 |
| `_load_i18n_keywords("vi")` | `nl_policy_conflict_detector.py` | GM253 |
| `detect_all_languages()` extended to 18 languages | `logic/api.py` | GL252/GM253 |

### Tests added

63 tests in `tests/mcp/unit/test_v29_sessions.py` (GG247–GP256)

---

## 3. Phase / Feature Status Table

| Phase | Feature | Status | Delivered |
|-------|---------|--------|-----------|
| GRAMMAR | GrammarNL stage 1b + fallback | ✅ Complete | v13/v15 |
| TDFOL | TDFOL NL pattern tests (skip-guarded) | ✅ Complete | v16/v17 |
| ZKP | ZKPBridge + Groth16 wired | ✅ Complete | v15/v16 |
| BRIDGE | UCANPolicyBridge + evaluate_with_manager + audited | ✅ Complete | v16→v18 |
| COMPILER | NLUCANPolicyCompiler + explain + iter + batch + with_explain + fail_fast | ✅ Complete | v19→v25 |
| CONFLICT | NL conflict detection + i18n (18 langs) | ✅ Complete | v15→v29 |
| DELEGATION | DelegationManager + merge + async + metrics + active_tokens + by_resource + wildcard + by_actor + combined | ✅ Complete | v15→v29 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult + to_dict + from_dict + round-trip | ✅ Complete | v14→v27 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence split + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| CHINESE | _ZH_DEONTIC_KEYWORDS + E2E | ✅ Complete | v24/v25 |
| KOREAN | _KO_DEONTIC_KEYWORDS + E2E | ✅ Complete | v26/v27 |
| ARABIC | _AR_DEONTIC_KEYWORDS + E2E | ✅ Complete | v26/v27 |
| SWEDISH | _SV_DEONTIC_KEYWORDS + E2E | ✅ Complete | v27/v29 |
| RUSSIAN | _RU_DEONTIC_KEYWORDS + E2E | ✅ Complete | v27/v29 |
| GREEK | _EL_DEONTIC_KEYWORDS + E2E | ✅ Complete | v28/v29 |
| TURKISH | _TR_DEONTIC_KEYWORDS + E2E | ✅ Complete | v28/v29 |
| HINDI | _HI_DEONTIC_KEYWORDS + E2E (Devanagari) | ✅ Complete | v28/v29 |
| POLISH | _PL_DEONTIC_KEYWORDS + E2E | ✅ Complete | v29 |
| VIETNAMESE | _VI_DEONTIC_KEYWORDS + E2E | ✅ Complete | v29 |
| BATCH | compile_batch() + fail_fast + with_explain + policy_ids shorter | ✅ Complete | v23→v25 |
| DENSITY | conflict_density() + all 18 langs | ✅ Complete | v24→v29 |
| LEAST_CONFLICTED | least_conflicted_language() | ✅ Complete | v25 |
| WILDCARD | active_tokens_by_resource("*") | ✅ Complete | v25 |
| MERGE_DICT | ComplianceMergeResult.to_dict() + from_dict() + round-trip | ✅ Complete | v25/v26/v27 |
| ABOVE_THRESHOLD | languages_above_threshold(n) + invariant test | ✅ Complete | v26/v27 |
| BY_ACTOR | active_tokens_by_actor(actor) + merge combined | ✅ Complete | v26→v29 |
| BY_ACTOR_RESOURCE | active_tokens_by_actor() ∩ active_tokens_by_resource() combined | ✅ Complete | v27 |
| THRESHOLD_DENSITY | languages_above_threshold + conflict_density combined | ✅ Complete | v27 |
| AUDIT_PIPELINE | PolicyAuditLog export/import + detect_all_languages full E2E | ✅ Complete | v29 |
| MAX_ENTRIES | import_jsonl max_entries ring-buffer clarified | ✅ Complete | v29 |

---

## 4. API Quick Reference (v29 additions)

```python
# GL252 – Polish detection
from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
    detect_i18n_clauses, _load_i18n_keywords,
)
kw = _load_i18n_keywords("pl")   # → {"permission": [...], "prohibition": [...], "obligation": [...]}
clauses = detect_i18n_clauses("musi zaakceptować", "pl")  # → list[PolicyConflict]

# GM253 – Vietnamese detection
kw = _load_i18n_keywords("vi")   # → {"permission": [...], ...}
clauses = detect_i18n_clauses("phải tuân thủ", "vi")

# Full pipeline (18 languages)
from ipfs_datasets_py.logic.api import detect_all_languages
report = detect_all_languages("user may read; admin must approve")
assert len(report.by_language) >= 18  # fr/es/de/en/pt/nl/it/ja/zh/ko/ar/sv/ru/el/tr/hi/pl/vi

# GP256 – Audit log + language detection E2E
from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
log = PolicyAuditLog()
for lang in report.by_language:
    log.record(policy_cid=lang, intent_cid="intent", decision="allow")
count = log.export_jsonl("/tmp/audit.jsonl", metadata={"source": "detect_all_languages"})
# count == len(report.by_language) == 18
log2 = PolicyAuditLog()
imported = log2.import_jsonl("/tmp/audit.jsonl")
# imported == 18 (metadata line skipped)
```

---

## 5. Supported Language Codes (v29)

| Code | Language | Added |
|------|----------|-------|
| `fr` | French | v13 |
| `es` | Spanish | v13 |
| `de` | German | v13 |
| `en` | English | v20 |
| `pt` | Portuguese | v21 |
| `nl` | Dutch | v21 |
| `it` | Italian | v22 |
| `ja` | Japanese | v23 |
| `zh` | Chinese (Simplified) | v24 |
| `ko` | Korean | v26 |
| `ar` | Arabic | v26 |
| `sv` | Swedish | v27 |
| `ru` | Russian | v27 |
| `el` | Greek | v28 |
| `tr` | Turkish | v28 |
| `hi` | Hindi (Devanagari) | v28 |
| `pl` | Polish | v29 |
| `vi` | Vietnamese | v29 |

---

## 6. v30 Backlog

| Session | Target | Priority |
|---------|--------|----------|
| GQ257 | Polish text → `detect_i18n_clauses("pl")` E2E | 🟢 Low |
| GR258 | Vietnamese text → `detect_i18n_clauses("vi")` E2E | 🟢 Low |
| GS259 | `detect_all_languages()` all 18 slots list-typed | 🟢 Low |
| GT260 | `conflict_density()` with full 18-lang populated report | 🟡 Med |
| GU261 | `languages_above_threshold()` with all 18 languages | 🟡 Med |
| GV262 | Thai (`"th"`) keyword table → 19 languages | 🟡 Med |
| GW263 | Indonesian (`"id"`) keyword table → 20 languages | 🟡 Med |
| GX264 | `compile_batch_with_explain` + 18-lang combined pipeline | 🔴 High |
| GY265 | `PolicyAuditLog` + 18-language metadata export/import | 🔴 High |
| GZ266 | `active_tokens_by_actor` + `by_resource` + `merge` triple E2E | 🔴 High |
