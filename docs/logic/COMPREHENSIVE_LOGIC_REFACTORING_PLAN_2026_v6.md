# Comprehensive Logic Module Refactoring & Improvement Plan — 2026 v6.0

**Date:** 2026-02-22  
**Status:** 🟢 Active Plan — Supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md`  
**Scope:** `ipfs_datasets_py/logic/` + `mcp_server/`  
**Reference:** See `ARCHITECTURE_UCAN_PIPELINE.md` for full pipeline diagrams.

---

## Executive Summary

This is the authoritative logic improvement plan as of 2026-02-22 v14 session.

| Session | Module | Tests Added | Status |
|---------|--------|-------------|--------|
| v13 (NL→UCAN) | CEC/nl, integration, mcp_server | 64 | ✅ Complete |
| v14 (RevocationList/DelegationStore/UCANPolicyBridge) | ucan_delegation.py, ucan_policy_bridge.py | 59 | ✅ Complete |
| v15 (Phases 2b-8) | did_key_manager, temporal_policy, policy_audit_log | 63 | ✅ Complete |
| v16 (Groth16 Rust backend) | zkp/backends, ucan_zkp_bridge | 50 | ✅ Complete |
| v13-MCP (AO99–AS103/AI93/TDFOL-T1/T2) | interface_descriptor, TDFOL strategies | 77 | ✅ Complete |
| v14-MCP (AT104–AZ110+BA111+BC113) | dispatch_pipeline, p2p_transport, compliance, risk, NL parsers | 79 | ✅ Complete |

**Grand total v14:** 2,805 + 79 = **2,884 tests** · 8 skip · 0 failing

---

## 1. All-Phase Status Table

### UCAN / Policy Phases

| Phase | Description | Status | Key Modules |
|-------|-------------|--------|-------------|
| 1 | Core NL→UCAN pipeline | ✅ Complete | `CEC/nl/nl_to_policy_compiler.py`, `dcec_to_ucan_bridge.py`, `nl_ucan_policy_compiler.py` |
| 2a | DID:key generation + py-ucan integration | ✅ Complete | `did_key_manager.py` |
| 2b | DID-Signed UCAN Tokens | ✅ Complete | `did_key_manager.sign_delegation_token()` |
| 3a | Grammar-based NL fallback | ✅ Complete | `grammar_nl_policy_compiler.py` |
| 3b | Stage 1b NLToDCECCompiler integration | ✅ Complete | `nl_to_policy_compiler.compile_sentence()` |
| 3c | Multi-language NL support (FR/DE/ES) | ✅ Complete | `french_parser.py`, `spanish_parser.py`, `german_parser.py`, `language_detector.py` |
| 4 | ZKP→UCAN bridge (simulation) | ✅ Complete | `zkp/ucan_zkp_bridge.py` |
| 4b | Real Groth16 ZKP proof | ✅ Complete | `zkp/backends/groth16.py`, `zkp/backends/groth16_ffi.py` |
| 5 | Import hygiene & blessed API | ✅ Complete | `logic/api.py` |
| 6 | Performance & caching | ✅ Complete | `PolicyEvaluator._decision_cache`, `DelegationEvaluator._chain_cache` |
| 7 | Security hardening | ✅ Complete | `security_validator.py`, `RevocationList.save/load` |
| 8 | Observability & CI | ✅ Complete | `policy_audit_log.py` |

### MCP Server Profiles

| Profile | Module | Status |
|---------|--------|--------|
| A: MCP-IDL | `interface_descriptor.py` + `toolset_slice()` | ✅ AO99 complete |
| B: CID-Native Artifacts | `cid_artifacts.py` + `dispatch_with_trace()` | ✅ Complete |
| C: UCAN Delegation | `ucan_delegation.py` + `DelegationStore` + `RevocationList` | ✅ Complete |
| D: Temporal Deontic Policy | `temporal_policy.py` + `PolicyRegistry` + caches | ✅ Complete |
| E: P2P Transport + Pipeline | `mcp_p2p_transport.py` + `dispatch_pipeline.py` | ✅ AT104/AU105 complete |
| F: Compliance | `compliance_checker.py` | ✅ AV106 complete |
| G: Risk Gate | `risk_scorer.py` | ✅ AW107 complete |

### Logic Module Coverage Phases

| Module | Coverage Before | Coverage After | Status |
|--------|----------------|----------------|--------|
| `strategies/modal_tableaux.py` | ~74% | ~90% (TDFOL-T1) | ✅ v13-MCP |
| `strategies/strategy_selector.py` | ~85% | ~95% (TDFOL-T2) | ✅ v13-MCP |
| `TDFOL/security_validator.py` | ~70% | ~92% (v15) | ✅ v15 |
| `integration/cec_bridge.py` | ~65% | ~82% (BA111) | ✅ v14-MCP |
| `CEC/nl/french_parser.py` | ~60% | ~75% (BC113) | ✅ v14-MCP |
| `CEC/nl/spanish_parser.py` | ~60% | ~75% (BC113) | ✅ v14-MCP |
| `CEC/nl/german_parser.py` | ~60% | ~75% (BC113) | ✅ v14-MCP |
| `CEC/nl/language_detector.py` | ~72% | ~88% (BC113) | ✅ v14-MCP |

---

## 2. Module Map (v6 — complete picture)

```
ipfs_datasets_py/
├── logic/
│   ├── api.py                          ← Blessed public API ✅
│   ├── ARCHITECTURE.md                 ← Component status matrix
│   ├── ARCHITECTURE_UCAN_PIPELINE.md   ← Full pipeline diagrams ✅
│   │
│   ├── CEC/
│   │   ├── nl/
│   │   │   ├── nl_to_policy_compiler.py     ← Phase 1 + 3b ✅
│   │   │   ├── dcec_to_ucan_bridge.py       ← Phase 1 ✅
│   │   │   ├── grammar_nl_policy_compiler.py ← Phase 3a ✅
│   │   │   ├── french_parser.py             ← Phase 3c ✅
│   │   │   ├── spanish_parser.py            ← Phase 3c ✅
│   │   │   ├── german_parser.py             ← Phase 3c ✅
│   │   │   └── language_detector.py         ← Phase 3c ✅
│   │   ├── native/                          ← CEC core ✅
│   │   └── provers/                         ← CEC provers ✅
│   │
│   ├── integration/
│   │   ├── nl_ucan_policy_compiler.py  ← Full NL→UCAN pipeline ✅
│   │   ├── ucan_policy_bridge.py       ← DelegationStore + RevocationList bridge ✅
│   │   └── cec_bridge.py              ← CEC ↔ Z3/IPFS/Router bridge ✅
│   │
│   ├── TDFOL/
│   │   ├── security_validator.py       ← Phase 7 hardened ✅
│   │   └── strategies/
│   │       ├── modal_tableaux.py       ← TDFOL-T1 coverage ✅
│   │       └── strategy_selector.py    ← TDFOL-T2 coverage ✅
│   │
│   └── zkp/
│       ├── ucan_zkp_bridge.py          ← Phase 4 + 4b (Groth16) ✅
│       ├── backends/
│       │   ├── groth16.py              ← Real Groth16 backend ✅
│       │   └── groth16_ffi.py          ← Rust binary FFI ✅
│       └── GROTH16_INTEGRATION_PLAN_2026.md
│
├── mcp_server/
│   ├── dispatch_pipeline.py            ← AT104 NEW ✅
│   ├── mcp_p2p_transport.py            ← AU105 NEW ✅
│   ├── compliance_checker.py           ← AV106 NEW ✅
│   ├── risk_scorer.py                  ← AW107 NEW ✅
│   ├── policy_audit_log.py             ← Phase 8 ✅
│   ├── did_key_manager.py              ← Phase 2a/2b ✅
│   ├── secrets_vault.py                ← Phase 7 ✅
│   ├── ucan_delegation.py              ← Profile C ✅
│   ├── temporal_policy.py              ← Profile D ✅
│   ├── interface_descriptor.py         ← Profile A ✅
│   └── cid_artifacts.py               ← Profile B ✅
│
└── processors/
    └── groth16_backend/                ← Rust binary + artifacts ✅
        ├── src/                        ← Rust source (ark-groth16)
        ├── artifacts/v1/ v2/           ← Proving/verifying keys
        └── build.sh                    ← Build convenience script
```

---

## 3. Key Invariants for Future Sessions

These are the most important "gotchas" discovered across v13–v14 sessions:

### PolicyEvaluator
- Use `register_policy()` — **not** `register()`
- `_policies` is keyed by `policy_cid` (not `policy_id`)
- `valid_until` boundary is **CLOSED**: `t > valid_until` denies; `t == valid_until` is still valid
- `_decision_cache` key is `(policy_cid, intent_cid, actor)`

### DelegationEvaluator
- `can_invoke()` requires `leaf_cid=` kwarg
- `build_chain()` follows `proof_cid` root-first (reversed)
- `Capability.matches()` requires BOTH resource AND ability to match ('*' on either side)

### IntentObject
- Has only `interface_cid`, `tool`, `input_cid` fields — **no** `actor`/`params`/`context`

### ComplianceChecker
- `tool_name_convention` rule has `removable=False` (cannot be removed)
- `fail_fast=True` stops after first failure — report has only 1 result

### RiskScorer
- `score_and_gate()` raises `RiskGateError` if `score > max_acceptable_risk` (strict >)
- `trust_factor = 1 - trust_bonus` where `trust_bonus = min(0.5, level)`
- `complexity_penalty = min(0.2, len(params) * 0.02)`

### DispatchPipeline
- `short_circuit=True` (default): remaining enabled stages appear in `stages_skipped` after denial
- `fail_open=True` (default per stage): handler exception → allowed=True
- `PipelineMetricsRecorder.record_stage(skipped=True)` does NOT increment `stage_executions`

### DIDKeyManager / SecretsVault
- All cryptographic operations require `py-ucan>=1.0.0` (optional dep)
- Tests that call `export_secret_b64()` / `rotate_key()` / vault `set()`/`get()` MUST use `@pytest.mark.skipif(not _ucan_available(), ...)`
- `total_recorded()` is a **method** — call it with `()`; `clear()` clears buffer but NOT `_total_recorded`

### PolicyAuditLog
- `stats()` returns `by_decision` key (not `decision_counts`)
- `clear()` empties `self._entries` buffer only; `total_recorded()` count does NOT reset

### LanguageDetector
- French detection requires high keyword density (many `le/la/ne/pas/doit/peut` tokens)
- Use `"Il ne doit pas accéder aux fichiers sans autorisation préalable"` for reliable French test

---

## 4. Evergreen Backlog (v15 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| BD114 | `dispatch_pipeline.py` E2E with real compliance + risk handlers | Med | 🔴 High |
| BE115 | `compliance_checker.py` + `dispatch_pipeline.py` integration | Low | 🔴 High |
| BF116 | `risk_scorer.py` + `mcp_p2p_transport.py` rate-limit-per-risk | Med | 🟡 Med |
| BG117 | `policy_audit_log.py` → Prometheus bridge | Low | 🟡 Med |
| BH118 | `ucan_delegation.py` DelegationManager + metrics | Med | 🔴 High |
| BI119 | `did_key_manager.py` rotate_key + chain migration | High | 🔴 High |
| BJ120 | `nl_ucan_policy.py` FilePolicyStore + IPFSPolicyStore | Med | 🟡 Med |
| BK121 | Groth16 circuit_version=2 trace + witness schema v2 | High | 🟢 Low |
| BL122 | `NLUCANPolicyCompiler` conflict detection | Med | 🟡 Med |
| BM123 | `cec_bridge.py` Z3 path (mock Z3) → 95%+ coverage | Low | 🟡 Med |
| BN124 | `strategies/cec_delegate.py` coverage gap | Low | 🟢 Low |
| BO125 | `language_detector.py` edge cases (short text, emojis) | Low | 🟢 Low |
| BP126 | CI integration — GitHub Actions workflow for logic tests | Med | 🟡 Med |
| BQ127 | spaCy NL accuracy (deferred from Phase 3) | High | 🟢 Low |

---

## 5. Success Criteria

### Code Quality
- All new production modules: stdlib-only (no hard external deps)
- All new classes: docstrings + type hints
- No circular imports in `logic/` or `mcp_server/`

### Test Coverage
- All new modules: ≥80% line coverage
- All new integration points: smoke test + edge case

### Security
- No secrets committed to repo
- All file writes: `0o600` permissions
- ZKP: simulation warning always emitted when `IPFS_DATASETS_ENABLE_GROTH16=0`
- Compliance + Risk: fail-closed by default

### Documentation
- Every plan doc is numbered (v1→v6 chain complete)
- `ARCHITECTURE_UCAN_PIPELINE.md` diagrams current with v14 additions
- `GROTH16_INTEGRATION_PLAN_2026.md` current with Phase 4b complete
