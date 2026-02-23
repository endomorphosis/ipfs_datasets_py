# Master Improvement Plan 2026 — v24
> Branch: `copilot/create-refactoring-plan-again`  
> Session date: 2026-02-23  
> Supersedes: `MASTER_IMPROVEMENT_PLAN_2026_v23.md`

---

## 1. Session Overview

This session implements 10 backlog items (EI197–ER206) identified in v23's
"v24 Candidates" table, advancing the logic-layer, delegation management,
i18n conflict detection, and compiler facilities.

| Session | Module | Description | Tests |
|---------|--------|-------------|-------|
| EI197 | `ucan_delegation.py` | `DelegationManager.active_tokens_by_resource(resource)` | 7 |
| EJ198 | `nl_ucan_policy_compiler.py` | `compile_batch_with_explain()` | 6 |
| EK199 | `compliance_checker.py` | `ComplianceMergeResult.total` property | 5 |
| EL200 | `logic/api.py` | `I18NConflictReport.conflict_density()` | 5 |
| EM201 | `nl_policy_conflict_detector.py` | `_ZH_DEONTIC_KEYWORDS` Chinese (9th lang) | 7 |
| EN202 | `nl_ucan_policy_compiler.py` | `compile_batch(fail_fast=True)` | 6 |
| EO203 | `ucan_delegation.py` | `active_token_count` multi-revoke caching tests | 5 |
| EP204 | `nl_policy_conflict_detector.py` | Japanese text → `detect_i18n_clauses("ja")` | 6 |
| EQ205 | `portuguese_parser.py` | `get_clauses_by_type` + `detect_i18n_clauses("pt")` | 5 |
| ER206 | `policy_audit_log.py` | `clear()` + `export_jsonl()` round-trip tests | 5 |
| **v24 total** | | | **57** |

---

## 2. Production Changes

### `ipfs_datasets_py/mcp_server/ucan_delegation.py`

- **EI197** — `DelegationManager.active_tokens_by_resource(resource)`:
  generator yielding `(cid, token)` pairs from `active_tokens()` where any
  `Capability.resource == resource` or `== "*"`.  Each token yielded at most
  once per call (breaks after first matching capability).

### `ipfs_datasets_py/logic/integration/nl_ucan_policy_compiler.py`

- **EJ198** — `NLUCANPolicyCompiler.compile_batch_with_explain(sentences_list,
  policy_ids=None)` → `List[Tuple[NLUCANCompilerResult, str]]`: delegates to
  `compile_batch()` then pairs each result with `result.explain()`.

- **EN202** — `compile_batch(*, fail_fast: bool = False)`: new keyword-only
  flag; when `True`, iteration stops after the first result with non-empty
  `errors`; partial list returned.

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

- **EK199** — `ComplianceMergeResult.total` `@property` = `added +
  skipped_protected + skipped_duplicate`.  Does not affect `int` equality
  semantics (those use `added` only).

### `ipfs_datasets_py/logic/api.py`

- **EL200** — `I18NConflictReport.conflict_density()` method:
  `total_conflicts / len(by_language)`;  `0.0` when empty.

- **EM201** — `detect_all_languages()` docstring updated to mention `"zh"`;
  `_SUPPORTED_LANGS` extended to 9 languages:
  `("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh")`.

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

- **EM201** — `_ZH_DEONTIC_KEYWORDS` inline Chinese deontic keyword table
  (3 types; 7 keywords each).  `_load_i18n_keywords("zh")` returns it.
  `_load_i18n_keywords` docstring updated to list `"zh"` as supported.

---

## 3. Key Invariants (v24)

| Component | Invariant |
|-----------|-----------|
| `active_tokens_by_resource(r)` | Result ⊆ `active_tokens()`; each token at most once |
| `compile_batch_with_explain` | `len == len(input)`; `t[1] == t[0].explain()` for each tuple |
| `ComplianceMergeResult.total` | `== added + skipped_protected + skipped_duplicate` |
| `conflict_density()` | `total_conflicts / len(by_language)`; `0.0` for empty |
| `_ZH_DEONTIC_KEYWORDS` | Inline; 3 types; `_load_i18n_keywords("zh")` is it |
| `detect_all_languages()` | 9 languages: `{"fr","es","de","en","pt","nl","it","ja","zh"}` |
| `compile_batch(fail_fast=True)` | Stops after first result with errors |
| `active_token_count` caching | Invalidated by every `revoke()` call |

---

## 4. Test Coverage (v24)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestEI197ActiveTokensByResource` | EI197 | 7 |
| `TestEJ198CompileBatchWithExplain` | EJ198 | 6 |
| `TestEK199ComplianceMergeResultTotal` | EK199 | 5 |
| `TestEL200ConflictDensity` | EL200 | 5 |
| `TestEM201ChineseKeywords` | EM201 | 7 |
| `TestEN202CompileBatchFailFast` | EN202 | 6 |
| `TestEO203ActiveTokenCountCaching` | EO203 | 5 |
| `TestEP204JapaneseIntegration` | EP204 | 6 |
| `TestEQ205PortuguesePipelineCombined` | EQ205 | 5 |
| `TestER206ClearExportRoundTrip` | ER206 | 5 |
| **v24 total** | | **57** |

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
| **v24** | **57** | **3,457** |

---

## 6. Security Summary (v24)

No vulnerabilities introduced:
- `active_tokens_by_resource` respects revocation list — fail-closed.
- Chinese keywords are inline — no external fetching.
- `compile_batch(fail_fast=True)` stops early on error — doesn't expose
  more data on failure.
- `conflict_density()` divides by language-slot count (never 0 in practice
  since `detect_all_languages()` always populates all slots).

---

## 7. v25 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| ES207 | `DelegationManager.active_tokens_by_resource("*")` edge case — wildcard matches all | Low | 🟢 Low |
| ET208 | `compile_batch_with_explain` + `fail_fast=True` combined | Low | 🟢 Low |
| EU209 | `ComplianceMergeResult.to_dict()` — {"added","skipped_protected","skipped_duplicate","total"} | Low | 🟢 Low |
| EV210 | `I18NConflictReport.least_conflicted_language()` — complement of `most_conflicted_language()` | Low | 🟢 Low |
| EW211 | `_ZH_DEONTIC_KEYWORDS` obligation keyword coverage test | Low | 🟢 Low |
| EX212 | `compile_batch` `policy_ids` shorter than batches — auto-ID fills tail | Low | 🟡 Med |
| EY213 | `active_tokens_by_resource` + revocation combined: resource match but revoked | Low | 🟢 Low |
| EZ214 | `detect_all_languages` Chinese text → `by_language["zh"]` non-empty | Med | 🔴 High |
| FA215 | `conflict_density()` with all 9 languages populated | Low | 🟡 Med |
| FB216 | `NLUCANPolicyCompiler.compile_batch_with_explain` `fail_fast=True` variant | Low | 🟡 Med |
