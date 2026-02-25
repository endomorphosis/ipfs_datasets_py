# Master Improvement Plan 2026 — v12: MCP++ Integration Layer (Session 56)

**Created:** 2026-02-22 (Session 56)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v11.md](MASTER_IMPROVEMENT_PLAN_2026_v11.md)

---

## Overview

Session 56 implements all five "Next Steps" from v11, completing the MCP++
integration layer:

1. **Async tool registration** — `AsyncPolicyRegistrar` (anyio task group)
2. **Persistent policy store** — `FilePolicyStore` (JSON, CID-validated)
3. **PubSubBus ↔ P2PServiceManager bridge** — `PubSubBridge`
4. **Pipeline metrics** — `PipelineMetricsRecorder`
5. **DID key manager integration** — `DIDSignedDelegation` + sign/verify

---

## Session 56 Changes

### 1 — Async Policy Registration ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

Added **`AsyncPolicyRegistrar`**:

- Registers multiple NL policies concurrently using an `anyio.create_task_group()`.
- Each compilation runs in a worker thread via `anyio.to_thread.run_sync()`, keeping
  the event loop free for LLM-backed or I/O-heavy compilers.
- Graceful sync fallback when `anyio` is not installed.
- Correctly uses `registry if registry is not None else get_policy_registry()` (fixes
  the falsy-empty-registry pitfall where `registry or default` would silently fall
  back to the global singleton for any newly-created empty `PolicyRegistry`).

```python
registrar = AsyncPolicyRegistrar(registry)
await registrar.register_many({
    "admin_only": "Only admin may call admin_tools.",
    "read_public": "All users may call read_tools.",
})
```

### 2 — Persistent Policy Store ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/nl_ucan_policy.py`

Added **`FilePolicyStore`**:

- Serialises the `PolicyRegistry` as a JSON file mapping
  `name → {nl_policy, description, source_cid}`.
- `save()` — writes atomically (creates parent directories).
- `load()` — re-derives the CID of each stored NL text; if it differs from
  the stored `source_cid` (indicating file-level edit or tampering), the
  policy is transparently recompiled and a DEBUG log is emitted.
- Missing / unreadable files return 0 without raising.

```python
store = FilePolicyStore("/var/lib/mcp/policies.json", registry)
store.save()    # persist on graceful shutdown
store.load()    # restore on startup
```

### 3 — PubSubBus ↔ P2PServiceManager Bridge ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

Added **`PubSubBridge`** + **`get_global_bus()`**:

- `connect(service_manager)` — registers one handler per canonical
  `PubSubEventType` topic; each handler forwards `(topic_key, payload)` to
  `service_manager.announce_capability()` when that method exists.
- `disconnect()` — removes all bridge handlers and detaches from the
  service manager.
- `is_connected` property — read-only lifecycle flag.
- `get_global_bus()` — returns the module-level `PubSubBus` singleton (lazy
  init); suitable for test injection or external use.
- Fixed: `_make_handler()` now takes no arguments (the `t` parameter was
  unused and could confuse linters); `topic_key` arrives at handler call time
  from the `PubSubBus.publish()` invocation.

```python
bridge = PubSubBridge()
bridge.connect(p2p_service_manager)   # wired
bus = get_global_bus()
bus.publish(PubSubEventType.INTERFACE_ANNOUNCE.value, {"cid": "bafy-..."})
# → service_manager.announce_capability("/mcp+p2p/topics/interface_cid/1.0.0", {...})
bridge.disconnect()
```

### 4 — Pipeline Metrics Recorder ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/dispatch_pipeline.py`

Added **`PipelineMetricsRecorder`**:

- Wraps a `DispatchPipeline`; `check_and_record(intent)` runs the pipeline
  and feeds the result to the monitoring subsystem.
- Calls `EnhancedMetricsCollector.track_tool_execution(tool_name,
  execution_time_ms=0.0, success=passed)` so pipeline-level access-control
  events appear in the monitoring dashboard alongside ordinary tool metrics.
- Maintains in-process `allow_counts` / `denial_counts` dicts for fast
  local inspection without touching the collector.
- `get_stats()` → `{allow_counts, denial_counts, total_allows, total_denials}`.
- `reset()` clears all local counters.
- Exceptions from the collector are swallowed (monitoring is best-effort).
- Uses `result.allowed` (boolean attribute) not `result.verdict == "allow"`
  (string property) for the primary branching decision.

```python
recorder = PipelineMetricsRecorder(pipeline)
result = recorder.check_and_record(intent)
print(recorder.get_stats())
# → {'allow_counts': {'my_tool': 42}, 'denial_counts': {}, ...}
```

### 5 — DID Key Manager Integration ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Added **`DIDSignedDelegation`**, **`sign_delegation()`**, and
**`verify_delegation_signature()`**:

- `DIDSignedDelegation(delegation, signature, signer_did, verified)` — wraps
  a `Delegation` with a hex Ed25519 signature and the DID:key of the signer.
- `sign_delegation(delegation, *, key_manager)` — serialises the delegation
  to canonical JSON, calls `key_manager.sign(payload)`, and returns a
  `DIDSignedDelegation`. Falls back to a `"did:key:unsigned"` sentinel
  with empty signature when the key manager is absent or raises.
- `verify_delegation_signature(signed, *, key_manager)` — re-derives the
  JSON payload and calls `key_manager.verify(payload, sig_bytes)`. Returns
  `False` on empty signature, absent manager, or any exception.
- Both helpers look for the global `did_key_manager.get_default_manager()`
  singleton when no explicit *key_manager* is given.

```python
cap = Capability(resource="mcp:tool", ability="invoke")
d = Delegation(cid="cid1", issuer="did:key:z6MkA", audience="did:key:z6MkB",
               capabilities=[cap])
signed = sign_delegation(d, key_manager=manager)
ok = verify_delegation_signature(signed, key_manager=manager)
```

---

## Bug Fixes

| File | Bug | Fix |
|------|-----|-----|
| `nl_ucan_policy.py` | `FilePolicyStore.__init__` used `registry or default` — empty registry triggers fallback to global singleton | Changed to `registry if registry is not None else default` |
| `nl_ucan_policy.py` | Same bug in `AsyncPolicyRegistrar.__init__` | Same fix |
| `ucan_delegation.py` | Unused `hashlib` import inside `sign_delegation()` | Removed |
| `mcp_p2p_transport.py` | Missing `import logging` / `logger` | Added |
| `dispatch_pipeline.py` | Missing `Dict`, `List`, `Optional` in `from typing import` | Added |

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53, **56** |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54, 55, **56** |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53, 55 |
| Compliance | `compliance_checker.py` | 53 |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54, **56** |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51, 52, **56** |
| Server pipeline gate | `server.py` | 55 |
| Policy MCP tools | `policy_management_tool.py` | 55 |
| Pubsub bus | `mcp_p2p_transport.py` | 55 |
| **Async policy registration** | `nl_ucan_policy.py` | **56** |
| **Persistent policy store** | `nl_ucan_policy.py` | **56** |
| **PubSub ↔ P2P bridge** | `mcp_p2p_transport.py` | **56** |
| **Pipeline metrics** | `dispatch_pipeline.py` | **56** |
| **DID delegation signing** | `ucan_delegation.py` | **56** |

**431 spec tests pass (sessions 50–56).**

---

## Next Steps (Session 57+)

1. **IPFS-backed policy store** — Extend `FilePolicyStore` with an
   `IPFSPolicyStore` variant that pins policies to IPFS and retrieves them
   by CID (using the `ipfs_kit_py` client).
2. **RevocationList** — Add `RevocationList` + `can_invoke_with_revocation()`
   to `ucan_delegation.py` (already in `create-refactoring-plan-again` branch;
   needs porting here).
3. **DelegationStore** — Add persistent `DelegationStore.save()/load()` backed
   by a JSON file (analogous to `FilePolicyStore`).
4. **Compliance rule plugins** — Expose `ComplianceChecker.add_rule()` via an
   MCP tool so operators can add custom compliance rules at runtime without
   restarting the server.
5. **End-to-end test** — Write an integration test that exercises the full
   dispatch pipeline + pubsub bridge + monitoring recorder in a single
   anyio-driven test.
