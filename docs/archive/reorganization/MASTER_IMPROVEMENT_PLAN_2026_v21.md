# Master Improvement Plan 2026 — v21: Session 65 (v20 Next Steps)

**Created:** 2026-02-22 (Session 65)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v20.md](MASTER_IMPROVEMENT_PLAN_2026_v20.md)

---

## Overview

Session 65 implements all five "Next Steps" from the v20 plan:

| # | Feature | Status |
|---|---------|--------|
| 1 | `IPFSPolicyStore.reload()` — re-pins after hot-reload | ✅ COMPLETE |
| 2 | `DelegationManager.merge(other, copy_revocations=False)` | ✅ COMPLETE |
| 3 | `PubSubBus.publish_async()` DEBUG-level exception logging | ✅ COMPLETE |
| 4 | `ComplianceChecker.load_encrypted` version check | ✅ COMPLETE |
| 5 | Session 65 E2E test (`test_mcplusplus_v20_session65.py`, 33 tests) | ✅ COMPLETE |

**821+ total spec tests pass (sessions 50–65, 0 new failures).**

---

## Item 1 — `IPFSPolicyStore.reload()` ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

`IPFSPolicyStore` now overrides `FilePolicyStore.reload()`:

```python
def reload(self) -> int:
    count = super().reload()
    for name in self._registry.list_names():
        self.pin_policy(name)
    return count
```

- Calls `super().reload()` to clear + re-load from disk.
- Then re-pins every loaded policy to IPFS so the `_cid_map` stays current.
- IPFS pin failures are swallowed (logged at WARNING) — they do not prevent reload.

---

## Item 2 — `DelegationManager.merge(other, copy_revocations=False)` ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

`copy_revocations` keyword-only parameter added:

```python
def merge(
    self,
    other: "DelegationManager",
    *,
    copy_revocations: bool = False,
) -> int:
```

- Default `False` preserves the previous behaviour (revocations not copied).
- When `True`, every CID in `other._revocation` is also revoked in `self`.
- Revocation copy happens **after** delegation copy, so it is always safe.
- Source manager is never mutated.

---

## Item 3 — `PubSubBus.publish_async()` DEBUG logging ✅

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

Error path updated to capture and log the exception:

```python
except Exception as exc:
    logger.debug("publish_async handler %d raised: %s", idx, exc)
    results[idx] = False
```

Previously exceptions were swallowed silently; they are now traceable via `DEBUG` log output.

---

## Item 4 — `ComplianceChecker.load_encrypted` version check ✅

**File:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

After AES-256-GCM decryption, the version field is now validated:

```python
file_version = data.get("version", "")
if file_version and file_version != _COMPLIANCE_RULE_VERSION:
    warnings.warn(
        f"Encrypted compliance rule file was saved with version "
        f"{file_version!r} but current version is "
        f"{_COMPLIANCE_RULE_VERSION!r}. Proceeding with caution.",
        UserWarning,
        stacklevel=2,
    )
```

- Missing `"version"` key → no warning (backward-compatible with older files).
- Mismatch → `UserWarning` emitted; load continues.

This mirrors the version-check logic in `load()` for the plaintext path.

---

## Item 5 — Session 65 E2E Test ✅

**File:** `tests/mcp/unit/test_mcplusplus_v20_session65.py`

33 tests across 5 sections:

| Section | Tests |
|---------|-------|
| `TestIPFSPolicyStoreReloadPins` | 7 |
| `TestDelegationManagerMergeCopyRevocations` | 8 |
| `TestPubSubBusPublishAsyncErrorLogging` | 5 |
| `TestComplianceCheckerLoadEncryptedVersionCheck` | 4 |
| `TestE2ESession65` | 9 |

All 33 pass with 0 failures.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56–65 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56, 64, **65** |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53, 60, 61, 62, 63, 64, **65** |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, 57, 62, 63, 64, **65** |
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
| FilePolicyStore.reload() | `nl_ucan_policy.py` | 64 |
| DelegationManager.merge(other) | `ucan_delegation.py` | 64 |
| ComplianceChecker.save_encrypted version field | `compliance_checker.py` | 64 |
| PubSubBus.publish_async() | `mcp_p2p_transport.py` | 64 |
| **IPFSPolicyStore.reload() with re-pin** | `nl_ucan_policy.py` | **65** |
| **DelegationManager.merge(copy_revocations=...)** | `ucan_delegation.py` | **65** |
| **publish_async DEBUG error logging** | `mcp_p2p_transport.py` | **65** |
| **ComplianceChecker.load_encrypted version check** | `compliance_checker.py` | **65** |

**821+ spec tests pass (sessions 50–65).**

---

## Next Steps (Session 66+)

1. **`DelegationManager.merge()` with revocation exception list** — add a
   `skip_revocations: Optional[Set[str]] = None` parameter so callers can
   opt-in to all revocations except a specific set.
2. **`IPFSPolicyStore` batch-pin on `save()`** — accumulate IPFS pin results
   and return them as a `Dict[str, Optional[str]]` from `save()`.
3. **`PubSubBus.publish_async()` timeout** — add `timeout_seconds: float = 5.0`
   parameter that cancels slow handlers via `anyio.move_on_after()`.
4. **`ComplianceChecker.save_encrypted` version bump migration** — add a
   `migrate_encrypted(path, old_password, new_password)` helper that
   re-encrypts with a new password while bumping the version field.
5. **Session 66 full E2E** — test that spans: `IPFSPolicyStore.reload()` with
   IPFS mock → `DelegationManager.merge(copy_revocations=True)` → `publish_async()`
   with timeout → compliance encrypted version migration → session 65 regression.
