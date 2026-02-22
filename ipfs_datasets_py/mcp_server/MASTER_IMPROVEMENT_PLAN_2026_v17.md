# MASTER IMPROVEMENT PLAN 2026 — v17
**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-22
**Status:** v17 complete — 3,073 tests total

---

## Summary

v17 completes all high-priority backlog items from the v16 "Next Steps" list
(BX134–CH144).  Key deliverables:

| # | Session | Description | Status |
|---|---------|-------------|--------|
| 1 | BX134 | `NLPolicyConflictDetector.detect_and_warn()` — emits UserWarning + PolicyAuditLog | ✅ |
| 2 | BZ136 | `UCANPolicyBridge.evaluate_with_manager()` — full DelegationManager UCAN check | ✅ |
| 3 | CA137 | `DispatchPipeline(audit_log=…)` — records every stage result | ✅ |
| 4 | CB138 | `detect_i18n_conflicts()` + `I18NConflictResult` — FR/ES/DE keyword scan | ✅ |
| 5 | CC139 | `DelegationChain.to_ascii_tree()` + `__str__` + `__len__` | ✅ |
| 6 | CD140 | `logic/api.py` smoke tests — all `__all__` symbols load without error | ✅ |
| 7 | CE141 | `PipelineMetricsRecorder(audit_log=…)` — summary entry per pipeline run | ✅ |
| 8 | CH144 | 7 MCP tools for DelegationManager + PolicyAuditLog | ✅ |

---

## Production Changes

### `logic/CEC/nl/nl_policy_conflict_detector.py`

- **BX134** — `NLPolicyConflictDetector.detect_and_warn(clauses, *, audit_log=None, policy_cid="nl_policy")`:
  calls `detect()`, emits `UserWarning` per conflict, optionally records to `PolicyAuditLog`
- **CB138** — `detect_i18n_conflicts(text, language="fr") -> I18NConflictResult`:
  keyword-level simultaneous permission+prohibition scan; supports `"fr"`, `"es"`, `"de"`
- **CB138** — `I18NConflictResult` dataclass: `language`, `has_permission`, `has_prohibition`,
  `has_simultaneous_conflict`, `matched_permission_keywords`, `matched_prohibition_keywords`, `to_dict()`
- **CB138** — `_I18N_KEYWORD_LOADERS` dispatch table + `_load_i18n_keywords(language)` loader

### `mcp_server/ucan_delegation.py`

- **CC139** — `DelegationChain.to_ascii_tree() -> str`: multi-line ASCII tree of issuer→audience links;
  empty chain returns `"(empty chain)"`; last row uses `└─`, middle rows use `├─`
- **CC139** — `DelegationChain.__str__()` delegates to `to_ascii_tree()`
- **CC139** — `DelegationChain.__len__()` returns `len(self.tokens)`

### `logic/integration/ucan_policy_bridge.py`

- **BZ136** — `UCANPolicyBridge.evaluate_with_manager(policy_cid, *, tool, actor, leaf_cid, at_time, manager)`:
  uses `DelegationManager.is_revoked()` + `can_invoke()` instead of the bridge's internal
  `DelegationStore`; `manager=None` falls back to standard `evaluate()`

### `mcp_server/dispatch_pipeline.py`

- **CA137** — `DispatchPipeline.__init__(…, audit_log=None)`: records each executed stage result
  to `PolicyAuditLog` via `audit_log.record(policy_cid="pipeline:<stage>", …)`
- **CE141** — `PipelineMetricsRecorder.__init__(…, audit_log=None)`: writes summary audit entry
  on every `record_run()` call with `policy_cid="pipeline:<namespace>:run"`

### `logic/api.py`

- **CD140 / CB138** — `_CD140_I18N_AVAILABLE` flag; conditional `__all__` extension for
  `detect_i18n_conflicts`, `I18NConflictResult`

### `mcp_server/tools/logic_tools/delegation_audit_tool.py` *(new file)*

- **CH144** — 7 MCP tools:
  `delegation_add_token`, `delegation_can_invoke`, `delegation_revoke`,
  `delegation_revoke_chain`, `delegation_get_metrics`, `audit_log_recent`, `audit_log_stats`
- `DELEGATION_AUDIT_TOOLS` registry list for MCP server discovery

---

## Key Invariants (v17)

| Component | Invariant |
|-----------|-----------|
| `detect_and_warn` | Emits one `UserWarning` per conflict; `audit_log` records have `decision="deny"`, `actor="conflict_detector"` |
| `detect_i18n_conflicts` | Keyword scan only — no clause compilation; supports `"fr"`, `"es"`, `"de"` only |
| `to_ascii_tree` | Single-token chain uses `└─` (no `├─`); empty chain → `"(empty chain)"` |
| `evaluate_with_manager` | `manager=None` → exact same path as `evaluate()`; revocation check is first gate |
| `DispatchPipeline audit_log` | Records stage results only for *executed* (non-skipped) stages |
| `PipelineMetricsRecorder audit_log` | Writes one entry per `record_run()` call; `policy_cid` contains namespace |
| `delegation_audit_tool` | All 7 tools return `{"status": "ok", …}` on success, `{"status": "error", "error": …}` on failure |

---

## Test Coverage

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestBX134DetectAndWarn` | BX134 | 5 |
| `TestBZ136EvaluateWithManager` | BZ136 | 5 |
| `TestCA137DispatchPipelineAudit` | CA137 | 6 |
| `TestCB138I18NConflicts` | CB138 | 8 |
| `TestCC139DelegationChainAscii` | CC139 | 10 |
| `TestCD140ApiSmoke` | CD140 | 7 |
| `TestCE141MetricsRecorderAudit` | CE141 | 6 |
| `TestCH144DelegationAuditTool` | CH144 | 10 |
| **Total v17** | | **57** |

**Cumulative:** 3,016 (v16) + 57 (v17) = **3,073 tests** · 23 skip · 0 failing

---

## v18 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| CI145 | `delegation_audit_tool` — `delegation_chain_ascii` tool returning chain viz | Low | 🟡 Med |
| CJ146 | `NLPolicyConflictDetector.detect_i18n_clauses()` — full French/Spanish/German clause compilation + detect | High | 🔴 High |
| CK147 | `UCANPolicyBridge.evaluate_with_manager()` + audit: `evaluate_audited_with_manager()` | Low | 🟡 Med |
| CL148 | `FilePolicyStore` + `IPFSPolicyStore` — encrypted-at-rest policy bundles | Med | 🟡 Med |
| CM149 | `DelegationManager` + Prometheus `mcp_delegation_chain_depth_max` gauge | Low | 🟡 Med |
| CN150 | `logic/api.py` — `evaluate_with_manager` convenience wrapper | Low | 🟢 Low |
| CO151 | TDFOL NL spaCy integration tests (skip-guarded) | Med | 🟡 Med |
| CP152 | Groth16 Phase 4b — circuit_version=2 witness schema + trace | High | 🟢 Low |
