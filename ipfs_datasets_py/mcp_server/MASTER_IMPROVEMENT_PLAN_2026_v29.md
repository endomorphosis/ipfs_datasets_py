# MASTER IMPROVEMENT PLAN 2026 — v29

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Session:** GG247–GP256 (v29)
**Cumulative total:** 3,695 + 63 = **3,758 tests**

---

## 1. Session Summary (v29)

| Session | Module | What was done |
|---------|--------|---------------|
| GG247 | `nl_policy_conflict_detector.py` + `logic/api.py` | Greek text → `detect_i18n_clauses("el")` E2E (7 tests) |
| GH248 | `nl_policy_conflict_detector.py` + `logic/api.py` | Turkish text → `detect_i18n_clauses("tr")` E2E (7 tests) |
| GI249 | `nl_policy_conflict_detector.py` + `logic/api.py` | Hindi text → `detect_i18n_clauses("hi")` E2E (7 tests) |
| GJ250 | `logic/api.py` | `detect_all_languages()` all 16 (now ≥16) slots non-None + list-typed (6 tests) |
| GK251 | `logic/api.py` | `conflict_density()` with 16-lang populated report (6 tests) |
| GL252 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_PL_DEONTIC_KEYWORDS` inline Polish; `detect_all_languages()` → 17 languages (7 tests) |
| GM253 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_VI_DEONTIC_KEYWORDS` inline Vietnamese; `detect_all_languages()` → 18 languages (8 tests) |
| GN254 | `ucan_delegation.py` | `DelegationManager.merge()` + `active_tokens_by_actor()` combined E2E (5 tests) |
| GO255 | `nl_ucan_policy_compiler.py` + `logic/api.py` | `compile_batch_with_explain` → `I18NConflictReport` combined pipeline (5 tests) |
| GP256 | `policy_audit_log.py` + `logic/api.py` | `export_jsonl` + `import_jsonl` + `detect_all_languages` full E2E (5 tests) |

**New test file:** `tests/mcp/unit/test_v29_sessions.py` (63 tests)

---

## 2. Production Changes (v29)

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

**GL252:** `_PL_DEONTIC_KEYWORDS` inline Polish keyword table (3 types, 7 keywords each):
- `"permission"`: `"może"`, `"wolno"`, `"jest dozwolone"`, …
- `"prohibition"`: `"nie może"`, `"jest zabronione"`, `"jest zakazane"`, …
- `"obligation"`: `"musi"`, `"jest zobowiązany"`, `"należy"`, …

**GM253:** `_VI_DEONTIC_KEYWORDS` inline Vietnamese keyword table (3 types, 7 keywords each):
- `"permission"`: `"có thể"`, `"được phép"`, `"có quyền"`, …
- `"prohibition"`: `"không được"`, `"bị cấm"`, `"cấm"`, …
- `"obligation"`: `"phải"`, `"cần phải"`, `"có nghĩa vụ"`, …

`_load_i18n_keywords()` extended with `"pl"` and `"vi"` branches. Docstring updated to list all 18 supported languages.

### `ipfs_datasets_py/logic/api.py`

**GL252/GM253:** `_SUPPORTED_LANGS` extended from 16 to **18 languages**:

```python
_SUPPORTED_LANGS = (
    "fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh",
    "ko", "ar", "sv", "ru", "el", "tr", "hi", "pl", "vi"
)
```

---

## 3. Key Invariants (v29)

| Component | Invariant |
|-----------|-----------|
| `detect_all_languages(text)` | Returns **≥ 18** language slots |
| `_load_i18n_keywords("pl")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` |
| `_load_i18n_keywords("vi")` | Returns `{"permission":…, "prohibition":…, "obligation":…}` |
| `PolicyAuditLog.import_jsonl` return | Total entries processed (not capped by `max_entries`) |
| `PolicyAuditLog.recent(N)` after import | Capped by `max_entries` ring buffer |
| `DelegationManager.merge()` + `active_tokens_by_actor()` | Merged tokens visible; revoke() removes; idempotent |

---

## 4. Compatibility Notes (v29)

No backward-compatibility fixes required. All v28 tests that asserted `>= 16` remain valid. The `import_jsonl` max-entries behaviour is correctly documented: the **return value** counts all processed entries; the in-memory buffer is capped by `max_entries`.

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
| **v29** | **63** | **3,758** |

---

## 6. Security Summary (v29)

No vulnerabilities introduced:
- `_PL_DEONTIC_KEYWORDS` and `_VI_DEONTIC_KEYWORDS` are inline constant string tables — no network access.
- `detect_all_languages()` adds two more constant-time loop iterations.
- `import_jsonl` max-entries ring buffer is a pure in-memory operation.
- `DelegationManager.merge()` + `active_tokens_by_actor()` combination respects existing fail-closed revocation.
- Vietnamese and Polish strings are valid UTF-8 — handled correctly by Python `str`.

---

## 7. v30 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| GQ257 | Polish text → `detect_i18n_clauses("pl")` E2E | Low | 🟢 Low |
| GR258 | Vietnamese text → `detect_i18n_clauses("vi")` E2E | Low | 🟢 Low |
| GS259 | `detect_all_languages()` all 18 slots list-typed | Low | 🟢 Low |
| GT260 | `conflict_density()` with full 18-lang populated report | Low | 🟡 Med |
| GU261 | `languages_above_threshold()` with all 18 languages | Low | 🟡 Med |
| GV262 | Thai (`"th"`) keyword table → 19 languages | Med | 🟡 Med |
| GW263 | Indonesian (`"id"`) keyword table → 20 languages | Med | 🟡 Med |
| GX264 | `compile_batch_with_explain` + `detect_all_languages` 18-lang combined | Med | 🔴 High |
| GY265 | `PolicyAuditLog` + all 18 languages metadata export/import | Med | 🔴 High |
| GZ266 | `active_tokens_by_actor` + `active_tokens_by_resource` + `merge` triple combined | Med | 🔴 High |
