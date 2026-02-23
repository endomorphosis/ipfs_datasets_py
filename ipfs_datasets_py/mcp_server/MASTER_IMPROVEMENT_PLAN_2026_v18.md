# MASTER IMPROVEMENT PLAN 2026 — v18

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-22
**Supersedes:** v17
**Status:** Complete ✅

---

## Session Table (v18)

| Session | Target Module | Symbol(s) Added | Tests | Status |
|---------|--------------|-----------------|-------|--------|
| CI145 | `delegation_audit_tool.py` | `delegation_chain_ascii` | 6 | ✅ |
| CJ146 | `nl_policy_conflict_detector.py` | `detect_i18n_clauses` | 7 | ✅ |
| CK147 | `ucan_policy_bridge.py` | `evaluate_audited_with_manager` | 9 | ✅ |
| CM149 | `ucan_delegation.py` | `get_metrics.max_chain_depth`, `record_delegation_metrics` | 8 | ✅ |
| CN150 | `logic/api.py` | `evaluate_with_manager`, `detect_i18n_clauses` | 7 | ✅ |
| **v18 total** | | | **39** | ✅ |

**Cumulative:** 3,073 (v17) + 39 (v18) → **3,112 tests** · 0 failing

---

## Production Changes (v18)

### `mcp_server/tools/logic_tools/delegation_audit_tool.py`

- **CI145** — `delegation_chain_ascii(leaf_cid, **kwargs)`: builds delegation chain via
  `DelegationManager.get_evaluator().build_chain(leaf_cid)`, then renders it as ASCII via
  `DelegationChain.to_ascii_tree()`. Returns `{"status":"ok","leaf_cid":...,"ascii_tree":...,"chain_length":N}`.
  Added as 8th entry in `DELEGATION_AUDIT_TOOLS`.

### `logic/CEC/nl/nl_policy_conflict_detector.py`

- **CJ146** — `detect_i18n_clauses(text, language="fr") -> List[PolicyConflict]`: full clause
  compilation using `FrenchParser`/`SpanishParser`/`GermanParser` → internal `_Clause` objects →
  `NLPolicyConflictDetector.detect()`. Unsupported language returns `[]`. Parser ImportError returns `[]`.
  Reachable from `logic/api.py` as `detect_i18n_clauses`.

### `logic/integration/ucan_policy_bridge.py`

- **CK147** — `UCANPolicyBridge.evaluate_audited_with_manager(policy_cid, *, tool, actor, leaf_cid,
  at_time, manager, audit_log, intent_cid)`: wraps `evaluate_with_manager()` and records decision to
  `audit_log` when provided. Audit errors caught as `(TypeError, AttributeError, ValueError)` and
  logged at DEBUG.

### `mcp_server/ucan_delegation.py`

- **CM149 (get_metrics)** — `DelegationManager.get_metrics()` now returns `max_chain_depth: int`:
  iterates `list_cids()` and calls `build_chain(cid)` to find the longest chain. Returns 0 when
  empty or on evaluation errors.
- **CM149 (record_delegation_metrics)** — New module-level function `record_delegation_metrics(manager, collector)`:
  sets 3 gauges on `collector`: `mcp_revoked_cids_total`, `mcp_delegation_store_depth`,
  `mcp_delegation_chain_depth_max`. `manager=None` is a no-op. All exceptions swallowed at DEBUG.

### `logic/api.py`

- **CN150** — `evaluate_with_manager(policy_cid, tool, *, actor, leaf_cid, at_time, manager,
  audit_log)`: module-level convenience wrapper around
  `UCANPolicyBridge.evaluate_audited_with_manager()`. Returns `BridgeEvaluationResult` or `None`
  if bridge unavailable. Added to `__all__` (conditional on `_CN150_BRIDGE_AVAILABLE`).
- **CJ146** — `detect_i18n_clauses` re-exported in `__all__` if import succeeds.

---

## Key Invariants (v18)

| Component | Invariant |
|-----------|-----------|
| `delegation_chain_ascii` | Returns `{"status":"ok"}` even for unknown CIDs (empty chain); `{"status":"error"}` only on build exceptions |
| `detect_i18n_clauses` | Keyword-scan `detect_i18n_conflicts` is a pre-filter; this function does full clause compilation. Unsupported lang → `[]` |
| `evaluate_audited_with_manager` | Audit errors narrow-caught: `(TypeError, AttributeError, ValueError)`. `intent_cid` defaults to `"bridge_intent"` |
| `get_metrics.max_chain_depth` | Iterates all CIDs; `0` when empty or exception; never raises |
| `record_delegation_metrics` | 3 gauges: `mcp_revoked_cids_total` / `mcp_delegation_store_depth` / `mcp_delegation_chain_depth_max` |
| `evaluate_with_manager` (api.py) | Returns `None` when bridge import fails; otherwise forwards to `evaluate_audited_with_manager` |
| `DELEGATION_AUDIT_TOOLS` length | Now **8** (CI145 added). Previous v17 count-check updated to `>= 7` |

---

## Test Coverage

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestCI145DelegationChainAsciiTool` | CI145 | 6 |
| `TestCJ146DetectI18NClauses` | CJ146 | 7 |
| `TestCK147EvaluateAuditedWithManager` | CK147 | 9 |
| `TestCM149DelegationMetrics` | CM149 | 8 |
| `TestCN150EvaluateWithManagerApi` | CN150 | 7 |
| **v18 total** | | **39** |

---

## v19 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| CQ153 | `DelegationManager.merge_and_publish(other, pubsub)` — merge + PubSub RECEIPT_DISSEMINATE | Low | 🟡 Med |
| CR154 | `ComplianceChecker.diff(other)` — return added/removed/changed rules vs another checker | Low | 🟡 Med |
| CS155 | `PolicyAuditLog.export_jsonl(path)` — bulk export to JSONL file + `import_jsonl(path)` | Med | 🟡 Med |
| CT156 | `logic/api.py` — `detect_i18n_clauses` for all 3 languages convenience + `I18NConflictReport` | Low | 🟢 Low |
| CU157 | TDFOL NL spaCy integration tests (skip-guarded when spaCy absent) | Med | 🟡 Med |
| CV158 | Groth16 Phase 4b — `circuit_version=2` witness schema + trace annotations | High | 🟢 Low |
| CW159 | `NLUCANPolicyCompiler.explain()` — human-readable explanation of a compiled policy | Med | 🟡 Med |
| CX160 | Full `dispatch_pipeline.py` + `DelegationManager` + `PolicyAuditLog` E2E smoke test | Med | 🔴 High |
