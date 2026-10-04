# Comprehensive Logic Module Refactoring & Improvement Plan — 2026 v3.0

**Date:** 2026-02-22  
**Status:** 🟢 Active Plan — Supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md`  
**Scope:** `ipfs_datasets_py/logic/` (287+ Python files, 96k+ LOC, 70+ active docs)  
**Authoritative reference docs:**
- `MASTER_REFACTORING_PLAN_2026.md` (v22.0, Phases 1–8)  
- `NL_UCAN_POLICY_COMPILER_PLAN.md` (v1.0, Phase 1 ✅)
- `EVERGREEN_IMPROVEMENT_PLAN.md` (continuous)

---

## Executive Summary

The `logic/` module is production-ready at ~97% test coverage with **5,600+** passing tests
across TDFOL, CEC, integration, ZKP, FOL, deontic, common, and security layers.

**v3.0 of this plan** focuses on **five strategic pillars** for the 2026 improvement cycle:

1. **NL→UCAN Deontic Compiler** (Phase 1 ✅ complete; Phase 2/3 planned)
2. **DID-Signed UCAN Tokens** (Phase 2 — DelegationStore + RevocationList + real signing)
3. **Grammar-Based NL Parsing** (Phase 3 — upgrade regex→compositional grammar)
4. **ZKP→UCAN Bridge** (Phase 4 — ZKP proof as cryptographic capability evidence)
5. **Import Hygiene & API Surface** (Phase 5 — blessed API, shims, layering enforcement)

---

## 1. Current State Snapshot (2026-02-22)

| Component | Tests | Coverage | Status |
|-----------|-------|----------|--------|
| TDFOL (Phases 1–12) | 1,526+ | ~97% | ✅ Production-ready |
| CEC Native (Phases 1–3) | 450+ | ~97% | ✅ Production-ready |
| CEC NL Parsers | 200+ | ~100% | ✅ All 4 parsers 100% |
| CEC NL Policy Compiler | 64 | ~100% | ✅ Phase 1 complete |
| CEC Grammar NL Compiler | 19 | ~100% | ✅ Complete (v13) |
| Integration Layer | 2,907+ | 99% | ✅ 55 uncovered = dead/symai |
| UCAN Policy Bridge | 59 | ~100% | ✅ New (v14) |
| MCP DelegationStore + RevocationList | 35 | ~100% | ✅ New (v14) |
| Temporal Policy Evaluator | 50+ | ~95% | ✅ Edge cases added (v14) |
| ZKP Module | 35+ | ~85% | ⚠️ Simulation only |
| ZKP→UCAN Bridge (stub) | 25 | ~100% | ⚠️ Simulation only (v13) |
| FOL Converter | ~40 | ~95% | ✅ Production-ready |
| Deontic Converter | ~40 | ~95% | ✅ Production-ready |
| MCP Server B2 Tools | 1,457+ | — | ✅ 53 categories |

---

## 2. Architecture Overview (Updated v3)

```
Natural Language Text
        │
        ▼  [Stage 1: Pattern OR Grammar]
┌────────────────────────────────────────────────────────────────┐
│  CEC NL Layer  (logic/CEC/nl/)                                 │
│                                                                  │
│  ┌─────────────────────┐  ┌──────────────────────────────┐    │
│  │ NLToDCECCompiler    │  │ GrammarNLPolicyCompiler      │    │
│  │ (37 regex patterns) │  │ (DCECEnglishGrammar-driven)  │    │
│  └─────────────────────┘  └──────────────────────────────┘    │
│                                                                  │
│  Output: DeonticFormula(OBLIGATION|PERMISSION|PROHIBITION,      │
│          Predicate, agent, resource, temporal_window)           │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼  [Stage 2: DCEC → Deontic Policy]
┌────────────────────────────────────────────────────────────────┐
│  NLToDCECCompiler  (CEC/nl/nl_to_policy_compiler.py)           │
│  DeonticFormula → PolicyClause → PolicyObject (temporal)       │
└────────────────────────────┬───────────────────────────────────┘
                             │
              ┌──────────────┴────────────────┐
              ▼                               ▼
     [Stage 3a: UCAN stubs]        [Stage 3b: ZKP Evidence]
┌─────────────────────────┐   ┌──────────────────────────────┐
│ DCECToUCANBridge        │   │ ZKPToUCANBridge              │
│ DCEC → DelegationToken  │   │ ZKP proof hash → UCAN caveat │
│ (stub, unsigned)        │   │ (simulation mode, warns)     │
└────────────┬────────────┘   └──────────────┬───────────────┘
             │                               │
             └───────────────┬───────────────┘
                             │
                             ▼  [Stage 4: Integration + DID Signing]
┌────────────────────────────────────────────────────────────────┐
│  UCANPolicyBridge  (logic/integration/ucan_policy_bridge.py)   │
│                                                                  │
│  NLUCANPolicyCompiler (3-stage coordinator)                     │
│  PolicyEvaluator (temporal deontic evaluation)                  │
│  DelegationStore + RevocationList (token persistence)           │
│  DIDKeyManager → real Ed25519 signed tokens (optional)         │
│  SecretsVault → encrypted API key storage                       │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Phase-by-Phase Work Plan

### Phase 1 — Core NL→UCAN Pipeline ✅ COMPLETE (v13 session)

**What was built:**

| Module | Purpose | Tests |
|--------|---------|-------|
| `logic/CEC/nl/nl_to_policy_compiler.py` | NL → DCEC → PolicyClause/PolicyObject | 22 |
| `logic/CEC/nl/dcec_to_ucan_bridge.py` | DCEC formulas → UCAN Capability/DelegationToken | 18 |
| `logic/integration/nl_ucan_policy_compiler.py` | Full 3-stage pipeline coordinator | 24 |
| `mcp_server/tools/logic_tools/nl_ucan_policy_tool.py` | MCP server tools (compile/evaluate/inspect) | — |

**Semantic mapping:**

| DCEC Operator | PolicyClause type | UCAN outcome |
|--------------|------------------|--------------|
| `OBLIGATION` | `"obligation"` | `DelegationToken` (ability: `<action>/execute`) |
| `PERMISSION` | `"permission"` | `DelegationToken` (ability: `<action>/invoke`) |
| `PROHIBITION` | `"prohibition"` | `DenyCapability` (no delegation issued) |

---

### Phase 2 — DID-Signed UCAN Tokens ✅ PARTIAL (v13+v14)

**What was built:**

| Module | Purpose | Tests |
|--------|---------|-------|
| `mcp_server/did_key_manager.py` | Ed25519 DID:key generation/persistence/signing | 43 |
| `mcp_server/secrets_vault.py` | AES-256-GCM encrypted secret storage | included |
| `mcp_server/ucan_delegation.py` + `RevocationList` + `DelegationStore` | Delegation token store + revocation | 35 |
| `logic/integration/ucan_policy_bridge.py` | Integration glue | 59 |

**Remaining work (Phase 2b):**

- [ ] `DIDKeyManager.sign_delegation_token(token)` — sign a stub `DelegationToken` with the DID private key, emitting a real UCAN JWT
- [ ] `UCANPolicyBridge.compile_and_sign(nl_text)` — compile NL → signed DelegationTokens (one per permission)
- [ ] `mcp_server/tools/logic_tools/nl_ucan_policy_tool.py` — expose `nl_sign_policy(nl_text, audience_did)` MCP tool
- [ ] Tests: 15+ for signed token round-trip

**Key design decision:** `py-ucan` is optional. When absent, stub tokens are used. When present, real Ed25519 signatures are produced. This ensures zero hard dependency on `py-ucan` in the `logic/` module.

---

### Phase 3 — Grammar-Based NL Parsing ✅ PARTIAL (v13 session)

**What was built:**

| Module | Purpose | Tests |
|--------|---------|-------|
| `logic/CEC/nl/grammar_nl_policy_compiler.py` | `GrammarNLPolicyCompiler` (grammar+heuristic) | 19 |

**Current state:**
- Uses `DCECEnglishGrammar` when available for compositional parsing
- Falls back to keyword-based heuristic when grammar unavailable
- `NLToDCECCompiler` (Stage 1) still uses 37 regex patterns

**Remaining work (Phase 3b):**

- [ ] Integrate `GrammarNLPolicyCompiler` as the default Stage 1 parser in `NLToDCECCompiler`
  (currently they are separate; regex is still default)
- [ ] Increase NL accuracy: TDFOL 65% → 80%+ for deontic sentences
- [ ] Spanish language support (French/German stubs exist)
- [ ] Test: multilingual policy string round-trip (EN/FR/DE → same clauses)

---

### Phase 4 — ZKP→UCAN Bridge ⚠️ SIMULATION ONLY (v13 session)

**What was built:**

| Module | Purpose | Tests |
|--------|---------|-------|
| `logic/zkp/ucan_zkp_bridge.py` | `ZKPToUCANBridge` (ZKP proof → UCAN caveat) | 25 |

**Key constraint:** The ZKP module (`logic/zkp/`) is **simulation-only**. No real zero-knowledge
proofs are generated. The bridge always emits a `UserWarning` to make this clear.

**Remaining work (Phase 4b — requires Groth16 backend):**

- [ ] Real ZKP: enable `IPFS_DATASETS_ENABLE_GROTH16=1` to use Rust FFI backend
- [ ] `ZKPCapabilityEvidence` → real UCAN caveat (proof_hash as verified evidence)
- [ ] Test: end-to-end from TDFOL theorem → ZKP proof → UCAN delegation

---

### Phase 5 — Import Hygiene & Blessed API 🔄 Ongoing

**Goals:**
1. `logic/api.py` — single blessed entry point for all logic module functionality
2. Layering enforcement: `common` + `types` must not import from higher layers
3. Compatibility shims for any moved symbols (with `DeprecationWarning`)
4. "Import quiet" tests: importing `ipfs_datasets_py.logic` must produce no warnings

**Remaining work:**

- [ ] Audit all cross-layer imports: `integration/` must not be imported by `CEC/native/`
- [ ] Add `logic/__init__.py` public API surface (`__all__`)
- [ ] `logic/api.py`: expose `compile_nl_policy`, `evaluate_policy`, `build_delegation_chain`
- [ ] Import-quiet test: `python -c "import ipfs_datasets_py.logic"` produces no output

---

### Phase 6 — Performance & Caching 🔄 Ongoing

**Current:**
- Proof caching: 100–20000x speedup via CID-based cache (CEC + TDFOL)
- Parallel proving: 2–8 workers (TDFOL)

**Remaining work:**

- [ ] `PolicyEvaluator` memoization: cache decision per `(policy_cid, intent_cid, actor)`
- [ ] `DelegationEvaluator` chain assembly cache: avoid re-walking proof_cid links on each call
- [ ] Benchmark: policy evaluation throughput (target: 10,000 evaluations/sec)

---

### Phase 7 — Security Hardening 🔄 Ongoing

**Current:**
- TDFOL security validator: 70% coverage
- ZKP: simulation warnings
- DID key: 0o600 file permissions

**Remaining work:**

- [ ] `TDFOL/security_validator.py` coverage: 70% → 90%
- [ ] `RevocationList`: add persistence (write to encrypted vault via `SecretsVault`)
- [ ] Rate-limiting for policy evaluation (prevent DoS via complex NL inputs)
- [ ] Audit `DelegationChain.is_valid_chain()` for cycle attacks

---

### Phase 8 — Observability & CI Integration 🔄 Ongoing

**Remaining work from MASTER_REFACTORING_PLAN_2026 Phase 8:**

- [ ] Wire performance baselines into GitHub Actions CI
- [ ] `TDFOL/performance_dashboard.py`: expose Prometheus metrics endpoint
- [ ] Policy evaluation audit log: every `PolicyEvaluator.evaluate()` call writes to audit trail
- [ ] `logic/integration/` 99% coverage → remove or document the remaining 55 dead/symai lines

---

## 4. UCAN Deontic Logic Parsing — Architecture Detail

### 4.1 The Full Pipeline (Implemented)

```
NL sentence: "Alice must not delete records after 2026-12-31"
    │
    │  Stage 1: Pattern matching + temporal extraction
    ▼
DeonticFormula(
    operator=PROHIBITION,
    predicate=Predicate("delete", [Arg("alice", "Agent"), Arg("records", "Thing")]),
    temporal_constraint=TemporalConstraint(after="2026-12-31")
)
    │
    │  Stage 2: DCEC → PolicyClause
    ▼
PolicyClause(
    clause_type="prohibition",
    actor="alice",
    action="delete",
    resource="records",
    valid_from=<datetime("2026-12-31")>,
)
    │
    │  Stage 3a: PolicyClause → PolicyObject
    ▼
PolicyObject(clauses=[...], policy_cid="bafy...")
    │
    │  Stage 3b: DeonticFormula → UCAN (stubs)
    ▼
DenyCapability(resource="logic/delete", ability="delete/invoke")
    │
    │  Stage 4: Registration + Evaluation
    ▼
PolicyEvaluator.evaluate(intent, policy_cid, actor="alice")
→ DecisionObject(decision="deny", justification="Prohibited by clause...")
```

### 4.2 The Full Pipeline (with DID signing — Phase 2b)

```
NL sentence: "Bob is permitted to read files"
    │
    │  Stages 1–3 (same as above) → DelegationToken (stub)
    │
    │  Stage 4b: DID signing
    ▼
DIDKeyManager.sign_delegation_token(stub_token)
→ signed UCAN JWT: "eyJ..."
    │
    │  Stage 5: Verification
    ▼
DIDKeyManager.verify_delegation(jwt, required_capabilities=[...])
→ True  (cryptographic proof that root issued this delegation)
```

### 4.3 The ZKP Evidence Track (Phase 4b — future)

```
TDFOL theorem: "∀x. (agent(x) ∧ authorized(x)) → permitted_to_read(x)"
    │
    │  ZKP prover (Groth16 when available, simulation now)
    ▼
ZKPProof(proof_data, public_inputs, theorem_hash)
    │
    │  ZKPToUCANBridge
    ▼
ZKPCapabilityEvidence(
    proof_hash="abc...",
    theorem_cid="bafy...",
    is_simulation=True  # ← warning emitted
)
    │
    │  UCAN caveat attachment
    ▼
DelegationToken(
    capabilities=[Capability("logic/read", "read/invoke")],
    nonce="zkp:abc...:16charprefix",  # proof embedded
)
```

---

## 5. Known Limitations and Mitigations

| Limitation | Severity | Mitigation |
|-----------|---------|------------|
| ZKP is simulation-only | ⚠️ High | `UserWarning` always emitted; Groth16 backend ready when Rust FFI available |
| DelegationToken stubs are unsigned | ⚠️ High | `DIDKeyManager.sign_delegation_token()` planned (Phase 2b) |
| NL accuracy ~60–75% | 🟡 Medium | Grammar-based parser planned (Phase 3b); spaCy NER in Phase 7 |
| No persistence for RevocationList | 🟡 Medium | `SecretsVault` integration planned (Phase 7) |
| Temporal constraint extraction from NL | 🟡 Medium | Basic date patterns implemented; complex temporal expressions deferred |
| Multi-agent policies (delegation chains > 1 hop) | 🟡 Medium | `DelegationChain` supports it; NL compiler generates single-hop only |
| No conflict detection between clauses | 🟡 Medium | Planned in Phase 3b |

---

## 6. Session Log

| Session | Date | New Modules | New Tests | Phase |
|---------|------|------------|-----------|-------|
| v13 NL pipeline | 2026-02-22 | `nl_to_policy_compiler.py`, `dcec_to_ucan_bridge.py`, `nl_ucan_policy_compiler.py`, MCP tool | 64 | 1 ✅ |
| v13 Logic refactoring | 2026-02-22 | `grammar_nl_policy_compiler.py`, `zkp/ucan_zkp_bridge.py`, plan v2 | 60 | 3/4 partial |
| v13 DID/UCAN | 2026-02-22 | `did_key_manager.py`, `secrets_vault.py`, dep additions | 43 | 2 partial |
| **v14 Logic+UCAN** | **2026-02-22** | **`ucan_policy_bridge.py`, `RevocationList`, `DelegationStore`** | **59** | **2/8** |

---

## 7. Next Sessions (v15 candidates)

| Session | Target | Rationale | Phase |
|---------|--------|-----------|-------|
| V15a | `DIDKeyManager.sign_delegation_token()` + `UCANPolicyBridge.compile_and_sign()` | Real signed tokens | 2b |
| V15b | `GrammarNLPolicyCompiler` as default in `NLToDCECCompiler` | Improve NL accuracy | 3b |
| V15c | `logic/api.py` blessed public surface + `__all__` | Import hygiene | 5 |
| V15d | `PolicyEvaluator` memoization cache | Performance | 6 |
| V15e | `TDFOL/security_validator.py` coverage 70% → 90% | Security hardening | 7 |
| V15f | End-to-end integration test: NL → signed JWT → verify | CI integration | 8 |
| V15g | Spanish language NL policy support | Internationalisation | 3b |
| V15h | RevocationList JSON persistence via SecretsVault | Security | 7 |

---

## 8. Success Criteria

| Metric | Current | Target | Phase |
|--------|---------|--------|-------|
| NL→Policy clause accuracy (deontic) | ~70% | ~90% | 3b |
| Policy evaluation latency | <5ms | <1ms | 6 |
| DelegationToken signing (real) | ❌ stub | ✅ Ed25519 JWT | 2b |
| ZKP proof as UCAN caveat | ❌ simulation | ✅ Groth16 | 4b |
| `logic/` import produces no warnings | ✅ yes | ✅ yes | 5 |
| All logic modules ≥90% coverage | ~97% avg | ≥97% | ongoing |
| Security validator coverage | 70% | 90% | 7 |

---

*This document supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` (archived).*  
*Next version: `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v4.md` after Phase 2b + 3b complete.*
