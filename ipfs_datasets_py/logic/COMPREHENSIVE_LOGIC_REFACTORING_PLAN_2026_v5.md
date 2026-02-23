# Comprehensive Logic Module Refactoring & Improvement Plan — 2026 v5.0

**Date:** 2026-02-22  
**Status:** 🟢 Active Plan — Supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v4.md`  
**Scope:** `ipfs_datasets_py/logic/` + `mcp_server/`  
**Reference:** See `ARCHITECTURE_UCAN_PIPELINE.md` for full pipeline diagrams.

---

## Executive Summary

This is the authoritative logic improvement plan as of 2026-02-22 v13 session.

| Session | Module | Tests Added | Status |
|---------|--------|-------------|--------|
| v13 (NL→UCAN) | CEC/nl, integration, mcp_server | 64 | ✅ Complete |
| v14 (RevocationList/DelegationStore/UCANPolicyBridge) | ucan_delegation.py, ucan_policy_bridge.py | 59 | ✅ Complete |
| v15 (Phases 2b-8) | did_key_manager, temporal_policy, policy_audit_log | 63 | ✅ Complete |
| v16 (Groth16 Rust backend) | zkp/backends, ucan_zkp_bridge | 50 | ✅ Complete |
| v13-MCP (AO99–AS103/AI93/TDFOL-T1/T2) | interface_descriptor, grpc_transport, prometheus, otel, TDFOL strategies | 77 | ✅ Complete |

**Grand total session v13:** 2,728 + 77 = **2,805 tests** · 0 failing

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
| 4 | ZKP→UCAN bridge (simulation) | ✅ Complete | `zkp/ucan_zkp_bridge.py` |
| 4b | Real Groth16 ZKP proof | ✅ Complete | `zkp/backends/groth16.py`, `zkp/backends/groth16_ffi.py` |
| 5 | Import hygiene & blessed API | ✅ Complete | `logic/api.py` |
| 6 | Performance & caching | ✅ Complete | `PolicyEvaluator._decision_cache`, `DelegationEvaluator._chain_cache` |
| 7 | Security hardening | ✅ Complete | `security_validator.py`, `RevocationList.save/load` |
| 8 | Observability & CI | ✅ Complete | `policy_audit_log.py` |

### MCP Server Phases

| Profile | Module | Status |
|---------|--------|--------|
| A: MCP-IDL | `interface_descriptor.py` + `toolset_slice()` | ✅ AO99 complete |
| B: CID-Native Artifacts | `cid_artifacts.py` + `dispatch_with_trace()` | ✅ Complete |
| C: UCAN Delegation | `ucan_delegation.py` + `DelegationStore` + `RevocationList` | ✅ Complete |
| D: Temporal Deontic Policy | `temporal_policy.py` + `PolicyRegistry` + caches | ✅ Complete |
| E: P2P Transport | `mcp_p2p_transport.py` + `dispatch_pipeline.py` | ✅ Complete |

### TDFOL Strategy Phases

| Module | Coverage Before | Coverage After | Status |
|--------|----------------|----------------|--------|
| `strategies/modal_tableaux.py` | ~74% | ~90% (TDFOL-T1) | ✅ v13 |
| `strategies/strategy_selector.py` | ~85% | ~95% (TDFOL-T2) | ✅ v13 |
| `strategies/cec_delegate.py` | ~88% | ~88% (pending) | 🔶 v14 candidate |
| `strategies/forward_chaining.py` | ~95% | ~95% | ✅ No gaps |
| `TDFOL/security_validator.py` | ~70% | ~92% (v15) | ✅ v15 |

---

## 2. New in v5.0 (Session v13-MCP / TDFOL-T1/T2)

### AO99 — toolset_slice() (Profile A §7)

**`mcp_server/interface_descriptor.py`** new function:

```python
def toolset_slice(
    cids: List[str],
    budget: Optional[int] = None,
    sort_fn: Optional[Any] = None,
) -> List[str]:
    """Budget-bounded CID slice, optionally re-ranked by sort_fn."""
```

- `sort_fn` key callable; sorted ascending (lowest = most preferred)
- `budget=None` → no truncation
- `budget=0` → empty list

### TDFOL-T1 — ModalTableauxStrategy

**New tests** in `tests/unit_tests/logic/test_v13_tdfol_strategy_coverage.py`:
- `_prove_basic_modal(formula_in_KB, ...)` → `ProofStatus.PROVED` + proof step
- `_prove_basic_modal(formula_not_in_KB, ...)` → `ProofStatus.UNKNOWN`
- `estimate_cost()` variants: simple (2.0), nested temporal (4.0), mixed (3.0)
- `get_priority()` → 80, > ForwardChaining priority
- `_has_deontic_operators`, `_has_temporal_operators`, `_has_nested_temporal`

### TDFOL-T2 — StrategySelector

**New tests** in `tests/unit_tests/logic/test_v13_tdfol_strategy_coverage.py`:
- `add_strategy()` + re-sort by priority
- `select_multiple(max_strategies=N)` length and ordering
- `_get_fallback_strategy()` raises ValueError when strategies=[]

---

## 3. Outstanding Work (v14 Candidates)

### Logic Layer

| ID | Module | Work Item | Priority |
|----|--------|-----------|----------|
| BA111 | `integration/cec_bridge.py` | 95%+ coverage (currently ~85%) | High |
| BB112 | `zkp/` | Groth16 circuit_version=2 trace end-to-end | Medium |
| BC113 | `CEC/nl/` | Multi-language NL policy (FR/DE/ES parsers) | Medium |
| BD114 | `TDFOL/strategies/cec_delegate.py` | 88%→95% coverage | Medium |
| BE115 | `TDFOL/` | `_select_modal_logic_type` broken import fix | Low |
| BF116 | `CEC/nl/tdfol_nl_preprocessor.py` | 60%→75% (requires spaCy) | Deferred |
| BG117 | `integration/proof_cache.py` | Add TTL expiry tests | Low |

### MCP Server Layer

| ID | Module | Work Item | Priority |
|----|--------|-----------|----------|
| AT104 | `dispatch_pipeline.py` | Stage-skip metrics + PipelineMetricsRecorder | High |
| AU105 | `mcp_p2p_transport.py` | TokenBucketRateLimiter conformance tests | Medium |
| AV106 | `compliance_checker.py` | Custom rule registration + removal | Medium |
| AW107 | `risk_scorer.py` | `score_and_gate()` full round-trip | Medium |
| AX108 | `policy_audit_log.py` | Sink callable + JSONL file + stats | Medium |
| AY109 | `did_key_manager.py` | `rotate_key()` + delegation chain migration | Medium |
| AZ110 | `secrets_vault.py` | `.enc` path encrypted-at-rest round-trip | Low |

---

## 4. Architecture Reference

See `ARCHITECTURE_UCAN_PIPELINE.md` for full ASCII-art diagrams covering:

1. NL→Policy→UCAN pipeline (primary flow)
2. DID-signing track (with py-ucan JWT output)
3. ZKP evidence track (Groth16 BN254 + fallback simulation)
4. Temporal evaluation (closed-world, prohibition-first)
5. Delegation chain + revocation (DelegationStore + RevocationList)
6. Audit log (ring buffer + JSONL sink)
7. Module map

---

## 5. Module Inventory

### New Modules Added (v13–v16 sessions)

| Module | Purpose |
|--------|---------|
| `logic/CEC/nl/grammar_nl_policy_compiler.py` | Grammar-driven NL→PolicyClause (fallback) |
| `logic/CEC/nl/dcec_to_ucan_bridge.py` | DCEC formula→UCAN DelegationToken |
| `logic/CEC/nl/nl_to_policy_compiler.py` | NL→DCEC compiler (Stage 1 + 1b) |
| `logic/integration/nl_ucan_policy_compiler.py` | Full NL→UCAN end-to-end |
| `logic/integration/ucan_policy_bridge.py` | UCANPolicyBridge + SignedPolicyResult |
| `logic/zkp/ucan_zkp_bridge.py` | ZKP proof→DelegationToken+ZKPCapabilityEvidence |
| `logic/zkp/backends/groth16.py` | Python ZKP backend (Groth16 via Rust subprocess) |
| `logic/zkp/backends/groth16_ffi.py` | FFI helper: invoke `groth16` Rust binary |
| `mcp_server/did_key_manager.py` | Ed25519 DID:key + UCAN minting + signing |
| `mcp_server/secrets_vault.py` | HKDF-SHA256→AES-256-GCM secrets vault |
| `mcp_server/ucan_delegation.py` | UCAN Delegation Chain + DelegationStore + RevocationList |
| `mcp_server/interface_descriptor.py` | MCP-IDL Profile A + `toolset_slice()` |
| `mcp_server/cid_artifacts.py` | CID-Native Artifacts Profile B |
| `mcp_server/temporal_policy.py` | Temporal Deontic Policy Profile D + PolicyRegistry |
| `mcp_server/policy_audit_log.py` | Policy evaluation audit trail (ring buffer + JSONL) |
| `mcp_server/dispatch_pipeline.py` | DispatchPipeline (5 opt-in stages) |
| `mcp_server/mcp_p2p_transport.py` | P2P Transport Profile E + PubSubBus |
| `mcp_server/event_dag.py` | EventDAG (strict/non-strict causal append) |
| `mcp_server/risk_scorer.py` | RiskScorer (tool×trust×params) |
| `mcp_server/compliance_checker.py` | ComplianceChecker (6 built-in rules) |

---

## 6. Key Invariants for Future Sessions

1. **PolicyEvaluator** uses `register_policy()` not `register()`; `_policies` keyed by `policy_cid`
2. **IntentObject** has only `tool` + `input_cid` + `interface_cid` (no `issuer`/`params`)
3. **valid_until** boundary is CLOSED: `t > valid_until` → expired; `t == valid_until` → valid
4. **DelegationEvaluator.can_invoke()** requires `leaf_cid=` keyword arg
5. **RevocationList** is `set[str]` (type hint); `.save()` 0o600; `.enc` path → vault encryption
6. **ZKPToUCANBridge** emits `UserWarning` for simulation; silent for real Groth16
7. **GrammarNLPolicyCompiler** returns `GrammarCompilationResult` (not `CompiledUCANPolicy`)
8. **toolset_slice()** sorts ascending (lowest key = most preferred); budget is pre-sort
9. **ModalTableauxStrategy.estimate_cost()**: base=2.0; nested_temporal×2.0; mixed×1.5
10. **StrategySelector**: strategies always sorted by priority descending after `add_strategy()`
