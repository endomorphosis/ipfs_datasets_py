# Comprehensive Logic Refactoring Plan 2026 — v12

**Date:** 2026-02-23
**Version:** v12 (supersedes v11)
**Status:** All phases complete through v20 ✅

---

## 1. Phase Status Table

| Phase | Title | Status | Sessions |
|-------|-------|--------|---------|
| 1 | NL→UCAN pipeline | ✅ Complete | v10–v12 |
| 2 | DID-signed UCAN tokens | ✅ Complete | v13 (Phase 2b) |
| 3 | Grammar-based NL parsing | ✅ Complete | v13 (Phase 3b) |
| 4 | ZKP→UCAN bridge | 🟡 Simulation (Groth16 wired v16) | v16, defer Phase 4b |
| 5 | Import hygiene & blessed API | ✅ Complete | v15 Phase 5, v16 BW133, v18 CN150, v19 CT156, v20 DC165 |
| 6 | Performance & caching | ✅ Complete | v15 Phase 6, v18 CM149 |
| 7 | Security hardening | ✅ Complete | v15 Phase 7 |
| 8 | Observability & CI integration | ✅ Complete | v15 Phase 8, v18 CM149, v19 CS155, v20 CZ162 |
| 9 | Delegation lifecycle | ✅ Complete | v15 BH118, v16 BN124/BR128/BS129, v19 CQ153, v20 CY161 |
| 10 | Compliance tooling | ✅ Complete | v14 AV106, v18 CR154, v19 CR154, v20 DA163 |
| 11 | NL conflict detection | ✅ Complete | v15 BL122, v17 BX134/CB138, v18 CJ146, v19 CT156, v20 DC165 |
| 12 | Compiler introspection | ✅ Complete | v19 CW159, v20 DB164 |

---

## 2. Module Map (v12, authoritative)

### `logic/CEC/nl/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `nl_to_policy_compiler.py` | `NLToDCECCompiler`, `CLAUSE_TYPE_*` | v10 |
| `dcec_to_ucan_bridge.py` | `DCECToUCANBridge` | v10 |
| `grammar_nl_policy_compiler.py` | `GrammarNLPolicyCompiler` | v13 |
| `nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts`, `detect_i18n_conflicts`, `I18NConflictResult`, `detect_and_warn`, `detect_i18n_clauses`, **`_EN_DEONTIC_KEYWORDS` (v20)** | v14→v20 |
| `language_detector.py` | `LanguageDetector` | v14 |
| `french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | v14 |
| `spanish_parser.py` | `SpanishParser`, `get_spanish_deontic_keywords` | v14 |
| `german_parser.py` | `GermanParser`, `get_german_deontic_keywords` | v14 |
| `base_parser.py` | `BaseParser` | v14 |

### `logic/integration/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult`, `BridgeEvaluationResult`, `evaluate_with_manager`, `evaluate_audited_with_manager`, `SignedPolicyResult` | v10→v18 |
| `nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler`, `NLUCANCompilerResult.explain()`, **`compile_explain()` (v20)** | v10→v20 |

### `logic/api.py`

All public symbols (v20):

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
- **v20 (DC165)**: `detect_all_languages()` now covers 4 languages: `fr`, `es`, `de`, **`en`**

### `mcp_server/`

| Module | Key Symbols | Version |
|--------|------------|---------|
| `ucan_delegation.py` | `DelegationToken`, `Capability`, `Delegation`, `DelegationEvaluator`, `DelegationStore`, `RevocationList`, `DelegationChain`, `DelegationManager`, `get_delegation_manager`, `can_invoke_with_revocation`, `record_delegation_metrics`, `merge()`, **`merge_and_publish()` (v19/v20 CY161: +metrics)** | v10→v20 |
| `dispatch_pipeline.py` | `DispatchPipeline`, `PipelineStage`, `PipelineMetricsRecorder`, `make_default_pipeline`, `make_full_pipeline`, `make_delegation_stage` | v14→v16 |
| `compliance_checker.py` | `ComplianceChecker`, `ComplianceRule`, `make_default_checker`, `diff()`, **`merge()` (v20 DA163)** | v14→v20 |
| `risk_scorer.py` | `RiskLevel`, `RiskScorer`, `RiskGateError`, `RiskScoringPolicy` | v14 |
| `mcp_p2p_transport.py` | `TokenBucketRateLimiter`, `LengthPrefixFramer`, `MCPMessage`, `P2PSessionConfig`, `MCP_P2P_PROTOCOL_ID` | v14 |
| `policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `get_audit_log`, `export_jsonl()`, `import_jsonl()`, **`export_jsonl(metadata=None)` (v20 CZ162)** | v15→v20 |
| `audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | v15 |
| `tools/logic_tools/delegation_audit_tool.py` | 8 MCP tools + `DELEGATION_AUDIT_TOOLS` | v17→v18 |

---

## 3. Key Invariants (cumulative v12)

### `DelegationManager.merge_and_publish()` (CQ153 / CY161)
- Payload: `{"type":"merge","added":N,"total":M,"metrics":{...}}`
- `"metrics"` contains the full snapshot from `get_metrics()` (e.g. `token_count`, `revoked_count`, `max_chain_depth`)
- pubsub exceptions swallowed at DEBUG — never raises to caller
- `"added"` and `"total"` keys always present (backward-compatible)

### `PolicyAuditLog.export_jsonl()` (CS155 / CZ162)
- `metadata=None` → identical to v19 behaviour (no header line)
- `metadata=dict` → writes `{"__metadata__":dict}` as first line
- Return value counts audit entries only (not the metadata header)
- Overwrites target file; creates parent dirs

### `ComplianceChecker.merge()` (DA163)
- Appends rules from `other` not already present in `self` (by `rule_id`)
- Preserves `self` rule order; new rules appended in `other`'s order
- Returns count of added rules (0 if all were already present)
- Symmetric: `diff(other)["added_rules"]` IDs == what `merge(other)` would add

### `NLUCANPolicyCompiler.compile_explain()` (DB164)
- Returns `(NLUCANCompilerResult, str)` 2-tuple
- `explanation == result.explain()` — always consistent
- Never raises independently (delegates to `compile()` and `explain()`)

### `detect_i18n_conflicts(text, "en")` (DC165)
- Uses `_EN_DEONTIC_KEYWORDS` inline (no external module required)
- Returns `I18NConflictResult` with `language="en"`
- No import needed beyond `nl_policy_conflict_detector` itself

### `detect_all_languages()` (CT156 / DC165)
- Always sets all 4 language keys: `"fr"`, `"es"`, `"de"`, **`"en"`**
- ImportError per-language → empty list in that slot (no raise)
- `total_conflicts == 0` when all per-language lists are empty

---

## 4. Evergreen Backlog (v21 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| DG169 | `PolicyAuditLog.import_jsonl()` — skip `__metadata__` header lines | Low | 🟡 Med |
| DH170 | `ComplianceChecker.merge(copy_disabled=False)` | Low | 🟢 Low |
| DI171 | `compile_explain()` line iterator variant | Low | 🟢 Low |
| DJ172 | `detect_all_languages()` — add `"pt"` (Portuguese) inline keywords | Med | 🟡 Med |
| DK173 | `DelegationManager.merge_and_publish_async()` | Med | 🟡 Med |
| DL174 | Full E2E: merge + export_jsonl(metadata) + import_jsonl round-trip | Med | 🔴 High |
| DM175 | `diff()` + `merge()` combined idempotency E2E | Low | 🟡 Med |
| DN176 | `detect_all_languages()` with `"nl"` (Dutch) inline keywords | Med | 🟡 Med |

---

## 5. Success Criteria (v12)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,232 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v13 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v13 Phase 3b |
| Conflict detection | detect + warn + i18n keyword + full clause + all-languages + **English** | ✅ BL122/BX134/CB138/CJ146/CT156/DC165 |
| Bridge DelegationManager | evaluate_with_manager + audited | ✅ BZ136/CK147 |
| Audit ↔ Pipeline | Both integrate | ✅ CA137/CE141 |
| Audit ↔ Prometheus | Bridge wired | ✅ BG117 |
| Delegation metrics | 3 Prometheus gauges + max_chain_depth | ✅ CM149 |
| MCP tools | Delegation + audit (8 tools) | ✅ CH144/CI145 |
| API blessed | `evaluate_with_manager` + `detect_i18n_clauses` + `detect_all_languages` (4 langs) | ✅ CN150/CJ146/CT156/DC165 |
| Delegation merge | merge() + merge_and_publish() (+ metrics CY161) | ✅ CQ153/CY161 |
| Compliance diff + merge | diff() + merge() | ✅ CR154/DA163 |
| Audit JSONL I/O | export_jsonl(metadata) + import_jsonl() | ✅ CS155/CZ162 |
| Compiler explain | explain() + compile_explain() | ✅ CW159/DB164 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
