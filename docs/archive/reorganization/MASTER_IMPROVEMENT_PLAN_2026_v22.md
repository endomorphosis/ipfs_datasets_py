# Master Improvement Plan 2026 — v22: Session 66 (v21 Next Steps)

**Created:** 2026-02-23 (Session 66)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v21.md](MASTER_IMPROVEMENT_PLAN_2026_v21.md)

---

## Overview

Session 66 implements all five "Next Steps" from the v21 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `DelegationManager.merge(skip_revocations=None)` — selective revocation copy | ✅ COMPLETE |
| 2 | `IPFSPolicyStore.save()` → `Dict[str, Optional[str]]` batch-pin results | ✅ COMPLETE |
| 3 | `PubSubBus.publish_async(timeout_seconds=5.0)` per-handler anyio timeout | ✅ COMPLETE |
| 4 | `ComplianceChecker.migrate_encrypted(path, old_password, new_password)` | ✅ COMPLETE |
| 5 | Session 66 E2E test (`test_mcplusplus_v21_session66.py`, 42 tests) | ✅ COMPLETE |

**863+ total spec tests pass (sessions 50–66, 0 new failures).**

---

## Item 1 — `DelegationManager.merge(skip_revocations=None)` ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added `skip_revocations: Optional[Set[str]] = None` keyword-only parameter:

```python
def merge(
    self,
    other: "DelegationManager",
    *,
    copy_revocations: bool = False,
    skip_revocations: Optional[Set[str]] = None,
) -> int:
```

- When `copy_revocations=True` and `skip_revocations` is not None, CIDs in the skip set are **excluded** from the revocation copy.
- Allows callers to opt in to almost-all revocations while selectively preserving specific CIDs (e.g. for graceful migration windows).
- Source manager is never mutated.
- Default `None` (or empty set) copies all revocations (preserves v65 behavior).

---

## Item 2 — `IPFSPolicyStore.save()` → `Dict[str, Optional[str]]` ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

Return type changed from `None` to `Dict[str, Optional[str]]`:

```python
def save(self) -> Dict[str, Optional[str]]:
    super().save()
    results: Dict[str, Optional[str]] = {}
    for name in self._registry.list_names():
        results[name] = self.pin_policy(name)
    return results
```

- Each policy name maps to its IPFS CID string, or `None` if pinning failed.
- Empty registry → empty dict `{}`.
- File is always written (via `super().save()`) regardless of pin results.
- Enables callers to know which policies were successfully pinned without re-checking the CID map.

---

## Item 3 — `PubSubBus.publish_async(timeout_seconds=5.0)` ✅

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

Added `timeout_seconds: float = 5.0` keyword-only parameter:

```python
async def publish_async(
    self,
    topic: Union[str, "PubSubEventType"],
    payload: Dict[str, Any],
    *,
    timeout_seconds: float = 5.0,
) -> int:
```

- Each handler is wrapped in `anyio.move_on_after(timeout_seconds)`.
- When `timeout_seconds <= 0`, no timeout is applied (backward-compatible unlimited mode).
- Timed-out handlers count as not-notified (result `False`).
- Falls back to sync `publish()` with `UserWarning` when anyio is absent (unchanged).

---

## Item 4 — `ComplianceChecker.migrate_encrypted()` ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

New method for password rotation and version migration:

```python
def migrate_encrypted(
    self,
    path: str,
    old_password: str,
    new_password: str,
) -> bool:
```

- Decrypts `path` using `old_password` (AES-256-GCM with SHA-256 key derivation).
- Bumps `"version"` field to `_COMPLIANCE_RULE_VERSION`.
- Re-encrypts with `new_password` using a fresh random nonce.
- Returns `True` on success; `False` on wrong password (`InvalidTag`), missing file, too-short file, or `cryptography` absent.
- Emits `UserWarning` when `cryptography` is not installed.

---

## Item 5 — Session 66 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v21_session66.py`

42 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestDelegationManagerMergeSkipRevocations` | 9 |
| `TestIPFSPolicyStoreSaveBatchPin` | 6 |
| `TestPubSubBusPublishAsyncTimeout` | 7 |
| `TestComplianceCheckerMigrateEncrypted` | 10 |
| `TestE2ESession66` | 10 |

All 42 pass with 0 failures.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–66 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56, 64, 65, **66** |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, 61, 62, 63, 64, 65, **66** |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62, 63, 64, 65, **66** |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| **DelegationManager.merge(skip_revocations)** | `ucan_delegation.py` | **66** |
| **IPFSPolicyStore.save() → batch-pin dict** | `nl_ucan_policy.py` | **66** |
| **publish_async(timeout_seconds)** | `mcp_p2p_transport.py` | **66** |
| **ComplianceChecker.migrate_encrypted** | `compliance_checker.py` | **66** |

**863+ spec tests pass (sessions 50–66).**

---

## Next Steps (Session 67+)

1. **`DelegationManager.merge()` audit log** — when `copy_revocations=True`, record
   each newly-copied revocation in a `PolicyAuditLog` via `audit_log=None` kwarg.
2. **`IPFSPolicyStore.save()` pin retry** — add `max_retries: int = 1` kwarg; retry
   failed pins once before recording `None` in the result dict.
3. **`PubSubBus.publish_async()` timeout report** — return a namedtuple
   `PublishAsyncResult(notified, timed_out)` instead of a bare `int` so callers
   can distinguish slow handlers from failed ones.
4. **`ComplianceChecker.migrate_encrypted()` backup** — atomically create a
   `<path>.bak` backup of the original before overwriting, and clean it up
   only when the write succeeds.
5. **Session 67 full E2E** — test the full pipeline: policy store save with
   batch-pin dict → publish_async with timeout → delegation merge with skip +
   audit → compliance encrypt/migrate/rotate → session 66 regression.
