# MASTER IMPROVEMENT PLAN 2026 — v19

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Supersedes:** v18
**Status:** Complete ✅

---

## Session Table (v19)

| Session | Target Module | Symbol(s) Added | Tests | Status |
|---------|--------------|-----------------|-------|--------|
| CQ153 | `ucan_delegation.py` | `DelegationManager.merge()`, `merge_and_publish()` | 8 | ✅ |
| CR154 | `compliance_checker.py` | `ComplianceChecker.diff()` | 7 | ✅ |
| CS155 | `policy_audit_log.py` | `PolicyAuditLog.export_jsonl()`, `import_jsonl()` | 8 | ✅ |
| CW159 | `nl_ucan_policy_compiler.py` | `NLUCANCompilerResult.explain()` | 9 | ✅ |
| CT156 | `logic/api.py` | `I18NConflictReport`, `detect_all_languages()` | 10 | ✅ |
| CX160 | E2E smoke | `DispatchPipeline` + `DelegationManager` + `PolicyAuditLog` | 7 | ✅ |
| CU157 | `TDFOL/nl/` | `PatternType`, `Pattern`, `PatternMatch` tests | 10 | ✅ |
| **v19 total** | | | **59** | ✅ |

**Cumulative:** 3,112 (v18) + 59 (v19) → **3,171 tests** · 0 failing

---

## Production Changes (v19)

### `mcp_server/ucan_delegation.py`

- **CQ153 (merge)** — `DelegationManager.merge(other: DelegationManager) -> int`:
  Copies non-duplicate tokens from `other._store.list_cids()` into `self`.
  Tokens whose CID is already present are silently skipped.  Revocations are
  **not** copied.  Invalidates evaluator + metrics caches when `added > 0`.
  Returns number of tokens added (0 if all duplicates).

- **CQ153 (merge_and_publish)** — `DelegationManager.merge_and_publish(other, pubsub) -> int`:
  Calls `merge(other)`, then calls `pubsub.publish("receipt_disseminate",
  {"type":"merge","added":N,"total":M})`.  Duck-typed: `pubsub` only needs
  `.publish(str, dict)`.  Exceptions from pubsub swallowed at DEBUG.
  Returns number of tokens added.

### `mcp_server/compliance_checker.py`

- **CR154** — `ComplianceChecker.diff(other: ComplianceChecker) -> dict`:
  Returns a diff dict with four keys:
  - `added_rules` — rule IDs present in `other` but not in `self` (sorted list)
  - `removed_rules` — rule IDs present in `self` but not in `other` (sorted list)
  - `common_rules` — rule IDs present in both (sorted list)
  - `changed_rules` — rule IDs in both where `description` or `removable` differs

### `mcp_server/policy_audit_log.py`

- **CS155 (export_jsonl)** — `PolicyAuditLog.export_jsonl(path: str) -> int`:
  Writes all current in-memory entries to *path* as JSONL (one JSON object per
  line; overwrites existing file; creates parent directories).  Returns count.

- **CS155 (import_jsonl)** — `PolicyAuditLog.import_jsonl(path: str) -> int`:
  Reads JSONL from *path* and appends valid entries to the in-memory buffer
  (respecting `max_entries` ring buffer).  Returns count imported.  Returns 0
  for non-existent files.  Malformed lines are skipped with DEBUG log.

### `logic/integration/nl_ucan_policy_compiler.py`

- **CW159** — `NLUCANCompilerResult.explain() -> str`:
  Returns a human-readable multi-line string describing the compilation outcome:
  `"Compilation succeeded/failed."`, sentence/clause/formula/token counts,
  delegation evaluator readiness, and any errors/warnings (first 3 each).

### `logic/api.py`

- **CT156 (I18NConflictReport)** — New dataclass with:
  - `by_language: Dict[str, List[PolicyConflict]]`
  - `total_conflicts: int` property (sum across all languages)
  - `languages_with_conflicts: List[str]` property (sorted list of non-empty langs)
  - `to_dict()` method (calls `conflict.to_dict()` for each entry)

- **CT156 (detect_all_languages)** — `detect_all_languages(text: str) -> I18NConflictReport`:
  Runs `detect_i18n_clauses(text, lang)` for `"fr"`, `"es"`, `"de"`.  Returns
  `I18NConflictReport` with per-language results (empty lists on ImportError).

- Both symbols added to `__all__` unconditionally (since `I18NConflictReport`
  is defined in `api.py` itself, not imported).

---

## Key Invariants (v19)

| Component | Invariant |
|-----------|-----------|
| `DelegationManager.merge()` | Does NOT copy revocations; invalidates caches only when `added>0`; returns 0 for empty source |
| `DelegationManager.merge_and_publish()` | pubsub exceptions swallowed at DEBUG; always returns the token count |
| `ComplianceChecker.diff()` | `changed_rules` ⊆ `common_rules`; all four keys always present |
| `PolicyAuditLog.export_jsonl()` | Overwrites file; creates parent dirs; returns count |
| `PolicyAuditLog.import_jsonl()` | 0 for missing path; skips malformed lines; respects `max_entries` ring buffer |
| `NLUCANCompilerResult.explain()` | Never raises; returns `str`; mentions "succeeded" or "failed" |
| `I18NConflictReport` | Always contains all 3 language keys after `detect_all_languages()`; `total_conflicts` is 0 when all lists empty |
| `detect_all_languages()` | Returns `I18NConflictReport`; ImportError per-language → empty list (not raise) |

---

## Test Coverage

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestCQ153DelegationManagerMerge` | CQ153 | 8 |
| `TestCR154ComplianceCheckerDiff` | CR154 | 7 |
| `TestCS155AuditLogJsonlIO` | CS155 | 8 |
| `TestCW159CompilerExplain` | CW159 | 9 |
| `TestCT156I18NConflictReport` | CT156 | 10 |
| `TestCX160FullPipelineE2E` | CX160 | 7 |
| `TestCU157TDFOLNLPatterns` | CU157 | 10 |
| **v19 total** | | **59** |

---

## v20 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| CY161 | `DelegationManager.merge_and_publish()` — publish full metrics snapshot, not just merge count | Low | 🟡 Med |
| CZ162 | `PolicyAuditLog.export_jsonl()` → include metadata field in export | Low | 🟢 Low |
| DA163 | `ComplianceChecker.merge(other)` — add rules from other; symmetric to diff | Low | 🟡 Med |
| DB164 | `NLUCANPolicyCompiler.compile_explain(sentences)` — compile + explain in one call | Low | 🟢 Low |
| DC165 | `detect_all_languages()` — add `"en"` keyword pass via English NL conflict detector | Med | 🟡 Med |
| DD166 | Full `DelegationManager.merge_and_publish()` with PubSubBus | Med | 🟡 Med |
| DE167 | TDFOL NL `NLParser.parse()` with mocked spaCy — verify formula type inference | Med | 🟡 Med |
| DF168 | `evaluate_with_manager` + `detect_all_languages` combined end-to-end test | Med | 🔴 High |
