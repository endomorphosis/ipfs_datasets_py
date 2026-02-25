# Master Improvement Plan 2026 — v19: Session 63 (v18 Next Steps)

**Created:** 2026-02-22 (Session 63)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v18.md](MASTER_IMPROVEMENT_PLAN_2026_v18.md)

---

## Overview

Session 63 implements all five "Next Steps" from the v18 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `_POLICY_STORE_VERSION` + versioned `FilePolicyStore.save/load` | ✅ COMPLETE |
| 2 | `IPFSPolicyStore.save_encrypted / load_encrypted` | ✅ COMPLETE |
| 3 | `DelegationManager.revoke_chain()` → RECEIPT_DISSEMINATE pubsub | ✅ COMPLETE |
| 4 | `ComplianceChecker.merge(other)` | ✅ COMPLETE |
| 5 | Session 63 E2E test (`test_mcplusplus_v18_session63.py`) | ✅ COMPLETE |

**756+ total spec tests pass (sessions 50–63, 0 new failures).**

---

## Item 1 — `FilePolicyStore` Version Control ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

### `_POLICY_STORE_VERSION = "1"`

A new module-level constant tracks the schema version of persisted policy JSON
files (mirrors `_COMPLIANCE_RULE_VERSION` in `compliance_checker.py`).

### `save()` — versioned format

```json
{
  "version": "1",
  "policies": {
    "policy_name": {
      "nl_policy": "...",
      "description": "...",
      "source_cid": "bafy..."
    }
  }
}
```

### `load()` — version check + backward compatibility

```python
if "policies" in raw:
    file_version = raw.get("version", "")
    if file_version and file_version != _POLICY_STORE_VERSION:
        warnings.warn("Policy store file ... migration may be needed.", UserWarning)
    data = raw["policies"]
else:
    data = raw  # legacy flat format — no warning
```

- Files **without** a `"version"` key (old format) are accepted silently.
- Files with a **matching** version do **not** warn.
- Only files with an **explicitly different** version trigger the warning.

### `save_encrypted()` — also versioned

The AES-256-GCM encrypted companion file (`<path>.enc`) now encrypts the
versioned `{"version": "1", "policies": {...}}` payload instead of the bare
policy dict. `load_encrypted()` leverages `load()` for unified version
checking.

---

## Item 2 — `IPFSPolicyStore.save_encrypted / load_encrypted` ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

Two methods added to `IPFSPolicyStore` (delegates to `FilePolicyStore`):

### `save_encrypted(password)`

Delegates to `super().save_encrypted(password)`. The encrypted file does
**not** interact with IPFS — encryption is strictly at-rest local storage.
IPFS pinning is performed separately by `save()`.

### `load_encrypted(password)`

Delegates to `super().load_encrypted(password)`. Returns 0 on missing file /
wrong password.

```python
from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore, PolicyRegistry

reg = PolicyRegistry()
store = IPFSPolicyStore("/var/lib/mcp/policies.json", reg)
reg.register("admin_only", "Only admin may call admin_tools.")
store.save_encrypted("my-passphrase")

reg2 = PolicyRegistry()
store2 = IPFSPolicyStore("/var/lib/mcp/policies.json", reg2)
count = store2.load_encrypted("my-passphrase")
assert count == 1
```

All three persistent stores (`RevocationList`, `ComplianceChecker`,
`FilePolicyStore`, `IPFSPolicyStore`) now support at-rest encrypted storage
with a consistent AES-256-GCM pattern.

---

## Item 3 — `DelegationManager.revoke_chain()` → PubSub Notification ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

`DelegationManager.revoke_chain()` now publishes a `RECEIPT_DISSEMINATE`
event to the global `PubSubBus` after revoking:

```python
bus.publish(
    PubSubEventType.RECEIPT_DISSEMINATE,
    {"type": "revocation", "root_cid": root_cid, "count": count},
)
```

- The import is **lazy** (inside the method) to avoid circular imports.
- All pubsub exceptions are swallowed (`except Exception: pass`) — the
  notification is best-effort and must never block revocation.
- The published `"count"` field exactly matches the return value.

This enables peer nodes to observe revocations in real time via the pubsub
bus, supporting the MCP+P2P distributed revocation dissemination pattern.

---

## Item 4 — `ComplianceChecker.merge(other)` ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

```python
def merge(self, other: "ComplianceChecker") -> int:
    """Merge rules and deny-list entries from *other*.

    Rules that already exist in this checker are **not** overwritten.
    Returns the number of newly-added rules.
    """
```

Behaviour:
- Iterates `other._rule_order` in order → adds rules not already in `self`.
- Unions `other._deny_list` into `self._deny_list`.
- Returns count of newly-added rules (0 if all duplicates).
- Does not mutate `other`.

```python
from ipfs_datasets_py.mcp_server.compliance_checker import (
    ComplianceChecker, make_default_compliance_checker,
)

security = ComplianceChecker(deny_list={"exploit_tool"})
security.add_rule("no_exploit", ...)

audit = ComplianceChecker(deny_list={"legacy_tool"})
audit.add_rule("audit_required", ...)

combined = ComplianceChecker()
combined.merge(security)  # → 1
combined.merge(audit)     # → 1
# combined now has both rules + both deny-list entries
```

---

## Item 5 — Session 63 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v18_session63.py`

38 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestFilePolicyStoreVersionControl` | 9 |
| `TestIPFSPolicyStoreEncryption` | 7 |
| `TestDelegationManagerRevokePubsub` | 5 |
| `TestComplianceCheckerMerge` | 10 |
| `TestE2ESession63` | 7 |

All 38 pass.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–63 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, 61, 62, **63** |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62, **63** |
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
| **_POLICY_STORE_VERSION + versioned save/load** | `nl_ucan_policy.py` | **63** |
| **IPFSPolicyStore.save_encrypted / load_encrypted** | `nl_ucan_policy.py` | **63** |
| **DelegationManager.revoke_chain → pubsub** | `ucan_delegation.py` | **63** |
| **ComplianceChecker.merge(other)** | `compliance_checker.py` | **63** |

**756+ spec tests pass (sessions 50–63).**

---

## Next Steps (Session 64+)

1. **`FilePolicyStore.reload()`** — hot-reload method (like `ComplianceChecker.reload()`): clear registry and re-`load()` from disk without creating a new instance.
2. **`DelegationManager.merge(other)`** — merge `DelegationStore` entries from another manager (like `ComplianceChecker.merge()`).
3. **`ComplianceChecker.save_encrypted` version field** — the encrypted compliance rule file should also include a `"version"` field (matching `ComplianceChecker.save()`).
4. **`PubSubBus.publish_async()`** — async variant of `publish()` for use with anyio task groups; falls back to sync `publish()` when anyio is absent.
5. **Session 64 full E2E** — test that spans: `FilePolicyStore.reload()` → `DelegationManager.merge()` → `PubSubBus.publish_async()` → monitoring gauge read → session 63 regression.
