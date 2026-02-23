# Comprehensive Logic Refactoring Plan 2026 — v11

**Date:** 2026-02-23
**Version:** v11 (supersedes v10)
**Status:** All phases complete through v19 ✅

---

## 1. Phase Status Table

| Phase | Title | Status | Sessions |
|-------|-------|--------|---------|
| 1 | NL→UCAN pipeline | ✅ Complete | v10–v12 |
| 2 | DID-signed UCAN tokens | ✅ Complete | v13 (Phase 2b) |
| 3 | Grammar-based NL parsing | ✅ Complete | v13 (Phase 3b) |
| 4 | ZKP→UCAN bridge | 🟡 Simulation (Groth16 wired v16) | v16, defer Phase 4b |
| 5 | Import hygiene & blessed API | ✅ Complete | v15 Phase 5, v16 BW133, v18 CN150, v19 CT156 |
| 6 | Performance & caching | ✅ Complete | v15 Phase 6, v18 CM149 |
| 7 | Security hardening | ✅ Complete | v15 Phase 7 |
| 8 | Observability & CI integration | ✅ Complete | v15 Phase 8, v18 CM149, v19 CS155 |
| 9 | Delegation lifecycle | ✅ Complete | v15 BH118, v16 BN124/BR128/BS129, v19 CQ153 |
| 10 | Compliance tooling | ✅ Complete | v14 AV106, v18 CR154 (new), v19 CR154 |
| 11 | NL conflict detection | ✅ Complete | v15 BL122, v17 BX134/CB138, v18 CJ146, v19 CT156 |
| 12 | Compiler introspection | ✅ Complete | v19 CW159 |

---

## 2. Module Map (v11, authoritative)

### `logic/CEC/nl/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `nl_to_policy_compiler.py` | `NLToDCECCompiler`, `CLAUSE_TYPE_*` | v10 |
| `dcec_to_ucan_bridge.py` | `DCECToUCANBridge` | v10 |
| `grammar_nl_policy_compiler.py` | `GrammarNLPolicyCompiler` | v13 |
| `nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts`, `detect_i18n_conflicts`, `I18NConflictResult`, `detect_and_warn`, `detect_i18n_clauses` | v14→v18 |
| `language_detector.py` | `LanguageDetector` | v14 |
| `french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | v14 |
| `spanish_parser.py` | `SpanishParser`, `get_spanish_deontic_keywords` | v14 |
| `german_parser.py` | `GermanParser`, `get_german_deontic_keywords` | v14 |
| `base_parser.py` | `BaseParser` | v14 |

### `logic/integration/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult`, `BridgeEvaluationResult`, `evaluate_with_manager`, `evaluate_audited_with_manager`, `SignedPolicyResult` | v10→v18 |
| `nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler`, `NLUCANCompilerResult.explain()` | v10→v19 |

### `logic/api.py`

All public symbols (v19):

- Core: `FOLConverter`, `convert_text_to_fol`, `DeonticConverter`, `convert_legal_text_to_deontic`
- Common: `LogicError`, `ConversionError`, `ValidationError`, `ProofError`, `TranslationError`,
  `BridgeError`, `ConfigurationError`, `DeonticError`, `ModalError`, `TemporalError`,
  `LogicConverter`, `ChainedConverter`, `ConversionResult`, `ConversionStatus`, `ValidationResult`,
  `UtilityMonitor`, `track_performance`, `with_caching`, `get_global_stats`, `clear_global_cache`,
  `reset_global_stats`, `BoundedCache`, `ProofCache`, `CachedProofResult`, `get_global_cache`
- Types: `DeonticOperator`, `DeonticFormula`, `DeonticRuleSet`, `LegalAgent`, `LegalContext`,
  `TemporalCondition`, `TemporalOperator`, `ProofStatus`, `ProofResult`, `ProofStep`,
  `LogicTranslationTarget`, `TranslationResult`, `AbstractLogicFormula`, `Formula`, `Predicate`,
  `Variable`, `Constant`, `And`, `Or`, `Not`, `Implies`, `Forall`, `Exists`, `LogicOperator`,
  `Quantifier`, `FormulaType`, `ConfidenceScore`, `ComplexityScore`, `ComplexityMetrics`,
  `Prover`, `Converter`, `BridgeCapability`, `BridgeMetadata`, `BridgeConfig`,
  `ProverRecommendation`, `FOLOutputFormat`, `PredicateCategory`, `FOLFormula`,
  `FOLConversionResult`, `PredicateExtraction`
- NL→UCAN: `compile_nl_to_policy`, `evaluate_nl_policy`, `build_signed_delegation`,
  `NLToDCECCompiler`, `DCECToUCANBridge`, `NLUCANPolicyCompiler`, `GrammarNLPolicyCompiler`,
  `UCANPolicyBridge`, `SignedPolicyResult`, `BridgeCompileResult`, `BridgeEvaluationResult`
- Delegation (conditional): `DelegationManager`, `get_delegation_manager`
- Conflict detection (conditional): `NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts`,
  `detect_i18n_conflicts`, `I18NConflictResult`, `detect_i18n_clauses`
- Bridge (conditional): `evaluate_with_manager`
- **v19 (unconditional)**: `I18NConflictReport`, `detect_all_languages`

### `mcp_server/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `ucan_delegation.py` | `DelegationToken`, `Capability`, `Delegation`, `DelegationEvaluator`, `DelegationStore`, `RevocationList`, `DelegationChain`, `DelegationManager`, `get_delegation_manager`, `can_invoke_with_revocation`, `record_delegation_metrics`, **`merge()` (v19)**, **`merge_and_publish()` (v19)** | v10→v19 |
| `dispatch_pipeline.py` | `DispatchPipeline`, `PipelineStage`, `PipelineMetricsRecorder`, `make_default_pipeline`, `make_full_pipeline`, `make_delegation_stage` | v14→v16 |
| `compliance_checker.py` | `ComplianceChecker`, `ComplianceRule`, `make_default_checker`, **`diff()` (v19)** | v14→v19 |
| `risk_scorer.py` | `RiskLevel`, `RiskScorer`, `RiskGateError`, `RiskScoringPolicy` | v14 |
| `mcp_p2p_transport.py` | `TokenBucketRateLimiter`, `LengthPrefixFramer`, `MCPMessage`, `P2PSessionConfig`, `MCP_P2P_PROTOCOL_ID` | v14 |
| `policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `get_audit_log`, **`export_jsonl()` (v19)**, **`import_jsonl()` (v19)** | v15→v19 |
| `audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | v15 |
| `tools/logic_tools/delegation_audit_tool.py` | 8 MCP tools + `DELEGATION_AUDIT_TOOLS` | v17→v18 |

---

## 3. Key Invariants (cumulative v11)

### `DelegationManager.merge()` (CQ153)
- Copies tokens by iterating `other.list_cids()` → skips duplicates
- Does NOT copy revocations (use `revoke()` explicitly)
- Returns `0` for empty source or all-duplicate source
- Invalidates `_evaluator` and `_metrics_cache` only when `added > 0`

### `DelegationManager.merge_and_publish()` (CQ153)
- Always calls `pubsub.publish("receipt_disseminate", {...})` after merge
- payload: `{"type":"merge", "added":N, "total":M}`
- pubsub exceptions swallowed at DEBUG — never raises to caller
- Returns same count as `merge()`

### `ComplianceChecker.diff()` (CR154)
- `changed_rules` is always a subset of `common_rules`
- All four keys (`added_rules`, `removed_rules`, `common_rules`, `changed_rules`) always present
- "Changed" means different `description` OR different `removable`

### `PolicyAuditLog.export_jsonl()` (CS155)
- Overwrites the target file (not appends)
- Creates parent directories via `Path.mkdir(parents=True, exist_ok=True)`
- Returns count of entries written

### `PolicyAuditLog.import_jsonl()` (CS155)
- Returns `0` for non-existent path (no exception)
- Respects `max_entries` ring buffer during import
- Malformed lines silently skipped at DEBUG

### `NLUCANCompilerResult.explain()` (CW159)
- Never raises; returns a `str`
- Mentions "succeeded" for `success=True`, "failed" for `success=False`
- Shows counts from `metadata` dict (policy_clauses, dcec_formulas, ucan_tokens, ucan_denials)
- Shows first 3 errors / first 3 warnings (not all)

### `I18NConflictReport` + `detect_all_languages()` (CT156)
- `detect_all_languages()` always sets all 3 language keys (`"fr"`, `"es"`, `"de"`)
- ImportError per-language → empty list in that slot (no raise)
- `total_conflicts == 0` when all per-language lists are empty
- Both symbols are unconditionally in `__all__` (defined in `api.py` itself)

---

## 4. Evergreen Backlog (v20 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| CY161 | `merge_and_publish()` — publish full metrics snapshot | Low | 🟡 Med |
| CZ162 | `export_jsonl()` metadata field inclusion | Low | 🟢 Low |
| DA163 | `ComplianceChecker.merge(other)` — symmetric to `diff()` | Low | 🟡 Med |
| DB164 | `NLUCANPolicyCompiler.compile_explain(sentences)` | Low | 🟢 Low |
| DC165 | `detect_all_languages()` — add `"en"` pass | Med | 🟡 Med |
| DD166 | Full `merge_and_publish()` with real PubSubBus | Med | 🟡 Med |
| DE167 | TDFOL NL `NLParser.parse()` with mocked spaCy | Med | 🟡 Med |
| DF168 | `evaluate_with_manager` + `detect_all_languages` combined E2E | Med | 🔴 High |

---

## 5. Success Criteria (v11)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,171 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v13 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v13 Phase 3b |
| Conflict detection | detect + warn + i18n keyword + full clause + all-languages | ✅ BL122/BX134/CB138/CJ146/CT156 |
| Bridge DelegationManager | evaluate_with_manager + audited | ✅ BZ136/CK147 |
| Audit ↔ Pipeline | Both integrate | ✅ CA137/CE141 |
| Audit ↔ Prometheus | Bridge wired | ✅ BG117 |
| Delegation metrics | 3 Prometheus gauges + max_chain_depth | ✅ CM149 |
| MCP tools | Delegation + audit (8 tools) | ✅ CH144/CI145 |
| API blessed | `evaluate_with_manager` + `detect_i18n_clauses` + `detect_all_languages` | ✅ CN150/CJ146/CT156 |
| Delegation merge | merge() + merge_and_publish() | ✅ CQ153 |
| Compliance diff | diff() | ✅ CR154 |
| Audit JSONL I/O | export_jsonl() + import_jsonl() | ✅ CS155 |
| Compiler explain | NLUCANCompilerResult.explain() | ✅ CW159 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
