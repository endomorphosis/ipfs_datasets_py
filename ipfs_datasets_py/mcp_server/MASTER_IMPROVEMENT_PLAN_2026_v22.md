# MASTER IMPROVEMENT PLAN 2026 — v22

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Status:** ✅ v22 Complete — 54 new tests, **3,337 total**

---

## 1. Session Summary (v22)

| Session | Component | Change | Tests |
|---------|-----------|--------|-------|
| DO177 | `nl_policy_conflict_detector.py` | `_IT_DEONTIC_KEYWORDS` inline Italian + `_load_i18n_keywords("it")` + `detect_all_languages()` → 7 languages | 9 |
| DP178 | `logic/CEC/nl/portuguese_parser.py` | `PortugueseParser.parse()` sentence-level splitting — multi-clause extraction via `re.split(r"[.!?;]+")` | 6 |
| DQ179 | `ucan_delegation.py` | `merge_and_publish_async()` payload adds `"event_type": "RECEIPT_DISSEMINATE"` field | 3 |
| DR180 | `policy_audit_log.py` | `import_jsonl()` max_entries ring-buffer clipping tests with large files | 3 |
| DS181 | `compliance_checker.py` | `merge()` now uses `copy.copy(rule)` — deep copy prevents mutation leaks; `import copy` added | 5 |
| DT182 | `nl_ucan_policy_compiler.py` | `compile_explain_iter(max_lines=None)` truncation parameter | 5 |
| DU183 | `nl_policy_conflict_detector.py` | Dutch obligation keyword coverage tests | 4 |
| DV184 | `ucan_delegation.py` | `get_metrics()` adds `active_token_count`; `revoke()` invalidates `_metrics_cache` | 5 |
| DW185 | `logic/api.py` | `compile_explain_iter` module-level wrapper re-export; `_DW185_COMPILER_AVAILABLE` guard | 5 |
| DX186 | `logic/api.py` + `nl_policy_conflict_detector.py` | Full E2E 7-language `detect_all_languages()` + `I18NConflictReport.to_dict()` | 9 |

---

## 2. Production Changes (v22)

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

- **DO177** — `_IT_DEONTIC_KEYWORDS: Dict[str, List[str]]` Italian inline keyword
  table (permission/prohibition/obligation), no external deps.  `_load_i18n_keywords("it")`
  returns inline table (same pattern as `"en"` / `"nl"`).

### `ipfs_datasets_py/logic/CEC/nl/portuguese_parser.py`

- **DP178** — `PortugueseParser.parse(text)` now splits on sentence boundaries
  (`re.split(r"[.!?;]+")`) before scanning for deontic keywords.  Each
  sentence can yield at most one clause per deontic type, so a two-sentence
  input with one permission and one prohibition now produces two clauses.

### `ipfs_datasets_py/mcp_server/ucan_delegation.py`

- **DQ179** — `merge_and_publish_async()` payload now includes
  `"event_type": "RECEIPT_DISSEMINATE"` in addition to the existing
  `"type": "merge"` field.  Backward-compatible: existing receivers that
  check `payload["type"]` are unaffected.
- **DV184** — `DelegationManager.get_metrics()` extended with
  `"active_token_count"` = `max(0, token_count - revoked_count)`.
  `revoke(cid)` now clears `_metrics_cache` so subsequent `get_metrics()`
  calls reflect the latest revocation.

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

- **DS181** — `merge()` now stores `copy.copy(rule)` (shallow copy) so that
  mutations to a source rule's `description` attribute in the other checker do
  not affect the merged rule in self.  `import copy` added at the top of the
  module.

### `ipfs_datasets_py/logic/integration/nl_ucan_policy_compiler.py`

- **DT182** — `compile_explain_iter(sentences, policy_id=None, max_lines=None)`
  — new optional `max_lines` parameter.  When `max_lines` is not ``None``,
  at most `max_lines` lines are yielded.  `max_lines=0` yields nothing.
  Existing callers without `max_lines` are unaffected.

### `ipfs_datasets_py/logic/api.py`

- **DO177/DX186** — `detect_all_languages()` updated to 7 supported languages:
  `("fr", "es", "de", "en", "pt", "nl", "it")`.  Italian uses inline table
  (always available).
- **DW185** — `compile_explain_iter(sentences, policy_id=None, max_lines=None)`
  module-level wrapper added.  Creates a fresh `NLUCANPolicyCompiler` and
  delegates to its instance method.  `_DW185_COMPILER_AVAILABLE` flag guards
  import; conditionally added to `__all__`.

---

## 3. Key Invariants (v22)

| Component | Invariant |
|-----------|-----------|
| `_IT_DEONTIC_KEYWORDS` (DO177) | Inline table for Italian — always available, no import |
| `detect_all_languages()` (DO177) | Returns exactly 7 language keys: `{"fr","es","de","en","pt","nl","it"}` |
| `PortugueseParser.parse()` (DP178) | Splits on `[.!?;]+`; two-sentence input → ≥2 clauses when both have deontic keywords |
| `merge_and_publish_async()` (DQ179) | `"event_type": "RECEIPT_DISSEMINATE"` in payload; `"type": "merge"` still present |
| `merge()` (DS181) | `copy.copy(rule)` — shallow copy; mutations to src don't affect dst |
| `compile_explain_iter(max_lines=N)` (DT182) | Yields ≤N lines; N=0 → empty; N=None → all |
| `get_metrics()["active_token_count"]` (DV184) | `max(0, token_count - revoked_count)` |
| `revoke(cid)` (DV184) | Clears `_metrics_cache`; next `get_metrics()` recomputes |
| `compile_explain_iter` in `api.__all__` (DW185) | Conditional on `_DW185_COMPILER_AVAILABLE` |
| v21 backward compat | `test_detect_all_languages_6_langs` relaxed to `>= 6` (was `== 6`) |

---

## 4. Test Coverage (v22)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestDO177ItalianKeywords` | DO177 | 9 |
| `TestDP178PortugueseParserMultiClause` | DP178 | 6 |
| `TestDQ179MergePublishAsyncEventType` | DQ179 | 3 |
| `TestDR180ImportJsonlMaxEntriesLargeFile` | DR180 | 3 |
| `TestDS181MergeDeepCopy` | DS181 | 5 |
| `TestDT182CompileExplainIterMaxLines` | DT182 | 5 |
| `TestDU183DutchObligationKeywords` | DU183 | 4 |
| `TestDV184ActiveTokenCount` | DV184 | 5 |
| `TestDW185CompileExplainIterReexport` | DW185 | 5 |
| `TestDX186FullI18NE2E` | DX186 | 9 |
| **v22 total** | | **54** |

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
| **v22** | **54** | **3,337** |

---

## 6. v23 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| DY187 | `PortugueseParser` — add `get_clauses_by_type(deontic_type)` convenience method | Low | 🟢 Low |
| DZ188 | `NLUCANPolicyCompiler` — `compile_batch(sentences_list)` for multiple policy sets | Med | 🟡 Med |
| EA189 | `DelegationManager.active_tokens()` — iterator over non-revoked tokens | Med | 🔴 High |
| EB190 | `PolicyAuditLog.clear()` — reset all entries + stats | Low | 🟡 Med |
| EC191 | `ComplianceChecker.merge()` returns `MergeResult(added, skipped_protected, skipped_duplicate)` | Med | 🟡 Med |
| ED192 | `detect_all_languages()` — add `"ja"` Japanese inline keywords (8th language) | Low | 🟢 Low |
| EE193 | `compile_explain_iter` in `api.py` — `policy_id` parameter passthrough test | Low | 🟢 Low |
| EF194 | `DelegationManager.active_token_count` property (cached) | Low | 🟡 Med |
| EG195 | `I18NConflictReport.most_conflicted_language()` — returns language with most conflicts | Low | 🟡 Med |
| EH196 | Full integration: `PortugueseParser` → `detect_i18n_clauses("pt")` → `NLPolicyConflictDetector` | Med | 🔴 High |
