# MASTER IMPROVEMENT PLAN 2026 — v26

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Session:** FC217–FL226 (v26)
**Cumulative total:** 3,510 + 61 = **3,571 tests**

---

## 1. Session Summary (v26)

| Session | Module | What was done |
|---------|--------|---------------|
| FC217 | `logic/api.py` | `I18NConflictReport.languages_above_threshold(n)` — sorted list of languages with > n conflicts (6 tests) |
| FD218 | `ucan_delegation.py` | `DelegationManager.active_tokens_by_actor(actor)` — yields `(cid, token)` pairs filtered by `token.audience == actor` (6 tests) |
| FE219 | `compliance_checker.py` | `ComplianceMergeResult.from_dict(d)` classmethod — reconstruct from `to_dict()` output; unknown keys silently ignored; missing keys → 0 (7 tests) |
| FF220 | `nl_ucan_policy_compiler.py` | `compile_batch_with_explain` + shorter `policy_ids` combined test coverage (3 tests) |
| FG221 | `logic/api.py` | `least_conflicted_language()` with real `detect_all_languages()` output (4 tests) |
| FH222 | `nl_policy_conflict_detector.py` + `logic/api.py` | `detect_i18n_clauses` all 9 original languages round-trip (10 tests) |
| FI223 | `ucan_delegation.py` | `DelegationManager.merge()` + `active_tokens_by_resource()` combined E2E (5 tests) |
| FJ224 | `logic/api.py` | `conflict_density()` + `least_conflicted_language()` combined tests (6 tests) |
| FK225 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_KO_DEONTIC_KEYWORDS` Korean inline (3 types); `detect_all_languages()` → 10 languages (7 tests) |
| FL226 | `nl_policy_conflict_detector.py` + `logic/api.py` | `_AR_DEONTIC_KEYWORDS` Arabic inline (3 types); `detect_all_languages()` → 11 languages (8 tests) |

**New test file:** `tests/mcp/unit/test_v26_sessions.py` (61 tests)

---

## 2. Production Changes (v26)

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

**FK225:** `_KO_DEONTIC_KEYWORDS` inline Korean keyword table (3 types, 7 keywords each):
- `"permission"`: `"할 수 있다"`, `"허용된다"`, …
- `"prohibition"`: `"할 수 없다"`, `"금지된다"`, …
- `"obligation"`: `"해야 한다"`, `"필수적이다"`, …
- `_load_i18n_keywords("ko")` returns this table

**FL226:** `_AR_DEONTIC_KEYWORDS` inline Arabic keyword table (3 types, 7 keywords each):
- `"permission"`: `"يجوز"`, `"مسموح"`, …
- `"prohibition"`: `"لا يجوز"`, `"محظور"`, …
- `"obligation"`: `"يجب"`, `"ينبغي"`, …
- `_load_i18n_keywords("ar")` returns this table

### `ipfs_datasets_py/logic/api.py`

**FC217:** `I18NConflictReport.languages_above_threshold(n)` method:

```python
def languages_above_threshold(self, n: int) -> List[str]:
    return sorted(
        lang for lang, conflicts in self.by_language.items()
        if len(conflicts) > n
    )
```

**FK225/FL226:** `detect_all_languages()` `_SUPPORTED_LANGS` extended from 9 to 11:

```python
_SUPPORTED_LANGS = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar")
```

### `ipfs_datasets_py/mcp_server/ucan_delegation.py`

**FD218:** `DelegationManager.active_tokens_by_actor(actor)` generator:

```python
def active_tokens_by_actor(self, actor: str):
    for cid, token in self.active_tokens():
        if token.audience == actor:
            yield cid, token
```

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

**FE219:** `ComplianceMergeResult.from_dict(d)` classmethod:

```python
@classmethod
def from_dict(cls, d: Dict[str, Any]) -> "ComplianceMergeResult":
    return cls(
        added=int(d.get("added", 0)),
        skipped_protected=int(d.get("skipped_protected", 0)),
        skipped_duplicate=int(d.get("skipped_duplicate", 0)),
    )
```

---

## 3. Key Invariants (v26)

| Component | Invariant |
|-----------|-----------|
| `languages_above_threshold(0)` | Equivalent to `languages_with_conflicts` (sorted) |
| `languages_above_threshold(n)` for high n | Returns `[]` when no language exceeds threshold |
| `active_tokens_by_actor(actor)` | Never yields revoked tokens |
| `ComplianceMergeResult.from_dict(to_dict())` | Round-trip preserves `added`, `skipped_*`, and `total` |
| `from_dict({})` | All fields default to `0` |
| `from_dict({"added":5})` | `total == 5` |
| `detect_all_languages(text)` | Has exactly 11 language slots: `fr/es/de/en/pt/nl/it/ja/zh/ko/ar` |
| `_load_i18n_keywords("ko")` | Returns dict with `permission`, `prohibition`, `obligation` |
| `_load_i18n_keywords("ar")` | Returns dict with `permission`, `prohibition`, `obligation` |

---

## 4. Test Coverage (v26)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestFC217LanguagesAboveThreshold` | FC217 | 6 |
| `TestFD218ActiveTokensByActor` | FD218 | 6 |
| `TestFE219ComplianceMergeResultFromDict` | FE219 | 7 |
| `TestFF220CompileBatchWithExplainShortPolicyIds` | FF220 | 3 |
| `TestFG221LeastConflictedWithRealDetectAll` | FG221 | 4 |
| `TestFH222DetectI18NClausesAllLanguages` | FH222 | 10 |
| `TestFI223MergeAndActiveTokensByResource` | FI223 | 5 |
| `TestFJ224ConflictDensityAndLeastConflicted` | FJ224 | 6 |
| `TestFK225KoreanKeywords` | FK225 | 7 |
| `TestFL226ArabicKeywords` | FL226 | 8 |
| **v26 total** | | **61 (+ 1 skip)** |

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
| **v26** | **61** | **3,571** |

---

## 6. Security Summary (v26)

No vulnerabilities introduced:
- `languages_above_threshold()` is a pure iteration over existing data.
- `active_tokens_by_actor()` respects revocation (fail-closed via `active_tokens()`).
- `ComplianceMergeResult.from_dict()` uses `int()` coercion — no injection risk.
- Korean/Arabic keywords are inline string tables — no network access.

---

## 7. v27 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| FM227 | `I18NConflictReport.languages_above_threshold(n)` + `conflict_density()` combined | Low | 🟢 Low |
| FN228 | `DelegationManager.active_tokens_by_actor()` + `active_tokens_by_resource()` combined | Low | 🟢 Low |
| FO229 | `ComplianceMergeResult.from_dict()` + `to_dict()` round-trip property test | Low | 🟢 Low |
| FP230 | Korean text → `detect_all_languages(text)["ko"]` non-empty E2E | Low | 🟡 Med |
| FQ231 | Arabic text → `detect_all_languages(text)["ar"]` non-empty E2E | Low | 🟡 Med |
| FR232 | `detect_all_languages()` all 11 slots present + conflict_density() over 11 langs | Low | 🟡 Med |
| FS233 | `languages_above_threshold(0)` == sorted `languages_with_conflicts` invariant test | Low | 🟢 Low |
| FT234 | `active_tokens_by_actor()` combined with `merge_and_publish()` | Low | 🟡 Med |
| FU235 | Swedish (`"sv"`) keyword table → 12 languages | Med | 🟡 Med |
| FV236 | Russian (`"ru"`) keyword table → 13 languages | Med | 🟡 Med |
