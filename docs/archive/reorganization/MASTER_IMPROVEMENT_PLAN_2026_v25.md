# Master Improvement Plan 2026 — v25: Session 69 (v24 Next Steps)

**Created:** 2026-02-23 (Session 69)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v24.md](MASTER_IMPROVEMENT_PLAN_2026_v24.md)

---

## Overview

Session 69 implements all five "Next Steps" from the v24 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `MergePlan` dataclass + `DelegationManager.merge(dry_run=True)` | ✅ COMPLETE |
| 2 | `IPFSReloadResult(count, pin_results)` NamedTuple + `IPFSPolicyStore.reload()` returns it | ✅ COMPLETE |
| 3 | `PubSubBus.publish_async(priority=0)` — `__mcp_priority__` attribute-based ordering | ✅ COMPLETE |
| 4 | `ComplianceChecker.bak_exists(path)` static helper | ✅ COMPLETE |
| 5 | Session 69 E2E test (`test_mcplusplus_v24_session69.py`, 37 tests) | ✅ COMPLETE |

**971+ total spec tests pass (sessions 50–69, 0 new failures).**

---

## Item 1 — `MergePlan` + `DelegationManager.merge(dry_run=True)` ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

```python
@dataclass
class MergePlan:
    would_add: List[str] = field(default_factory=list)
    would_skip_conflicts: List[str] = field(default_factory=list)

    @property
    def add_count(self) -> int: ...
    @property
    def conflict_count(self) -> int: ...
```

`merge(dry_run=True)` returns a `MergePlan` without mutating state.
`merge(dry_run=False)` (default) performs the merge and returns an `int`.
`MergePlan` added to `__all__`.

---

## Item 2 — `IPFSReloadResult` structured return type ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

```python
class IPFSReloadResult(NamedTuple):
    count: int
    pin_results: Dict[str, Optional[str]]
```

`IPFSPolicyStore.reload()` now returns `IPFSReloadResult(count=N, pin_results={name: cid_or_None})`.
Callers can inspect which pins succeeded/failed after reload.

---

## Item 3 — `PubSubBus.publish_async(priority=0)` ✅

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

```python
async def publish_async(
    self, topic, payload, *, timeout_seconds=5.0, priority=0
) -> PublishAsyncResult:
```

Handlers are sorted by `getattr(h, "__mcp_priority__", 0)` (descending)
before invocation.  Higher-priority handlers are placed at the front of the
task list.  The `publish_async()` task group fires all concurrently; order
only affects which handler starts first inside the group.

---

## Item 4 — `ComplianceChecker.bak_exists(path)` ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

```python
@staticmethod
def bak_exists(path: str) -> bool:
    return os.path.exists(path + ".bak")
```

Lightweight pre-check before `restore_from_bak()`.  Avoids the overhead of
a failed restore attempt when no backup exists.

---

## Item 5 — Session 69 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v24_session69.py`

37 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestDelegationManagerMergeDryRun` | 10 |
| `TestIPFSReloadResult` | 7 |
| `TestPubSubBusPublishAsyncPriority` | 6 |
| `TestComplianceCheckerBakExists` | 8 |
| `TestE2ESession69` | 6 |

All 37 pass with 0 failures.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–69 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56, 64, 65, 66, 67, 68, **69** |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, 61, 62, 63, 64, 65, 66, 67, 68, **69** |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62, 63, 64, 65, 66, 67, 68, **69** |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| **MergePlan + dry_run** | `ucan_delegation.py` | **69** |
| **IPFSReloadResult** | `nl_ucan_policy.py` | **69** |
| **publish_async priority** | `mcp_p2p_transport.py` | **69** |
| **ComplianceChecker.bak_exists** | `compliance_checker.py` | **69** |

**971+ spec tests pass (sessions 50–69).**

---

## Next Steps (Session 70+)

1. **`DelegationManager.merge()` audit trail** — when `dry_run=False` and an
   `audit_log` is provided, record `{"event": "merge_add", "cid": cid}` for
   each newly-added delegation (mirrors the existing `revocation_copied` audit
   entries).
2. **`IPFSReloadResult` total_failed property** — `sum(1 for v in
   pin_results.values() if v is None)` for quick failure count.
3. **`PubSubBus.subscribe(topic, handler, *, priority=0)`** — allow callers
   to register a priority at subscribe time (stored as `__mcp_priority__`),
   eliminating the need to manually annotate handler functions.
4. **`ComplianceChecker.bak_path(path)`** — static helper returning the
   expected `.bak` path for *path* (i.e., `path + ".bak"`), reducing magic
   string duplication in callers.
5. **Session 70 full E2E** — combined regression covering all session 60–69
   features using a single `pytest`-style fixture (no `import pytest` required
   so it runs with standard `unittest`).
