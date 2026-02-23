# MASTER IMPROVEMENT PLAN 2026 — v27

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Session:** FM227–FV236 (v27)
**Cumulative total:** 3,571 + 62 = **3,633 tests**

---

## 1. Session Summary (v27)

| Session | Module | What was done |
|---------|--------|---------------|
| FM227 | `logic/api.py` | `languages_above_threshold(n)` + `conflict_density()` combined tests (6 tests) |
| FN228 | `ucan_delegation.py` | `active_tokens_by_actor()` + `active_tokens_by_resource()` combined tests (5 tests) |
| FO229 | `compliance_checker.py` | `ComplianceMergeResult.from_dict()` + `to_dict()` round-trip property tests (6 tests) |
| FP230 | `nl_policy_conflict_detector.py` + `logic/api.py` | Korean text → `detect_all_languages(text)["ko"]` non-empty E2E (6 tests) |
| FQ231 | `nl_policy_conflict_detector.py` + `logic/api.py` | Arabic text → `detect_all_languages(text)["ar"]` non-empty E2E (6 tests) |
| FR232 | `logic/api.py` | `detect_all_languages()` all 13 slots + `conflict_density()` over 13 langs (7 tests) |
| FS233 | `logic/api.py` | `languages_above_threshold(0)` == sorted `languages_with_conflicts` invariant (6 tests) |
| FT234 | `ucan_delegation.py` | `active_tokens_by_actor()` combined with `merge_and_publish()` (5 tests) |
| FU235 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_SV_DEONTIC_KEYWORDS` inline Swedish (3 types, 7 kw); `detect_all_languages()` → 12 languages (8 tests) |
| FV236 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_RU_DEONTIC_KEYWORDS` inline Russian (3 types, 7 kw); `detect_all_languages()` → 13 languages (9 tests) |

**New test file:** `tests/mcp/unit/test_v27_sessions.py` (62 tests)

---

## 2. Production Changes (v27)

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

**FU235:** `_SV_DEONTIC_KEYWORDS` inline Swedish keyword table (3 types, 7 keywords each):
- `"permission"`: `"får"`, `"tillåts"`, `"har rätt att"`, …
- `"prohibition"`: `"får inte"`, `"är förbjudet"`, …
- `"obligation"`: `"måste"`, `"ska"`, `"är skyldig att"`, …
- `_load_i18n_keywords("sv")` returns this table

**FV236:** `_RU_DEONTIC_KEYWORDS` inline Russian keyword table (3 types, 7 keywords each):
- `"permission"`: `"можно"`, `"разрешено"`, `"имеет право"`, …
- `"prohibition"`: `"нельзя"`, `"запрещено"`, `"не разрешено"`, …
- `"obligation"`: `"должен"`, `"обязан"`, `"необходимо"`, …
- `_load_i18n_keywords("ru")` returns this table

Both tables inserted before `_ZH_DEONTIC_KEYWORDS` for consistent ordering.
`_load_i18n_keywords()` extended with `language == "sv"` and `language == "ru"` branches.

### `ipfs_datasets_py/logic/api.py`

**FR232/FU235/FV236:** `_SUPPORTED_LANGS` extended from 11 to 13 languages:

```python
_SUPPORTED_LANGS = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar", "sv", "ru")
```

`detect_all_languages()` docstring updated to list all 13 languages.

---

## 3. Key Invariants (v27)

| Component | Invariant |
|-----------|-----------|
| `detect_all_languages(text)` | Has exactly **13** language slots: `fr/es/de/en/pt/nl/it/ja/zh/ko/ar/sv/ru` |
| `_load_i18n_keywords("sv")` | Returns dict with `permission`, `prohibition`, `obligation` |
| `_load_i18n_keywords("ru")` | Returns dict with `permission`, `prohibition`, `obligation` |
| `languages_above_threshold(0)` | `== sorted(languages_with_conflicts)` |
| `conflict_density()` with 13-lang report | Denominator is 13 |
| `active_tokens_by_actor()` ∩ `active_tokens_by_resource()` | Actor result ⊆ resource result when matching |
| `from_dict(to_dict())` | Perfect round-trip for `added`, `skipped_protected`, `skipped_duplicate`, `total` |

---

## 4. Test Coverage (v27)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestFM227ThresholdDensityCombined` | FM227 | 6 |
| `TestFN228ByActorAndByResourceCombined` | FN228 | 5 |
| `TestFO229ComplianceMergeResultRoundTrip` | FO229 | 6 |
| `TestFP230KoreanTextE2E` | FP230 | 6 |
| `TestFQ231ArabicTextE2E` | FQ231 | 6 |
| `TestFR232AllThirteenLanguagesAndDensity` | FR232 | 7 |
| `TestFS233AboveThresholdEqualsWithConflicts` | FS233 | 6 |
| `TestFT234ByActorAfterMergePublish` | FT234 | 5 |
| `TestFU235SwedishKeywords` | FU235 | 8 |
| `TestFV236RussianKeywords` | FV236 | 9 |
| **v27 total** | | **64** |

---

## 5. Cumulative Totals

| Version | Tests added | Running total |
|---------|------------|---------------|
| v13 | 77 | 2,805 |
| v14 | 114 | 2,884 |
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
| **v27** | **62** | **3,633** |

---

## 6. Security Summary (v27)

No vulnerabilities introduced:
- `_SV_DEONTIC_KEYWORDS` and `_RU_DEONTIC_KEYWORDS` are inline string tables — no network access.
- `detect_all_languages()` only adds two more constant-time loop iterations.
- All new tests are pure-Python — no file I/O or network.

---

## 7. v28 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| FW237 | Swedish text → `detect_i18n_clauses("sv")` returns list E2E | Low | 🟢 Low |
| FX238 | Russian text → `detect_i18n_clauses("ru")` returns list E2E | Low | 🟢 Low |
| FY239 | `detect_all_languages()` all 13 slots non-None | Low | 🟢 Low |
| FZ240 | `conflict_density()` with synthetic 13-lang populated report | Low | 🟡 Med |
| GA241 | Greek (`"el"`) keyword table → 14 languages | Med | 🟡 Med |
| GB242 | Turkish (`"tr"`) keyword table → 15 languages | Med | 🟡 Med |
| GC243 | Hindi (`"hi"`) keyword table → 16 languages | Med | 🟡 Med |
| GD244 | `I18NConflictReport.languages_above_threshold(n)` with 13 slots | Low | 🟢 Low |
| GE245 | `active_tokens_by_actor()` + `revoke()` + `active_token_count` combined | Low | 🟡 Med |
| GF246 | Full pipeline E2E: `detect_all_languages()` → `compile_batch()` | Med | 🔴 High |
