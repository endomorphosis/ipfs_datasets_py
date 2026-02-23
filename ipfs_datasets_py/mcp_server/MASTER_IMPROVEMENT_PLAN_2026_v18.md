# Master Improvement Plan 2026 — v18: Session 62 (v17 Next Steps)

**Created:** 2026-02-22 (Session 62)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v17.md](MASTER_IMPROVEMENT_PLAN_2026_v17.md)

---

## Overview

Session 62 implements all five "Next Steps" from the v17 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `DelegationManager.get_metrics()` — include `max_chain_depth` | ✅ COMPLETE |
| 2 | `record_delegation_metrics()` — emit `mcp_delegation_max_chain_depth` gauge | ✅ COMPLETE |
| 3 | `_COMPLIANCE_RULE_VERSION` + `save()/load()` version field | ✅ COMPLETE |
| 4 | Enterprise API integration test (source inspection + mock) | ✅ COMPLETE |
| 5 | `FilePolicyStore.save_encrypted / load_encrypted` | ✅ COMPLETE |

**718 total spec tests pass (sessions 50–62, 0 new failures).**

---

## Item 1+2 — DelegationEvaluator Chain Depth in P2P Health ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

### `DelegationManager.get_metrics()` extended

```python
return {
    "delegation_count": len(self._store),
    "revoked_cid_count": len(self._revocation),
    "max_chain_depth": self._max_chain_depth,   # NEW — 0 = unlimited
}
```

### `record_delegation_metrics()` extended

Added a third `set_gauge` call:

```python
collector.set_gauge(
    "mcp_delegation_max_chain_depth",
    float(metrics["max_chain_depth"]),
)
```

This means operators can now see the configured chain-depth limit alongside
`mcp_revoked_cids_total` and `mcp_delegation_store_depth` in the P2P health
dashboard and Prometheus metrics.

---

## Item 3 — Compliance Rule Version Control ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

### `_COMPLIANCE_RULE_VERSION = "1"`

A new module-level constant (exported in `__all__`) tracks the schema version
of persisted rule files.

### `save(path)` — adds `"version"` field

```json
{
  "version": "1",
  "rule_order": [...],
  "deny_list": [...]
}
```

### `load(path)` — version check

```python
file_version = data.get("version", "")
if file_version and file_version != _COMPLIANCE_RULE_VERSION:
    warnings.warn(
        f"Compliance rule file {path!r} was saved with version {file_version!r} "
        f"but current version is {_COMPLIANCE_RULE_VERSION!r}. "
        "Rule migration may be needed.",
        UserWarning,
    )
```

- Files **without** a `"version"` key (old format) do **not** warn.
- Files with a **matching** version do **not** warn.
- Only files with an **explicitly different** version trigger the warning.

---

## Item 4 — Enterprise API Integration Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v17_session62.py`

Tests 11 scenarios across `TestEnterpriseAPIDelegationRoutesIntegration`:

- Source inspection confirms `POST /delegations/revoke` and
  `GET /delegations/metrics` routes exist and call `revoke_chain`,
  `get_metrics`, and `mgr.save()`.
- Mock `get_delegation_manager()` round-trips verify route logic works as
  documented.
- `DelegationRevokeRequest` model verified (skipped if `anyio` absent).

---

## Item 5 — `FilePolicyStore` Encrypted Persistence ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

Two new methods added to `FilePolicyStore`:

### `save_encrypted(password)`

- Builds the in-memory JSON representation (same data as `save()`).
- Derives 32-byte AES key: `SHA-256(password)`.
- Generates 12-byte random nonce via `os.urandom(12)`.
- Encrypts with `AESGCM`; writes `<nonce 12 bytes> || <ciphertext>` to
  `<self.path>.enc`.
- Creates parent directories automatically.
- Falls back to plain `save()` with `UserWarning` when `cryptography` absent.

### `load_encrypted(password)`

- Reads `<self.path>.enc`; returns 0 on missing/short file.
- Decrypts with AES-256-GCM; returns 0 on `InvalidTag` (wrong password / tampered data).
- Writes plaintext to a `tempfile`, swaps `self.path` temporarily, calls
  `self.load()` for unified registration logic, then restores `self.path`.
- Falls back to plain `load()` with `UserWarning` when `cryptography` absent.

```python
from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore, PolicyRegistry

reg = PolicyRegistry()
store = FilePolicyStore("/var/lib/mcp/policies.json", reg)
reg.register("admin_only", "Only admin may call admin_tools.")
store.save_encrypted("my-passphrase")

reg2 = PolicyRegistry()
store2 = FilePolicyStore("/var/lib/mcp/policies.json", reg2)
count = store2.load_encrypted("my-passphrase")
assert count == 1
```

All three persistent stores (`RevocationList`, `ComplianceChecker`,
`FilePolicyStore`) now support at-rest encrypted storage with a consistent
AES-256-GCM pattern.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56, 57, 58, 59, 60, 61, **62** |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, 61, **62** |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, **62** |
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
| **DelegationManager.get_metrics() — max_chain_depth** | `ucan_delegation.py` | **62** |
| **record_delegation_metrics — mcp_delegation_max_chain_depth** | `ucan_delegation.py` | **62** |
| **_COMPLIANCE_RULE_VERSION + version field in save/load** | `compliance_checker.py` | **62** |
| **FilePolicyStore.save_encrypted / load_encrypted** | `nl_ucan_policy.py` | **62** |

**718+ spec tests pass (sessions 50–62).**

---

## Next Steps (Session 63+)

1. **`FilePolicyStore` version control** — add a `"version"` field to the
   persisted policy JSON (mirroring `_COMPLIANCE_RULE_VERSION` in
   `compliance_checker.py`) so policy-file migrations are detectable.
2. **`IPFSPolicyStore.save_encrypted`** — extend `IPFSPolicyStore` with
   encrypted persistence (delegates to `FilePolicyStore.save_encrypted`).
3. **`DelegationManager` — P2P pubsub notification on revocation** — when
   `revoke_chain()` is called, publish a `RECEIPT_DISSEMINATE` event to the
   global `PubSubBus` so peer nodes can observe revocations in real time.
4. **`ComplianceChecker.merge(other)`** — merge rules from another checker
   instance so composite rule sets can be assembled without reloading from disk.
5. **Session 63 E2E scenario** — test that spans: encrypted policy store →
   compliance version control → `DelegationManager` P2P pubsub revocation
   notification → monitoring gauge read → session 62 round-trip regression.
