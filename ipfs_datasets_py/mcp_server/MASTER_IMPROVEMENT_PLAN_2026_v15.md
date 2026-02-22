# MCP Server — Master Improvement Plan v15.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions BD114 + BE115 + BF116 + BG117 + BH118 + BL122 + BM123 + Transport-Fix COMPLETE**  
**Branch:** `copilot/create-refactoring-plan-again`  
**Spec alignment:** https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md  
**Preconditions:** All v14 phases ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v14.md](MASTER_IMPROVEMENT_PLAN_2026_v14.md))

**Baseline (as of 2026-02-22 v15 start):**
- 2,884 MCP + logic unit tests passing · 0 failing
- All v14 sessions AT104–BC113 complete

---

## Transport Clarification — gRPC vs MCP+P2P

**User feedback:** "I noticed you are using gRPC transport, I thought we were using mcp+p2p for transport."

**Resolution (implemented in this session):**

- **MCP+P2P is the canonical transport** — `mcp_p2p_transport.py` (Profile E, `/mcp+p2p/1.0.0`)
- **gRPC is an optional secondary bridge** — `grpc_transport.py` was created as a "conformance stub" in AQ101; it is NOT used by any MCP++ pipeline stage
- **Fix applied:** `grpc_transport.py` docstring updated with a prominent `IMPORTANT` note:
  > The canonical MCP transport is MCP+P2P (Profile E).
  > See `mcp_p2p_transport.py` for the primary transport implementation.
  > This module provides an **optional, secondary** gRPC bridge adapter for deployments that also need gRPC connectivity (e.g., bridging to existing gRPC service meshes). It is **not** used by the MCP++ pipeline stages.

### Transport Architecture

```
 MCP Client
     │
     ▼
 /mcp+p2p/1.0.0  ◄── canonical transport  (mcp_p2p_transport.py)
     │
     ├── TokenBucketRateLimiter
     ├── LengthPrefixFramer (u32 big-endian)
     ├── MCPMessage (JSON-RPC 2.0)
     └── PubSubBus → MCP_P2P_PUBSUB_TOPICS

 gRPC (optional)  ◄── secondary bridge     (grpc_transport.py)
     │
     └── GRPCTransportAdapter → HierarchicalToolManager
         (stub; not part of Profile E pipeline)
```

---

## MCP++ Specification Alignment — v15 additions

| Profile | Spec Chapter | Status | Implementation |
|---------|-------------|--------|---------------|
| A: MCP-IDL | `mcp-idl.md` | ✅ | `interface_descriptor.py` |
| B: CID-Native Artifacts | `cid-native-artifacts.md` | ✅ | `cid_artifacts.py` |
| C: UCAN Delegation | `ucan-delegation.md` | ✅ | `ucan_delegation.py` + `DelegationManager` (BH118 ✅) |
| D: Temporal Deontic Policy | `temporal-deontic-policy.md` | ✅ | `temporal_policy.py` |
| E: P2P Transport | `transport-mcp-p2p.md` | ✅ | `mcp_p2p_transport.py` |
| F: Dispatch Pipeline | pipeline §4 | ✅ | `dispatch_pipeline.py` |
| G: Compliance | spec §8 | ✅ | `compliance_checker.py` |
| H: Risk Gate | pipeline risk stage | ✅ | `risk_scorer.py` |
| I: Observability | monitoring spec | ✅ **New** | `audit_metrics_bridge.py` (BG117 ✅) |
| J: NL Conflict Detection | policy §5 | ✅ **New** | `logic/CEC/nl/nl_policy_conflict_detector.py` (BL122 ✅) |

---

## Phase BD114 — DispatchPipeline E2E + BE115 Compliance Integration

### Session BD114/BE115: Full pipeline with real compliance + risk stage handlers ✅ Complete

**Test file:** `tests/mcp/unit/test_v15_sessions.py`

**Key design:**
- `DispatchPipeline` with two real stage handlers:
  1. **compliance stage**: calls `ComplianceChecker.check()`, returns `allowed=False` on failure
  2. **risk stage**: calls `RiskScorer.score_and_gate()`, catches `RiskGateError`
- `short_circuit=True` (default): after compliance denial, risk is skipped
- `short_circuit=False`: risk still runs after compliance denial
- Stage can be disabled mid-test via `pipeline.skip_stage("compliance")`

#### TestDispatchPipelineE2E (8 tests):
- `test_valid_intent_passes_all_stages` — both stages executed, result.allowed=True
- `test_invalid_tool_name_denied_by_compliance` — denied_by == "compliance"
- `test_short_circuit_skips_risk_after_compliance_denial` — "risk" in stages_skipped
- `test_no_short_circuit_runs_all_stages` — risk in stages_executed even after denial
- `test_missing_actor_denied_by_compliance`
- `test_metrics_recorded_per_stage` — total_runs == 2
- `test_make_full_pipeline_allows_safe_intent`
- `test_pipeline_stage_can_be_disabled`

#### TestCompliancePipelineIntegration (4 tests):
- `test_custom_deny_rule_blocks_tool` — add_rule() + pipeline integration
- `test_remove_custom_rule_unblocks`
- `test_fail_fast_stops_at_first_failure`
- `test_compliance_report_to_dict`

---

## Phase BF116 — risk_scorer + mcp_p2p_transport Integration

### Session BF116: Rate-limit per risk level ✅ Complete

**Test file:** `tests/mcp/unit/test_v15_sessions.py`

**Key design:**
- Low risk → high-capacity `TokenBucketRateLimiter(rate=100, capacity=100)`
- High/Critical risk → tight `TokenBucketRateLimiter(rate=0.1, capacity=1)`
- Risk gate blocks before rate limiter is reached for dangerous tools

#### TestRiskRateLimiterIntegration (7 tests):
- `test_low_risk_uses_high_capacity_limiter`
- `test_high_risk_tool_gets_tight_limiter`
- `test_rate_limit_exhaustion_denies_requests`
- `test_risk_score_and_gate_raises_for_dangerous_tool`
- `test_p2p_session_config_makes_limiter`
- `test_risk_level_from_score_mapping` (all 7 thresholds)
- `test_combined_pipeline_risk_rate_limit`

---

## Phase BG117 — AuditMetricsBridge (audit → prometheus)

### Session BG117: PolicyAuditLog → PrometheusExporter ✅ Complete

**New production module:** `ipfs_datasets_py/mcp_server/audit_metrics_bridge.py`

**Key design:**
- `AuditMetricsBridge(audit_log, exporter, *, category="policy")`
- `attach()` — sets `audit_log._sink = self._sink`
- `detach()` — sets `audit_log._sink = None`
- `_sink(entry)` — calls `exporter.record_tool_call(category, tool, status, latency_seconds=0.0)`
- `forwarded_count` tracks total entries forwarded
- `connect_audit_to_prometheus(audit, exporter)` — one-shot convenience

#### TestAuditMetricsBridge (9 tests):
- `test_bridge_attach_sets_sink`
- `test_bridge_forwards_allow_to_exporter`
- `test_bridge_forwards_deny_to_exporter`
- `test_bridge_detach_removes_sink`
- `test_after_detach_records_not_forwarded`
- `test_connect_shorthand_returns_attached_bridge`
- `test_get_info_has_expected_keys`
- `test_multiple_records_counted`
- `test_custom_category_label`

---

## Phase BH118 — DelegationManager Full Lifecycle

### Session BH118: DelegationManager add/invoke/revoke/metrics ✅ Complete

**New production class:** `DelegationManager` in `ipfs_datasets_py/mcp_server/ucan_delegation.py`

**Key design:**
- `DelegationManager(path=None)` — wraps `DelegationStore` + `DelegationEvaluator` + `RevocationList`
- `add(token) → str` — adds token, invalidates evaluator cache
- `remove(cid) → bool` — removes token, invalidates cache
- `get(cid) → Optional[DelegationToken]`
- `list_cids() → List[str]`
- `revoke(cid)` — adds to `RevocationList`
- `revoke_chain(root_cid) → int` — revokes entire chain, returns count revoked
- `is_revoked(cid) → bool`
- `get_evaluator() → DelegationEvaluator` — lazy-cached; rebuilt on add/remove
- `can_invoke(principal, resource, ability, *, leaf_cid, at_time) → Tuple[bool, str]` — also checks revocation
- `save() → str` — persist store; `load() → int` — reload
- `get_metrics() → Dict[str, Any]` — token_count/revoked_count/has_path
- `get_delegation_manager()` — process-global singleton

#### TestDelegationManagerLifecycle (14 tests):
- `test_add_and_list`
- `test_can_invoke_after_add`
- `test_wrong_principal_denied`
- `test_expired_token_denied`
- `test_revoke_denies_subsequent_invoke`
- `test_is_revoked`
- `test_remove_removes_token`
- `test_get_returns_token`
- `test_get_metrics_keys`
- `test_len`
- `test_repr`
- `test_singleton_factory`
- `test_save_and_load`
- `test_evaluator_cache_invalidated_on_add`

---

## Phase BL122 — NLPolicyConflictDetector

### Session BL122: Simultaneous permission + prohibition detection ✅ Complete

**New production module:** `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

**Key design:**
- `NLPolicyConflictDetector(wildcard="*")` — stateless detector
- `detect(clauses) → List[PolicyConflict]`
  - `"simultaneous_perm_prohib"` — same (action, resource) is both permitted and prohibited for overlapping actors
  - `"multiple_obligations"` — same (action, resource, actor) has >1 obligation clause
- `PolicyConflict` — conflict_type / action / resource / actors / clause_types / description / to_dict()
- `detect_conflicts(clauses)` — module-level convenience
- **Wildcard handling:** if either permission or prohibition side has actor="*", it conflicts with all specific actors

#### TestNLPolicyConflictDetector (12 tests):
- `test_no_conflict_when_only_permission`
- `test_no_conflict_when_only_prohibition`
- `test_detects_simultaneous_perm_prohib`
- `test_no_conflict_for_different_actions`
- `test_wildcard_actor_triggers_conflict`
- `test_different_actors_no_conflict`
- `test_detects_duplicate_obligations`
- `test_single_obligation_no_conflict`
- `test_conflict_to_dict_has_expected_keys`
- `test_no_conflict_for_empty_clauses`
- `test_detector_with_real_nl_output` (integration with NLUCANPolicyCompiler)
- `test_description_is_human_readable`

---

## Phase BM123 — CECBridge Coverage

### Session BM123: Statistics + formula hash + strategy selection ✅ Complete

**Test file:** `tests/mcp/unit/test_v15_sessions.py`

#### TestCECBridgeCoverage (8 tests):
- `test_bridge_creates_without_dependencies`
- `test_get_statistics_has_expected_keys`
- `test_formula_hash_is_deterministic`
- `test_formula_hash_distinct_for_different_formulas`
- `test_select_strategy_returns_string`
- `test_prove_string_formula_returns_result`
- `test_prove_caches_result_when_proved`
- `test_prove_no_cache_always_calls_prover`
- `test_unified_proof_result_fields`

---

## Transport Documentation (TestTransportDocumentation — 6 tests)

- `test_mcp_p2p_protocol_id_is_primary` — `/mcp+p2p/1.0.0`
- `test_mcp_p2p_pubsub_topics_present` — all required topics present
- `test_grpc_module_docstring_mentions_mcp_p2p_as_canonical`
- `test_grpc_adapter_is_optional` — `is_running=False`, `GRPC_AVAILABLE` is bool
- `test_grpc_start_raises_without_grpc_package` — `ImportError` with "grpcio" hint
- `test_mcp_message_transport_uses_mcp_p2p_framing` — full LengthPrefixFramer round-trip

---

## Summary — v15 Sessions

| Session | Target | New Tests | Production changes | Status |
|---------|--------|-----------|-------------------|--------|
| BD114/BE115 | Pipeline E2E + compliance integration | 12 | — | ✅ |
| BF116 | Risk + P2P rate-limit integration | 7 | — | ✅ |
| BG117 | `audit_metrics_bridge.py` | 9 | New module | ✅ |
| BH118 | `DelegationManager` in `ucan_delegation.py` | 14 | New class | ✅ |
| BL122 | `nl_policy_conflict_detector.py` | 12 | New module | ✅ |
| BM123 | `cec_bridge.py` coverage | 9 | — | ✅ |
| Transport | gRPC docstring fix + MCP+P2P tests | 6 | `grpc_transport.py` docstring | ✅ |
| **Total** | | **69** | **2 new modules + 1 new class** | ✅ |

**Production files added:**
- `mcp_server/audit_metrics_bridge.py` — BG117: audit→prometheus bridge
- `logic/CEC/nl/nl_policy_conflict_detector.py` — BL122: conflict detection

**Production files modified:**
- `mcp_server/ucan_delegation.py` — BH118: `DelegationManager` class + `get_delegation_manager()`
- `mcp_server/grpc_transport.py` — Transport fix: docstring clarifying gRPC is optional secondary

**Grand total (all plans):**  
2,884 (through v14) + 69 (v15) = **2,953 MCP + logic unit tests** · 8 skip · 0 failing

---

## Next Steps (v16 candidates)

| Session | Target | Rationale | Priority |
|---------|--------|-----------|----------|
| BN124 | `DelegationManager.revoke_chain()` — multi-hop chain test | Test full chain revocation | 🔴 High |
| BO125 | `NLPolicyConflictDetector` integration with `UCANPolicyBridge` | Surface conflicts in bridge | 🔴 High |
| BP126 | `audit_metrics_bridge.py` + live Prometheus integration | Full observability smoke test | 🟡 Med |
| BQ127 | `nl_policy_conflict_detector.py` — i18n conflict detection (French/German/Spanish) | Phase 3c multi-language | 🟡 Med |
| BR128 | `DelegationManager` + `PolicyAuditLog` integration | Audit every can_invoke() call | 🟡 Med |
| BS129 | `dispatch_pipeline.py` + `DelegationManager` stage | Delegation as a pipeline stage | 🟡 Med |
| BT130 | `groth16_ffi.py` circuit_version=2 prove + verify | ZKP Phase 4b | 🟢 Low |
| BU131 | `cec_bridge.py` Z3 mock path full coverage | BM123 follow-up | 🟢 Low |
| BV132 | CI integration — GitHub Actions for logic + mcp tests | Continuous quality | 🟡 Med |
| BW133 | `logic/api.py` DelegationManager + conflict detector exports | Blessed API completeness | 🟡 Med |
