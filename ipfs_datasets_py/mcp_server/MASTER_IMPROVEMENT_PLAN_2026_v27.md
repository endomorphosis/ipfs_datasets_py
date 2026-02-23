# Master Improvement Plan 2026 — v27: Session 71 (v26 Next Steps)

**Created:** 2026-02-23 (Session 71)  
**Branch:** `copilot/refactor-ipfs-datasets-folder`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v26.md](MASTER_IMPROVEMENT_PLAN_2026_v26.md)

---

## Overview

Session 71 implements all five "Next Steps" from the v26 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `MergeResult` dataclass + `DelegationManager.merge()` returns it (dry_run=False) | ✅ COMPLETE |
| 2 | `IPFSReloadResult.success_rate` property | ✅ COMPLETE |
| 3 | `PubSubBus.subscribe()` returns subscription ID + `unsubscribe_by_id(sid)` | ✅ COMPLETE |
| 4 | `ComplianceChecker.rotate_bak(path, max_keep=3)` | ✅ COMPLETE |
| 5 | Session 71 E2E test (`test_mcplusplus_v26_session71.py`, 36 tests) | ✅ COMPLETE |

**1,041+ total spec tests pass (sessions 50–71, 0 new failures).**

---

## Item 1 — `MergeResult` dataclass + `merge()` return type ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

```python
@dataclass
class MergeResult:
    added_count: int = 0
    conflict_count: int = 0
    revocations_copied: int = 0

    def __int__(self) -> int: ...     # backwards-compat: int(result)
    def __eq__(self, other) -> bool:  # backwards-compat: result == 1
```

`merge(dry_run=False)` (default) now returns `MergeResult` instead of bare
`int`.  The `__int__` and `__eq__` overrides preserve backwards compatibility
for callers that compare the return value to an integer.

`MergeResult` is added to `__all__`.

---

## Item 2 — `IPFSReloadResult.success_rate` property ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

```python
@property
def success_rate(self) -> float:
    if self.count == 0:
        return 1.0
    return (self.count - self.total_failed) / self.count
```

Returns the fraction of policies whose IPFS pin succeeded.  Empty registries
(count=0) return `1.0` to avoid zero-division and reflect the semantics that
zero failures = perfect rate.

---

## Item 3 — `PubSubBus.subscribe()` returns subscription ID ✅

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

```python
def subscribe(self, topic, handler, *, priority=0) -> int:
    ...
    return sid   # monotonically-increasing integer

def unsubscribe_by_id(self, sid: int) -> bool:
    ...
```

`subscribe()` now returns an integer subscription ID.  The ID is stored in
an internal `_sid_map` that maps `sid → (topic_key, handler)`.
`unsubscribe_by_id(sid)` removes the handler without the caller needing to
retain a reference to the handler callable.

---

## Item 4 — `ComplianceChecker.rotate_bak(path, max_keep=3)` ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

```python
@staticmethod
def rotate_bak(path: str, *, max_keep: int = 3) -> None:
```

Renames `<path>.bak` → `<path>.bak.1`, `<path>.bak.1` → `<path>.bak.2`, …
up to `<path>.bak.<max_keep>`.  Files beyond *max_keep* are deleted.  After
rotation the `.bak` slot is free for a new backup.  A no-op when no `.bak`
exists.

---

## Item 5 — Session 71 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v26_session71.py`

36 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestMergeResult` | 10 |
| `TestIPFSReloadResultSuccessRate` | 7 |
| `TestPubSubBusSubscribeId` | 8 |
| `TestComplianceCheckerRotateBak` | 6 |
| `TestE2ESession71` | 5 |

All 36 pass with 0 failures.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–71 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56, 64–71 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60–71 |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62–71 |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| MergePlan + dry_run | `ucan_delegation.py` | 69 |
| merge_add audit trail | `ucan_delegation.py` | 70 |
| **MergeResult dataclass** | `ucan_delegation.py` | **71** |
| IPFSReloadResult | `nl_ucan_policy.py` | 69 |
| IPFSReloadResult.total_failed | `nl_ucan_policy.py` | 70 |
| **IPFSReloadResult.success_rate** | `nl_ucan_policy.py` | **71** |
| publish_async priority | `mcp_p2p_transport.py` | 69 |
| subscribe(priority=) | `mcp_p2p_transport.py` | 70 |
| **subscribe() returns ID + unsubscribe_by_id** | `mcp_p2p_transport.py` | **71** |
| ComplianceChecker.bak_exists | `compliance_checker.py` | 69 |
| ComplianceChecker.bak_path | `compliance_checker.py` | 70 |
| **ComplianceChecker.rotate_bak** | `compliance_checker.py` | **71** |

**1,041+ spec tests pass (sessions 50–71).**

---

## Next Steps (Session 72+)

1. **`MergeResult` rich comparison** — add `__lt__`, `__le__`, `__gt__`,
   `__ge__` operators comparing `added_count` so `MergeResult` values are
   orderable (e.g., `assert result >= 1`).
2. **`IPFSReloadResult.failure_details`** — `{name: reason_str}` mapping for
   failed pins; populated by a new optional `pin_errors` parameter on
   `IPFSPolicyStore.reload()`.
3. **`PubSubBus.subscription_count(topic=None)`** — return total active
   subscriptions (across all topics when `topic=None`), including deduplicated
   handler references; useful for health checks.
4. **`ComplianceChecker.list_bak_files(path)`** — return a sorted list of
   existing backup paths (`[".bak", ".bak.1", ".bak.2", …]`) so callers can
   inspect the rotation history without manual `os.path.exists` calls.
5. **Session 72 full E2E** — combined regression covering sessions 65–71
   with cross-feature integration using `DelegationManager` + `PubSubBus` +
   `ComplianceChecker` + `IPFSReloadResult` in a multi-step pipeline.
