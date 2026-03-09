# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v14

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Supersedes:** v13
**Status:** ✅ v14 Complete — 3,337 total tests, 0 failing

---

## 1. Executive Summary

This version supersedes v13 and incorporates all v22 session deliverables:
- **DO177**: Italian (`"it"`) inline keywords; `detect_all_languages()` → 7 languages
- **DP178**: `PortugueseParser.parse()` sentence-level splitting + multi-clause extraction
- **DQ179**: `merge_and_publish_async()` payload `"event_type": "RECEIPT_DISSEMINATE"`
- **DR180**: `import_jsonl()` large-file + `max_entries` clipping tests
- **DS181**: `merge()` now uses `copy.copy(rule)` (deep-copy isolation)
- **DT182**: `compile_explain_iter(max_lines=None)` truncation parameter
- **DU183**: Dutch obligation keyword coverage tests
- **DV184**: `get_metrics()["active_token_count"]`; `revoke()` invalidates cache
- **DW185**: `compile_explain_iter` module-level wrapper in `logic/api.py`
- **DX186**: Full E2E 7-language `detect_all_languages()` + `I18NConflictReport.to_dict()`

---

## 2. Module Inventory (cumulative)

### Core logic modules

| Module | Key Additions | Version Added |
|--------|--------------|---------------|
| `logic/api.py` | `compile_explain_iter` (DW185), `detect_all_languages()` → 7 langs (DO177/DX186), `evaluate_with_manager`, `I18NConflictReport`, `detect_i18n_clauses`, `DelegationManager`, ... | v13→v22 |
| `logic/TDFOL/security_validator.py` | `_acquire_concurrent_slot()`, proof hash excludes metadata | v15 |
| `logic/integration/ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult.conflicts`, `evaluate_with_manager`, `evaluate_audited_with_manager` | v14→v18 |
| `logic/integration/nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler`, `compile_explain()`, `compile_explain_iter(max_lines)` (DT182) | v14→v22 |
| `logic/CEC/nl/nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `detect_conflicts`, `detect_i18n_conflicts`, `_EN_DEONTIC_KEYWORDS`, `_NL_DEONTIC_KEYWORDS`, **`_IT_DEONTIC_KEYWORDS`** (DO177) | v15→v22 |
| `logic/CEC/nl/french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | v13 |
| `logic/CEC/nl/spanish_parser.py` | `SpanishParser`, `get_spanish_deontic_keywords` | v13 |
| `logic/CEC/nl/german_parser.py` | `GermanParser`, `get_german_deontic_keywords` | v13 |
| `logic/CEC/nl/portuguese_parser.py` | `PortugueseParser` + **sentence-level splitting** (DP178), `PortugueseClause`, `get_portuguese_deontic_keywords` | v21→v22 |
| `logic/zkp/ucan_zkp_bridge.py` | `ZKPToUCANBridge`, Groth16 auto-provision | v16 |
| `logic/zkp/backends/groth16_ffi.py` | `setup(version, seed)`, `artifacts_exist()` | v16 |

### MCP server modules

| Module | Key Additions | Version Added |
|--------|--------------|---------------|
| `mcp_server/policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `export_jsonl(metadata)`, `import_jsonl()` (skips `__metadata__`) | v15→v21 |
| `mcp_server/ucan_delegation.py` | `DelegationManager`, `merge()`, `merge_and_publish()`, `merge_and_publish_async()` + `"event_type"` (DQ179), **`get_metrics()["active_token_count"]`** (DV184), **`revoke()` cache invalidation** (DV184) | v15→v22 |
| `mcp_server/compliance_checker.py` | `ComplianceChecker`, `diff()`, `merge(include_protected_rules)` + **deep-copy** (DS181) | v14→v22 |
| `mcp_server/dispatch_pipeline.py` | `DispatchPipeline`, `PipelineStage`, `PipelineMetricsRecorder`, `make_delegation_stage()` | v14→v16 |
| `mcp_server/mcp_p2p_transport.py` | `TokenBucketRateLimiter`, `LengthPrefixFramer`, `MCPMessage`, `P2PSessionConfig`, `MCP_P2P_PUBSUB_TOPICS` | v14 |
| `mcp_server/audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | v15 |
| `mcp_server/tools/logic_tools/delegation_audit_tool.py` | 8 MCP tools + `DELEGATION_AUDIT_TOOLS` | v17→v18 |

---

## 3. Key Invariants (cumulative v14)

### Italian inline keywords (DO177)
- `_IT_DEONTIC_KEYWORDS` — 3 types (permission/prohibition/obligation), all inline
- `_load_i18n_keywords("it")` returns `_IT_DEONTIC_KEYWORDS` directly
- `detect_all_languages()` returns keys for all 7 languages: `{"fr","es","de","en","pt","nl","it"}`

### PortugueseParser sentence splitting (DP178)
- `parse(text)` splits on `[.!?;]+` before keyword scanning
- Yields multiple clauses when sentences contain different deontic types
- Empty input → empty list; single sentence still works as before

### `merge_and_publish_async()` event_type (DQ179)
- Payload: `{"type":"merge","event_type":"RECEIPT_DISSEMINATE","added":N,"total":M,"metrics":{...}}`
- Both `"type"` (backward compat) and `"event_type"` (new) present

### `merge()` deep copy (DS181)
- `copy.copy(rule)` applied for each copied rule
- Source rule mutations do not affect merged dst rule

### `compile_explain_iter(max_lines=N)` (DT182)
- `N=None` → all lines; `N=0` → empty; `N>len(lines)` → all lines
- Generator type preserved

### `active_token_count` (DV184)
- `get_metrics()["active_token_count"] == max(0, token_count - revoked_count)`
- `revoke(cid)` clears `_metrics_cache` (was only cleared by add/remove/load)

### `compile_explain_iter` in `api.__all__` (DW185)
- Module-level wrapper creates fresh `NLUCANPolicyCompiler()` per call
- Conditional on `_DW185_COMPILER_AVAILABLE`; `max_lines` forwarded

---

## 4. All-Phase Status Table

| Phase | Component | Status | Version |
|-------|-----------|--------|---------|
| 1 | FOL/DCEC base types | ✅ Complete | v13 |
| 2a | DID key management | ✅ Complete | v13 |
| 2b | DID signing (sign_delegation_token) | ✅ Complete | v15 |
| 3a | NL policy compiler | ✅ Complete | v13 |
| 3b | Grammar NL Stage 1b fallback | ✅ Complete | v15 |
| 4 | UCAN policy bridge | ✅ Complete | v14 |
| 5 | logic/api.py exports | ✅ Complete | v15→v22 |
| 6 | Evaluator caches | ✅ Complete | v15 |
| 7 | Security validator atomic + vault | ✅ Complete | v15 |
| 8 | Policy audit log | ✅ Complete | v15 |
| ZKP | ZKP bridge + Groth16 Rust FFI | ✅ Complete | v16 |
| CONFLICT | NL conflict detection + i18n (7 langs) | ✅ Complete | v15→v22 |
| DELEGATION | DelegationManager + async merge + metrics | ✅ Complete | v15→v22 |
| COMPLIANCE | ComplianceChecker + include_protected + deep-copy | ✅ Complete | v14→v22 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence splitting | ✅ Complete | v21→v22 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |

---

## 5. Evergreen Backlog (v23 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| DY187 | `PortugueseParser.get_clauses_by_type(deontic_type)` convenience method | Low | 🟢 Low |
| DZ188 | `NLUCANPolicyCompiler.compile_batch(sentences_list)` — multiple policy sets | Med | 🟡 Med |
| EA189 | `DelegationManager.active_tokens()` — iterator over non-revoked tokens | Med | 🔴 High |
| EB190 | `PolicyAuditLog.clear()` — reset all entries + stats | Low | 🟡 Med |
| EC191 | `ComplianceChecker.merge()` returns `MergeResult(added, skipped_protected, skipped_duplicate)` | Med | 🟡 Med |
| ED192 | `detect_all_languages()` — add `"ja"` Japanese inline keywords (8th language) | Low | 🟢 Low |
| EE193 | `compile_explain_iter` in `api.py` — `policy_id` passthrough test | Low | 🟢 Low |
| EF194 | `DelegationManager.active_token_count` property (cached) | Low | 🟡 Med |
| EG195 | `I18NConflictReport.most_conflicted_language()` — lang with most conflicts | Low | 🟡 Med |
| EH196 | Full integration: `PortugueseParser` → `detect_i18n_clauses("pt")` → `NLPolicyConflictDetector` | Med | 🔴 High |

---

## 6. Success Criteria (v14)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,337 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | 7 languages | ✅ v22 (fr/es/de/en/pt/nl/it) |
| Delegation merge | sync + async + event_type | ✅ CQ153/CY161/DK173/DQ179 |
| Compliance merge | include_protected + deep-copy | ✅ DA163/DH170/DS181 |
| Audit JSONL I/O | round-trip with metadata, large file | ✅ CS155/CZ162/DG169/DR180 |
| Compiler explain | eager + lazy + max_lines | ✅ CW159/DB164/DI171/DT182 |
| Portuguese parser | sentence-level multi-clause | ✅ DJ172/DP178 |
| Italian keywords | _IT_DEONTIC_KEYWORDS | ✅ DO177 |
| Active token count | in get_metrics() | ✅ DV184 |
| Revoke cache invalidation | on revoke() | ✅ DV184 |
| compile_explain_iter re-export | in api.__all__ | ✅ DW185 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
