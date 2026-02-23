# MASTER IMPROVEMENT PLAN 2026 — v23

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Status:** ✅ v23 Complete — 63 new tests, **3,400 total**

---

## 1. Session Summary (v23)

| Session | Component | Change | Tests |
|---------|-----------|--------|-------|
| DY187 | `logic/CEC/nl/portuguese_parser.py` | `PortugueseParser.get_clauses_by_type(text, deontic_type)` convenience filter | 6 |
| DZ188 | `logic/integration/nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler.compile_batch(sentences_list, policy_ids=None)` | 6 |
| EA189 | `mcp_server/ucan_delegation.py` | `DelegationManager.active_tokens()` — non-revoked token iterator | 7 |
| EB190 | `mcp_server/policy_audit_log.py` | Tests for existing `clear()` (buffer cleared; `total_recorded` preserved) | 5 |
| EC191 | `mcp_server/compliance_checker.py` | `ComplianceMergeResult` NamedTuple; `merge()` returns `ComplianceMergeResult` | 10 |
| ED192 | `logic/CEC/nl/nl_policy_conflict_detector.py` | `_JA_DEONTIC_KEYWORDS` inline Japanese + `detect_all_languages()` → 8 langs | 7 |
| EE193 | `logic/api.py` (via `_DW185`) | `compile_explain_iter` `policy_id` + `max_lines` passthrough tests | 3 |
| EF194 | `mcp_server/ucan_delegation.py` | `DelegationManager.active_token_count` cached property | 5 |
| EG195 | `logic/api.py` | `I18NConflictReport.most_conflicted_language()` | 7 |
| EH196 | `logic/CEC/nl/nl_policy_conflict_detector.py` + `portuguese_parser.py` | Full integration tests: PT text → `detect_i18n_clauses("pt")` | 5 |

---

## 2. Production Changes (v23)

### `ipfs_datasets_py/logic/CEC/nl/portuguese_parser.py`

- **DY187** — `PortugueseParser.get_clauses_by_type(text, deontic_type)`:
  convenience wrapper around `parse()` that filters results.  Returns an empty
  list when *deontic_type* is unknown.  Does **not** modify the existing
  `parse()` method.

### `ipfs_datasets_py/logic/integration/nl_ucan_policy_compiler.py`

- **DZ188** — `NLUCANPolicyCompiler.compile_batch(sentences_list, policy_ids=None)`:
  iterates over `sentences_list`, delegates each element to `compile()`, and
  returns `List[NLUCANCompilerResult]`.  `policy_ids[i]` forwarded when present;
  `None` entries auto-generate IDs.  Empty input → `[]`.

### `ipfs_datasets_py/mcp_server/ucan_delegation.py`

- **EA189** — `DelegationManager.active_tokens()` generator:
  iterates over `_store.list_cids()`, skips revoked CIDs, yields `(cid, token)`
  pairs.  Each call produces a fresh generator — iterable twice.

- **EF194** — `DelegationManager.active_token_count` `@property`:
  delegates to `get_metrics()["active_token_count"]`; therefore consistent
  with the memoised cache and automatically invalidated by `revoke()`/`add()`/
  `remove()`/`load()`.

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

- **EC191** — `ComplianceMergeResult(added, skipped_protected, skipped_duplicate)`
  `NamedTuple` added to module. Documents the relaxed hash-equality contract
  (int-compat `__eq__`).  `merge()` return type changed from `int` →
  `ComplianceMergeResult`.  All existing tests that compare `merge()` result to
  `int` continue to work via `__eq__` / `__int__`.

  `skipped_protected` increments when `include_protected_rules=False` and a
  rule has `removable=False`.  `skipped_duplicate` increments when a rule
  whose `rule_id` is already present is skipped.

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

- **ED192** — `_JA_DEONTIC_KEYWORDS` inline Japanese keyword table
  (permission 7 / prohibition 7 / obligation 7).  `_load_i18n_keywords("ja")`
  returns it.  Docstring updated to mention `"ja"` as a supported language.

### `ipfs_datasets_py/logic/api.py`

- **ED192/EG195** — `detect_all_languages()` extended to 8 supported languages
  `("fr", "es", "de", "en", "pt", "nl", "it", "ja")`.  Docstring updated.

- **EG195** — `I18NConflictReport.most_conflicted_language()` method: iterates
  `by_language`, returns the language key with the highest conflict count, or
  `None` when all lists are empty.  Tie resolution: first in dict insertion
  order (deterministic for fixed `detect_all_languages()` call order).

---

## 3. Key Invariants (v23)

| Component | Invariant |
|-----------|-----------|
| `get_clauses_by_type(text, type)` | Result ⊆ `parse(text)`; filters by `deontic_type`; empty for unknown type |
| `compile_batch(batches)` | `len(result) == len(batches)`; `result[i].metadata["policy_id"] == policy_ids[i]` when supplied |
| `active_tokens()` | Yields only non-revoked CIDs; fresh generator per call |
| `active_token_count` | `== get_metrics()["active_token_count"]`; invalidated by `revoke()`/`add()`/... |
| `ComplianceMergeResult` | `result == N` ↔ `result.added == N`; `int(result) == result.added` |
| `merge()` skipped_protected | Counts rules with `removable=False` when `include_protected_rules=False` |
| `merge()` skipped_duplicate | Counts rules already present in `self` by `rule_id` |
| `_JA_DEONTIC_KEYWORDS` | Inline (always available); 3 types; `_load_i18n_keywords("ja")` returns it |
| `detect_all_languages()` | 8 languages: `{"fr","es","de","en","pt","nl","it","ja"}` |
| `most_conflicted_language()` | `None` when all empty; tie → first in insertion order |

---

## 4. Test Coverage (v23)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestDY187PortugueseGetClausesByType` | DY187 | 6 |
| `TestDZ188CompileBatch` | DZ188 | 6 |
| `TestEA189ActiveTokens` | EA189 | 7 |
| `TestEB190PolicyAuditLogClear` | EB190 | 5 |
| `TestEC191ComplianceMergeResult` | EC191 | 10 |
| `TestED192JapaneseKeywords` | ED192 | 7 |
| `TestEE193CompileExplainIterPolicyId` | EE193 | 3 |
| `TestEF194ActiveTokenCount` | EF194 | 5 |
| `TestEG195MostConflictedLanguage` | EG195 | 7 |
| `TestEH196PortugueseIntegration` | EH196 | 5 |
| **v23 total** | | **63** |

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
| **v23** | **63** | **3,400** |

---

## 6. Security Summary (v23)

No vulnerabilities introduced:
- `ComplianceMergeResult` int-compat hash contract documented — not a security risk.
- `active_tokens()` respects revocation list — fail-closed.
- Japanese keywords are inline — no external fetching.
- `get_clauses_by_type()` delegates to `parse()` — same trust boundary.

---

## 7. v24 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| EI197 | `DelegationManager.active_tokens_by_resource(resource)` — filter by capability | Low | 🟢 Low |
| EJ198 | `NLUCANPolicyCompiler.compile_batch` — return `List[Tuple[NLUCANCompilerResult, str]]` variant | Low | 🟢 Low |
| EK199 | `ComplianceMergeResult.total` property = `added + skipped_protected + skipped_duplicate` | Low | 🟢 Low |
| EL200 | `I18NConflictReport.conflict_density()` — `total_conflicts / supported_languages` | Low | 🟡 Med |
| EM201 | `detect_all_languages()` — Chinese (`"zh"`) inline keywords (9th language) | Low | 🟡 Med |
| EN202 | `NLUCANPolicyCompiler.compile_batch` with `fail_fast=True` option | Med | 🟡 Med |
| EO203 | `DelegationManager.active_token_count` cached property test: multiple revokes | Low | 🟢 Low |
| EP204 | Full integration: Japanese text → `detect_i18n_clauses("ja")` → `NLPolicyConflictDetector` | Med | 🔴 High |
| EQ205 | `PortugueseParser.get_clauses_by_type` + `detect_i18n_clauses("pt")` combined test | Low | 🟡 Med |
| ER206 | `PolicyAuditLog.clear()` + `export_jsonl()` round-trip: cleared log exports 0 entries | Low | 🟢 Low |
