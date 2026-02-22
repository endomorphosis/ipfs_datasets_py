# Master Improvement Plan 2026 — v9: MCP++ Spec Alignment

**Created:** 2026-02-22 (Session 50)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v8.md](MASTER_IMPROVEMENT_PLAN_2026_v8.md)

---

## Overview

This document defines Phase P (MCP++ spec alignment): a set of new modules that
align `ipfs_datasets_py/mcp_server` with the optional-but-backward-compatible
**MCP++** execution profiles defined at the `Mcp-Plus-Plus` reference repository.

MCP++ core design stance:
- **Do not break MCP** — keep MCP JSON-RPC message semantics intact.
- Add functionality via **profile negotiation** and **wrapping/enveloping**.
- Make artifacts **content-addressed (CID-native)** for verifiable, immutable provenance.

---

## Spec Reference Summary

| Profile | Spec Document | Status |
|---------|---------------|--------|
| Profile A — MCP-IDL (Interface Contracts) | `docs/spec/mcp-idl.md` | ✅ Session 50 |
| Profile B — CID-Native Execution Artifacts | `docs/spec/cid-native-artifacts.md` | ✅ Session 50 |
| Profile C — UCAN Capability Delegation | `docs/spec/ucan-delegation.md` | 🔲 Future |
| Profile D — Temporal Deontic Policy | `docs/spec/temporal-deontic-policy.md` | ✅ Session 50 |
| Event DAG, Concurrency, Ordering | `docs/spec/event-dag-ordering.md` | ✅ Session 50 |
| Risk Scoring & Scheduling | `docs/spec/risk-scheduling.md` | 🔲 Future |
| Profile E — P2P Transport Binding | `docs/spec/transport-mcp-p2p.md` | 🔲 Partial (p2p_service_manager.py) |

---

## Phase P: MCP++ Spec Alignment

### P1 — Profile A: MCP-IDL ✅ COMPLETE (Session 50)

**Module:** `ipfs_datasets_py/mcp_server/interface_descriptor.py`

Implements the CID-addressed interface contract system (runtime-queryable,
hash-stable, toolset-sliceable):

- `InterfaceDescriptor` — normative descriptor object with required fields:
  `name`, `namespace`, `version`, `methods[]`, `errors[]`, `requires[]`, `compatibility`
- `MethodSignature` — per-method input/output schema container
- `CompatibilityInfo` — `compatible_with[]` / `supersedes[]` metadata
- `InterfaceRepository` — in-process registry implementing:
  - `interfaces/list` → `list()`
  - `interfaces/get` → `get(interface_cid)`
  - `interfaces/compat` → `check_compat(interface_cid, local_capabilities)`
  - `interfaces/select` → `toolset_slice(semantic_tags, budget, required_capabilities)`
- `CompatVerdict` — structured compat result (`compatible`, `reasons`, `requires_missing`, `suggested_alternatives`)

**Tests:** 17 tests in `test_mcplusplus_spec_session50.py`

---

### P2 — Profile B: CID-Native Execution Artifacts ✅ COMPLETE (Session 50)

**Module:** `ipfs_datasets_py/mcp_server/cid_artifacts.py`

Implements the CID-native artifact objects used by all MCP++ profiles:

- `artifact_cid(obj)` — canonical JSON → SHA-256 → `"bafy-mock-<hex>"` CID helper
- `IntentObject` — pre-execution "what I plan to do" (→ `intent_cid`)
- `DecisionObject` — policy evaluation result (→ `decision_cid`)
- `ReceiptObject` — immutable execution outcome for audit/disputes (→ `receipt_cid`)
- `ExecutionEnvelope` — pre/post-execution CID bundle (→ `envelope_cid`)
- `EventNode` — single Event DAG node linking the above (→ `event_cid`)

**Tests:** 26 tests in `test_mcplusplus_spec_session50.py`

---

### P3 — Profile D: Temporal Deontic Policy Evaluation ✅ COMPLETE (Session 50)

**Module:** `ipfs_datasets_py/mcp_server/temporal_policy.py`

Implements the runtime policy evaluation engine:

- `PolicyClause` — single deontic clause: `"permission"` / `"prohibition"` / `"obligation"`
  with temporal validity bounds (`valid_from`, `valid_until`, `obligation_deadline`)
- `PolicyObject` — content-addressed policy container (→ `policy_cid`)
- `make_simple_permission_policy(actor, action, ...)` — factory for test/simple scenarios
- `PolicyEvaluator.evaluate(intent, policy, ...)` — produces `DecisionObject` with:
  - verdict: `"allow"` / `"deny"` / `"allow_with_obligations"`
  - wildcard `"*"` actor and action matching
  - temporal validity enforcement (past `valid_until` → deny; future `valid_from` → deny)
  - prohibition short-circuits to deny
  - obligation accumulation when permission + obligation both match

**Tests:** 18 tests in `test_mcplusplus_spec_session50.py`

---

### P4 — Event DAG, Concurrency, and Ordering ✅ COMPLETE (Session 50)

**Module:** `ipfs_datasets_py/mcp_server/event_dag.py`

Implements the append-only, content-addressed execution history:

- `EventDAG` — the DAG container:
  - `append(node)` — idempotent, returns `event_cid`; strict mode validates parents
  - `get(event_cid)` — node retrieval
  - `frontier()` — leaf nodes (no children); represents current state
  - `walk(event_cid)` — topological BFS walk to roots (deduplicated)
  - `descendants(event_cid)` — all nodes appended after a given node (for rollback)
  - `rollback_to(event_cid)` — alias for `descendants()`
  - `are_concurrent(cid_a, cid_b)` — partial order: concurrent if neither is an ancestor
- `build_linear_dag(nodes)` — convenience helper for single-agent scenarios

**Tests:** 20 tests in `test_mcplusplus_spec_session50.py`

---

### P5 — Profile C: UCAN Capability Delegation 🔲 FUTURE

**Target module:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Implements capability token chains for delegable execution authority.

Blocked on: UCAN library selection and crypto primitive availability in the
target deployment environment.  The `requires[]` field in `InterfaceDescriptor`
and `proofs_checked[]` / `proof_cid` in artifacts already reserve the namespace.

---

### P6 — Risk Scoring and Scheduling 🔲 FUTURE

**Target module:** `ipfs_datasets_py/mcp_server/risk_scheduler.py`

Implements peer reputation and priority scheduling derived from the Event DAG:
- Risk metrics from `decision_cid` violation history
- Fibonacci-heap-inspired priority queue
- Locality-sensitive grouping for neighbourhood consensus

---

### P7 — Profile E: P2P Transport Baseline Compliance 🔲 PARTIAL

**Existing:** `p2p_service_manager.py`, `p2p_mcp_registry_adapter.py`, `register_p2p_tools.py`

Alignment gaps vs. `transport-mcp-p2p.md` spec:
- [ ] Explicit libp2p protocol ID `/mcp+p2p/1.0.0`
- [ ] Length-prefixed message framing documentation
- [ ] Maximum frame size policy
- [ ] Rate limiting / per-peer quota documentation
- [ ] Pubsub topic documentation for receipt/decision dissemination

---

## Test Summary

| Session | Tests Added | Cumulative |
|---------|-------------|------------|
| Session 45–49 | 86+33+13+… | ~200 |
| **Session 50** | **91** | **~291** |

All 91 new tests pass; 33 pre-existing session tests still pass.

---

## Architecture Notes

The four new modules form a clean dependency chain:

```
interface_descriptor.py   ← Profile A (no mcp_server deps)
        │
        ▼
cid_artifacts.py          ← Profile B (uses hashlib + json only)
        │
        ▼
temporal_policy.py        ← Profile D (imports DecisionObject, IntentObject from cid_artifacts)
        │
        ▼
event_dag.py              ← DAG (imports EventNode from cid_artifacts)
```

All modules are stdlib-only (no external deps beyond Python 3.12+), making them
safe to import in any deployment context.

---

## Next Steps (Session 51+)

1. **P5** — UCAN delegation stubs with pluggable verifier interface
2. **P6** — Risk scorer reading from EventDAG  
3. **P7** — Formal `mcp+p2p` transport ID documentation
4. **Integration** — Wire `PolicyEvaluator` into `server.py` dispatch path
5. **Exposure** — Register `InterfaceRepository` endpoints as MCP tools
6. **Coverage** — Add more edge-case tests for temporal boundary conditions
