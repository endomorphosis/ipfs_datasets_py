# Master Improvement Plan 2026 — v11: MCP++ Integration Layer

**Created:** 2026-02-22 (Session 55)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v10.md](MASTER_IMPROVEMENT_PLAN_2026_v10.md)

---

## Overview

Session 55 implements all five "Next Steps" from v10 — the integration layer
that wires together the individual MCP++ spec modules into the live server.

---

## Session 55 Changes

### 1 — `server.py` Pipeline Integration ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/server.py`

- Added `self._dispatch_pipeline = None` to `__init__` (opt-in gate, no behaviour change
  by default).
- Added `set_pipeline(pipeline)` / `get_pipeline()` public methods so callers can
  attach a :class:`~dispatch_pipeline.DispatchPipeline` at runtime without
  subclassing.
- Added `register_tools()` block that registers 6 policy management tools via
  `tools/logic_tools/policy_management_tool.py` using a `try/except ImportError`
  guard (no hard dependency).

### 2 — MCP Tool Exposure ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/tools/logic_tools/policy_management_tool.py`

Exposes both the :class:`~nl_ucan_policy.PolicyRegistry` and the
:class:`~interface_descriptor.InterfaceRepository` as callable MCP tools:

| Tool | Description |
|------|-------------|
| `policy_register` | Compile and register an NL policy |
| `policy_list` | List registered policy names |
| `policy_remove` | Remove a named policy |
| `policy_evaluate` | Evaluate actor+tool against a policy |
| `interface_register` | Register an Interface Descriptor |
| `interface_list` | List registered Interface CIDs |

Key implementation details:

- Uses `DecisionObject.decision` (not `.verdict`) — the spec field is `decision`.
- `InterfaceDescriptor` requires `namespace` arg; `policy_management_tool.py` defaults
  `namespace=name`.
- `IntentObject` requires `(interface_cid, tool, input_cid)` positional args.

### 3 — Risk from EventDAG ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/risk_scorer.py`

Added `risk_score_from_dag(dag, tool_name, *, rollback_penalty, error_penalty,
max_penalty)`:

- Counts rollback events (`output_cid` contains `"rollback"`) and error events
  (`receipt_cid` is empty) in the DAG's `_nodes` dict.
- Returns a float penalty in `[0, max_penalty]` (default max 0.50).
- Conservative: counts all events across the DAG (not per-tool filtered) since
  `intent_cid` is an opaque hash; callers can pre-filter the DAG for per-tool
  isolation.

### 4 — Pubsub Integration ✅ COMPLETE

**File:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

Added:

- **`PubSubEventType`** — `str` Enum with the 4 canonical topic names from
  `MCP_P2P_PUBSUB_TOPICS`: `INTERFACE_ANNOUNCE`, `RECEIPT_DISSEMINATE`,
  `DECISION_DISSEMINATE`, `SCHEDULING_SIGNAL`.
- **`PubSubBus`** — In-process pubsub bus mirroring the libp2p GossipSub API:
  `subscribe(topic, handler)`, `unsubscribe(topic, handler)`, `publish(topic,
  payload)`, `topic_count(topic)`, `clear(topic?)`.
  - Deduplicates handlers (same handler + topic = registered once).
  - Handles both raw `str` topic names and `PubSubEventType` values.
  - Returns handler notification count from `publish()`.

### 5 — Coverage Hardening ✅ COMPLETE

**File:** `tests/mcp/unit/test_mcplusplus_spec_session55.py`

57 new tests covering all items above.

---

## Cumulative MCP++ Status

| Component | Module | Sessions |
|-----------|--------|---------|
| Profile A — MCP-IDL | `interface_descriptor.py` | 50 |
| Profile B — CID-Native Artifacts | `cid_artifacts.py` | 50 |
| Profile C — UCAN Delegation | `ucan_delegation.py` | 53 |
| Profile D — Temporal Deontic Policy | `temporal_policy.py` | 50 |
| Profile E — P2P Transport | `mcp_p2p_transport.py` | 54/55 |
| Event DAG | `event_dag.py` | 50 |
| Risk Scoring | `risk_scorer.py` | 53/55 |
| Compliance | `compliance_checker.py` | 53 |
| HTM Schema CID | `hierarchical_tool_manager.py` | 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | 54 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | 51/52 |
| Server pipeline gate | `server.py` | **55** |
| Policy MCP tools | `policy_management_tool.py` | **55** |
| Pubsub bus | `mcp_p2p_transport.py` | **55** |

**All 8 spec chapters + integration layer are now implemented.**  
**384 spec tests pass (sessions 50–55).**

---

## Next Steps (Session 56+)

1. **Async tool registration** — Make `register_tools()` policy block async-safe
   (policy compilation currently happens synchronously).
2. **Persistent policy store** — Add a file-backed or IPFS-backed
   `PolicyRegistry` that survives server restarts.
3. **PubSubBus ↔ P2PServiceManager bridge** — Connect `PubSubBus.publish()`
   to the real `P2PServiceManager` announcement hooks in `p2p_service_manager.py`.
4. **Pipeline metrics** — Feed `DispatchPipeline` stage denials back into
   `monitoring.py` for observability.
5. **DID key manager integration** — Connect `did_key_manager.py` to
   `ucan_delegation.py` so delegations can be signed with real Ed25519 keys.
