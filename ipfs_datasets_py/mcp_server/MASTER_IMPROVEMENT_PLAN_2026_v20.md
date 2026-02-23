# MASTER IMPROVEMENT PLAN 2026 — v20

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Supersedes:** v19
**Status:** Complete ✅

---

## Session Table (v20)

| Session | Target Module | Symbol(s) Added / Modified | Tests | Status |
|---------|--------------|---------------------------|-------|--------|
| CY161 | `ucan_delegation.py` | `DelegationManager.merge_and_publish()` — full metrics snapshot in payload | 7 | ✅ |
| CZ162 | `policy_audit_log.py` | `PolicyAuditLog.export_jsonl(metadata=None)` — optional header line | 7 | ✅ |
| DA163 | `compliance_checker.py` | `ComplianceChecker.merge(other) -> int` | 7 | ✅ |
| DB164 | `nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler.compile_explain(sentences)` | 8 | ✅ |
| DC165 | `nl_policy_conflict_detector.py` + `logic/api.py` | English (`"en"`) keyword pass in `detect_all_languages()` | 8 | ✅ |
| DD166 | (test only) | `merge_and_publish()` with duck-typed PubSubBus | 6 | ✅ |
| DE167 | (test only) | TDFOL `NLParser.parse()` with mocked dependencies | 10 | ✅ |
| DF168 | (test only) | `evaluate_with_manager` + `detect_all_languages` combined E2E | 8 | ✅ |
| **v20 total** | | | **61** | ✅ |

**Cumulative:** 3,171 (v19) + 61 (v20) → **3,232 tests** · 0 failing  
_(2 skipped — spaCy/TDFOL deps not installed in CI)_

---

## Production Changes (v20)

### `mcp_server/ucan_delegation.py`

- **CY161** — `DelegationManager.merge_and_publish(other, pubsub) -> int`:
  Payload now includes a `"metrics"` key containing the full snapshot from
  `get_metrics()` (e.g. `token_count`, `revoked_count`, `max_chain_depth`).
  Consumers no longer need a separate round-trip to discover post-merge state.
  Existing `"added"` and `"total"` keys are preserved.

### `mcp_server/policy_audit_log.py`

- **CZ162** — `PolicyAuditLog.export_jsonl(path, *, metadata=None) -> int`:
  Optional keyword parameter `metadata: Optional[Dict[str, Any]]`.  When
  provided, writes a header line `{"__metadata__": {...}}` as the first line
  of the JSONL file before any audit entries.  Return value counts only
  audit entries (not the metadata line).  Backward-compatible: callers
  that do not pass `metadata` see identical behaviour to v19.

### `mcp_server/compliance_checker.py`

- **DA163** — `ComplianceChecker.merge(other: ComplianceChecker) -> int`:
  Copies rules from `other` whose `rule_id` is not already present in
  `self`.  Preserves existing rule order; new rules are appended.
  Returns count of rules added (0 if all were already present).
  Symmetric relationship with `diff()`: the IDs returned in
  `diff(other)["added_rules"]` are exactly those `merge(other)` would add.

### `logic/integration/nl_ucan_policy_compiler.py`

- **DB164** — `NLUCANPolicyCompiler.compile_explain(sentences, policy_id=None)`:
  Convenience method that calls `compile(sentences, policy_id)` and returns
  `(result, result.explain())` as a 2-tuple.  Removes boilerplate for
  callers needing both the structured result and a printable summary.
  `Tuple` import added to the module's `typing` imports.

### `logic/CEC/nl/nl_policy_conflict_detector.py`

- **DC165** — English deontic keywords added as `_EN_DEONTIC_KEYWORDS`:
  - `permission`: `["may", "can", "is permitted", "is allowed",
    "is authorized", "has the right to", "is entitled to"]`
  - `prohibition`: `["must not", "cannot", "shall not", "is prohibited",
    "is forbidden", "is not allowed", "is not permitted"]`
  - `obligation`: `["must", "shall", "is required to", "is obligated to",
    "has to"]`
  `_load_i18n_keywords("en")` returns `_EN_DEONTIC_KEYWORDS` directly
  (no parser module required).  `detect_i18n_conflicts(text, "en")` now
  works out of the box.

### `logic/api.py`

- **DC165** — `detect_all_languages()`: `_SUPPORTED_LANGS` extended from
  `("fr", "es", "de")` to `("fr", "es", "de", "en")`.  The English pass
  uses `detect_i18n_clauses(text, "en")` which falls back gracefully to
  the lightweight keyword scan.  The `I18NConflictReport.by_language` dict
  now always has four keys after calling `detect_all_languages()`.

---

## Key Invariants (v20)

| Component | Invariant |
|-----------|-----------|
| `DelegationManager.merge_and_publish()` (CY161) | Payload always includes `"metrics"` dict from `get_metrics()`; `"added"` and `"total"` keys preserved |
| `PolicyAuditLog.export_jsonl()` (CZ162) | `metadata=None` → no header line (backward-compatible); header line not counted in return value |
| `ComplianceChecker.merge()` (DA163) | Symmetric with `diff()`; skips duplicates by `rule_id`; preserves order |
| `NLUCANPolicyCompiler.compile_explain()` (DB164) | Returns `(NLUCANCompilerResult, str)` 2-tuple; explanation equals `result.explain()` |
| `detect_all_languages()` (DC165) | Now returns 4-language report `{"fr","es","de","en"}`; English always available (no extra deps) |
| `detect_i18n_conflicts(text, "en")` (DC165) | Works without any parser module; uses inline `_EN_DEONTIC_KEYWORDS` |

---

## Test Coverage

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestCY161MergePublishMetrics` | CY161 | 7 |
| `TestCZ162ExportJsonlMetadata` | CZ162 | 7 |
| `TestDA163ComplianceCheckerMerge` | DA163 | 7 |
| `TestDB164CompileExplain` | DB164 | 8 |
| `TestDC165EnglishKeywords` | DC165 | 8 |
| `TestDD166MergeAndPublishWithBus` | DD166 | 6 |
| `TestDE167TDFOLNLParserMocked` | DE167 | 10 (2 skip) |
| `TestDF168EvaluateAndDetectE2E` | DF168 | 8 |
| **v20 total** | | **61** |

---

## v21 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| DG169 | `PolicyAuditLog.import_jsonl()` — honour `__metadata__` header line (skip it) | Low | 🟡 Med |
| DH170 | `ComplianceChecker.merge()` — `copy_disabled=False` flag: if `True`, skip rules with `removable=False` | Low | 🟢 Low |
| DI171 | `NLUCANPolicyCompiler.compile_explain()` — stream explanation lines via iterator | Low | 🟢 Low |
| DJ172 | `detect_all_languages()` — add `"pt"` (Portuguese) via a new `portuguese_parser.py` | Med | 🟡 Med |
| DK173 | `DelegationManager.merge_and_publish()` — async pubsub variant (`merge_and_publish_async`) | Med | 🟡 Med |
| DL174 | Full E2E: `merge()` + `export_jsonl(metadata=...)` + `import_jsonl()` — round-trip test | Med | 🔴 High |
| DM175 | `ComplianceChecker.diff()` + `merge()` combined idempotency test | Low | 🟡 Med |
| DN176 | `detect_all_languages()` with `"nl"` (Dutch) inline keywords | Med | 🟡 Med |
