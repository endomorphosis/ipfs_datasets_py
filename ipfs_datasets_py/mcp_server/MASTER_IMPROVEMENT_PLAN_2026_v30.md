# MASTER IMPROVEMENT PLAN 2026 — v30

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Session:** GQ257–GZ266 (v30)
**Cumulative total:** 3,758 + 65 = **3,823 tests**

---

## 1. Session Summary (v30)

| Session | Module | What was done |
|---------|--------|---------------|
| GQ257 | `nl_policy_conflict_detector.py` + `logic/api.py` | Polish text → `detect_i18n_clauses("pl")` E2E (7 tests) |
| GR258 | `nl_policy_conflict_detector.py` + `logic/api.py` | Vietnamese text → `detect_i18n_clauses("vi")` E2E (7 tests) |
| GS259 | `logic/api.py` | `detect_all_languages()` all 18 original slots list-typed (6 tests) |
| GT260 | `logic/api.py` | `conflict_density()` with full 18-lang populated report (6 tests) |
| GU261 | `logic/api.py` | `languages_above_threshold()` with all 18 languages (6 tests) |
| GV262 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_TH_DEONTIC_KEYWORDS` inline Thai; `detect_all_languages()` → 19 languages (8 tests) |
| GW263 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_ID_DEONTIC_KEYWORDS` inline Indonesian; `detect_all_languages()` → 20 languages (9 tests) |
| GX264 | `nl_ucan_policy_compiler.py` + `logic/api.py` | `compile_batch_with_explain` + `detect_all_languages` 18-lang combined (5 tests) |
| GY265 | `policy_audit_log.py` + `logic/api.py` | `PolicyAuditLog` + 18-language metadata export/import (5 tests) |
| GZ266 | `ucan_delegation.py` | `active_tokens_by_actor` + `active_tokens_by_resource` + `merge` triple E2E (6 tests) |

**New test file:** `tests/mcp/unit/test_v30_sessions.py` (65 tests)

---

## 2. Production Changes (v30)

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

**GV262:** `_TH_DEONTIC_KEYWORDS` inline Thai keyword table (3 types, 7 keywords each):
- `"permission"`: `"สามารถ"`, `"ได้รับอนุญาต"`, `"มีสิทธิ์"`, …
- `"prohibition"`: `"ห้าม"`, `"ไม่อนุญาต"`, `"ไม่ได้รับอนุญาต"`, …
- `"obligation"`: `"ต้อง"`, `"จำเป็นต้อง"`, `"มีหน้าที่"`, …

**GW263:** `_ID_DEONTIC_KEYWORDS` inline Indonesian keyword table (3 types, 7 keywords each):
- `"permission"`: `"boleh"`, `"diizinkan"`, `"diperbolehkan"`, …
- `"prohibition"`: `"dilarang"`, `"tidak boleh"`, `"tidak diizinkan"`, …
- `"obligation"`: `"harus"`, `"wajib"`, `"diwajibkan"`, …

`_load_i18n_keywords()` extended with `"th"` and `"id"` branches. Docstring updated to list all 20 supported languages.

### `ipfs_datasets_py/logic/api.py`

**GV262/GW263:** `_SUPPORTED_LANGS` extended from 18 to **20 languages**:

```python
_SUPPORTED_LANGS = (
    "fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh",
    "ko", "ar", "sv", "ru", "el", "tr", "hi", "pl", "vi", "th", "id"
)
```

---

## 3. Key Invariants (v30)

| Component | Invariant |
|-----------|-----------|
| `detect_all_languages(text)` | Returns **≥ 20** language slots |
| `_load_i18n_keywords("th")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` with Thai scripts |
| `_load_i18n_keywords("id")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` with Indonesian words |
| `languages_above_threshold(0)` | Equals `sorted(languages_with_conflicts)` |
| `active_tokens_by_actor(a)` ∩ `active_tokens_by_resource(r)` | Overlapping cids are the same objects; wildcard token in both |
| Triple merge + revoke + count | `active_token_count` consistent after triple operation |

---

## 4. Compatibility Notes (v30)

No backward-compatibility fixes required. All v29 tests that asserted `>= 18` remain valid. The `_SUPPORTED_LANGS` tuple expansion is additive-only — existing per-slot keys remain present with the same semantics.

---

## 5. Cumulative Progress

| Session | New tests | Cumulative |
|---------|-----------|-----------|
| v13 | 339 | 339 |
| v14 | 384 | 723 |
| v15 | 69 | 2,953 |
| v16 | 63 | 3,016 |
| v17 | 57 | 3,073 |
| v18 | 39 | 3,112 |
| v19 | 59 | 3,171 |
| v20 | 61 | 3,232 |
| v21 | 51 | 3,283 |
| v22 | 54 | 3,337 |
| v23 | 63 | 3,400 |
| v24 | 57 | 3,457 |
| v25 | 53 | 3,510 |
| v26 | 61 | 3,571 |
| v27 | 62 | 3,633 |
| v28 | 62 | 3,695 |
| v29 | 63 | 3,758 |
| **v30** | **65** | **3,823** |

---

## 6. Security Summary (v30)

No vulnerabilities introduced:
- `_TH_DEONTIC_KEYWORDS` and `_ID_DEONTIC_KEYWORDS` are inline constant string tables — no network access.
- Thai script (UTF-8 Thai block) and Indonesian (Latin) strings are handled correctly by Python `str`.
- `detect_all_languages()` iterates over a fixed constant tuple — no dynamic code execution.
- `active_tokens_by_actor` + `active_tokens_by_resource` combination still respects fail-closed revocation via `active_tokens()`.

---

## 7. v31 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| HA267 | Thai text → `detect_i18n_clauses("th")` E2E | Low | 🟢 Low |
| HB268 | Indonesian text → `detect_i18n_clauses("id")` E2E | Low | 🟢 Low |
| HC269 | `detect_all_languages()` all 20 slots list-typed | Low | 🟢 Low |
| HD270 | `conflict_density()` with full 20-lang populated report | Low | 🟡 Med |
| HE271 | `languages_above_threshold()` with all 20 languages | Low | 🟡 Med |
| HF272 | Bengali (`"bn"`) keyword table → 21 languages | Med | 🟡 Med |
| HG273 | Malay (`"ms"`) keyword table → 22 languages | Med | 🟡 Med |
| HH274 | `compile_batch_with_explain` + all 20-lang combined | Med | 🔴 High |
| HI275 | `PolicyAuditLog` + all 20-language metadata export/import | Med | 🔴 High |
| HJ276 | `active_tokens_by_actor` + `by_resource` + `merge` + `revoke` quad combined | Med | 🔴 High |
