# Master Improvement Plan 2026 — v10: MCP++ Spec — Transport + Integrated Dispatch

**Created:** 2026-02-22 (Session 54)  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Reference:** https://github.com/endomorphosis/Mcp-Plus-Plus  
**Supersedes:** [MASTER_IMPROVEMENT_PLAN_2026_v9.md](MASTER_IMPROVEMENT_PLAN_2026_v9.md)

---

## Overview

Session 54 completes the remaining "Next Steps" items from v9:

1. **P7** — Profile E: `mcp+p2p` transport binding constants and helpers.
2. **Integration** — Composable dispatch pipeline wiring all MCP++ profiles.
3. **NL→UCAN chain** — `PipelineIntent` bridges NL-UCAN gate to delegation.

---

## Session 54 Changes

### P7 — Profile E: `mcp+p2p` Transport Binding ✅ COMPLETE

**Module:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py`

Implements the carriage constants and helpers from
`docs/spec/transport-mcp-p2p.md`:

- **Normative constants:**
  - `MCP_P2P_PROTOCOL_ID = "/mcp+p2p/1.0.0"` — canonical libp2p stream protocol ID
    (Section 3.1.1)
  - `MCP_P2P_SESSION_PROTOCOL_ID`, `MCP_P2P_EVENTS_PROTOCOL_ID` — sub-protocols
  - `DEFAULT_MAX_FRAME_BYTES = 16 MiB`, `MIN_MAX_FRAME_BYTES = 1 MiB`
  - `MCP_P2P_PUBSUB_TOPICS` — 4 topic names for event dissemination
    (Section 6)

- **`P2PSessionState`** — 6-state lifecycle enum (DISCONNECTED → CONNECTING →
  HANDSHAKING → ACTIVE → CLOSING → CLOSED) (Section 3.2)

- **`MCPMessage`** — lightweight JSON-RPC wrapper with `to_bytes()`/`from_bytes()`,
  `is_request()`/`is_notification()`/`is_response()` type checks

- **`LengthPrefixFramer`** — implements the u32 big-endian length prefix framing
  recommended in Section 5.1:
  - `encode(message)` → `<4-byte header><JSON body>`
  - `decode_header(bytes)` → declared body length
  - `decode_body(bytes)` → MCPMessage
  - `decode(frame)` → MCPMessage (complete round-trip)
  - `FrameTooBigError` for frames exceeding `max_frame_bytes`

- **`P2PSessionConfig`** — per-session configuration dataclass with `make_framer()`
  factory

- **`TokenBucketRateLimiter`** — simple token-bucket stub implementing the
  "peers SHOULD rate-limit incoming messages" recommendation (Section 7)

### Integration — Composable Dispatch Pipeline ✅ COMPLETE

**Module:** `ipfs_datasets_py/mcp_server/dispatch_pipeline.py`

Wires all MCP++ execution profiles into a single, opt-in pre-dispatch
pipeline:

```
DispatchPipeline.check(intent)
    │
    ├── Stage 1: Compliance (ComplianceChecker)
    ├── Stage 2: Risk scoring (RiskScorer)
    ├── Stage 3: UCAN delegation (DelegationEvaluator)
    ├── Stage 4: Temporal deontic policy (PolicyEvaluator)
    └── Stage 5: NL-UCAN gate (UCANPolicyGate)
```

- **`PipelineIntent`** — unified intent dataclass with:
  - `tool_name` + `tool` (alias) — bridges temporal_policy and compliance_checker
  - `actor` — used by compliance, policy, delegation, nl_ucan_gate stages
  - `params` — used by compliance params_are_serializable rule
  - `intent_cid` — SHA-256-based CID computed in `__post_init__`
  - `get(field, default)` — dict-style accessor for risk_scorer

- **`PipelineConfig`** — all-disabled-by-default config (opt-in stages);
  accepts pre-built checker/scorer/evaluator instances

- **`DispatchPipeline`** — main pipeline class:
  - `check(intent)` → `PipelineResult` (short-circuits on first denial)
  - `record_execution(intent, result, error)` → `ReceiptObject` + DAG append
  - `attach_event_dag(dag)` — connects execution history

- **`PipelineResult`** — aggregated result with:
  - `allowed: bool`, `verdict: str`
  - `stage_outcomes: list[StageOutcome]`
  - `blocking_stage: PipelineStage | None`
  - `to_dict()` — JSON-serialisable representation

- **`make_default_pipeline()`** — fully pass-through (all stages disabled)
- **`make_full_pipeline(**kwargs)`** — all stages enabled with optional DI

### Test Coverage

| Module | Tests | Coverage |
|--------|-------|----------|
| `mcp_p2p_transport.py` | 37 new tests | ~90% |
| `dispatch_pipeline.py` | 36 new tests | ~85% |

All 360 session 45-54 tests pass.

---

## Cumulative MCP++ Spec Status

| Profile | Module(s) | Status |
|---------|-----------|--------|
| A — MCP-IDL | `interface_descriptor.py` | ✅ Session 50 |
| B — CID-Native Artifacts | `cid_artifacts.py` | ✅ Session 50 |
| C — UCAN Delegation | `ucan_delegation.py` | ✅ Session 53 |
| D — Temporal Deontic Policy | `temporal_policy.py` | ✅ Session 50 |
| E — P2P Transport | `mcp_p2p_transport.py` | ✅ Session 54 |
| Event DAG | `event_dag.py` | ✅ Session 50 |
| Risk Scoring | `risk_scorer.py` | ✅ Session 53 |
| Compliance | `compliance_checker.py` | ✅ Session 53 |
| HTM Schema CID | `hierarchical_tool_manager.py` | ✅ Session 53 |
| Integrated Pipeline | `dispatch_pipeline.py` | ✅ Session 54 |
| NL→UCAN Policy Gate | `nl_ucan_policy.py` | ✅ Session 51/52 |

**All 8 spec chapters are now implemented.**

---

## Next Steps (Session 55+)

1. **server.py integration** — Plumb `DispatchPipeline` into `server.py`
   `handle_tool_call()` path as an opt-in gate.
2. **MCP tool exposure** — Register `InterfaceRepository` and `PolicyRegistry`
   endpoints as MCP tools so AI agents can query/manage policies.
3. **Risk from EventDAG** — Feed `event_dag.py` rollback/dispute counts into
   `risk_scorer.py` per-tool risk overrides.
4. **Pubsub integration** — Connect `mcp_p2p_transport.py` pubsub topics to
   `p2p_service_manager.py` announcement hooks.
5. **Coverage hardening** — Add edge-case tests for temporal boundary conditions,
   token bucket refill scheduling, and delegation cycle detection.
