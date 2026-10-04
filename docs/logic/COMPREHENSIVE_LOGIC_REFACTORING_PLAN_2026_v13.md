# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v13

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Supersedes:** v12
**Status:** ✅ v13 Complete — 3,283 total tests, 0 failing

---

## 1. Executive Summary

This version supersedes v12 and incorporates all v21 session deliverables:
- **DG169**: `import_jsonl()` round-trip fixed (skips `__metadata__` header)
- **DH170**: `ComplianceChecker.merge(include_protected_rules=False)` — guards non-removable rules
- **DI171**: `compile_explain_iter()` — lazy line-by-line explanation iterator
- **DJ172**: New `portuguese_parser.py` — no-dep keyword-based parser
- **DK173**: `DelegationManager.merge_and_publish_async()` — async pubsub variant
- **DL174**: Full E2E merge+export+import round-trip tests
- **DM175**: `diff()` + `merge()` combined idempotency verified
- **DN176**: Dutch (`"nl"`) inline keywords — `detect_all_languages()` now covers 6 languages

---

## 2. Module Inventory (cumulative)

### Core logic modules

| Module | Key Additions | Version Added |
|--------|--------------|---------------|
| `logic/api.py` | `NLUCANPolicyCompiler`, `NLUCANCompilerResult`, `PolicyAuditLog`, `DelegationManager`, `NLPolicyConflictDetector`, `detect_conflicts`, `detect_all_languages`, `I18NConflictReport`, `detect_i18n_clauses`, `evaluate_with_manager`, `I18NConflictReport` (6 langs) | v13→v21 |
| `logic/TDFOL/security_validator.py` | `_acquire_concurrent_slot()`, proof hash excludes metadata | v15 |
| `logic/integration/ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult.conflicts`, `evaluate_with_manager`, `evaluate_audited_with_manager` | v14→v18 |
| `logic/integration/nl_ucan_policy_compiler.py` | `NLUCANPolicyCompiler`, `compile_explain()`, **`compile_explain_iter()`** (DI171) | v14→v21 |
| `logic/CEC/nl/nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `detect_conflicts`, `detect_i18n_conflicts`, `detect_i18n_clauses`, `_EN_DEONTIC_KEYWORDS`, **`_NL_DEONTIC_KEYWORDS`** (DN176) | v15→v21 |
| `logic/CEC/nl/french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | v13 |
| `logic/CEC/nl/spanish_parser.py` | `SpanishParser`, `get_spanish_deontic_keywords` | v13 |
| `logic/CEC/nl/german_parser.py` | `GermanParser`, `get_german_deontic_keywords` | v13 |
| **`logic/CEC/nl/portuguese_parser.py`** (**NEW — DJ172**) | `PortugueseParser`, `PortugueseClause`, `get_portuguese_deontic_keywords` | v21 |
| `logic/zkp/ucan_zkp_bridge.py` | `ZKPToUCANBridge`, Groth16 auto-provision | v16 |
| `logic/zkp/backends/groth16_ffi.py` | `setup(version, seed)`, `artifacts_exist()` | v16 |

### MCP server modules

| Module | Key Additions | Version Added |
|--------|--------------|---------------|
| `mcp_server/policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `export_jsonl(metadata)`, **`import_jsonl()` skips `__metadata__`** (DG169) | v15→v21 |
| `mcp_server/ucan_delegation.py` | `DelegationManager`, `merge()`, `merge_and_publish()`, **`merge_and_publish_async()`** (DK173) | v15→v21 |
| `mcp_server/compliance_checker.py` | `ComplianceChecker`, `diff()`, **`merge(include_protected_rules=False)`** (DH170) | v14→v21 |
| `mcp_server/dispatch_pipeline.py` | `DispatchPipeline`, `PipelineStage`, `PipelineMetricsRecorder`, `make_delegation_stage()` | v14→v16 |
| `mcp_server/mcp_p2p_transport.py` | `TokenBucketRateLimiter`, `LengthPrefixFramer`, `MCPMessage`, `P2PSessionConfig`, `MCP_P2P_PROTOCOL_ID` | v14 |
| `mcp_server/audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | v15 |
| `mcp_server/tools/logic_tools/delegation_audit_tool.py` | 8 MCP tools + `DELEGATION_AUDIT_TOOLS` | v17→v18 |

---

## 3. Key Invariants (cumulative v13)

### `import_jsonl()` round-trip (DG169)
- Lines with `"__metadata__"` key are silently skipped (DEBUG logged)
- Return value counts audit entries only — metadata lines excluded
- Full round-trip: `export_jsonl(path, metadata=M)` → `import_jsonl(path)` → count == original entries

### `ComplianceChecker.merge(include_protected_rules=False)` (DH170)
- Default: skips rules with `removable=False` — they are "protected" built-ins
- `include_protected_rules=True`: copies all rules regardless of `removable` flag
- Still idempotent: calling merge twice never adds duplicates
- Symmetric relationship with `diff()` preserved (with caveat: diff counts all IDs, merge may skip non-removable)

### `compile_explain_iter()` (DI171)
- Returns a `types.GeneratorType` (lazy — compiled once, then lines yielded)
- `"\n".join(list(iter)) == result.explain().rstrip("\n")`
- Partially consumable without error (iterator pattern)

### `PortugueseParser` (DJ172)
- Zero external dependencies — pure keyword matching
- `parse(text) -> List[PortugueseClause]`
- At most one clause per deontic type per parse call
- `get_portuguese_deontic_keywords()` registered in `_I18N_KEYWORD_LOADERS["pt"]`

### `merge_and_publish_async()` (DK173)
- Coroutine (`asyncio.iscoroutinefunction == True`)
- Prefers `publish_async` (coroutine) over `publish` (sync) on pubsub
- Exceptions from pubsub swallowed at DEBUG — never raises to caller
- Payload identical to `merge_and_publish()`: `{"type":"merge","added":N,"total":M,"metrics":{...}}`

### `detect_all_languages()` 6-language (DN176)
- Always returns keys for all 6 languages: `{"fr","es","de","en","pt","nl"}`
- English and Dutch use inline tables → always available, no import needed
- Portuguese requires `portuguese_parser.py` → ImportError → empty list
- French/Spanish/German use existing parser modules → ImportError → empty list
- Old `>= {"fr","es","de","en"}` set-subset tests remain valid

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
| 5 | logic/api.py exports | ✅ Complete | v15→v21 |
| 6 | Evaluator caches | ✅ Complete | v15 |
| 7 | Security validator atomic + vault | ✅ Complete | v15 |
| 8 | Policy audit log | ✅ Complete | v15 |
| ZKP | ZKP bridge + Groth16 Rust FFI | ✅ Complete | v16 |
| CONFLICT | NL conflict detection + i18n (6 langs) | ✅ Complete | v15→v21 |
| DELEGATION | DelegationManager + async merge | ✅ Complete | v15→v21 |
| COMPLIANCE | ComplianceChecker + include_protected_rules | ✅ Complete | v14→v21 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser | ✅ Complete | v21 |

---

## 5. Evergreen Backlog (v22 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| DO177 | `detect_all_languages()` — add `"it"` (Italian) inline keywords | Low | 🟡 Med |
| DP178 | `PortugueseParser.parse()` — sentence-level splitting + multi-clause extraction | Med | 🟡 Med |
| DQ179 | `merge_and_publish_async()` — include `PubSubEventType.RECEIPT_DISSEMINATE` | Low | 🟢 Low |
| DR180 | `import_jsonl()` — `max_entries` clipping test across large files | Low | 🟡 Med |
| DS181 | `ComplianceChecker.merge(include_protected_rules=True)` — deep copy rules to avoid mutation | Med | 🟡 Med |
| DT182 | `compile_explain_iter()` — `max_lines=None` truncation parameter | Low | 🟢 Low |
| DU183 | `detect_i18n_conflicts("nl")` — obligation keyword coverage test | Low | 🟢 Low |
| DV184 | `DelegationManager.get_metrics()` — `active_token_count` (non-revoked) | Med | 🔴 High |
| DW185 | `logic/api.py` — `compile_explain_iter` re-export | Low | 🟢 Low |
| DX186 | Full E2E with 6-language `detect_all_languages()` + real conflict text | Med | 🔴 High |

---

## 6. Success Criteria (v13)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,283 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | All 6 languages | ✅ v21 (fr/es/de/en/pt/nl) |
| Delegation merge | sync + async pubsub | ✅ CQ153/CY161/DK173 |
| Compliance merge | include_protected_rules flag | ✅ DA163/DH170 |
| Audit JSONL I/O | round-trip with metadata | ✅ CS155/CZ162/DG169 |
| Compiler explain | eager + lazy iterator | ✅ CW159/DB164/DI171 |
| Portuguese parser | PortugueseParser | ✅ DJ172 |
| Dutch keywords | _NL_DEONTIC_KEYWORDS | ✅ DN176 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
