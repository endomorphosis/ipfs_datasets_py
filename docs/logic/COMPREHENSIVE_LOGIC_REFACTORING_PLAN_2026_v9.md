# COMPREHENSIVE LOGIC REFACTORING PLAN 2026 — v9
**Status:** All 8 phases complete through v17 · v18 candidates listed
**Tests:** 3,073 total · 0 failing
**Supersedes:** v8 (2026-02-22)

---

## 1. Phase Status (All Complete)

| Phase | Description | Status | Deliverables |
|-------|-------------|--------|--------------|
| 1 | NL→UCAN pipeline | ✅ | `nl_to_policy_compiler.py`, `dcec_to_ucan_bridge.py`, `nl_ucan_policy_compiler.py` |
| 2 | DID-signed UCAN tokens | ✅ | `did_key_manager.py`, `ucan_policy_bridge.compile_and_sign()` |
| 3 | Grammar-based NL parsing | ✅ | `grammar_nl_policy_compiler.py`, Stage-1b fallback in NLToDCECCompiler |
| 4 | ZKP→UCAN bridge (simulation) | ✅ | `zkp/ucan_zkp_bridge.py`, Groth16 backend (real Groth16 enabled by `IPFS_DATASETS_ENABLE_GROTH16=1`) |
| 5 | Blessed API (`logic/api.py`) | ✅ | 87 symbols in `__all__`; conditional extensions for delegation, conflict, i18n |
| 6 | Performance & caching | ✅ | `PolicyEvaluator._decision_cache`, `DelegationEvaluator._chain_cache` |
| 7 | Security hardening | ✅ | Atomic `_acquire_concurrent_slot()`, proof hash excludes metadata, `RevocationList` AES-256-GCM |
| 8 | Observability & CI | ✅ | `policy_audit_log.py`, `audit_metrics_bridge.py`, `AuditEntry`, JSONL sink |

---

## 2. Module Map (v9)

### `logic/` core

| File | Key symbols | v17 additions |
|------|-------------|---------------|
| `api.py` | 87 `__all__` symbols | `detect_i18n_conflicts`, `I18NConflictResult` (CD140/CB138) |
| `CEC/nl/nl_policy_conflict_detector.py` | `NLPolicyConflictDetector`, `PolicyConflict`, `detect_conflicts` | `detect_and_warn()` (BX134), `detect_i18n_conflicts()`, `I18NConflictResult` (CB138) |
| `CEC/nl/grammar_nl_policy_compiler.py` | `GrammarNLPolicyCompiler`, `GrammarCompilationResult` | — |
| `CEC/nl/french_parser.py` | `FrenchParser`, `get_french_deontic_keywords` | — |
| `CEC/nl/spanish_parser.py` | `SpanishParser`, `get_spanish_deontic_keywords` | — |
| `CEC/nl/german_parser.py` | `GermanParser`, `get_german_deontic_keywords` | — |
| `integration/ucan_policy_bridge.py` | `UCANPolicyBridge`, `BridgeCompileResult`, `BridgeEvaluationResult` | `evaluate_with_manager()` (BZ136) |

### `mcp_server/` extensions

| File | Key symbols | v17 additions |
|------|-------------|---------------|
| `ucan_delegation.py` | `DelegationManager`, `DelegationStore`, `RevocationList`, `DelegationChain` | `to_ascii_tree()`, `__str__`, `__len__` on `DelegationChain` (CC139) |
| `dispatch_pipeline.py` | `DispatchPipeline`, `PipelineMetricsRecorder`, `PipelineStage` | `audit_log=` param in both (CA137, CE141) |
| `policy_audit_log.py` | `PolicyAuditLog`, `AuditEntry`, `get_audit_log` | — |
| `audit_metrics_bridge.py` | `AuditMetricsBridge`, `connect_audit_to_prometheus` | — |
| `tools/logic_tools/delegation_audit_tool.py` | 7 MCP tools + `DELEGATION_AUDIT_TOOLS` | **NEW** (CH144) |

---

## 3. Key Invariants (cumulative v9)

### `detect_and_warn()`
- Emits one `UserWarning` per conflict (not per clause)
- Audit entries: `decision="deny"`, `actor="conflict_detector"`, `intent_cid="conflict:<conflict_type>"`
- Silently skips audit entry when `audit_log.record()` raises `TypeError/AttributeError/ValueError`

### `detect_i18n_conflicts()`
- Keyword scan only — **no full clause compilation**
- Supported languages: `"fr"` (French), `"es"` (Spanish), `"de"` (German)
- Unsupported language codes → empty `I18NConflictResult` (no error raised)
- `has_simultaneous_conflict = has_permission AND has_prohibition`
- `matched_*_keywords` lists contain all matching keywords, not just the first

### `DelegationChain.to_ascii_tree()`
- Empty chain → literal string `"(empty chain)"`
- 1 token → `└─[0] …` (last-row corner only)
- N > 1 tokens → `├─[0..N-2] …` + `└─[N-1] …`
- CID is truncated to 12 chars + `…` when longer
- `__str__` is a direct alias for `to_ascii_tree()`

### `UCANPolicyBridge.evaluate_with_manager()`
- `manager=None` → same result as `evaluate()` (fallback)
- Revocation check via `manager.is_revoked(leaf_cid)` is the **first gate**
- UCAN chain check uses `manager.can_invoke(actor, …)` — includes revocation internally
- `leaf_cid=None` skips both revocation and UCAN chain checks

### `DispatchPipeline(audit_log=…)`
- Records **only executed** (non-skipped) stages
- `policy_cid = "pipeline:<stage_name>"`, `intent_cid = "pipeline_intent"`
- `tool` = `intent.get("tool", stage.name)`, `actor` = `intent.get("actor", "unknown")`
- Audit errors caught as `(TypeError, AttributeError, ValueError)` — logged as WARNING

### `PipelineMetricsRecorder(audit_log=…)`
- Records one summary entry per `record_run()` call
- `policy_cid = "pipeline:<namespace>:run"`, `intent_cid = "run:<total_runs>"`
- Counters (`total_runs`, `total_allowed`, `total_denied`) still increment even when audit fails

### `delegation_audit_tool`
- All 7 tools return `{"status": "ok", …}` on success, `{"status": "error", "error": str}` on failure
- `delegation_add_token` uses `DelegationToken(expiry=now + lifetime_seconds, …)` — not `issued_at`
- `delegation_can_invoke` calls `DelegationManager.can_invoke_audited()` (writes to global audit log)
- `delegation_revoke_chain` returns `revoked_count >= 1` even for unknown CIDs (BN124 fix)

---

## 4. Evergreen Backlog (v18 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| CI145 | `delegation_audit_tool` — `delegation_chain_ascii` tool | Low | 🟡 Med |
| CJ146 | `NLPolicyConflictDetector.detect_i18n_clauses()` — full FR/ES/DE clause compilation + detect | High | 🔴 High |
| CK147 | `UCANPolicyBridge.evaluate_audited_with_manager()` | Low | 🟡 Med |
| CL148 | `FilePolicyStore`/`IPFSPolicyStore` encrypted-at-rest policy bundles | Med | 🟡 Med |
| CM149 | Prometheus `mcp_delegation_chain_depth_max` gauge in `DelegationManager` | Low | 🟡 Med |
| CN150 | `logic/api.py` `evaluate_with_manager` convenience wrapper | Low | 🟢 Low |
| CO151 | TDFOL NL spaCy integration tests (skip-guarded) | Med | 🟡 Med |
| CP152 | Groth16 Phase 4b — `circuit_version=2` + EVM verifier stub | High | 🟢 Low |

---

## 5. Success Criteria (v9)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,073 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DelegationManager | Full lifecycle + ASCII | ✅ CC139 |
| Conflict detection | detect + warn + i18n | ✅ BX134 / CB138 |
| Bridge DelegationManager | evaluate_with_manager | ✅ BZ136 |
| Audit ↔ Pipeline | Both integrate | ✅ CA137 / CE141 |
| MCP tools | Delegation + audit | ✅ CH144 (7 tools) |
| API blessed | 87 symbols | ✅ CD140 |
