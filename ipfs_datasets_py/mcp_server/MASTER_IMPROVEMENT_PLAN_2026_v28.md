# MASTER IMPROVEMENT PLAN 2026 — v28

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Session:** FW237–GF246 (v28)
**Cumulative total:** 3,633 + 62 = **3,695 tests**

---

## 1. Session Summary (v28)

| Session | Module | What was done |
|---------|--------|---------------|
| FW237 | `nl_policy_conflict_detector.py` + `logic/api.py` | Swedish text → `detect_i18n_clauses("sv")` + `detect_all_languages()` E2E (6 tests) |
| FX238 | `nl_policy_conflict_detector.py` + `logic/api.py` | Russian text → `detect_i18n_clauses("ru")` + `detect_all_languages()` E2E (6 tests) |
| FY239 | `logic/api.py` | `detect_all_languages()` all 13 original slots are list-typed (6 tests) |
| FZ240 | `logic/api.py` | `conflict_density()` with synthetic 13-lang populated report (6 tests) |
| GA241 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_EL_DEONTIC_KEYWORDS` inline Greek; `detect_all_languages()` → 14 languages (7 tests) |
| GB242 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_TR_DEONTIC_KEYWORDS` inline Turkish; `detect_all_languages()` → 15 languages (7 tests) |
| GC243 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_HI_DEONTIC_KEYWORDS` inline Hindi; `detect_all_languages()` → 16 languages (7 tests) |
| GD244 | `logic/api.py` | `languages_above_threshold(n)` with many slots populated (6 tests) |
| GE245 | `ucan_delegation.py` | `active_tokens_by_actor()` + `revoke()` + `active_token_count` combined (6 tests) |
| GF246 | `logic/api.py` + `nl_ucan_policy_compiler.py` | Full pipeline E2E: `detect_all_languages()` → `compile_batch()` (5 tests) |

**New test file:** `tests/mcp/unit/test_v28_sessions.py` (62 tests)

---

## 2. Production Changes (v28)

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

**GA241:** `_EL_DEONTIC_KEYWORDS` inline Greek keyword table (3 types, 7 keywords each):
- `"permission"`: `"μπορεί"`, `"επιτρέπεται"`, …
- `"prohibition"`: `"απαγορεύεται"`, `"δεν επιτρέπεται"`, …
- `"obligation"`: `"πρέπει"`, `"υποχρεούται"`, …

**GB242:** `_TR_DEONTIC_KEYWORDS` inline Turkish keyword table:
- `"permission"`: `"yapabilir"`, `"izinlidir"`, …
- `"prohibition"`: `"yapamaz"`, `"yasaktır"`, …
- `"obligation"`: `"zorundadır"`, `"gereklidir"`, …

**GC243:** `_HI_DEONTIC_KEYWORDS` inline Hindi keyword table:
- `"permission"`: `"कर सकता है"`, `"अनुमति है"`, …
- `"prohibition"`: `"नहीं कर सकता"`, `"प्रतिबंधित है"`, …
- `"obligation"`: `"करना होगा"`, `"अनिवार्य है"`, …

`_load_i18n_keywords()` extended with `"el"`, `"tr"`, `"hi"` branches.

### `ipfs_datasets_py/logic/api.py`

**GA241/GB242/GC243:** `_SUPPORTED_LANGS` extended from 13 to **16 languages**:

```python
_SUPPORTED_LANGS = (
    "fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh",
    "ko", "ar", "sv", "ru", "el", "tr", "hi"
)
```

---

## 3. Compatibility Fix (v28)

`tests/mcp/unit/test_v27_sessions.py`: Three `== 13` assertions relaxed to `>= 13` to remain valid when `detect_all_languages()` returns 16 slots.

---

## 4. Key Invariants (v28)

| Component | Invariant |
|-----------|-----------|
| `detect_all_languages(text)` | Returns **≥ 16** language slots |
| `_load_i18n_keywords("el")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` |
| `_load_i18n_keywords("tr")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` |
| `_load_i18n_keywords("hi")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` |
| `active_token_count` after `revoke(cid)` | Decreases by 1 |
| `active_tokens_by_actor(A)` after `revoke(cid)` | cid not in results |

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
| **v28** | **62** | **3,695** |

---

## 6. Security Summary (v28)

No vulnerabilities introduced:
- `_EL_DEONTIC_KEYWORDS`, `_TR_DEONTIC_KEYWORDS`, and `_HI_DEONTIC_KEYWORDS` are inline constant string tables — no network access.
- `detect_all_languages()` adds three more constant-time loop iterations.
- `active_tokens_by_actor()` + `revoke()` combination respects the existing fail-closed revocation logic.
- All new tests are pure-Python — no file I/O beyond temporary files.

---

## 7. v29 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| GG247 | Greek text → `detect_i18n_clauses("el")` E2E | Low | 🟢 Low |
| GH248 | Turkish text → `detect_i18n_clauses("tr")` E2E | Low | 🟢 Low |
| GI249 | Hindi text → `detect_i18n_clauses("hi")` E2E | Low | 🟢 Low |
| GJ250 | `detect_all_languages()` all 16 slots non-None / list | Low | 🟢 Low |
| GK251 | `conflict_density()` with 16-lang populated report | Low | 🟡 Med |
| GL252 | Polish (`"pl"`) keyword table → 17 languages | Med | 🟡 Med |
| GM253 | Vietnamese (`"vi"`) keyword table → 18 languages | Med | 🟡 Med |
| GN254 | `DelegationManager.merge()` + `active_tokens_by_actor()` combined E2E | Med | 🔴 High |
| GO255 | `compile_batch_with_explain` → `I18NConflictReport` combined pipeline | Med | 🔴 High |
| GP256 | `PolicyAuditLog.export_jsonl` + `import_jsonl` + `detect_all_languages` full E2E | Med | 🔴 High |
