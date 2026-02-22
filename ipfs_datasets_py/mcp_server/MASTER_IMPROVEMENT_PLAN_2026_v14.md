# MCP Server — Master Improvement Plan v14.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions AT104 + AU105 + AV106 + AW107 + AX108 + AY109 + AZ110 COMPLETE**  
**Branch:** `copilot/create-refactoring-plan-again`  
**Spec alignment:** https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md  
**Preconditions:** All v13 phases ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v13.md](MASTER_IMPROVEMENT_PLAN_2026_v13.md))

**Baseline (as of 2026-02-22 v14 start):**
- 2,805 MCP + logic unit tests passing · 0 failing
- All v13 sessions AO99–TDFOL-T2 complete

---

## MCP++ Specification Alignment — v14 additions

| Profile | Spec Chapter | Status | Implementation |
|---------|-------------|--------|---------------|
| A: MCP-IDL | `mcp-idl.md` | ✅ | `interface_descriptor.py` + `toolset_slice()` (AO99 ✅) |
| B: CID-Native Artifacts | `cid-native-artifacts.md` | ✅ | `cid_artifacts.py` + `dispatch_with_trace()` |
| C: UCAN Delegation | `ucan-delegation.md` | ✅ | `ucan_delegation.py` + `DelegationStore` + `RevocationList` |
| D: Temporal Deontic Policy | `temporal-deontic-policy.md` | ✅ | `temporal_policy.py` + `PolicyRegistry` + caches |
| E: P2P Transport | `transport-mcp-p2p.md` | ✅ **New module** | `mcp_p2p_transport.py` (AT104-AU105 ✅) |
| F: Dispatch Pipeline | pipeline spec §4 | ✅ **New module** | `dispatch_pipeline.py` (AT104 ✅) |
| G: Compliance | spec §8 | ✅ **New module** | `compliance_checker.py` (AV106 ✅) |
| H: Risk Gate | pipeline risk stage | ✅ **New module** | `risk_scorer.py` (AW107 ✅) |

---

## Phase AT104 — DispatchPipeline + PipelineMetricsRecorder (Session AT104)

### Session AT104: dispatch_pipeline.py ✅ Complete

**Production file:** `ipfs_datasets_py/mcp_server/dispatch_pipeline.py` (new)

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

Key design:
- `DispatchPipeline(stages, metrics_recorder, short_circuit)` — sequential stage execution
- `PipelineStage(name, handler, enabled, fail_open)` — named, togglable stage
- `PipelineMetricsRecorder` — aggregate counters per stage (executions/skips/denials/avg_duration_ms)
- `PipelineResult.denied_by` — which stage denied the intent
- `make_default_pipeline()` — 2-stage (tool_name + actor_present)
- `make_full_pipeline()` — 5-stage Profile E: compliance→risk→delegation→policy→nl_ucan_gate

#### TestDispatchPipelineBasics (9 tests):
- Import smoke test
- `make_default_pipeline()` runs with valid intent → allowed
- Missing tool name → denied by `tool_name_check`
- Short-circuit: remaining enabled stages appear in `stages_skipped`
- No short-circuit: all stages run even after denial
- `skip_stage()` disables stage; stage appears in `stages_skipped`
- `enable_stage()` re-enables; handler runs on next `run()`
- `stage_names` property lists all stages in order
- Handler exception + `fail_open=True` → allowed
- Handler exception + `fail_open=False` → denied

#### TestPipelineMetricsRecorder (7 tests):
- Initial state: `total_runs == 0`
- `record_run(allowed)` increments `total_allowed` / `total_denied`
- `record_stage(skipped=False)` → `stage_executions` + `avg_stage_duration_ms`
- `record_stage(skipped=True)` → `stage_skips` only
- `reset()` clears all counters
- `namespace` field in `get_metrics()`
- `pipeline.get_metrics()` delegates to recorder

---

## Phase AU105 — mcp_p2p_transport.py (Session AU105)

### Session AU105: TokenBucketRateLimiter + LengthPrefixFramer + MCPMessage ✅ Complete

**Production file:** `ipfs_datasets_py/mcp_server/mcp_p2p_transport.py` (new)

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

Key design:
- `TokenBucketRateLimiter(rate, capacity)` — thread-safe token bucket
- `LengthPrefixFramer` — big-endian u32 length codec
- `MCPMessage(method, params, id, jsonrpc)` — JSON-RPC 2.0 envelope
- `P2PSessionConfig(max_connections, timeout_seconds, rate_limit, capacity, ...)` 
- `MCP_P2P_PROTOCOL_ID = "/mcp+p2p/1.0.0"`
- `MCP_P2P_PUBSUB_TOPICS` — well-known topic names

#### TestTokenBucketRateLimiter (9 tests):
- Consume succeeds when available
- Consume fails when bucket empty
- `available()` starts at capacity
- `reset()` refills to capacity
- Invalid rate raises `ValueError`
- Invalid capacity raises `ValueError`
- `get_info()` has `rate`/`capacity`/`available`
- Thread-safe concurrent consume (80 threads, 100 capacity)
- `P2PSessionConfig.make_rate_limiter()` creates correctly configured limiter

#### TestLengthPrefixFramer (4 tests):
- Encode/decode roundtrip with exact remainder
- Decode with trailing second frame
- Empty payload roundtrip
- Incomplete frame raises `ValueError`

#### TestMCPMessage (5 tests):
- Default `id` is 32-char UUID hex
- `to_dict()` has method/params/jsonrpc fields
- Bytes roundtrip preserves method/params/id
- Missing method raises `ValueError`
- Constants: `MCP_P2P_PROTOCOL_ID` + `MCP_P2P_PUBSUB_TOPICS` keys

---

## Phase AV106 — compliance_checker.py (Session AV106)

### Session AV106: ComplianceChecker + custom rule add/remove ✅ Complete

**Production file:** `ipfs_datasets_py/mcp_server/compliance_checker.py` (new)

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

Key design:
- `ComplianceRule(rule_id, description, check_fn, removable)` — named predicate
- `ComplianceChecker(rules, fail_fast)` — ordered rule set
- `ComplianceReport(results, intent_snapshot)` — passed/failed aggregation
- Built-in rules: `tool_name_convention`, `intent_has_actor`, `actor_is_valid`, `params_are_serializable`
- `make_default_checker()` — pre-loaded with 4 built-in rules

#### TestComplianceCheckerBuiltIn (5 tests):
- Valid intent → `report.passed=True`, `failed_rules=[]`
- Invalid tool name (`Read-File!`) → `tool_name_convention` in failed
- Missing actor → `intent_has_actor` in failed
- Invalid actor (`!!bad!!`) → `actor_is_valid` in failed
- Non-JSON-serialisable params → `params_are_serializable` in failed

#### TestComplianceCheckerCustomRules (8 tests):
- `add_rule()` increases `len(checker)` by 1
- Duplicate `rule_id` raises `ValueError`
- `remove_rule()` returns `True` when found, decreases count
- `remove_rule()` returns `False` when not found
- `remove_rule()` raises `ValueError` when `removable=False`
- `list_rules()` returns list of dicts with `rule_id`/`description`
- `fail_fast=True` stops at first failure (1 result)
- `ComplianceResult.to_dict()` has rule_id/passed/message

---

## Phase AW107 — risk_scorer.py (Session AW107)

### Session AW107: RiskScorer + score_and_gate() ✅ Complete

**Production file:** `ipfs_datasets_py/mcp_server/risk_scorer.py` (new)

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

Key design:
- `RiskLevel(Enum)` — NEGLIGIBLE/LOW/MEDIUM/HIGH/CRITICAL with `from_score()`
- `RiskScoringPolicy(tool_risk_overrides, default_risk, actor_trust_levels, max_acceptable_risk)`
- `RiskAssessment` — score/level/is_acceptable/tool_base_risk/trust_factor/complexity_penalty
- `RiskScorer(policy)` — computes risk and optionally gates
- Formula: `score = base_risk * (1 - trust_bonus) + complexity_penalty`

#### TestRiskLevelFromScore (5 tests):
- 0.0 → NEGLIGIBLE; 0.19 → NEGLIGIBLE
- 0.2 → LOW; 0.39 → LOW
- 0.4 → MEDIUM
- 0.6 → HIGH
- 0.8 → CRITICAL; 1.0 → CRITICAL

#### TestRiskScorer (8 tests):
- Default scorer: `read` + `alice` → score in [0,1], is_acceptable=True
- High base risk tool (`delete`: 0.9) → HIGH/CRITICAL level
- Trust reduces score vs. untrusted actor
- Complexity penalty from many params
- `score_and_gate()` returns assessment for low-risk tool
- `score_and_gate()` raises `RiskGateError` for dangerous tool
- `RiskGateError.assessment.tool` is set
- `get_info()` / `to_dict()` have required keys

---

## Phase AX108 — policy_audit_log (Session AX108)

### Session AX108: Sink callable + JSONL file + stats ✅ Complete

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

#### TestPolicyAuditLogSink (3 tests):
- Sink callable receives `AuditEntry` on `record()`
- Sink NOT called when `enabled=False`
- Sink that raises does NOT crash the audit log

#### TestPolicyAuditLogJSONL (2 tests):
- JSONL file written with correct JSON fields per line
- Multiple `PolicyAuditLog` instances append to same file

#### TestPolicyAuditLogStats (3 tests):
- `stats()` has `total_recorded` and `by_decision` keys
- `clear()` empties in-memory buffer (`all_entries() == []`)
- Ring buffer with `max_entries=5` holds at most 5 entries

---

## Phase AY109 — did_key_manager (Session AY109)

### Session AY109: rotate_key() + info() ✅ Complete (4 tests; 3 need py-ucan)

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

- `rotate_key()` returns new DID ≠ old DID  *(requires py-ucan)*
- `rotate_key()` persists — reload gives same new DID  *(requires py-ucan)*
- `info()` has `did`/`ucan_available`/`key_file` keys  *(always)*
- `export_secret_b64()` is stable  *(requires py-ucan)*

---

## Phase AZ110 — secrets_vault (Session AZ110)

### Session AZ110: list/iter/delete + encrypted round-trip ✅ Complete (6 tests; 5 need py-ucan)

**Test file:** `tests/mcp/unit/test_v14_sessions.py`

- `list_names()` returns all set secret names  *(requires py-ucan)*
- `for name in vault:` iterates names  *(requires py-ucan)*
- `delete()` removes secret; `get()` returns `None`  *(requires py-ucan)*
- `len(vault)` tracks count through set/delete  *(requires py-ucan)*
- Encrypted round-trip: plaintext absent on disk; reload decrypts  *(requires py-ucan)*
- `info()` has `vault_file`/`secret_count`  *(always)*

---

## Summary — v14 Sessions

| Session | Target | New Tests | Production changes | Status |
|---------|--------|-----------|-------------------|--------|
| AT104 | `dispatch_pipeline.py` | 16 | New module | ✅ |
| AU105 | `mcp_p2p_transport.py` | 18 | New module | ✅ |
| AV106 | `compliance_checker.py` | 13 | New module | ✅ |
| AW107 | `risk_scorer.py` | 13 | New module | ✅ |
| AX108 | `policy_audit_log.py` | 8 | — | ✅ |
| AY109 | `did_key_manager.py` | 4 (+3 skip) | — | ✅ |
| AZ110 | `secrets_vault.py` | 6 (+5 skip) | — | ✅ |
| BA111 | `cec_bridge.py` | 13 | — | ✅ |
| BC113 | NL multi-language parsers | 22 | — | ✅ |
| **Total** | | **79 + 8 skip** | **4 new modules** | ✅ |

**Production files added:**
- `mcp_server/dispatch_pipeline.py` — Profile E §4 pipeline
- `mcp_server/mcp_p2p_transport.py` — Profile E §5 transport primitives
- `mcp_server/compliance_checker.py` — Profile A §8 compliance checker
- `mcp_server/risk_scorer.py` — Pipeline risk gate

**Grand total (all plans):**  
2,805 (through v13) + 79 (v14) = **2,884 MCP + logic unit tests** · 8 skip · 0 failing

---

## Next Steps (v15 candidates)

| Session | Target | Rationale | Spec alignment |
|---------|--------|-----------|----------------|
| BD114 | `dispatch_pipeline.py` — end-to-end with real handlers (compliance→risk→delegation) | Full pipeline smoke test | Profile E §4 |
| BE115 | `compliance_checker.py` + `dispatch_pipeline.py` integration | Compliance stage in pipeline | Profile A §8 |
| BF116 | `risk_scorer.py` + `mcp_p2p_transport.py` integration | Rate-limit per risk level | Profile E §5 |
| BG117 | `policy_audit_log.py` + Prometheus exporter integration | Audit→metrics bridge | Phase 8 |
| BH118 | `ucan_delegation.py` DelegationManager full round-trip | Delegation lifecycle | Profile C |
| BI119 | `did_key_manager.py` delegation chain migration after `rotate_key()` | Key rotation spec | Profile C |
| BJ120 | `nl_ucan_policy.py` FilePolicyStore + IPFSPolicyStore | Policy persistence | Profile D |
| BK121 | Groth16 circuit_version=2 trace + witness schema v2 | ZKP Phase 4b | ZKP §4 |
| BL122 | `NLUCANPolicyCompiler` conflict detection (simultaneous permission + prohibition) | NL accuracy | Phase 3c |
| BM123 | Logic `integration/cec_bridge.py` Z3 path (mock Z3) | cec_bridge 95%+ coverage | BA111 follow-up |
