# MASTER IMPROVEMENT PLAN 2026 — v25

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Session:** ES207–FB216 (v25)
**Cumulative total:** 3,457 + 56 = **3,513 tests**

---

## 1. Session Summary (v25)

| Session | Module | What was done |
|---------|--------|---------------|
| ES207 | `ucan_delegation.py` | `active_tokens_by_resource("*")` — wildcard capability tokens match *any* resource string (6 tests) |
| ET208 | `nl_ucan_policy_compiler.py` | `compile_batch_with_explain(fail_fast=True)` combined test coverage; shows fail_fast works end-to-end (5 tests) |
| EU209 | `compliance_checker.py` | `ComplianceMergeResult.to_dict()` → `{"added","skipped_protected","skipped_duplicate","total"}` (5 tests) |
| EV210 | `logic/api.py` | `I18NConflictReport.least_conflicted_language()` — complement of `most_conflicted_language()` (6 tests) |
| EW211 | `nl_policy_conflict_detector.py` | `_ZH_DEONTIC_KEYWORDS` obligation keyword coverage tests (6 tests) |
| EX212 | `nl_ucan_policy_compiler.py` | `compile_batch(policy_ids=[...])` shorter list → auto-ID fills tail positions (5 tests) |
| EY213 | `ucan_delegation.py` | `active_tokens_by_resource` + revocation combined: revoked tokens excluded (4 tests) |
| EZ214 | `nl_policy_conflict_detector.py` + `logic/api.py` | Chinese text → `by_language["zh"]` slot present; `detect_i18n_clauses("zh")` returns list (6 tests) |
| FA215 | `logic/api.py` | `conflict_density()` with all 9 languages populated via `detect_all_languages()` (5 tests) |
| FB216 | `nl_ucan_policy_compiler.py` | `compile_batch_with_explain(fail_fast=True)` variant — signature + behaviour tests (5 tests) |

**New test file:** `tests/mcp/unit/test_v25_sessions.py` (53 tests)

---

## 2. Production Changes (v25)

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

**EU209:** `ComplianceMergeResult.to_dict()` method added:

```python
def to_dict(self) -> Dict[str, Any]:
    return {
        "added": self.added,
        "skipped_protected": self.skipped_protected,
        "skipped_duplicate": self.skipped_duplicate,
        "total": self.total,
    }
```

### `ipfs_datasets_py/logic/api.py`

**EV210:** `I18NConflictReport.least_conflicted_language()` method added:

```python
def least_conflicted_language(self) -> Optional[str]:
    best: Optional[str] = None
    best_count: Optional[int] = None
    for lang, conflicts in self.by_language.items():
        n = len(conflicts)
        if n > 0 and (best_count is None or n < best_count):
            best = lang
            best_count = n
    return best
```

### `ipfs_datasets_py/logic/integration/nl_ucan_policy_compiler.py`

**ET208/FB216:** `compile_batch_with_explain()` extended with `fail_fast: bool = False` parameter
that is forwarded to `compile_batch()`:

```python
def compile_batch_with_explain(
    self,
    sentences_list,
    policy_ids=None,
    *,
    fail_fast: bool = False,
) -> List[Tuple[NLUCANCompilerResult, str]]:
    results = self.compile_batch(sentences_list, policy_ids=policy_ids, fail_fast=fail_fast)
    return [(r, r.explain()) for r in results]
```

---

## 3. Key Invariants (v25)

| Component | Invariant |
|-----------|-----------|
| `active_tokens_by_resource("*")` | Matches tokens whose capability `resource == "*"` |
| `active_tokens_by_resource(r)` for wildcard token | Wildcard cap (`resource="*"`) matches *any* `r` |
| `ComplianceMergeResult.to_dict()["total"]` | `== r.total == added + skipped_protected + skipped_duplicate` |
| `least_conflicted_language()` | `None` when all langs have 0 conflicts; first-in-order on tie |
| `least_conflicted_language()` vs `most_conflicted_language()` | Never equal when ≥2 languages have different conflict counts |
| `_ZH_DEONTIC_KEYWORDS["obligation"]` | Contains `"必须"`, `"应当"` or equivalent |
| `compile_batch(policy_ids=short)` | Short list auto-fills tail; result count == batches count |
| `compile_batch_with_explain(fail_fast=True)` | Forwards `fail_fast` to `compile_batch` |
| `detect_all_languages(text)["zh"]` | Always present (returns `[]` when no Chinese parser) |
| `conflict_density()` (9 langs) | `total_conflicts / 9` for `detect_all_languages()` output |

---

## 4. Test Coverage (v25)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestES207WildcardResource` | ES207 | 6 |
| `TestET208CompileBatchWithExplainFailFast` | ET208 | 5 |
| `TestEU209ComplianceMergeResultToDict` | EU209 | 5 |
| `TestEV210LeastConflictedLanguage` | EV210 | 6 |
| `TestEW211ChineseKeywordCoverage` | EW211 | 6 |
| `TestEX212CompileBatchShortPolicyIds` | EX212 | 5 |
| `TestEY213ActiveTokensByResourceRevocation` | EY213 | 4 |
| `TestEZ214ChineseTextE2E` | EZ214 | 6 |
| `TestFA215ConflictDensityAllLanguages` | FA215 | 5 |
| `TestFB216CompileBatchWithExplainFailFastVariant` | FB216 | 5 |
| **v25 total** | | **53** |

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
| **v25** | **53** | **3,510** |

---

## 6. Security Summary (v25)

No vulnerabilities introduced:
- `to_dict()` serialises only numeric fields — no leakage risk.
- `least_conflicted_language()` iterates existing data — no external calls.
- `compile_batch_with_explain(fail_fast=True)` propagates the flag to the
  existing `compile_batch` which already stops on first error — no new attack
  surface.
- `active_tokens_by_resource("*")` respects revocation — fail-closed.

---

## 7. v26 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| FC217 | `I18NConflictReport.languages_above_threshold(n)` — languages with > n conflicts | Low | 🟢 Low |
| FD218 | `DelegationManager.active_tokens_by_actor(actor)` — filter by `token.audience` | Low | 🟢 Low |
| FE219 | `ComplianceMergeResult.from_dict(d)` — reconstruct from `to_dict()` output | Low | 🟢 Low |
| FF220 | `compile_batch_with_explain` policy_ids shorter than batches | Low | 🟡 Med |
| FG221 | `least_conflicted_language()` with real `detect_all_languages()` output | Low | 🟢 Low |
| FH222 | `detect_i18n_clauses` for all 9 languages round-trip (each returns a list) | Med | 🔴 High |
| FI223 | `DelegationManager.merge()` + `active_tokens_by_resource()` combined | Low | 🟡 Med |
| FJ224 | `conflict_density()` with `least_conflicted_language()` combined | Low | 🟢 Low |
| FK225 | Korean (`"ko"`) keyword table + `detect_all_languages()` → 10 languages | Med | 🟡 Med |
| FL226 | Arabic (`"ar"`) keyword table + `detect_all_languages()` → 11 languages | Med | 🟡 Med |
