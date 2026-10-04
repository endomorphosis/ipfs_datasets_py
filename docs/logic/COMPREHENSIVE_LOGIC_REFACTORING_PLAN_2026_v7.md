# Comprehensive Logic Module Refactoring & Improvement Plan — 2026 v7.0

**Date:** 2026-02-22  
**Status:** 🟢 Active Plan — Supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md`  
**Scope:** `ipfs_datasets_py/logic/` + `mcp_server/`  
**Reference:** See `ARCHITECTURE_UCAN_PIPELINE.md` for full pipeline diagrams.  
**Transport:** MCP+P2P (`/mcp+p2p/1.0.0`) is the canonical transport — gRPC is optional only.

---

## Executive Summary

This is the authoritative logic improvement plan as of 2026-02-22 v15 session.

| Session | Module | Tests Added | Status |
|---------|--------|-------------|--------|
| v13 (NL→UCAN) | CEC/nl, integration, mcp_server | 64 | ✅ Complete |
| v14 (RevocationList/DelegationStore/UCANPolicyBridge) | ucan_delegation.py, ucan_policy_bridge.py | 59 | ✅ Complete |
| v15 (Phases 2b-8) | did_key_manager, temporal_policy, policy_audit_log | 63 | ✅ Complete |
| v16 (Groth16 Rust backend) | zkp/backends, ucan_zkp_bridge | 50 | ✅ Complete |
| v13-MCP (AO99–TDFOL-T2) | interface_descriptor, TDFOL strategies | 77 | ✅ Complete |
| v14-MCP (AT104–BC113) | dispatch_pipeline, p2p_transport, compliance, risk, NL parsers | 79 | ✅ Complete |
| v15-MCP (BD114–BM123 + Transport) | audit_metrics_bridge, DelegationManager, conflict_detector, gRPC fix | 69 | ✅ Complete |

**Grand total v15:** 2,884 + 69 = **2,953 tests** · 8 skip · 0 failing

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
| 3d | NL policy conflict detection | ✅ Complete | `CEC/nl/nl_policy_conflict_detector.py` (BL122) |
| 4 | ZKP→UCAN bridge (simulation) | ✅ Complete | `zkp/ucan_zkp_bridge.py` |
| 4b | Real Groth16 ZKP proof | ✅ Complete | `zkp/backends/groth16.py`, `zkp/backends/groth16_ffi.py` |
| 5 | Import hygiene & blessed API | ✅ Complete | `logic/api.py` |
| 6 | Performance & caching | ✅ Complete | `PolicyEvaluator._decision_cache`, `DelegationEvaluator._chain_cache` |
| 7 | Security hardening | ✅ Complete | `security_validator.py`, `RevocationList.save/load` |
| 8 | Observability & CI | ✅ Complete | `policy_audit_log.py`, `audit_metrics_bridge.py` (BG117) |

### MCP Server Profiles

| Profile | Module | Status |
|---------|--------|--------|
| A: MCP-IDL | `interface_descriptor.py` + `toolset_slice()` | ✅ AO99 complete |
| B: CID-Native Artifacts | `cid_artifacts.py` + `dispatch_with_trace()` | ✅ Complete |
| C: UCAN Delegation | `ucan_delegation.py` + `DelegationStore` + `RevocationList` + `DelegationManager` | ✅ Complete (BH118) |
| D: Temporal Deontic Policy | `temporal_policy.py` + `PolicyRegistry` + caches | ✅ Complete |
| E: P2P Transport + Pipeline | `mcp_p2p_transport.py` + `dispatch_pipeline.py` | ✅ Complete |
| F: Compliance | `compliance_checker.py` | ✅ Complete |
| G: Risk Gate | `risk_scorer.py` | ✅ Complete |
| H: Transport Clarity | `grpc_transport.py` docstring fix | ✅ Transport-Fix complete |
| I: Observability Bridge | `audit_metrics_bridge.py` | ✅ BG117 complete |

### Transport Architecture (Canonical)

```
 ┌─────────────────────────────────────────────────────────┐
 │  MCP Client                                             │
 │       │                                                 │
 │       ▼                                                 │
 │  /mcp+p2p/1.0.0  ◄── CANONICAL (mcp_p2p_transport.py) │
 │       │                                                 │
 │       ├── TokenBucketRateLimiter                        │
 │       ├── LengthPrefixFramer (u32 big-endian)           │
 │       ├── MCPMessage (JSON-RPC 2.0)                     │
 │       └── PubSubBus → MCP_P2P_PUBSUB_TOPICS             │
 │                                                         │
 │  gRPC (OPTIONAL secondary) ◄── grpc_transport.py       │
 │       └── not part of MCP++ pipeline stages             │
 └─────────────────────────────────────────────────────────┘
```

---

## 2. Complete Module Map (v7)

```
ipfs_datasets_py/
├── logic/
│   ├── api.py                          ← Blessed public API ✅
│   ├── ARCHITECTURE.md                 ← Component status matrix
│   ├── ARCHITECTURE_UCAN_PIPELINE.md   ← Full pipeline diagrams ✅
│   │
│   ├── CEC/
│   │   ├── nl/
│   │   │   ├── nl_to_policy_compiler.py          ← Phase 1 + 3b ✅
│   │   │   ├── dcec_to_ucan_bridge.py             ← Phase 1 ✅
│   │   │   ├── grammar_nl_policy_compiler.py      ← Phase 3a ✅
│   │   │   ├── french_parser.py                   ← Phase 3c ✅
│   │   │   ├── spanish_parser.py                  ← Phase 3c ✅
│   │   │   ├── german_parser.py                   ← Phase 3c ✅
│   │   │   ├── language_detector.py               ← Phase 3c ✅
│   │   │   └── nl_policy_conflict_detector.py     ← Phase 3d ✅ NEW (BL122)
│   │   ├── native/                                ← CEC core ✅
│   │   └── provers/                               ← CEC provers ✅
│   │
│   ├── integration/
│   │   ├── nl_ucan_policy_compiler.py  ← Full NL→UCAN pipeline ✅
│   │   ├── ucan_policy_bridge.py       ← DelegationStore + RevocationList bridge ✅
│   │   └── cec_bridge.py              ← CEC ↔ Z3/IPFS/Router bridge ✅ (BM123)
│   │
│   ├── TDFOL/
│   │   ├── security_validator.py       ← Phase 7 hardened ✅
│   │   └── strategies/
│   │       ├── modal_tableaux.py       ← TDFOL-T1 coverage ✅
│   │       └── strategy_selector.py   ← TDFOL-T2 coverage ✅
│   │
│   └── zkp/
│       ├── ucan_zkp_bridge.py          ← Phase 4 + 4b (Groth16) ✅
│       ├── backends/
│       │   ├── groth16.py              ← Real Groth16 backend ✅
│       │   └── groth16_ffi.py          ← Rust binary FFI ✅
│       └── GROTH16_INTEGRATION_PLAN_2026.md
│
├── mcp_server/
│   ├── dispatch_pipeline.py            ← AT104 ✅
│   ├── mcp_p2p_transport.py            ← AU105 ✅ (CANONICAL TRANSPORT)
│   ├── compliance_checker.py           ← AV106 ✅
│   ├── risk_scorer.py                  ← AW107 ✅
│   ├── audit_metrics_bridge.py         ← BG117 ✅ NEW
│   ├── policy_audit_log.py             ← Phase 8 ✅
│   ├── did_key_manager.py              ← Phase 2a/2b ✅
│   ├── secrets_vault.py                ← Phase 7 ✅
│   ├── ucan_delegation.py              ← Profile C ✅ + DelegationManager (BH118)
│   ├── temporal_policy.py              ← Profile D ✅
│   ├── interface_descriptor.py         ← Profile A ✅
│   ├── cid_artifacts.py               ← Profile B ✅
│   ├── nl_ucan_policy.py              ← NL policy compiler bridge ✅
│   ├── grpc_transport.py              ← Optional secondary (not primary) ✅ Fixed
│   └── [plan docs]
│
└── processors/
    └── groth16_backend/                ← Rust binary + artifacts ✅
        ├── src/                        ← Rust source (ark-groth16)
        ├── artifacts/v1/ v2/           ← Proving/verifying keys
        └── build.sh                    ← Build convenience script
```

---

## 3. Key Invariants for Future Sessions (updated for v15)

### DelegationManager (NEW in BH118)
- `DelegationManager(path=None)` wraps `DelegationStore(store_path=path)` — note: **not** `path=path`
- `can_invoke()` internally calls `ev.can_invoke_with_revocation()` (revocation checked automatically)
- Evaluator cache is stored in `_evaluator`; set to `None` on `add()` / `remove()` / `load()`
- `revoke_chain(root_cid)` returns count of revoked tokens (1 minimum, even if chain fails to build)
- `get_delegation_manager()` is the process-global singleton (module-level `_global_manager`)

### AuditMetricsBridge (NEW in BG117)
- `attach()` sets `audit_log._sink = self._sink`; must be called AFTER construction
- `audit._sink` is a **bound method**; identity check must use `__func__`: `a._sink.__func__ is b._sink.__func__`
- `forwarded_count` is NOT thread-locked; safe for single-thread use
- `record_tool_call(category, tool, status, latency_seconds=0.0)` — all 4 args required

### NLPolicyConflictDetector (NEW in BL122)
- `_key(clause)` normalises to `"action::resource"` — wildcard resource = `"*"`
- `_actor(clause)` returns wildcard `"*"` when `clause.actor` is `None` or empty
- Wildcard actor on **either** side of perm/prohib → conflict (see `test_wildcard_actor_triggers_conflict`)
- `different_actors_no_conflict` — alice perm + bob prohib → no conflict (non-overlapping sets)
- `to_dict()` keys: conflict_type / action / resource / actors / clause_types / description

### PolicyEvaluator (from v14)
- Use `register_policy()` — **not** `register()`
- `valid_until` boundary is **CLOSED**: `t > valid_until` denies

### DelegationEvaluator (from v14)
- `can_invoke(principal, resource, ability, *, leaf_cid)` — positional args, `leaf_cid` kwarg
- `can_invoke_with_revocation(principal, resource, ability, *, leaf_cid, revocation_list)`

### AuditLog (from v14)
- `record(policy_cid, intent_cid, decision, *, tool, actor)` — keyword-only `tool`/`actor`
- `stats()` returns `by_decision` key (not `decision_counts`)
- `clear()` empties buffer; `total_recorded()` count is NOT reset

---

## 4. Evergreen Backlog (v16 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| BN124 | `DelegationManager.revoke_chain()` — multi-hop chain test | Low | 🔴 High |
| BO125 | `NLPolicyConflictDetector` ↔ `UCANPolicyBridge` integration | Med | 🔴 High |
| BP126 | `audit_metrics_bridge.py` Prometheus HTTP server smoke test | Low | 🟡 Med |
| BQ127 | Multi-language conflict detection (French/Spanish/German) | Med | 🟡 Med |
| BR128 | `DelegationManager` + `PolicyAuditLog` — audit every can_invoke() | Low | 🟡 Med |
| BS129 | `dispatch_pipeline.py` + `DelegationManager` as a stage | Med | 🟡 Med |
| BT130 | Groth16 circuit_version=2 trace + witness schema v2 | High | 🟢 Low |
| BU131 | `cec_bridge.py` Z3 mock path → 95%+ coverage | Low | 🟡 Med |
| BV132 | CI: GitHub Actions for logic tests + mcp tests | Med | 🟡 Med |
| BW133 | `logic/api.py` — add DelegationManager + conflict_detector exports | Low | 🟡 Med |
| BX134 | `nl_policy_conflict_detector.py` — report conflicts as policy warnings | Med | 🟡 Med |
| BY135 | `DelegationManager.save_encrypted(password)` — AES-256-GCM store | High | 🟢 Low |

---

## 5. Success Criteria

### Code Quality
- All new production modules: stdlib-only (no hard external deps)
- All new classes: docstrings + type hints
- No circular imports in `logic/` or `mcp_server/`
- MCP+P2P is the canonical transport; gRPC secondary status documented

### Test Coverage
- All new modules: ≥80% line coverage
- All new integration points: smoke test + edge case

### Security
- No secrets committed to repo
- All file writes: `0o600` permissions
- Compliance + Risk: fail-closed by default
- DelegationManager: revocation checked before chain evaluation

### Documentation
- `MASTER_IMPROVEMENT_PLAN_2026_v15.md` — v15 sessions documented
- `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md` (this file) — current state
- `grpc_transport.py` — prominently marked as optional secondary transport
