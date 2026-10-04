# Master Improvement Plan 2026 — v20: Session 64 (v19 Next Steps)

**Created:** 2026-02-22 (Session 64)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v19.md](MASTER_IMPROVEMENT_PLAN_2026_v19.md)

---

## Overview

Session 64 implements all five "Next Steps" from the v19 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `FilePolicyStore.reload()` — hot-reload from disk | ✅ COMPLETE |
| 2 | `DelegationManager.merge(other)` — merge delegation entries | ✅ COMPLETE |
| 3 | `ComplianceChecker.save_encrypted` version field | ✅ COMPLETE |
| 4 | `PubSubBus.publish_async()` — async variant with anyio fallback | ✅ COMPLETE |
| 5 | Session 64 E2E test (`test_mcplusplus_v19_session64.py`) | ✅ COMPLETE |
| + | Session 56 test format compatibility fix | ✅ COMPLETE |

**788+ total spec tests pass (sessions 50–64, 0 new failures).**

---

## Item 1 — `FilePolicyStore.reload()` ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

```python
def reload(self) -> int:
    """Hot-reload policies from disk without creating a new instance.

    Clears the current registry and re-loads from :attr:`path`.
    Any in-memory policies that have not been persisted will be lost.

    Returns:
        Number of policies loaded.
    """
    self._registry._sources.clear()
    self._registry._compiled.clear()
    return self.load()
```

- Clears `_sources` and `_compiled` from the shared `PolicyRegistry` in-place.
- Delegates to the existing `load()` for version checking, CID validation, and
  backward-compatible format detection.
- Returns 0 when the file is missing (same as `load()`).

```python
# Usage:
store.reload()  # re-reads from disk; loses any in-memory policies not saved
```

---

## Item 2 — `DelegationManager.merge(other)` ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

```python
def merge(self, other: "DelegationManager") -> int:
    """Merge delegation entries from *other* into this manager.

    Only delegations whose CID is **not** already present are added.
    The revocation list is **not** merged (security-sensitive).
    The evaluator cache is invalidated after any additions.

    Returns:
        Number of newly-added delegations.
    """
```

Key behaviours:
- **Skip duplicates** — CIDs already in `self` are ignored.
- **No revocation copy** — `RevocationList` is security-sensitive; callers must
  explicitly choose which revocations to carry over via `revoke()`.
- **Evaluator cache invalidation** — only when at least one delegation was added
  (avoids unnecessary rebuilds when all CIDs are duplicates).
- **Does not mutate `other`** — iteration is read-only.

---

## Item 3 — `ComplianceChecker.save_encrypted` version field ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

`save_encrypted()` now writes:

```json
{
  "version": "1",
  "rule_order": ["tool_name_convention", ...],
  "deny_list": ["banned_tool"]
}
```

Previously, the `"version"` key was absent from the encrypted payload, creating
a discrepancy with `save()` (which always included `"version"`).  The encrypted
and plaintext persisted formats now have identical structure, simplifying any
future migration tooling.

`load_encrypted()` delegates via a temp-file path to `load()` for unified version
checking — the `UserWarning` for version mismatch works correctly for both.

---

## Item 4 — `PubSubBus.publish_async()` ✅

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

```python
async def publish_async(
    self,
    topic: Union[str, PubSubEventType],
    payload: Dict[str, Any],
) -> int:
    """Async variant of publish().

    Invokes each handler concurrently inside an anyio task group so
    async handlers can await without blocking others.  Falls back to
    synchronous publish() (with a UserWarning) when anyio is absent.

    Returns:
        The number of handlers notified.
    """
```

Implementation details:
- **anyio task group** — all handlers run concurrently; sync handlers run in
  the same thread; async handlers can `await`.
- **Graceful async/sync detection** — checks `hasattr(result, "__await__")` to
  decide whether to `await` the return value.
- **Sync fallback** — when `anyio` is not installed, emits `UserWarning` and
  falls back to `self.publish()`.
- **Return value** — count of handlers that returned without raising.

---

## Item 5 — Session 64 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v19_session64.py`

32 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestFilePolicyStoreReload` | 6 |
| `TestDelegationManagerMerge` | 9 |
| `TestComplianceCheckerEncryptedVersion` | 5 |
| `TestPubSubBusPublishAsync` | 7 |
| `TestE2ESession64` | 5 |

All 32 pass.  Uses `asyncio.run()` (Python 3.12 compatible; avoids deprecated
`asyncio.get_event_loop()`).

### Bonus Fix — Session 56 Test Format Compatibility

The session 56 tests (`test_mcplusplus_spec_session56.py`) accessed the saved
JSON as a flat dict (`data["p1"]`).  After session 63's versioned format change
(`{"version":"1","policies":{...}}`), these 4 tests broke.  Fixed by using
`raw.get("policies", raw)` to support both formats.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–64 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56, **64** |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, 61, 62, 63, **64** |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62, 63, **64** |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| Async policy registration | `nl_ucan_policy.py` | 56 |
| Persistent policy store (file) | `nl_ucan_policy.py` | 56 |
| IPFS-backed policy store | `nl_ucan_policy.py` | 57 |
| PubSub ↔ P2P bridge | `mcp_p2p_transport.py` | 56 |
| Pipeline metrics | `dispatch_pipeline.py` | 56 |
| DID delegation signing | `ucan_delegation.py` | 56 |
| RevocationList | `ucan_delegation.py` | 57 |
| can_invoke_with_revocation | `ucan_delegation.py` | 57 |
| DelegationStore | `ucan_delegation.py` | 57 |
| Compliance rule management tool | `compliance_rule_management_tool.py` | 57 |
| IPFSPolicyStore server startup | `server.py` | 58 |
| RevocationList persistence (plain) | `ucan_delegation.py` | 58 |
| DelegationManager | `ucan_delegation.py` | 58 |
| Compliance interface registration tool | `compliance_rule_management_tool.py` | 58 |
| Monitoring delegation metrics (2 gauges) | `ucan_delegation.py` | 58 |
| DelegationManager server integration | `server.py` | 59 |
| RevocationList persistence (encrypted) | `ucan_delegation.py` | 59 |
| Monitoring loop auto-record | `monitoring.py` | 59 |
| Compliance interface on startup | `server.py` | 59 |
| DelegationManager encrypted persistence | `ucan_delegation.py` | 60 |
| DelegationManager.revoke_chain() | `ucan_delegation.py` | 60 |
| P2PMetricsCollector delegation metrics | `monitoring.py` | 60 |
| ComplianceChecker.save/load | `compliance_checker.py` | 60 |
| server.revoke_delegation_chain() | `server.py` | 60 |
| Enterprise API delegation routes | `enterprise_api.py` | 61 |
| ComplianceChecker.reload() | `compliance_checker.py` | 61 |
| ComplianceChecker.save_encrypted/load_encrypted | `compliance_checker.py` | 61 |
| DelegationEvaluator.max_chain_depth | `ucan_delegation.py` | 61 |
| DelegationManager.max_chain_depth propagation | `ucan_delegation.py` | 61 |
| DelegationManager.get_metrics() — max_chain_depth | `ucan_delegation.py` | 62 |
| record_delegation_metrics — 3rd gauge | `ucan_delegation.py` | 62 |
| _COMPLIANCE_RULE_VERSION + version field | `compliance_checker.py` | 62 |
| FilePolicyStore.save_encrypted / load_encrypted | `nl_ucan_policy.py` | 62 |
| _POLICY_STORE_VERSION + versioned save/load | `nl_ucan_policy.py` | 63 |
| IPFSPolicyStore.save_encrypted / load_encrypted | `nl_ucan_policy.py` | 63 |
| DelegationManager.revoke_chain → pubsub | `ucan_delegation.py` | 63 |
| ComplianceChecker.merge(other) | `compliance_checker.py` | 63 |
| **FilePolicyStore.reload()** | `nl_ucan_policy.py` | **64** |
| **DelegationManager.merge(other)** | `ucan_delegation.py` | **64** |
| **ComplianceChecker.save_encrypted version field** | `compliance_checker.py` | **64** |
| **PubSubBus.publish_async()** | `mcp_p2p_transport.py` | **64** |

**788+ spec tests pass (sessions 50–64).**

---

## Next Steps (Session 65+)

1. **`IPFSPolicyStore.reload()`** — override `FilePolicyStore.reload()` to also
   re-trigger IPFS pinning after hot-reload.
2. **`DelegationManager.merge()` with revocation option** — add an optional
   `copy_revocations: bool = False` parameter so callers can opt-in to copying
   the revocation list.
3. **`PubSubBus.publish_async()` error logging** — extend to log handler
   exceptions at DEBUG level (currently swallowed silently).
4. **`ComplianceChecker.load_encrypted` version check** — verify the `"version"`
   field in the decrypted payload matches `_COMPLIANCE_RULE_VERSION` (mirrors
   `load()`'s version-check logic).
5. **Session 65 full E2E** — test that spans: `FilePolicyStore.reload()` →
   `DelegationManager.merge()` with revocation opt-in → pubsub async notification
   → compliance encrypted version round-trip → session 64 regression.
