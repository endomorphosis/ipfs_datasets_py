# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v22

**Supersedes:** v21
**Date:** 2026-02-23
**Branch:** `copilot/create-refactoring-plan-again`
**Version:** v22 (session GQ257–GZ266)
**Total tests:** 3,823

---

## 1. Overview

This document supersedes v21 of the comprehensive logic refactoring plan for
`ipfs_datasets_py/logic/` and `ipfs_datasets_py/mcp_server/`.  All phases from
v1–v21 are complete (see §3).  This version records the v30 session additions
and defines the v31 evergreen backlog.

---

## 2. v30 Session Changes

### New / Modified Methods

| Symbol | Module | Session |
|--------|--------|---------|
| `_TH_DEONTIC_KEYWORDS` inline Thai table | `nl_policy_conflict_detector.py` | GV262 |
| `_ID_DEONTIC_KEYWORDS` inline Indonesian table | `nl_policy_conflict_detector.py` | GW263 |
| `_load_i18n_keywords("th")` | `nl_policy_conflict_detector.py` | GV262 |
| `_load_i18n_keywords("id")` | `nl_policy_conflict_detector.py` | GW263 |
| `detect_all_languages()` extended to 20 languages | `logic/api.py` | GV262/GW263 |

### Tests added

65 tests in `tests/mcp/unit/test_v30_sessions.py` (GQ257–GZ266)

---

## 3. Phase / Feature Status Table

| Phase | Feature | Status | Delivered |
|-------|---------|--------|-----------|
| GRAMMAR | GrammarNL stage 1b + fallback | ✅ Complete | v13/v15 |
| TDFOL | TDFOL NL pattern tests (skip-guarded) | ✅ Complete | v16/v17 |
| ZKP | ZKPBridge + Groth16 wired | ✅ Complete | v15/v16 |
| BRIDGE | UCANPolicyBridge + evaluate_with_manager + audited | ✅ Complete | v16→v18 |
| COMPILER | NLUCANPolicyCompiler + explain + iter + batch + with_explain + fail_fast | ✅ Complete | v19→v25 |
| CONFLICT | NL conflict detection + i18n (20 langs) | ✅ Complete | v15→v30 |
| DELEGATION | DelegationManager + merge + async + metrics + active_tokens + by_resource + wildcard + by_actor + triple combined | ✅ Complete | v15→v30 |
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
| POLISH | _PL_DEONTIC_KEYWORDS + E2E | ✅ Complete | v29/v30 |
| VIETNAMESE | _VI_DEONTIC_KEYWORDS + E2E | ✅ Complete | v29/v30 |
| THAI | _TH_DEONTIC_KEYWORDS + E2E | ✅ Complete | v30 |
| INDONESIAN | _ID_DEONTIC_KEYWORDS + E2E | ✅ Complete | v30 |
| BATCH | compile_batch() + fail_fast + with_explain + policy_ids shorter | ✅ Complete | v23→v25 |
| DENSITY | conflict_density() + all 20 langs | ✅ Complete | v24→v30 |
| LEAST_CONFLICTED | least_conflicted_language() | ✅ Complete | v25 |
| WILDCARD | active_tokens_by_resource("*") | ✅ Complete | v25 |
| MERGE_DICT | ComplianceMergeResult.to_dict() + from_dict() + round-trip | ✅ Complete | v25/v26/v27 |
| ABOVE_THRESHOLD | languages_above_threshold(n) + 20-lang invariant | ✅ Complete | v26→v30 |
| BY_ACTOR | active_tokens_by_actor(actor) + merge combined | ✅ Complete | v26→v29 |
| BY_ACTOR_RESOURCE | active_tokens_by_actor() ∩ active_tokens_by_resource() combined | ✅ Complete | v27/v30 |
| THRESHOLD_DENSITY | languages_above_threshold + conflict_density combined | ✅ Complete | v27 |
| AUDIT_PIPELINE | PolicyAuditLog export/import + detect_all_languages full E2E | ✅ Complete | v29/v30 |
| MAX_ENTRIES | import_jsonl max_entries ring-buffer clarified | ✅ Complete | v29 |
| TRIPLE_COMBINED | active_tokens_by_actor + by_resource + merge triple | ✅ Complete | v30 |

---

## 4. API Quick Reference (v30 additions)

```python
# GV262 – Thai detection
from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
    detect_i18n_clauses, _load_i18n_keywords,
)
kw = _load_i18n_keywords("th")   # → {"permission": [...], "prohibition": [...], "obligation": [...]}
clauses = detect_i18n_clauses("ต้องปฏิบัติตามกฎ", "th")  # → list

# GW263 – Indonesian detection
kw = _load_i18n_keywords("id")   # → {"permission": [...], ...}
clauses = detect_i18n_clauses("harus mematuhi peraturan", "id")

# Full pipeline (20 languages)
from ipfs_datasets_py.logic.api import detect_all_languages
report = detect_all_languages("user may read; admin must approve")
assert len(report.by_language) >= 20  # fr/es/de/en/.../th/id

# GZ266 – Triple combined delegation E2E
from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, DelegationToken, Capability
mgr_a = DelegationManager(path=None)
mgr_b = DelegationManager(path=None)
tok = DelegationToken(issuer="alice", audience="bob",
                      capabilities=[Capability(resource="files", ability="read")],
                      expiry=9999999999.0, nonce="unique")
mgr_b.add(tok)
mgr_a.merge(mgr_b)

actors = dict(mgr_a.active_tokens_by_actor("bob"))      # non-empty
resources = dict(mgr_a.active_tokens_by_resource("files"))  # same CID
```

---

## 5. Supported Language Codes (v30)

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
| `th` | Thai | v30 |
| `id` | Indonesian | v30 |

---

## 6. v31 Backlog

| Session | Target | Priority |
|---------|--------|----------|
| HA267 | Thai text → `detect_i18n_clauses("th")` E2E | 🟢 Low |
| HB268 | Indonesian text → `detect_i18n_clauses("id")` E2E | 🟢 Low |
| HC269 | `detect_all_languages()` all 20 slots list-typed | 🟢 Low |
| HD270 | `conflict_density()` with full 20-lang populated report | 🟡 Med |
| HE271 | `languages_above_threshold()` with all 20 languages | 🟡 Med |
| HF272 | Bengali (`"bn"`) keyword table → 21 languages | 🟡 Med |
| HG273 | Malay (`"ms"`) keyword table → 22 languages | 🟡 Med |
| HH274 | `compile_batch_with_explain` + all 20-lang combined | 🔴 High |
| HI275 | `PolicyAuditLog` + all 20-language metadata export/import | 🔴 High |
| HJ276 | `active_tokens_by_actor` + `by_resource` + `merge` + `revoke` quad combined | 🔴 High |
