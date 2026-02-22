# Master Improvement Plan 2026 — v17: Session 61 (v16 Next Steps)

**Created:** 2026-02-22 (Session 61)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v16.md](MASTER_IMPROVEMENT_PLAN_2026_v16.md)

---

## Overview

Session 61 implements all five "Next Steps" from the v16 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `enterprise_api.py` — `POST /delegations/revoke` + `GET /delegations/metrics` routes | ✅ COMPLETE |
| 2 | `ComplianceChecker.reload(path)` — hot-reload rule config | ✅ COMPLETE |
| 3 | `ComplianceChecker.save_encrypted/load_encrypted` — AES-256-GCM rule persistence | ✅ COMPLETE |
| 4 | `DelegationEvaluator.max_chain_depth` — reject over-deep chains | ✅ COMPLETE |
| 5 | Full server integration test (5 stores) | ✅ COMPLETE |

**664 total spec tests pass (sessions 50–61, 0 new failures).**

---

## Item 1 — Enterprise API Delegation Routes ✅

**File:** `ipfs_datasets_py/mcp_server/enterprise_api.py`

### `DelegationRevokeRequest` Pydantic model

```python
class DelegationRevokeRequest(BaseModel):
    root_cid: str = Field(..., description="Root CID of the delegation chain to revoke")
```

### `_setup_delegation_routes(app, get_current_user)`

New helper registered in `_setup_routes()`:

- **`POST /delegations/revoke`** — accepts `DelegationRevokeRequest`; calls
  `get_delegation_manager().revoke_chain(root_cid)` then `.save()`; returns
  `{"root_cid": str, "revoked_count": int}`; returns `revoked_count=0` on any
  exception.
- **`GET /delegations/metrics`** — calls `get_delegation_manager().get_metrics()`
  and returns `{"delegation_count": int, "revoked_cid_count": int}`; returns
  zeros on exception.

Both routes use lazy import of `get_delegation_manager` and are guarded with
`except Exception` so delegation failures never crash the REST API.

---

## Item 2 — `ComplianceChecker.reload(path)` ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

```python
def reload(self, path: str) -> int:
    self._rules.clear()
    self._rule_order.clear()
    self._deny_list.clear()
    return self.load(path)
```

- Clears all existing state before calling `load(path)`.
- Enables hot-reload: call `reload(path)` to replace the running checker's
  rules from disk without creating a new instance.
- Returns 0 on missing/corrupt file (same as `load()`).

---

## Item 3 — `ComplianceChecker` Encrypted Persistence ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

### `save_encrypted(path, password)`

- Derives 32-byte key from `SHA-256(password)`.
- Generates a random 12-byte nonce via `os.urandom(12)`.
- Encrypts `{"rule_order": [...], "deny_list": [...]}` JSON with AES-256-GCM.
- Writes `<nonce 12 bytes> || <ciphertext>` to *path*.
- Creates parent directories automatically.
- Falls back to plain `save()` with `UserWarning` when `cryptography` absent.

### `load_encrypted(path, password)`

- Reads the binary file; splits nonce (first 12 bytes) and ciphertext.
- Derives key the same way as `save_encrypted`.
- Decrypts with AES-256-GCM; returns 0 on `InvalidTag` or any error.
- Writes decrypted JSON to a `tempfile` and delegates to `load()`.
- Falls back to plain `load()` with `UserWarning` when `cryptography` absent.

```python
checker = make_default_compliance_checker(deny_list={"blocked"})
checker.save_encrypted("/var/lib/mcp/rules.enc", "my-secret")

restored = ComplianceChecker()
restored.load_encrypted("/var/lib/mcp/rules.enc", "my-secret")
assert "blocked" in restored._deny_list
```

---

## Item 4 — `DelegationEvaluator.max_chain_depth` ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

### `DelegationEvaluator.__init__(max_chain_depth=0)`

- `max_chain_depth=0` means **unlimited** (existing behaviour preserved).
- Stored as `self._max_chain_depth`.

### `build_chain()` enforcement

```python
if self._max_chain_depth > 0 and len(chain) > self._max_chain_depth:
    raise ValueError(
        f"Delegation chain length {len(chain)} exceeds max_chain_depth "
        f"{self._max_chain_depth}"
    )
```

- Raised **after** chain is assembled — cycle and missing-link errors are still
  detected first.

### `DelegationManager` propagation

- `DelegationManager.__init__(path=None, max_chain_depth=0)` — stores the limit.
- `get_evaluator()` sets `evaluator._max_chain_depth = self._max_chain_depth`
  whenever the evaluator is rebuilt.
- `get_delegation_manager(path=None, max_chain_depth=0)` — passes `max_chain_depth`
  through to `DelegationManager` on first creation.

```python
mgr = get_delegation_manager(max_chain_depth=5)
# Build a chain of 6 — can_invoke will return (False, "...max_chain_depth...")
ok, reason = mgr.can_invoke("leaf-cid", "tool", "alice")
assert not ok
assert "max_chain_depth" in reason
```

---

## Item 5 — Full Server Integration Test (5 Stores) ✅

**File:** `tests/mcp/unit/test_mcplusplus_v16_session61.py`

46 tests across 6 sections:

| Section | Tests | Scope |
|---------|-------|-------|
| `TestEnterpriseAPIDelegationRoutes` | 10 | Source inspection of enterprise_api.py routes |
| `TestComplianceCheckerReload` | 5 | `reload()` behaviour: clears state, restores deny list, missing file |
| `TestComplianceCheckerEncryptedPersistence` | 9 | `save_encrypted/load_encrypted` round-trip, wrong password, binary file, fallback |
| `TestDelegationEvaluatorMaxChainDepth` | 7 | Chain within/at/over limit, unlimited depth, error message |
| `TestDelegationManagerMaxChainDepth` | 4 | Manager init, evaluator propagation, singleton, can_invoke reject |
| `TestFullServerIntegration5Stores` | 11 | Policy/delegation/encryption/compliance/interface round-trips |

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56, 57, 58, 59, 60, **61** |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, **61** |
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
| DelegationManager encrypted persistence | `ucan_delegation.py` | 60 |
| DelegationManager.revoke_chain() | `ucan_delegation.py` | 60 |
| P2PMetricsCollector delegation metrics | `monitoring.py` | 60 |
| ComplianceChecker.save/load | `compliance_checker.py` | 60 |
| server.revoke_delegation_chain() | `server.py` | 60 |
| **Enterprise API delegation routes** | `enterprise_api.py` | **61** |
| **ComplianceChecker.reload()** | `compliance_checker.py` | **61** |
| **ComplianceChecker.save_encrypted/load_encrypted** | `compliance_checker.py` | **61** |
| **DelegationEvaluator.max_chain_depth** | `ucan_delegation.py` | **61** |
| **DelegationManager.max_chain_depth propagation** | `ucan_delegation.py` | **61** |

**664+ spec tests pass (sessions 50–61).**

---

## Next Steps (Session 62+)

1. **`DelegationEvaluator` chain depth in P2P health** — include `max_chain_depth`
   and current max-observed depth in `P2PMetricsCollector._record_delegation_metrics()`
   output so operators can tune the limit.
2. **Compliance rule version control** — add `version: str` field to the
   saved JSON and raise `UserWarning` when loading a file from a different
   version, so rule migrations are detectable.
3. **Enterprise API integration test** — add a `httpx.TestClient` round-trip
   test for `POST /delegations/revoke` and `GET /delegations/metrics` that
   mocks `get_delegation_manager()`.
4. **`FilePolicyStore` encrypted variant** — add
   `FilePolicyStore.save_encrypted / load_encrypted` mirroring the
   `ComplianceChecker` and `RevocationList` patterns, so all three persistent
   stores support encrypted at-rest storage.
5. **Session 62 E2E scenario** — test that spans: policy store →
   compliance rules (encrypted) → delegation chain (depth-limited) →
   pipeline check → enterprise API revoke → monitoring gauge read.
