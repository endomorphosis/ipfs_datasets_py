# ADR-006: MCP++ Specification Alignment

**Date:** 2026-02-22  
**Status:** Accepted  
**Branch:** `copilot/create-refactoring-plan-again`  
**Spec source:** https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md  

---

## Context

The `MASTER_IMPROVEMENT_PLAN_2026_v10.md` tasked further coverage improvement of
the MCP server modules.  Simultaneously the problem statement requested alignment
with the MCP++ specification published at
`github.com/endomorphosis/Mcp-Plus-Plus`.  

The spec defines five optional, backward-compatible execution profiles:

| Profile | Spec chapter | Description |
|---------|-------------|-------------|
| A | `mcp-idl.md` | CID-Addressed Interface Contracts |
| B | `cid-native-artifacts.md` | CID-Native Execution Artifacts |
| C | `ucan-delegation.md` | Capability Delegation (UCAN) |
| D | `temporal-deontic-policy.md` | Temporal Deontic Policy Evaluation |
| E | `transport-mcp-p2p.md` | `mcp+p2p` Transport Binding |

The existing `mcplusplus/` directory already implements Profile E (P2P transport,
peer registry, task queue, workflow DAG) as thin wrappers around
`ipfs_accelerate_py.mcplusplus_module`.  Profiles A, B, and D had no
counterpart in this repo.

---

## Decision

### 1. Implement Profile A — MCP-IDL (`interface_descriptor.py`)

- `InterfaceDescriptor` dataclass with required fields from §4.1 and recommended
  from §4.2.
- `canonical_bytes()` → deterministic UTF-8 JSON (sorted keys) → `interface_cid`
  via `sha256:<hex>` (spec-compatible, no external deps).
- `InterfaceRepository` exposes the three mandatory APIs from §5:
  `list()`, `get(cid)`, `compat(cid, required_cid=…)`.
- Optional `select(task_hint, budget)` from §6 implemented via semantic-tag overlap.
- Module-level singleton via `get_interface_repository()`.

### 2. Implement Profile B — CID-Native Artifacts (`cid_artifacts.py`)

Five artifact types from spec §3–§7:

| Class | spec ref |
|-------|----------|
| `IntentObject` | §4 |
| `DecisionObject` | §5 |
| `ReceiptObject` | §6 |
| `ExecutionEnvelope` | §2 |
| `EventNode` | §7 |

Each computes a `.cid` property lazily from `canonical_bytes()`.  All CIDs are
stable across process restarts for the same logical content.

### 3. Implement Profile D — Temporal Deontic Policy (`temporal_policy.py`)

- `PolicyClause` with `clause_type` (permission / prohibition / obligation),
  `actor`, `action`, `resource`, and temporal bounds (`valid_from`, `valid_until`).
- `PolicyObject` → `policy_cid` + `get_permissions/prohibitions/obligations()`.
- `PolicyEvaluator.evaluate(intent, policy_cid)` →
  * check prohibitions first (deny wins),
  * then permissions (closed-world: no match → deny),
  * collect matched obligations → `ALLOW_WITH_OBLIGATIONS` if any, else `ALLOW`.
- `make_simple_permission_policy()` convenience helper.
- Module-level singleton via `get_policy_evaluator()`.

### 4. Backward Compatibility

- No existing MCP JSON-RPC message formats were changed.
- All three new modules are **optional imports**; production code is unaffected
  if they are not used.
- The `mcplusplus/` wrappers for Profile E (P2P transport) are unchanged.

### 5. Not Implemented (deferred)

| Profile | Reason for deferral |
|---------|---------------------|
| C (UCAN) | Requires a third-party UCAN library; deferred to a future ADR |
| E (full libp2p wire) | `mcplusplus/` wrappers already exist; full wire conformance requires a live p2p node |
| Canonicalization test vectors | Deferred — spec §14 lists this as an open question |

---

## Consequences

**Positive:**
- Repository now has concrete implementations of Profiles A, B, D — the three
  that can be implemented without external dependencies.
- 68 new tests validate each artifact class, the repository APIs, the policy
  evaluator, and an end-to-end intent → decision → receipt → event DAG chain.
- The `interface_descriptor.py` module can be hooked into `hierarchical_tool_manager.py`
  to produce CID-addressed tool schemas (future work).

**Neutral:**
- `sha256:<hex>` CIDs are not multihash-compliant CIDv1 strings; they are
  intentionally simple until a multiformats dependency is approved.

**Negative / Risks:**
- The closed-world permission model in `PolicyEvaluator` may be too strict for
  some use cases; a future ADR may introduce an open-world option.
- Wildcard actor (`"*"`) matching is non-normative; will need review against the
  UCAN spec when Profile C lands.

---

## References

- MCP++ overview: `docs/architecture/overview.md`
- Spec chapters: `docs/spec/mcp-idl.md`, `cid-native-artifacts.md`,
  `temporal-deontic-policy.md`, `transport-mcp-p2p.md`
- New modules: `interface_descriptor.py`, `cid_artifacts.py`, `temporal_policy.py`
- Tests: `tests/mcp/unit/test_mcplusplus_spec_v11.py`
