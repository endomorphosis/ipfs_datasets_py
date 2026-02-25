# Master Improvement Plan 2026 — v26: Session 70 (v25 Next Steps)

**Created:** 2026-02-23 (Session 70)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v25.md](MASTER_IMPROVEMENT_PLAN_2026_v25.md)

---

## Overview

Session 70 implements all five "Next Steps" from the v25 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `DelegationManager.merge()` audit trail for `merge_add` events | ✅ COMPLETE |
| 2 | `IPFSReloadResult.total_failed` property | ✅ COMPLETE |
| 3 | `PubSubBus.subscribe(priority=0)` — stores priority as `__mcp_priority__` | ✅ COMPLETE |
| 4 | `ComplianceChecker.bak_path(path)` static helper | ✅ COMPLETE |
| 5 | Session 70 E2E test (`test_mcplusplus_v25_session70.py`, 34 tests) | ✅ COMPLETE |

**1,005+ total spec tests pass (sessions 50–70, 0 new failures).**

---

## Item 1 — `DelegationManager.merge()` audit trail for `merge_add` ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

When `dry_run=False` and an `audit_log` is provided, each newly-added
delegation emits:

```python
audit_log.append({"event": "merge_add", "cid": cid})
```

This is symmetric to the existing `revocation_copied` audit entries.
`audit_log.append()` exceptions are swallowed at DEBUG level — a broken
audit sink never prevents the merge.  `dry_run=True` does **not** record
audit entries.

---

## Item 2 — `IPFSReloadResult.total_failed` property ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

```python
@property
def total_failed(self) -> int:
    return sum(1 for v in self.pin_results.values() if v is None)
```

Added to the `IPFSReloadResult(count, pin_results)` NamedTuple as a regular
`@property`.  Callers no longer need to iterate `pin_results` manually.

---

## Item 3 — `PubSubBus.subscribe(priority=0)` ✅

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

`subscribe()` now accepts a keyword-only `priority: int = 0` parameter.
The priority value is stored as `handler.__mcp_priority__` (only when the
new value is higher than any existing attribute), making it available for
`publish_async()` handler ordering without requiring callers to manually
annotate their handler functions.

```python
bus.subscribe("topic", my_handler, priority=10)
assert my_handler.__mcp_priority__ == 10
```

---

## Item 4 — `ComplianceChecker.bak_path(path)` ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

```python
@staticmethod
def bak_path(path: str) -> str:
    return path + ".bak"
```

Complements `bak_exists()` and `restore_from_bak()`.  Avoids duplicating
the `path + ".bak"` magic string in callers.

---

## Item 5 — Session 70 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v25_session70.py`

34 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestDelegationManagerMergeAuditTrail` | 8 |
| `TestIPFSReloadResultTotalFailed` | 7 |
| `TestPubSubBusSubscribePriority` | 7 |
| `TestComplianceCheckerBakPath` | 7 |
| `TestE2ESession70` | 5 |

All 34 pass with 0 failures.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–70 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56, 64–70 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60–70 |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62–70 |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| MergePlan + dry_run | `ucan_delegation.py` | 69 |
| **merge_add audit trail** | `ucan_delegation.py` | **70** |
| IPFSReloadResult | `nl_ucan_policy.py` | 69 |
| **IPFSReloadResult.total_failed** | `nl_ucan_policy.py` | **70** |
| publish_async priority | `mcp_p2p_transport.py` | 69 |
| **subscribe(priority=)** | `mcp_p2p_transport.py` | **70** |
| ComplianceChecker.bak_exists | `compliance_checker.py` | 69 |
| **ComplianceChecker.bak_path** | `compliance_checker.py` | **70** |

**1,005+ spec tests pass (sessions 50–70).**

---

## Next Steps (Session 71+)

1. **`DelegationManager.merge()` summary result** — return a `MergeResult`
   dataclass (instead of bare `int`) containing `added_count`,
   `conflict_count`, and `revocations_copied` for richer callers.
2. **`IPFSReloadResult.success_rate`** — `(count - total_failed) / count`
   with 0-division guard returning `1.0` for empty registries (0 pins = 0
   failures = perfect rate).
3. **`PubSubBus.subscribe()` returns subscription ID** — integer handle
   allowing targeted `unsubscribe_by_id(sid)` without holding a reference
   to the handler function.
4. **`ComplianceChecker.rotate_bak(path)`** — rename existing `.bak` to
   `.bak.1`, `.bak.2`, … (up to `max_keep=3`) before creating a new `.bak`.
5. **Session 71 full E2E** — combined regression covering sessions 60–70
   with cross-feature integration: `DelegationManager` + `PubSubBus` +
   `ComplianceChecker` + `IPFSReloadResult` in a single end-to-end flow.
