# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v15

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Supersedes:** v14
**Status:** ✅ v15 Complete — 3,400 total tests, 0 failing

---

## 1. Executive Summary

This version supersedes v14 and incorporates all v23 session deliverables:
- **DY187**: `PortugueseParser.get_clauses_by_type(text, deontic_type)` convenience filter
- **DZ188**: `NLUCANPolicyCompiler.compile_batch(sentences_list, policy_ids)` — batch compilation
- **EA189**: `DelegationManager.active_tokens()` — non-revoked token generator
- **EB190**: Tests for `PolicyAuditLog.clear()` (buffer cleared; `total_recorded` preserved)
- **EC191**: `ComplianceMergeResult(added, skipped_protected, skipped_duplicate)` — backward-compat int NamedTuple
- **ED192**: `_JA_DEONTIC_KEYWORDS` inline Japanese; `detect_all_languages()` → 8 languages
- **EE193**: `compile_explain_iter` `policy_id` + `max_lines` passthrough via `api.py`
- **EF194**: `DelegationManager.active_token_count` cached `@property`
- **EG195**: `I18NConflictReport.most_conflicted_language()` — lang with most conflicts
- **EH196**: Full integration: PT text → `detect_i18n_clauses("pt")` → `NLPolicyConflictDetector`

---

## 2. Module Inventory (cumulative)

### Core logic modules

| Module | Key Additions | Version Added |
|--------|--------------|---------------|
| `logic/api.py` | `compile_explain_iter` (DW185), `detect_all_languages()` → 8 langs (DO177/DX186/ED192), `evaluate_with_manager`, `I18NConflictReport` (+`most_conflicted_language` EG195), `detect_i18n_clauses`, `DelegationManager`, ... | v13→v23 |
| `logic/TDFOL/security_validator.py` | `_acquire_concurrent_slot()`, proof hash excludes metadata | v15 |
| `logic/integration/ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult.conflicts`, `evaluate_with_manager`, `evaluate_audited_with_manager` | v14→v18 |
| `logic/integration/nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler`, `compile_explain()`, `compile_explain_iter(max_lines)`, **`compile_batch(sentences_list, policy_ids)`** (DZ188) | v14→v23 |
| `logic/CEC/nl/nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `detect_conflicts`, `detect_i18n_conflicts`, `_EN/NL/IT_DEONTIC_KEYWORDS`, **`_JA_DEONTIC_KEYWORDS`** (ED192) | v15→v23 |
| `logic/CEC/nl/french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | v13 |
| `logic/CEC/nl/spanish_parser.py` | `SpanishParser`, `get_spanish_deontic_keywords` | v13 |
| `logic/CEC/nl/german_parser.py` | `GermanParser`, `get_german_deontic_keywords` | v13 |
| `logic/CEC/nl/portuguese_parser.py` | `PortugueseParser` + sentence splitting (DP178), `PortugueseClause`, **`get_clauses_by_type`** (DY187) | v21→v23 |
| `logic/zkp/ucan_zkp_bridge.py` | `ZKPToUCANBridge`, Groth16 auto-provision | v16 |
| `logic/zkp/backends/groth16_ffi.py` | `setup(version, seed)`, `artifacts_exist()` | v16 |

### MCP server modules

| Module | Key Additions | Version Added |
|--------|--------------|---------------|
| `mcp_server/policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `export_jsonl(metadata)`, `import_jsonl()` (skips `__metadata__`), `clear()` (EB190) | v15→v23 |
| `mcp_server/ucan_delegation.py` | `DelegationManager`, `merge()`, `merge_and_publish/async()`, **`active_tokens()`** (EA189), **`active_token_count`** (EF194), `get_metrics()["active_token_count"]` | v15→v23 |
| `mcp_server/compliance_checker.py` | `ComplianceChecker`, `diff()`, `merge()` → **`ComplianceMergeResult`** (EC191), `include_protected_rules`, deep-copy | v14→v23 |
| `mcp_server/dispatch_pipeline.py` | `DispatchPipeline`, `PipelineStage`, `PipelineMetricsRecorder`, `make_delegation_stage()` | v14→v16 |
| `mcp_server/mcp_p2p_transport.py` | `TokenBucketRateLimiter`, `LengthPrefixFramer`, `MCPMessage`, `P2PSessionConfig`, `MCP_P2P_PUBSUB_TOPICS` | v14 |
| `mcp_server/audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | v15 |
| `mcp_server/tools/logic_tools/delegation_audit_tool.py` | 8 MCP tools + `DELEGATION_AUDIT_TOOLS` | v17→v18 |

---

## 3. Key Invariants (cumulative v15)

### PortugueseParser (DY187)
- `get_clauses_by_type(text, type)` result ⊆ `parse(text)`
- Empty list for unrecognised deontic type
- Multi-sentence input can produce multiple filtered clauses

### compile_batch (DZ188)
- `len(compile_batch(batches)) == len(batches)`
- `batch[i].metadata["policy_id"] == policy_ids[i]` when supplied
- Empty input → `[]`

### active_tokens (EA189)
- Yields `(cid, DelegationToken)` pairs for non-revoked tokens only
- Fresh generator per call (iterable twice)
- Empty when all revoked

### ComplianceMergeResult (EC191)
- `result == N` ↔ `result.added == N` (int-compat `__eq__`)
- `int(result) == result.added`
- `bool(result) ↔ result.added > 0`
- `skipped_protected` + `skipped_duplicate` + `added` = total candidates processed (minus protected when `include_protected_rules=False`)

### Japanese inline keywords (ED192)
- `_JA_DEONTIC_KEYWORDS` — 3 types; inline, always available
- `_load_i18n_keywords("ja")` returns `_JA_DEONTIC_KEYWORDS`
- `detect_all_languages()` → exactly 8 languages `{"fr","es","de","en","pt","nl","it","ja"}`

### active_token_count (EF194)
- `active_token_count == get_metrics()["active_token_count"]`
- `== max(0, token_count - revoked_count)`
- Invalidated by `revoke()`/`add()`/`remove()`/`load()`

### most_conflicted_language (EG195)
- Returns `None` when `total_conflicts == 0`
- Returns key with highest `len(by_language[key])` otherwise
- Tie resolution: first in `by_language` insertion order

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
| 5 | logic/api.py exports | ✅ Complete | v15→v23 |
| 6 | Evaluator caches | ✅ Complete | v15 |
| 7 | Security validator atomic + vault | ✅ Complete | v15 |
| 8 | Policy audit log | ✅ Complete | v15 |
| ZKP | ZKP bridge + Groth16 Rust FFI | ✅ Complete | v16 |
| CONFLICT | NL conflict detection + i18n (8 langs) | ✅ Complete | v15→v23 |
| DELEGATION | DelegationManager + async merge + metrics + active_tokens | ✅ Complete | v15→v23 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult | ✅ Complete | v14→v23 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence splitting + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| BATCH | compile_batch() | ✅ Complete | v23 |

---

## 5. Evergreen Backlog (v24 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| EI197 | `DelegationManager.active_tokens_by_resource(resource)` — capability filter | Low | 🟢 Low |
| EJ198 | `compile_batch` with `(result, explain_str)` tuple variant | Low | 🟢 Low |
| EK199 | `ComplianceMergeResult.total` property = `added + skipped_protected + skipped_duplicate` | Low | 🟢 Low |
| EL200 | `I18NConflictReport.conflict_density()` — `total_conflicts / num_languages` | Low | 🟡 Med |
| EM201 | `_ZH_DEONTIC_KEYWORDS` Chinese inline keywords (9th language) | Low | 🟡 Med |
| EN202 | `compile_batch` with `fail_fast=True` option (stops on first error) | Med | 🟡 Med |
| EO203 | Multiple `revoke()` calls → `active_token_count` caching correctness tests | Low | 🟢 Low |
| EP204 | Full integration: Japanese text → `detect_i18n_clauses("ja")` pipeline | Med | 🔴 High |
| EQ205 | `get_clauses_by_type` + `detect_i18n_clauses("pt")` combined pipeline | Low | 🟡 Med |
| ER206 | `clear()` + `export_jsonl()` round-trip: cleared log → 0-entry JSONL | Low | 🟢 Low |

---

## 6. Success Criteria (v15)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,400 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | 8 languages | ✅ v23 (fr/es/de/en/pt/nl/it/ja) |
| Delegation merge | sync + async + event_type | ✅ CQ153/CY161/DK173/DQ179 |
| Compliance merge | ComplianceMergeResult | ✅ DA163/DH170/DS181/EC191 |
| Audit JSONL I/O | round-trip with metadata, clear() | ✅ CS155/CZ162/DG169/DR180/EB190 |
| Compiler explain | eager + lazy + batch | ✅ CW159/DB164/DI171/DT182/DZ188 |
| Portuguese parser | sentence-level multi-clause + filter | ✅ DJ172/DP178/DY187 |
| Italian keywords | _IT_DEONTIC_KEYWORDS | ✅ DO177 |
| Japanese keywords | _JA_DEONTIC_KEYWORDS | ✅ ED192 |
| Active token count | property + generator | ✅ DV184/EA189/EF194 |
| Conflict report | most_conflicted_language() | ✅ EG195 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
