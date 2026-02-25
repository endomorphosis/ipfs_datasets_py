# Master Improvement Plan 2026 — v14: Phases G–L (Session 58)

**Created:** 2026-02-22 (Session 58)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v13.md](MASTER_IMPROVEMENT_PLAN_2026_v13.md)

---

## Overview

Session 58 implements all six phases (G–L) from the v13 "Next Steps" list,
completing the final MCP++ integration layer items:

| Phase | Name | Status |
|-------|------|--------|
| **G** | IPFSPolicyStore server startup integration | ✅ COMPLETE |
| **H** | `RevocationList.save()` / `.load()` persistence | ✅ COMPLETE |
| **I** | `DelegationManager` (DelegationStore + RevocationList + DelegationEvaluator) | ✅ COMPLETE |
| **J** | `compliance_register_interface()` MCP tool | ✅ COMPLETE |
| **K** | `record_delegation_metrics()` monitoring integration | ✅ COMPLETE |
| **L** | Documentation update (`v14.md` + `PHASES_STATUS.md`) | ✅ COMPLETE |

**539 total spec tests pass (sessions 50–58, 0 failures).**

---

## Phase G — IPFSPolicyStore Server Startup Integration ✅

**File:** `ipfs_datasets_py/mcp_server/server.py`

Added **`_initialize_policy_store()`** method and `_policy_store` attribute to
`IPFSDatasetsMCPServer.__init__`:

- Reads the `IPFS_POLICY_STORE_PATH` environment variable on startup.
- When set, creates an `IPFSPolicyStore` bound to the global `PolicyRegistry`
  and calls `load()` to restore all previously-saved policies.
- Graceful fallback: `ImportError` (module absent) and all other exceptions are
  logged as debug/warning; the server starts normally either way.
- `_policy_store = None` when the env var is absent.

```bash
IPFS_POLICY_STORE_PATH=/var/lib/mcp/policies.json python -m ipfs_datasets_py.mcp_server
# Server log: IPFSPolicyStore loaded from /var/lib/mcp/policies.json (3 policies restored)
```

---

## Phase H — RevocationList Persistence ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added **`RevocationList.save(path)`** and **`RevocationList.load(path)`**:

- `save(path)` — serialises `{"revoked": [...sorted CIDs...]}` to a JSON file;
  creates parent directories automatically.
- `load(path)` — deserialises and adds new CIDs to the existing set;
  returns the count of **newly** added CIDs; handles missing file,
  corrupt JSON, and non-string entries without raising.

```python
rl = RevocationList()
rl.revoke("cid-compromised")
rl.save("/var/lib/mcp/revoked.json")

rl2 = RevocationList()
rl2.load("/var/lib/mcp/revoked.json")
assert rl2.is_revoked("cid-compromised")
```

---

## Phase I — DelegationManager ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added **`DelegationManager`** — a single convenience class that bundles
`DelegationStore`, `RevocationList`, and a lazily-cached
`DelegationEvaluator`:

| Method | Description |
|--------|-------------|
| `add(delegation)` | Add a delegation; invalidates evaluator cache |
| `remove(cid)` | Remove a delegation by CID; invalidates cache |
| `revoke(cid)` | Mark a CID as revoked |
| `is_revoked(cid)` | Check revocation status |
| `get_evaluator()` | Return cached DelegationEvaluator (rebuilt after mutations) |
| `can_invoke(leaf, tool, actor)` | Full chain + revocation check |
| `save()` | Persist delegation store to disk |
| `load()` | Load delegations from disk; invalidates cache |
| `get_metrics()` | `{"delegation_count": int, "revoked_cid_count": int}` |

Added **`get_delegation_manager(path?)`** — process-global singleton factory.

```python
mgr = get_delegation_manager()
mgr.add(delegation)
mgr.revoke("compromised-leaf")
ok, reason = mgr.can_invoke("leaf", "some_tool", "alice")
mgr.save()
```

---

## Phase J — Compliance Rule Interface Registration ✅

**File:** `ipfs_datasets_py/mcp_server/tools/logic_tools/compliance_rule_management_tool.py`

Added **`compliance_register_interface()`** async MCP tool:

- Creates an `InterfaceDescriptor` whose `MethodSignature` list contains one
  entry per currently-registered compliance rule ID.
- Registers the descriptor in the module-level `InterfaceRepository` singleton
  from `policy_management_tool.py`.
- Returns `{"status": "registered", "interface_cid": "bafy-mock-...", "rule_count": N}`.
- **Idempotent**: repeated calls return the same deterministic CID.
- Registered interface appears in `interface_list()` results.

```python
result = await compliance_register_interface()
# {"status": "registered", "interface_cid": "bafy-mock-...", "rule_count": 6}
```

---

## Phase K — Monitoring Integration ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added **`record_delegation_metrics(manager, collector)`**:

- Calls `collector.set_gauge("mcp_revoked_cids_total", N)` where N is the
  number of CIDs in the manager's `RevocationList`.
- Calls `collector.set_gauge("mcp_delegation_store_depth", N)` where N is the
  number of stored delegations.
- All collector exceptions are swallowed with a warning (metric recording
  never crashes the server).

```python
from ipfs_datasets_py.mcp_server.ucan_delegation import (
    get_delegation_manager, record_delegation_metrics,
)
from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector

mgr = get_delegation_manager()
collector = EnhancedMetricsCollector()
record_delegation_metrics(mgr, collector)
# collector.gauges["mcp_revoked_cids_total"] == 0.0
# collector.gauges["mcp_delegation_store_depth"] == 0.0
```

---

## Phase L — Documentation Update ✅

- **`MASTER_IMPROVEMENT_PLAN_2026_v14.md`** (this file) — documents all 6
  completed phases.
- **`PHASES_STATUS.md`** — updated cumulative status table.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56, 57 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53 |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57 |
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
| **IPFSPolicyStore server startup** | `server.py` | **58** |
| **RevocationList persistence** | `ucan_delegation.py` | **58** |
| **DelegationManager** | `ucan_delegation.py` | **58** |
| **Compliance interface registration** | `compliance_rule_management_tool.py` | **58** |
| **Monitoring delegation metrics** | `ucan_delegation.py` | **58** |

**539 spec tests pass (sessions 50–58).**

---

## Next Steps (Session 59+)

1. **`DelegationManager` ↔ server integration** — Expose `get_delegation_manager()`
   via `server.py` alongside `set_pipeline()`, and call `save()` during graceful
   shutdown.
2. **Encrypted revocation persistence** — Optionally route `RevocationList.save/load`
   through `SecretsVault` (AES-256-GCM) when the `cryptography` package is available.
3. **Monitoring loop auto-record** — Call `record_delegation_metrics()` inside the
   `EnhancedMetricsCollector._monitoring_loop()` so metrics are surfaced every 30 s.
4. **`compliance_register_interface()` on server startup** — Register the compliance
   interface CID automatically in `register_tools()` so all MCP clients can discover it.
5. **E2E smoke test for all session 58 features** — Integration test covering the full
   lifecycle: startup (env var) → delegate → revoke → metric → shutdown.
