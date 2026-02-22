# MCP Server — Master Improvement Plan v11.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions X81 + X82 + W79 + V78 + AA85 + AB86 + AC87 + AD88 COMPLETE**  
**Branch:** `copilot/create-refactoring-plan-again`  
**Spec alignment:** https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md  
**Preconditions:** All v10 phases ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v10.md](MASTER_IMPROVEMENT_PLAN_2026_v10.md))

**Baseline (as of 2026-02-22 v11 start):**
- 2,197 MCP unit tests passing · 0 failing (from v10 grand total)
- All v10 sessions S71–U76 complete (98 new tests)

---

## MCP++ Specification Alignment

The v11 plan was updated to align with the **MCP++ specification** published at
[github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md](https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md).

The spec defines five optional execution profiles. Here is the mapping to this
repository:

| Profile | Spec Chapter | Status | Implementation |
|---------|-------------|--------|---------------|
| A: MCP-IDL | `mcp-idl.md` | ✅ **New module** | `interface_descriptor.py` |
| B: CID-Native Artifacts | `cid-native-artifacts.md` | ✅ **New module** | `cid_artifacts.py` |
| C: UCAN Delegation | `ucan-delegation.md` | ⏳ Deferred | External lib needed |
| D: Temporal Deontic Policy | `temporal-deontic-policy.md` | ✅ **New module** | `temporal_policy.py` |
| E: P2P Transport | `transport-mcp-p2p.md` | ✅ Existing | `mcplusplus/` wrappers |

See [ADR-006-mcp++-alignment.md](docs/adr/ADR-006-mcp++-alignment.md) for full rationale.

---

## Phase X — monitoring + p2p_service_manager (Sessions X81, X82)

### Session X81: monitoring._check_alerts threshold tests ✅ Complete

**File:** `tests/mcp/unit/test_coverage_v11_session81_82.py` — **16 tests**

#### TestCheckAlertsCpu (5 tests):
- Below threshold → no alert
- Above threshold → `cpu_high` alert appended
- Alert has `severity='warning'`
- Alert has `timestamp` key
- At-threshold boundary → no alert (strict `>`)

#### TestCheckAlertsMemory (3 tests):
- Above threshold → `memory_high` alert
- Below threshold → no alert
- Alert severity is `warning`

#### TestCheckAlertsErrorRate (3 tests):
- Above 5% → `error_rate_high` alert
- Alert severity is `critical`
- Below threshold → no alert

#### TestCheckAlertsResponseTime (3 tests):
- Above 5000 ms → `response_time_high` alert
- Alert severity is `warning`
- Below threshold → no alert

#### TestCheckAlertsAllFour (2 tests):
- All four thresholds breached simultaneously → exactly `{cpu_high, memory_high, error_rate_high, response_time_high}`
- All healthy → `alerts == []`

### Session X82: p2p_service_manager.stop() error paths ✅ Complete

**File:** `tests/mcp/unit/test_coverage_v11_session81_82.py` — **8 tests**

- No runtime → returns `True` immediately
- Success path → returns `True`
- `P2PServiceError` in `stop()` → returns `False`, calls `_restore_env`
- Generic exception in `stop()` → returns `False`, calls `_restore_env`
- `runtime.stop()` returns `False` → `stop()` returns `False`
- `_cleanup_mcplusplus_features` called before `stop()`

---

## Phase W — server init (Session W79)

### Session W79: server._initialize_mcp_server + _initialize_p2p_services ✅ Complete

**File:** `tests/mcp/unit/test_coverage_v11_session79_78.py` — **9 tests**

#### TestInitializeMCPServer (4 tests):
- `FastMCP` available → `_fastmcp_available=True`, `mcp` set
- `FastMCP=None` → `_fastmcp_available=False`, `mcp=None`
- `_fastmcp_available` flag correctly set
- FastMCP called with `'ipfs_datasets'` name

#### TestInitializeP2PServices (5 tests):
- `P2PServiceError` → `p2p=None`
- `ConfigurationError` → `p2p=None`
- Generic exception → `p2p=None`
- Success path → `p2p` manager instance set
- Module import failure (None) → `p2p=None`

---

## Phase V — enterprise_api factory (Session V78)

### Session V78: create_enterprise_api + start_enterprise_server ✅ Complete

**File:** `tests/mcp/unit/test_coverage_v11_session79_78.py` — **7 tests**

#### TestCreateEnterpriseApi (4 tests):
- Returns `EnterpriseGraphRAGAPI` instance
- Singleton — second call returns same instance
- Accepts `config` dict
- Instance has `app` attribute

#### TestStartEnterpriseServer (3 tests):
- Calls `uvicorn.Config` + `uvicorn.Server.serve()`
- Passes `host` and `port` to uvicorn Config
- Reuses existing `api_instance`

---

## Phase AA — Profile A: MCP-IDL (Session AA85)

### Session AA85: interface_descriptor.py — MCP-IDL Profile A ✅ Complete

**New module:** `ipfs_datasets_py/mcp_server/interface_descriptor.py`  
**File:** `tests/mcp/unit/test_mcplusplus_spec_v11.py` — **25 tests**

Key design (aligned to spec §2–§6):
- `_canonicalize()` → deterministic UTF-8 JSON (sorted keys)
- `compute_cid(bytes)` → `sha256:<hex>` identifier
- `InterfaceDescriptor` with all required (§4.1) and recommended (§4.2) fields
- `interface_cid` lazily computed from `canonical_bytes()`
- `to_dict()` / `from_dict()` roundtrip preserves CID
- `InterfaceRepository`: `register()`, `list()`, `get()`, `compat()`, `select()`
- Module-level singleton `get_interface_repository()`

#### TestComputeCid (4 tests):
#### TestInterfaceDescriptor (8 tests):
#### TestInterfaceRepository (11 tests + global singleton):

---

## Phase AB — Profile B: CID-Native Artifacts (Session AB86)

### Session AB86: cid_artifacts.py — Profile B ✅ Complete

**New module:** `ipfs_datasets_py/mcp_server/cid_artifacts.py`  
**File:** `tests/mcp/unit/test_mcplusplus_spec_v11.py` — **22 tests**

Key design (aligned to spec §2–§7):
- `IntentObject`: `tool`, `input_cid`, `interface_cid`, `constraints_policy_cid`, `correlation_id`, `declared_side_effects` → `.cid`
- `DecisionObject`: `decision` (allow/deny/allow_with_obligations), `intent_cid`, `policy_cid`, `proofs_checked`, `obligations` → `.cid`, `.is_allowed`
- `ReceiptObject`: `intent_cid`, `output_cid`, `decision_cid`, `observed_side_effects` → `.cid`
- `ExecutionEnvelope`: full MCP invocation wrapper (Profile B §2); `is_complete()`, `from_dict()`
- `EventNode`: DAG node linking all artifacts with `parents[]` causal chain
- `artifact_cid(data)`: convenience helper

---

## Phase AC — Profile D: Temporal Deontic Policy (Session AC87)

### Session AC87: temporal_policy.py — Profile D ✅ Complete

**New module:** `ipfs_datasets_py/mcp_server/temporal_policy.py`  
**File:** `tests/mcp/unit/test_mcplusplus_spec_v11.py` — **18 tests**

Key design (aligned to spec §2–§7):
- `PolicyClause`: `clause_type` (permission/prohibition/obligation), `actor`, `action`, temporal bounds, `is_temporally_valid(t)`
- `PolicyObject`: `policy_cid` + `get_permissions/prohibitions/obligations()`
- `PolicyEvaluator.evaluate(intent, policy_cid)`:
  1. Check prohibitions first (deny wins)
  2. Check permissions — no match → deny (closed-world)
  3. Collect matched obligations → `ALLOW_WITH_OBLIGATIONS` / `ALLOW`
- `make_simple_permission_policy()` helper
- Module-level singleton `get_policy_evaluator()`

---

## Phase AD — P2P Transport Alignment (Session AD88)

### Session AD88: P2P / integration alignment ✅ Complete

**File:** `tests/mcp/unit/test_mcplusplus_spec_v11.py` — **8 tests**

- Profile E (`mcplusplus/` wrappers) already covers P2P transport substrate
- New tests verify all three new spec modules import cleanly
- End-to-end chain: intent → policy evaluation → decision → receipt → event DAG

---

## Summary — v11 Sessions

| Session | Target | File | Tests | Status |
|---------|--------|------|-------|--------|
| X81 | `monitoring._check_alerts` | `test_coverage_v11_session81_82.py` | 16 | ✅ |
| X82 | `p2p_service_manager.stop()` | `test_coverage_v11_session81_82.py` | 8 | ✅ |
| W79 | `server._initialize_*` | `test_coverage_v11_session79_78.py` | 9 | ✅ |
| V78 | Enterprise API factory | `test_coverage_v11_session79_78.py` | 7 | ✅ |
| AA85 | **Profile A: MCP-IDL** | `test_mcplusplus_spec_v11.py` | 25 | ✅ |
| AB86 | **Profile B: CID artifacts** | `test_mcplusplus_spec_v11.py` | 22 | ✅ |
| AC87 | **Profile D: Temporal policy** | `test_mcplusplus_spec_v11.py` | 18 | ✅ |
| AD88 | **P2P transport alignment** | `test_mcplusplus_spec_v11.py` | 8 | ✅ |
| | ADR-006 alignment doc | `docs/adr/ADR-006-mcp++-alignment.md` | — | ✅ |
| **Total** | | | **113** | ✅ |

**Grand total (all plans):**  
2,197 (through v10) + 113 (v11) = **2,310 MCP unit tests**

---

## Next Steps (v12 candidates)

| Session | Target | Rationale | Spec alignment |
|---------|--------|-----------|----------------|
| AE89 | `interface_descriptor.py` — hook into `hierarchical_tool_manager.py` | Expose CID-addressed tool schemas | Profile A §5 |
| AF90 | `cid_artifacts.py` — `ExecutionEnvelope` wrapping in `dispatch()` | CID-trace every tool invocation | Profile B §2 |
| AG91 | `temporal_policy.py` — `PolicyRegistry` with IPFS persistence | Durable policy store | Profile D §2 |
| AH92 | Profile C (UCAN) stub — `ucan_delegation.py` + 15 tests | Start delegation chain | Profile C |
| AI93 | `fastapi_service.py` — `/datasets/*` inner-module mocked routes | V77 deferred dataset routes | — |
| AJ94 | `monitoring.py` — `_monitoring_loop` complete coverage | X84 deferred | — |
| AK95 | Enterprise analytics full round-trip (Y83) | job submit → process → query | — |
| AL96 | Coverage gap sweep (Z84) — push all modules to ≥90% | Final consolidation | — |
| AM97 | P2P conformance tests aligned to `mcp+p2p` spec §9 interop checklist | Wire-level conformance | Profile E §9 |
