# MASTER IMPROVEMENT PLAN 2026 — v16

**Branch:** `copilot/create-refactoring-plan-again`  
**Date:** 2026-02-22  
**Supersedes:** `MASTER_IMPROVEMENT_PLAN_2026_v15.md`

---

## v16 Session Overview

| Session | Description | Tests | Status |
|---------|-------------|-------|--------|
| BN124 | `DelegationManager.revoke_chain()` multi-hop | 6 | ✅ Complete |
| BO125 | `NLPolicyConflictDetector` ↔ `UCANPolicyBridge` integration | 5 | ✅ Complete |
| BP126 | `AuditMetricsBridge` + Prometheus smoke test | 5 | ✅ Complete |
| BR128 | `DelegationManager.can_invoke_audited()` | 8 | ✅ Complete |
| BS129 | `make_delegation_stage()` pipeline factory | 6 | ✅ Complete |
| BW133 | `logic/api.py` DelegationManager + conflict exports | 10 | ✅ Complete |
| TDFOL-NL-T3 | `PatternType` + `Pattern`/`PatternMatch` dataclasses | 12 | ✅ Complete |
| TDFOL-NL-T4 | `ParseOptions` + `ParseResult` dataclasses | 11 | ✅ Complete |

**Total v16 tests:** 63 (+ 1 skip when spaCy absent)  
**Grand total:** 2,953 + 63 = **3,016 tests** · 0 failing

---

## Production Changes

### `mcp_server/ucan_delegation.py`

**BN124:** Fixed `DelegationManager.revoke_chain()` — now handles empty chain
(unknown CID) by revoking the root CID directly and returning count=1:

```python
# Before: would return 0 for unknown CIDs (build_chain returns empty)
# After:
if chain.tokens:
    self._revocation.revoke_chain(chain)
    return len(chain.tokens)
# Empty chain → still revoke root_cid directly
self._revocation.revoke(root_cid)
return 1
```

**BR128:** Added `DelegationManager.can_invoke_audited()` — like `can_invoke()`
but records every decision to a `PolicyAuditLog` when one is provided:

```python
def can_invoke_audited(
    self, principal, resource, ability, *, leaf_cid,
    at_time=None, audit_log=None,
    policy_cid="delegation", intent_cid="intent",
) -> Tuple[bool, str]:
    ...
```

### `mcp_server/dispatch_pipeline.py`

**BS129:** Added `make_delegation_stage(manager)` factory function. Creates a
`PipelineStage` backed by a `DelegationManager` instance. The stage checks
`manager.can_invoke(actor, tool, "tools/invoke", leaf_cid=...)`.

### `logic/integration/ucan_policy_bridge.py`

**BO125:** Added `conflicts` field + `conflict_count` property to `BridgeCompileResult`.
`compile_nl()` now calls `NLPolicyConflictDetector.detect_conflicts()` after
compilation and populates `result.conflicts` + appends a warning per conflict.

### `logic/api.py`

**BW133:** Three new lazy imports + six new `__all__` symbols:
- `DelegationManager`, `get_delegation_manager` (from `mcp_server.ucan_delegation`)
- `NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts` (from `logic.CEC.nl.nl_policy_conflict_detector`)

---

## Key Invariants (updated for v16)

### DelegationManager.revoke_chain()
- Returns ≥ 1 always (even for unknown/nonexistent CIDs)
- For known chains: returns `len(chain.tokens)` (number of revoked tokens)
- For empty/unknown: revokes the root_cid itself and returns 1
- Fallback for exceptions (KeyError/ValueError/RuntimeError): same — revoke root, return 1

### DelegationManager.can_invoke_audited()
- Signature: `(principal, resource, ability, *, leaf_cid, at_time=None, audit_log=None, policy_cid="delegation", intent_cid="intent")`
- Records `decision = "allow" if allowed else "deny"` to audit_log
- If `audit_log is None`, behaves identically to `can_invoke()`
- `policy_cid` + `intent_cid` are passed through to `audit_log.record()`

### BridgeCompileResult.conflicts
- Default: `field(default_factory=list)` — always a list
- `conflict_count` property: `len(self.conflicts)`
- Populated by `compile_nl()` via `detect_conflicts(policy.clauses)`
- If detection fails (missing module/exception): `conflicts` stays `[]` silently

### make_delegation_stage()
- Returns `PipelineStage(name="delegation", handler=_delegation_handler)`
- Handler calls `manager.can_invoke(actor, tool, "tools/invoke", leaf_cid=leaf_cid)`
- Missing `actor`, `tool`, or `leaf_cid` in intent → deny gracefully (no crash)
- Integrates with `make_full_pipeline()` by replacing the `"delegation"` stage

### logic/api.py BW133 imports
- Use `import ipfs_datasets_py.logic.api as api` (NOT `from ipfs_datasets_py.logic import api`)
- The `__getattr__` in `logic/__init__.py` causes RecursionError with the latter

---

## v17 Candidates

| Session | Target | Priority |
|---------|--------|----------|
| BX134 | `nl_policy_conflict_detector.py` — emit conflicts as policy warnings in MCP tool | 🔴 High |
| BY135 | `DelegationManager.save_encrypted(password)` — AES-256-GCM store | 🟡 Med |
| BZ136 | `UCANPolicyBridge.evaluate()` with real `DelegationManager` (not just evaluator) | 🔴 High |
| CA137 | `dispatch_pipeline.py` + `PolicyAuditLog` integration — record every stage result | 🟡 Med |
| CB138 | `NLPolicyConflictDetector` i18n — French/Spanish/German conflict detection | 🟡 Med |
| CC139 | `DelegationChain` viz — ASCII printout of chain issuers | 🟢 Low |
| CD140 | `logic/api.py` smoke tests — all `__all__` symbols load without error | 🟡 Med |
| CE141 | `dispatch_pipeline.py` + `PolicyAuditLog` — `PipelineMetricsRecorder` writes audit entries | 🟡 Med |
| CF142 | `groth16_ffi.py` circuit_version=2 trace + witness schema v2 (Groth16 Phase 4b) | 🟢 Low |
| CG143 | TDFOL NL spaCy integration tests (skip-guarded) | 🟡 Med |
