# Comprehensive Logic Refactoring Plan 2026 — v10

**Date:** 2026-02-22
**Version:** v10 (supersedes v9)
**Status:** All phases complete through v18 ✅

---

## 1. Phase Status Table

| Phase | Title | Status | Sessions |
|-------|-------|--------|---------|
| 1 | NL→UCAN pipeline | ✅ Complete | v10–v12 |
| 2 | DID-signed UCAN tokens | ✅ Complete | v13 (Phase 2b) |
| 3 | Grammar-based NL parsing | ✅ Complete | v13 (Phase 3b) |
| 4 | ZKP→UCAN bridge | 🟡 Simulation (Groth16 wired v16) | v16, defer Groth16 Phase 4b |
| 5 | Import hygiene & blessed API | ✅ Complete | v15 (Phase 5), v16 (BW133), v18 (CN150) |
| 6 | Performance & caching | ✅ Complete | v15 (Phase 6) |
| 7 | Security hardening | ✅ Complete | v15 (Phase 7) |
| 8 | Observability & CI integration | ✅ Complete | v15 (Phase 8), v18 (CM149) |

---

## 2. Module Map (v10, authoritative)

### `logic/CEC/nl/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `nl_to_policy_compiler.py` | `NLToDCECCompiler`, `CLAUSE_TYPE_*` | v10 |
| `dcec_to_ucan_bridge.py` | `DCECToUCANBridge` | v10 |
| `grammar_nl_policy_compiler.py` | `GrammarNLPolicyCompiler` | v13 |
| `nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts`, `detect_i18n_conflicts`, `I18NConflictResult`, `detect_and_warn`, `detect_i18n_clauses` | v14→v18 |
| `language_detector.py` | `LanguageDetector` | v14 |
| `french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | v14 |
| `spanish_parser.py` | `SpanishParser` | v14 |
| `german_parser.py` | `GermanParser` | v14 |
| `base_parser.py` | `BaseParser` | v14 |

### `logic/integration/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult`, `BridgeEvaluationResult`, `evaluate_with_manager`, `evaluate_audited_with_manager`, `SignedPolicyResult` | v10→v18 |
| `nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler` | v10 |

### `logic/api.py`

All public symbols: `compile_nl_to_policy`, `evaluate_nl_policy`, `build_signed_delegation`,
`NLToDCECCompiler`, `GrammarNLPolicyCompiler`, `UCANPolicyBridge`, `BridgeCompileResult`,
`BridgeEvaluationResult`, `SignedPolicyResult`, `DelegationManager`, `get_delegation_manager`,
`NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts`, `detect_i18n_conflicts`,
`I18NConflictResult`, `detect_i18n_clauses`, `evaluate_with_manager` (v18).

### `mcp_server/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `ucan_delegation.py` | `DelegationToken`, `Capability`, `Delegation`, `DelegationEvaluator`, `DelegationStore`, `RevocationList`, `DelegationChain`, `DelegationManager`, `get_delegation_manager`, `can_invoke_with_revocation`, `record_delegation_metrics` | v10→v18 |
| `dispatch_pipeline.py` | `DispatchPipeline`, `PipelineStage`, `PipelineMetricsRecorder`, `make_default_pipeline`, `make_full_pipeline`, `make_delegation_stage` | v14→v16 |
| `compliance_checker.py` | `ComplianceChecker`, `ComplianceRule`, `make_default_checker` | v14 |
| `risk_scorer.py` | `RiskLevel`, `RiskScorer`, `RiskGateError`, `RiskScoringPolicy` | v14 |
| `mcp_p2p_transport.py` | `TokenBucketRateLimiter`, `LengthPrefixFramer`, `MCPMessage`, `P2PSessionConfig`, `MCP_P2P_PROTOCOL_ID` | v14 |
| `policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `get_audit_log` | v15 |
| `audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | v15 |
| `tools/logic_tools/delegation_audit_tool.py` | 8 MCP tools + `DELEGATION_AUDIT_TOOLS` | v17→v18 |

---

## 3. Key Invariants (cumulative v10)

### `detect_i18n_clauses()` (CJ146)
- Full clause compilation via language parser → `NLPolicyConflictDetector.detect()`
- Unsupported language → `[]` (no error raised)
- Parser ImportError → `[]` (debug-logged)
- Contrast with `detect_i18n_conflicts()` (keyword scan only, no compilation)

### `evaluate_audited_with_manager()` (CK147)
- Wraps `evaluate_with_manager()` + records to `audit_log`
- Audit errors: `(TypeError, AttributeError, ValueError)` caught and debug-logged
- `intent_cid` defaults to `"bridge_intent"` when not specified
- `audit_log=None` → no recording, same result as `evaluate_with_manager()`

### `DelegationManager.get_metrics()` (CM149)
- Returns `{"token_count":N, "revoked_count":N, "has_path":bool, "max_chain_depth":N}`
- `max_chain_depth` iterates all CIDs; 0 if empty or exception
- Always returns a dict with all 4 keys

### `record_delegation_metrics()` (CM149)
- Module-level function in `ucan_delegation.py`
- Sets exactly 3 gauges: `mcp_revoked_cids_total`, `mcp_delegation_store_depth`, `mcp_delegation_chain_depth_max`
- `manager=None` → no-op (no gauges set)
- Collector errors swallowed at DEBUG level

### `delegation_chain_ascii` MCP tool (CI145)
- 8th tool in `DELEGATION_AUDIT_TOOLS`
- Returns `{"status":"ok","ascii_tree":"...","chain_length":N}` for any leaf CID (even unknown → empty chain)
- Returns `{"status":"error","error":"..."}` only when `build_chain()` raises or manager init fails

### `evaluate_with_manager` (CN150, api.py)
- Module-level convenience over `UCANPolicyBridge.evaluate_audited_with_manager()`
- Returns `None` when bridge module is unavailable
- Added to `__all__` conditionally on `_CN150_BRIDGE_AVAILABLE`

---

## 4. Evergreen Backlog (v19 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| CQ153 | `DelegationManager.merge_and_publish(other, pubsub)` | Low | 🟡 Med |
| CR154 | `ComplianceChecker.diff(other)` | Low | 🟡 Med |
| CS155 | `PolicyAuditLog.export_jsonl(path)` + `import_jsonl(path)` | Med | 🟡 Med |
| CT156 | `I18NConflictReport` across all 3 languages | Low | 🟢 Low |
| CU157 | TDFOL NL spaCy integration tests | Med | 🟡 Med |
| CV158 | Groth16 Phase 4b — `circuit_version=2` | High | 🟢 Low |
| CW159 | `NLUCANPolicyCompiler.explain()` | Med | 🟡 Med |
| CX160 | Full dispatch_pipeline + DelegationManager + PolicyAuditLog E2E | Med | 🔴 High |

---

## 5. Success Criteria (v10)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,112 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v13 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v13 Phase 3b |
| Conflict detection | detect + warn + i18n keyword + full clause | ✅ BL122/BX134/CB138/CJ146 |
| Bridge DelegationManager | evaluate_with_manager + audited | ✅ BZ136/CK147 |
| Audit ↔ Pipeline | Both integrate | ✅ CA137/CE141 |
| Audit ↔ Prometheus | Bridge wired | ✅ BG117 |
| Delegation metrics | 3 Prometheus gauges + max_chain_depth | ✅ CM149 |
| MCP tools | Delegation + audit (8 tools) | ✅ CH144/CI145 |
| API blessed | `evaluate_with_manager` + `detect_i18n_clauses` | ✅ CN150/CJ146 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
| ZKP real proof | Real Groth16 (ENABLE_GROTH16=1) | ✅ v16 (defer Phase 4b) |
