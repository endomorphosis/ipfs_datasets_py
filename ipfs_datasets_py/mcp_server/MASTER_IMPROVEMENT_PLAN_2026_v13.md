# Master Improvement Plan 2026 — v13: Phases G–L (Session 57)

**Created:** 2026-02-22 (Session 57)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v12.md](MASTER_IMPROVEMENT_PLAN_2026_v12.md)

---

## Overview

Session 57 implements all six remaining phases (G–L) from the v12 "Next Steps"
list, completing the MCP++ integration layer:

| Phase | Name | Status |
|-------|------|--------|
| **G** | IPFS-backed policy store | ✅ COMPLETE |
| **H** | `RevocationList` + `can_invoke_with_revocation()` | ✅ COMPLETE |
| **I** | `DelegationStore` (persistent JSON) | ✅ COMPLETE |
| **J** | Compliance rule plugins via MCP tool | ✅ COMPLETE |
| **K** | End-to-end dispatch pipeline integration test | ✅ COMPLETE |
| **L** | Documentation update (`v13.md` + `PHASES_STATUS.md`) | ✅ COMPLETE |

**494 total spec tests pass (sessions 50–57, 0 failures).**

---

## Phase G — IPFS-backed Policy Store ✅

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

Added **`IPFSPolicyStore`** — extends `FilePolicyStore` with optional IPFS
pinning via `ipfs_kit_py`:

- `pin_policy(name)` — serialises the NL policy + CID metadata to JSON and
  pins it via `client.add()`; returns the IPFS `"Hash"` CID or `None` when
  IPFS is unavailable.
- `retrieve_from_ipfs(ipfs_cid)` — fetches policy data from IPFS by CID via
  `client.cat()`; returns the parsed dict or `None` on failure.
- `get_ipfs_cid(name)` — returns the IPFS CID of the last successful pin for
  *name*, or `None` if not yet pinned.
- `save()` — calls `FilePolicyStore.save()` first (always writes to disk), then
  calls `pin_policy()` for every registered policy.
- `load()` — delegates to `FilePolicyStore.load()` (IPFS retrieval available
  via `retrieve_from_ipfs()` for individual policies).
- Graceful fallback: when `ipfs_kit_py` is not installed or the client raises,
  all IPFS methods log a warning and return `None` without raising.

```python
store = IPFSPolicyStore("/var/lib/mcp/policies.json", registry,
                        ipfs_client=my_client)
store.save()              # writes JSON + pins to IPFS
cid = store.get_ipfs_cid("admin_only")  # "Qm..." or "bafy..."
store.retrieve_from_ipfs(cid)           # fetch back from IPFS
```

---

## Phase H — RevocationList + can_invoke_with_revocation ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added **`RevocationList`**:

- `revoke(cid)` — adds *cid* to the revoked set (O(1) insert).
- `is_revoked(cid)` — O(1) membership check.
- `revoke_chain(root_cid, evaluator)` — calls
  `DelegationEvaluator.build_chain(root_cid)` and revokes every delegation in
  the resulting chain; returns the count of **newly** revoked CIDs.
- `clear()` — removes all revocations.
- `to_list()` — returns sorted list of revoked CIDs.
- Supports `len()` and `in` operators.

Added **`can_invoke_with_revocation()`**:

```python
ok, reason = can_invoke_with_revocation(
    leaf_cid, tool, actor,
    evaluator=ev,
    revocation_list=revlist,
)
```

Checks every CID in the delegation chain against `revocation_list` before
performing the standard capability check.  Returns `(False, "... revoked")`
as soon as any revoked CID is found, without examining capabilities.

---

## Phase I — DelegationStore ✅

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added **`DelegationStore`** — persistent JSON store for `Delegation` objects:

- `add(delegation)` / `get(cid)` / `remove(cid)` / `list_cids()` — in-memory
  CRUD operations.
- `save()` — serialises all delegations to a JSON file; creates parent
  directories automatically.
- `load()` — reconstructs `Delegation` objects from JSON; handles missing or
  corrupt files without raising.
- `to_evaluator()` — creates a `DelegationEvaluator` populated with all
  stored delegations, ready for `can_invoke()` calls.
- Supports `len()`.

```python
store = DelegationStore("/var/lib/mcp/delegations.json")
store.add(delegation)
store.save()                # on shutdown

store2 = DelegationStore("/var/lib/mcp/delegations.json")
store2.load()               # on startup
ev = store2.to_evaluator()
ev.can_invoke("leaf-cid", resource="tool", ability="tool", actor="alice")
```

---

## Phase J — Compliance Rule Plugins via MCP Tool ✅

**File:** `ipfs_datasets_py/mcp_server/tools/logic_tools/compliance_rule_management_tool.py` (new)

Four MCP tools that expose `ComplianceChecker` rule management at runtime
without requiring a server restart:

| Tool | Description |
|------|-------------|
| `compliance_add_rule(rule_id, description, severity)` | Register a stub COMPLIANT rule |
| `compliance_list_rules()` | List all rule IDs in registration order |
| `compliance_remove_rule(rule_id)` | Remove a rule by ID |
| `compliance_check_intent(tool_name, actor, params)` | Run a synthetic intent through the global checker |

Key design decisions:
- Uses a module-level `_GLOBAL_CHECKER` singleton (lazy-init to
  `make_default_compliance_checker()`).
- `compliance_add_rule` raises `ValueError` for an empty `rule_id`.
- The registered stub always returns `COMPLIANT`; operators wanting non-trivial
  logic should use `ComplianceChecker.add_rule()` programmatically.
- All 4 tools are `async def` for MCP protocol compatibility.

---

## Phase K — End-to-end Dispatch Pipeline Integration Test ✅

**File:** `tests/mcp/unit/test_dispatch_pipeline_e2e_session57.py` (new, 63 tests)

Exercises the full MCP++ dispatch pipeline across all new and existing
components:

| Test Class | Coverage |
|------------|----------|
| `TestIPFSPolicyStore` | Phase G (9 tests) |
| `TestRevocationList` | Phase H: RevocationList (9 tests) |
| `TestCanInvokeWithRevocation` | Phase H: can_invoke_with_revocation (5 tests) |
| `TestDelegationStore` | Phase I (12 tests) |
| `TestComplianceRuleManagementTool` | Phase J (7 tests) |
| `TestDispatchPipelineEndToEnd` | Full pipeline integration (21 tests) |

Integration scenarios covered:

- NL policy → compile → `UCANPolicyGate.evaluate()`
- `PipelineMetricsRecorder.check_and_record()` → `get_stats()` / `reset()`
- `PubSubBridge.connect()` / `publish()` → `service_manager.announce_capability()`
- `EventDAG.append()` → `frontier()`
- `risk_score_from_dag()` with rollback/error `EventNode` fixtures
- `DelegationStore` save → load → `to_evaluator()` → `can_invoke_with_revocation()`
- Revocation blocks a previously valid chain

---

## Phase L — Documentation Update ✅

- **`MASTER_IMPROVEMENT_PLAN_2026_v13.md`** (this file) — documents all 6
  completed phases.
- **`PHASES_STATUS.md`** — updated cumulative status table and last-updated
  date.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, 56, **57** |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, 56 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53 |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, 56 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, 56, **57** |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| Async policy registration | `nl_ucan_policy.py` | 56 |
| Persistent policy store (file) | `nl_ucan_policy.py` | 56 |
| **IPFS-backed policy store** | `nl_ucan_policy.py` | **57** |
| PubSub ↔ P2P bridge | `mcp_p2p_transport.py` | 56 |
| Pipeline metrics | `dispatch_pipeline.py` | 56 |
| DID delegation signing | `ucan_delegation.py` | 56 |
| **RevocationList** | `ucan_delegation.py` | **57** |
| **can_invoke_with_revocation** | `ucan_delegation.py` | **57** |
| **DelegationStore** | `ucan_delegation.py` | **57** |
| **Compliance rule management tool** | `compliance_rule_management_tool.py` | **57** |

**494 spec tests pass (sessions 50–57).**

---

## Next Steps (Session 58+)

1. **Wire `IPFSPolicyStore` into server startup** — read `IPFS_POLICY_STORE_PATH`
   env var and restore the policy registry on boot.
2. **`RevocationList` persistence** — save/load revoked CIDs to the
   `SecretsVault` (encrypted) or a plain JSON file.
3. **`DelegationStore` + `RevocationList` as a `DelegationManager`** —
   single class that bundles store + revocation + evaluator, with a global
   singleton and `get_delegation_manager()` factory.
4. **Compliance rule plugin registry MCP endpoint** — expose the global
   checker as a named resource in the `InterfaceRepository` so clients can
   discover available rules.
5. **Monitoring integration** — surface `RevocationList.to_list()` length and
   `DelegationStore` depth as monitoring metrics via
   `EnhancedMetricsCollector`.
