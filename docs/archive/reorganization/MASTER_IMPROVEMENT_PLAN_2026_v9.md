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
| Profile C — UCAN Capability Delegation | `docs/spec/ucan-delegation.md` | ✅ Session 53 |
| Profile D — Temporal Deontic Policy | `docs/spec/temporal-deontic-policy.md` | ✅ Session 50 |
| Event DAG, Concurrency, Ordering | `docs/spec/event-dag-ordering.md` | ✅ Session 50 |
| Risk Scoring & Scheduling | `docs/spec/risk-scheduling.md` | ✅ Session 53 |
| Compliance Checking | (compliance rules) | ✅ Session 53 |
| HTM Schema CID + Trace Dispatch | (HTM extensions) | ✅ Session 53 |
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

### P5 — Profile C: UCAN Capability Delegation ✅ COMPLETE (Session 53)

**Module:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`

Implements capability token chains for delegable execution authority:

- `Capability(resource, ability)` — wildcard `"*"` on both dimensions
- `Delegation(cid, issuer, audience, capabilities, expiry, proof_cid, signature)`
- `DelegationEvaluator` — `build_chain(leaf_cid)` root-first traversal; `can_invoke()` with expiry + capability + actor checks; cycle detection
- `InvocationContext(intent_cid, ucan_proofs, policy_cid, context_cids)` — spec invocation shape
- Global singleton helpers: `get_delegation_evaluator()`, `add_delegation()`, `get_delegation()`

---

### P6 — Risk Scoring and Scheduling ✅ COMPLETE (Session 53)

**Module:** `ipfs_datasets_py/mcp_server/risk_scorer.py`

Lightweight risk scoring pipeline derived from tool + actor signals:

- `RiskLevel` enum: NEGLIGIBLE / LOW / MEDIUM / HIGH / CRITICAL with `from_score()` thresholds
- `RiskScore(level, score, factors, mitigation_hints)` — full audit trail
- `RiskScoringPolicy(tool_risk_overrides, default_risk, actor_trust_levels, max_acceptable_risk)`
- `RiskScorer.score_intent()` — combines base tool risk × actor trust attenuation + param complexity penalty
- `is_acceptable()` / `score_and_gate()` — decision objects for dispatch gating
- `make_default_risk_policy()` convenience

---

### P6b — Compliance Checking ✅ COMPLETE (Session 53)

**Module:** `ipfs_datasets_py/mcp_server/compliance_checker.py`

Rule-based compliance engine with 6 built-in rules:

- `tool_name_convention` — enforces `^[a-z][a-z0-9_]*$`
- `intent_has_actor` — warns when actor is absent
- `actor_is_valid` — rejects actors with whitespace
- `params_are_serializable` — warns on non-JSON params
- `tool_not_in_deny_list` — configurable deny-list
- `rate_limit_ok` — stub for future rate limiting

---

### P6c — HTM Schema CID + Trace Dispatch ✅ COMPLETE (Session 53)

**HierarchicalToolManager additions:**

- `get_tool_schema_cid(category, tool_name)` — CIDv1 (dag-cbor/sha2-256) of tool schema
- `dispatch_with_trace(category, tool_name, params)` — result + execution trace dict with `tool_schema_cid`, `category`, `tool`, `dispatch_status`

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
| **Session 51** | **67** | **~358** |
| **Session 52** | **0** (refactor only) | **~358** |
| **Session 53** | **96** | **~454** |

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

## Next Steps (Session 54+)

1. **P7** — Formal `mcp+p2p` transport ID documentation
2. **Integration** — Wire `PolicyEvaluator` + `UCANPolicyGate` + `RiskScorer` + `ComplianceChecker` into `server.py` dispatch path
3. **NL→UCAN** — Connect `nl_ucan_policy.py` `UCANPolicyGate` to use `ucan_delegation.py` `DelegationEvaluator` for richer chain-based authorization
4. **Exposure** — Register `InterfaceRepository` endpoints as MCP tools
5. **Coverage** — Add more edge-case tests for temporal boundary conditions
6. **Risk from EventDAG** — Feed `event_dag.py` rollback/dispute counts into `risk_scorer.py` policy
