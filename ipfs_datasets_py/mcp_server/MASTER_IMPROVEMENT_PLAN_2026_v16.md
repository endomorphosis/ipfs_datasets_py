# Master Improvement Plan 2026 — v16: Phases G–L (Session 60)

**Created:** 2026-02-22 (Session 60)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v15.md](MASTER_IMPROVEMENT_PLAN_2026_v15.md)

---

## Overview

Session 60 implements all five "Next Steps" from the v15 plan as six phases (G–L):

| Phase | Name | Status |
|-------|------|--------|
| **G** | `DelegationManager.save_encrypted` / `load_encrypted` | ✅ COMPLETE |
| **H** | `P2PMetricsCollector._record_delegation_metrics` in health check | ✅ COMPLETE |
| **I** | `ComplianceChecker.save(path)` / `load(path)` persistence | ✅ COMPLETE |
| **J** | `server.revoke_delegation_chain(root_cid)` | ✅ COMPLETE |
| **K** | Full E2E test (40 tests) | ✅ COMPLETE |
| **L** | Documentation update (`v16.md` + `PHASES_STATUS.md`) | ✅ COMPLETE |

**618 total spec tests pass (sessions 50–60, 0 new failures).**

---

## Phase G — DelegationManager Encrypted Persistence ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added two new methods to `DelegationManager`:

### `save_encrypted(password)`

- Derives the revocation file path as `<store_basename>.revoked.enc`
  (sibling of the JSON delegation store, using `os.path.splitext`).
- Delegates to `RevocationList.save_encrypted(enc_path, password)`.
- **Fallback**: plain `save()` with `UserWarning` when `cryptography` absent.

### `load_encrypted(password)`

- Reads companion `<store_basename>.revoked.enc`.
- Delegates to `RevocationList.load_encrypted(enc_path, password)`.
- Returns 0 without raising on any error (wrong password, missing file, etc.).
- **Fallback**: plain `load()` with `UserWarning` when `cryptography` absent.

### `revoke_chain(root_cid)` ← also added in Session 60

- Calls `RevocationList.revoke_chain(root_cid, self.get_evaluator())`.
- Returns the count of newly-revoked CIDs.

```python
mgr = DelegationManager("/var/lib/mcp/delegations.json")
mgr.revoke("compromised-cid")
mgr.save_encrypted("my-secret")

mgr2 = DelegationManager("/var/lib/mcp/delegations.json")
mgr2.load_encrypted("my-secret")
assert mgr2.is_revoked("compromised-cid")
```

---

## Phase H — P2PMetricsCollector Delegation Metrics ✅

**File:** `ipfs_datasets_py/mcp_server/monitoring.py`

Added `_record_delegation_metrics()` method to `P2PMetricsCollector` and
a call to it at the end of `get_alert_conditions()`:

```python
def _record_delegation_metrics(self) -> None:
    try:
        from .ucan_delegation import get_delegation_manager, record_delegation_metrics
        record_delegation_metrics(get_delegation_manager(), self.base_collector)
    except Exception as _exc:
        logger.debug("P2PMetricsCollector delegation metrics unavailable: %s", _exc)
```

- **Lazy import** avoids circular imports at module load time.
- **Exception swallowed** — delegation metrics are informational.
- `get_alert_conditions()` now calls `_record_delegation_metrics()` after
  computing P2P-specific alerts so gauges appear in the health dashboard.

---

## Phase I — ComplianceChecker Persistence ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

Added `save(path)` and `load(path)` methods to `ComplianceChecker`:

### `save(path)`

- Writes `{"rule_order": [...], "deny_list": [...]}` JSON.
- Creates parent directories if they do not exist.

### `load(path)`

- Restores `deny_list` from JSON.
- Re-wires built-in rule callables (`tool_name_convention`,
  `intent_has_actor`, `actor_is_valid`, `params_are_serializable`,
  `tool_not_in_deny_list`, `rate_limit_ok`) from the bound methods.
- Unknown rule IDs get a no-op COMPLIANT stub; callers must re-register the
  real implementation via `add_rule()`.
- Returns the count of rule IDs loaded; returns 0 on missing/corrupt file.

```python
checker = make_default_compliance_checker(deny_list={"blocked_tool"})
checker.save("/var/lib/mcp/compliance_rules.json")

checker2 = ComplianceChecker()
checker2.load("/var/lib/mcp/compliance_rules.json")
# checker2 now has all 6 rules + deny list restored
```

---

## Phase J — `server.revoke_delegation_chain()` ✅

**File:** `ipfs_datasets_py/mcp_server/server.py`

Added `revoke_delegation_chain(root_cid)` method to
`IPFSDatasetsMCPServer`:

- Calls `self._server_delegation_manager.revoke_chain(root_cid)`.
- Calls `mgr.save()` immediately after revoking to persist the updated state.
- Returns 0 when no manager is initialised or if `revoke_chain()` raises.

```python
server = IPFSDatasetsMCPServer(configs)
count = server.revoke_delegation_chain("compromised-root-cid")
# count is the number of newly-revoked CIDs; updated state persisted to disk
```

---

## Phase K — Full E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v15_session60.py`

40 tests across 5 test classes:

| Class | Tests | Scope |
|-------|-------|-------|
| `TestDelegationManagerEncryptedPersistence` | 7 | `save_encrypted`/`load_encrypted` round-trip, wrong password, missing file, fallback, empty list |
| `TestP2PMetricsCollectorDelegationMetrics` | 7 | Source inspection: `_record_delegation_metrics`, lazy import, exception guard, called from `get_alert_conditions` |
| `TestComplianceCheckerPersistence` | 10 | `save`/`load` round-trip, deny list restore, missing/corrupt file, parent dir creation, built-in rules run, unknown stubs |
| `TestServerRevokeDelegationChain` | 6 | Method exists, returns count, no-manager=0, exception=0, source has `revoke_chain`, calls `save()` |
| `TestFullE2E` | 10 | Full lifecycle: delegation encrypt/decrypt, compliance save/load, P2P source check, revoke_chain, metrics keys, method existence checks |

---

## Phase L — Documentation Update ✅

- **`MASTER_IMPROVEMENT_PLAN_2026_v16.md`** (this file) — documents all 6
  completed phases.
- **`PHASES_STATUS.md`** — updated cumulative status table.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56, 57, 58, 59, **60** |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, **60** |
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
| IPFSPolicyStore server startup | `server.py` | 58 |
| RevocationList persistence (plain) | `ucan_delegation.py` | 58 |
| DelegationManager | `ucan_delegation.py` | 58 |
| Compliance interface registration tool | `compliance_rule_management_tool.py` | 58 |
| Monitoring delegation metrics | `ucan_delegation.py` | 58 |
| DelegationManager server integration | `server.py` | 59 |
| RevocationList persistence (encrypted) | `ucan_delegation.py` | 59 |
| Monitoring loop auto-record | `monitoring.py` | 59 |
| Compliance interface on startup | `server.py` | 59 |
| **DelegationManager encrypted persistence** | `ucan_delegation.py` | **60** |
| **DelegationManager.revoke_chain()** | `ucan_delegation.py` | **60** |
| **P2PMetricsCollector delegation metrics** | `monitoring.py` | **60** |
| **ComplianceChecker.save/load** | `compliance_checker.py` | **60** |
| **server.revoke_delegation_chain()** | `server.py` | **60** |

**618+ spec tests pass (sessions 50–60).**

---

## Next Steps (Session 61+)

1. **`DelegationManager` HTTP API endpoint** — expose `revoke_delegation_chain`
   as a REST/MCP tool via `enterprise_api.py` (e.g. `POST /delegations/revoke`).
2. **Compliance rule hot-reload** — add a `reload(path)` method that calls
   `load(path)` and triggers re-evaluation of any cached decisions.
3. **Encrypted compliance rule store** — add `ComplianceChecker.save_encrypted`
   / `load_encrypted` mirroring the `RevocationList` pattern.
4. **Delegation chain depth limit** — add `max_chain_depth` config to
   `DelegationEvaluator` so overly-deep chains are rejected during evaluation.
5. **Full server integration test with all 5 stores** — test that spans:
   - Policy store (`IPFS_POLICY_STORE_PATH`)
   - Delegation store (`MCP_DELEGATION_STORE_PATH`)
   - Encrypted revocation store (`*.revoked.enc`)
   - Compliance rules store
   - Interface repository
   with server startup → register_tools → dispatch → shutdown + reload cycle.
