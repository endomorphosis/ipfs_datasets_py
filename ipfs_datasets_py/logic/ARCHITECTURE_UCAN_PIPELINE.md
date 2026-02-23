# NL→Policy→UCAN Pipeline — Complete Architecture Diagrams

**Version:** 2026-02-22 (Phase 2b–8 complete)  
**Supersedes:** partial diagrams in `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v3.md`

---

## 1. Full NL→Policy→UCAN Pipeline (Phases 1–2b)

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                   NATURAL LANGUAGE INPUT                                         ║
║  "Alice must not delete records. Bob is permitted to read files after 2026-01."  ║
╚══════════════════════════════════════════╤═══════════════════════════════════════╝
                                           │
                        ┌──────────────────▼──────────────────┐
                        │         STAGE 1 — NL PARSING         │
                        │                                       │
                        │  Primary:   NaturalLanguageConverter  │
                        │             (37+ regex patterns)      │
                        │             ↓ DCEC DeonticFormula     │
                        │                                       │
                        │  Fallback:  GrammarNLPolicyCompiler   │  ← Phase 3b
                        │  (Stage 1b) (DCECEnglishGrammar OR   │
                        │             keyword heuristic)        │
                        └──────────────────┬──────────────────┘
                                           │  DeonticFormula(
                                           │    operator=OBLIGATION|PERMISSION|PROHIBITION,
                                           │    predicate=Predicate("delete",…),
                                           │    temporal_constraint=TemporalConstraint(…)
                                           │  )
                        ┌──────────────────▼──────────────────┐
                        │       STAGE 2 — DCEC→POLICY          │
                        │                                       │
                        │  NLToDCECCompiler._dcec_formula_to_  │
                        │  clause()                            │
                        │                                       │
                        │  OBLIGATION  → PolicyClause(type=    │
                        │               "obligation", …)       │
                        │  PERMISSION  → PolicyClause(type=    │
                        │               "permission", …)       │
                        │  PROHIBITION → PolicyClause(type=    │
                        │               "prohibition", …)      │
                        └──────────────────┬──────────────────┘
                                           │  List[PolicyClause]
                        ┌──────────────────▼──────────────────┐
                        │     STAGE 3a — POLICY ASSEMBLY       │
                        │                                       │
                        │  PolicyObject(                        │
                        │    policy_cid="bafy…",               │
                        │    clauses=[…],                      │
                        │    version=1,                        │
                        │  )                                   │
                        │                                       │
                        │  PolicyEvaluator.register_policy()   │
                        └──────────────────┬──────────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
              ▼                            ▼                            ▼
  ┌───────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
  │  STAGE 3b:        │      │  STAGE 3c:           │      │  STAGE 3d:          │
  │  UCAN STUBS       │      │  ZKP EVIDENCE        │      │  DID SIGNING        │
  │  (Phase 1)        │      │  (Phase 4, sim.)     │      │  (Phase 2b)         │
  │                   │      │                      │      │                     │
  │ DCECToUCANBridge  │      │ ZKPToUCANBridge      │      │ DIDKeyManager       │
  │                   │      │                      │      │ .sign_delegation_   │
  │ PERMISSION →      │      │ ZKPProof.proof_hash  │      │  token(stub_token)  │
  │  DelegationToken  │      │ → UCAN caveat nonce  │      │                     │
  │  (unsigned stub)  │      │ (warns: simulation)  │      │ → signed UCAN JWT   │
  │                   │      │                      │      │   (Ed25519/py-ucan  │
  │ PROHIBITION →     │      │ ZKPCapabilityEvidence│      │    OR stub base64)  │
  │  DenyCapability   │      │  .is_simulation=True │      │                     │
  └─────────┬─────────┘      └──────────┬──────────┘      └──────────┬──────────┘
            │                           │                             │
            └───────────────────────────┼─────────────────────────────┘
                                        │
                        ┌───────────────▼──────────────────────┐
                        │     STAGE 4 — INTEGRATION LAYER       │
                        │                                       │
                        │  UCANPolicyBridge                     │
                        │    .compile_nl()  → BridgeCompileResult│
                        │    .evaluate()    → BridgeEvaluationResult│
                        │    .compile_and_sign() → SignedPolicyResult│
                        │                                       │
                        │  PolicyEvaluator (memoized, Phase 6)  │
                        │  DelegationEvaluator (chain cache)    │
                        │  DelegationStore (JSON persist)       │
                        │  RevocationList (vault persist Ph.7)  │
                        │  PolicyAuditLog (observability Ph.8)  │
                        └───────────────────────────────────────┘
```

---

## 2. DID-Signing Track (Phase 2b)

```
NL text: "Bob may invoke read_tool"
     │
     │  UCANPolicyBridge.compile_and_sign(
     │      nl_text="Bob may invoke read_tool",
     │      audience_did="did:key:z6MkBob…",
     │      lifetime_seconds=86400,
     │  )
     │
     ├─► compile_nl() → BridgeCompileResult
     │        └── delegation_tokens = [DelegationToken(
     │                issuer="did:example:root",
     │                audience="did:key:z6MkBob…",
     │                capabilities=[Capability("logic/read_tool","read_tool/invoke")]
     │            )]  ← UNSIGNED STUB
     │
     └─► DIDKeyManager.sign_delegation_token(stub_token)
              │
              ├── py-ucan available?
              │       YES → await ucan.build(issuer=keypair, …) → Ucan
              │             → .encode() → "eyJhbGc…"  (real Ed25519 JWT)
              │
              └── py-ucan NOT available
                      → base64.urlsafe_b64encode(json.dumps(payload))
                      → "stub:eyJpc3MiOiJk…"  (base64 stub)

SignedPolicyResult:
    .compile_result     (BridgeCompileResult)
    .signed_jwts        ["eyJhbGc…"]   OR   ["stub:eyJpc3MiO…"]
    .signing_available  True            OR   False
    .jwt_count          1

─── Verification path ───────────────────────────────────────────────────────

DIDKeyManager.verify_signed_token(jwt, required_capabilities=[("logic/read_tool","read_tool/invoke")])
    │
    ├── starts with "stub:" → decode base64 JSON → True (structural check only)
    │
    └── real JWT → ucan.verify(token, audience=our_did, required_capabilities=[…])
                    → VerifyResultOk → True
```

---

## 3. ZKP Evidence Track (Phase 4, Simulation Mode)

```
TDFOL theorem: "∀x.(agent(x) ∧ authorized(x)) → permitted_to_read(x)"
     │
     │  ZKPToUCANBridge.prove_and_delegate(
     │      theorem="∀x…",
     │      resource="logic/read",
     │      ability="read/invoke",
     │      prover=None,  ← simulation
     │  )
     │
     ├─► ZKPSimulationProver.prove(theorem) → ZKPProof(
     │       proof_data={"type":"simulation","theorem":…},
     │       proof_hash="sha256:abc123…",
     │       is_simulation=True,
     │   )
     │   ⚠ UserWarning("ZKP proof is a simulation…") emitted
     │
     └─► ZKPCapabilityEvidence(
             proof_hash="sha256:abc123…",
             theorem_cid="bafy-sha2-256-…",
             verifier_id="simulation-verifier",
             is_simulation=True,
         )
         │
         └─► DelegationToken(
                 capabilities=[Capability("logic/read","read/invoke")],
                 nonce="zkp:sha256:abc123:16chars",  ← proof embedded
             )
             ⚠ NOTE: this token is UNSIGNED and SIMULATION-ONLY

─── Future (Phase 4b, Groth16 backend) ────────────────────────────────────

IPFS_DATASETS_ENABLE_GROTH16=1
    → Rust FFI backend → real Groth16 proof
    → ZKPCapabilityEvidence.is_simulation = False
    → No warning emitted
    → proof_hash is cryptographically verified on verification path
```

---

## 4. Temporal Policy Evaluation (with Memoization, Phase 6)

```
PolicyEvaluator.evaluate(intent, policy_cid, actor="alice")
     │
     ├─► Phase 6: cache lookup (policy_cid, intent.cid, "alice") in _decision_cache
     │       HIT  → return cached DecisionObject immediately (O(1))
     │       MISS → continue below
     │
     ├─► 1. Check PROHIBITIONS (deny overrides)
     │       For each prohibition clause:
     │           clause.is_temporally_valid(now) ?   (valid_from ≤ now ≤ valid_until)
     │           _clause_matches(clause, intent, actor) ?
     │           → DENY
     │
     ├─► 2. Check PERMISSIONS (closed-world)
     │       For each permission clause:
     │           clause.is_temporally_valid(now) ?
     │           _clause_matches(clause, intent, actor) ?
     │           → permitted = True
     │       No match → DENY
     │
     ├─► 3. Collect OBLIGATIONS (if any)
     │       For each obligation clause:
     │           clause.is_temporally_valid(now) ?
     │           _clause_matches(clause, intent, actor) ?
     │           → spawned.append(Obligation(type=…, deadline=…))
     │
     ├─► Build DecisionObject(decision=ALLOW|ALLOW_WITH_OBLIGATIONS|DENY, …)
     │
     └─► Phase 6: store in _decision_cache[(policy_cid, intent_cid, actor)]
         → Phase 8: PolicyAuditLog.record_decision(decision_obj, tool=…, actor=…)
```

---

## 5. Delegation Chain + Revocation (Phase 6/7)

```
DelegationEvaluator
     ├── _tokens: {cid → DelegationToken}
     └── _chain_cache: {leaf_cid → DelegationChain}   ← Phase 6

build_chain(leaf_cid="cid:C"):
     ├── _chain_cache hit → return cached
     └── miss:
             C.proof_cid = "cid:B"
             B.proof_cid = "cid:A"
             A.proof_cid = None
             → chain = [A, B, C]  (root-first)
             → _chain_cache["cid:C"] = chain

can_invoke_with_revocation(principal, resource, ability, leaf_cid="cid:C",
                           revocation_list=RevocationList):
     ├── build_chain("cid:C") → [A, B, C]
     ├── for token in [A, B, C]:
     │       is_revoked(token.cid) → if any: DENY
     └── can_invoke(…) → (True, "")  OR  (False, "reason")

RevocationList  (Phase 7):
     ├── _revoked: set[str]   (in-memory)
     ├── .revoke(cid)
     ├── .is_revoked(cid) → bool
     ├── .save(path)   → JSON (plain) OR SecretsVault (path ends with .enc)
     └── .load(path)   → int (count)
```

---

## 6. Policy Audit Log (Phase 8)

```
PolicyAuditLog (singleton via get_audit_log())
     ├── _entries: List[AuditEntry]   (ring buffer, max 10,000)
     ├── _counters: {"allow":N, "deny":N, "allow_with_obligations":N}
     ├── _log_path: Optional[Path]    (JSONL append)
     └── _sink: Optional[Callable]   (Prometheus/Sentry forward)

Every PolicyEvaluator.evaluate() call:
     └── AuditEntry(
             timestamp    = time.time(),
             policy_cid   = "bafy…",
             intent_cid   = "bafy…",
             decision     = "allow",
             actor        = "alice",
             tool         = "read_tool",
             justification= "Permission granted.",
             obligations  = [],
             extra        = {},
         )
         │
         ├── appended to _entries (thread-safe)
         ├── _counters["allow"] += 1
         ├── _sink(entry)  (if configured)
         └── fh.write(entry.to_json() + "\n")  (if log_path set)

stats() → {
    total_recorded:  N,
    in_memory:       N,
    allow_count:     N,
    deny_count:      N,
    allow_rate:      0.0–1.0,
    deny_rate:       0.0–1.0,
    by_decision:     {"allow":N, "deny":N, …},
    log_path:        "/path/to/audit.jsonl",
    enabled:         True,
}
```

---

## 7. Module Map (logic/ + mcp_server/)

```
logic/
├── CEC/
│   └── nl/
│       ├── nl_to_policy_compiler.py    Stage 1+1b: NL → DCEC → PolicyClause
│       ├── grammar_nl_policy_compiler.py  Stage 1b: Grammar fallback (Phase 3b)
│       └── dcec_to_ucan_bridge.py      Stage 3b: DCEC formulas → UCAN stubs
├── integration/
│   ├── nl_ucan_policy_compiler.py      3-stage pipeline coordinator
│   └── ucan_policy_bridge.py          Full integration glue + compile_and_sign
└── zkp/
    └── ucan_zkp_bridge.py              Phase 4: ZKP proof → UCAN caveat

mcp_server/
├── temporal_policy.py                  PolicyEvaluator (+cache Phase 6)
├── ucan_delegation.py                  DelegationToken/Chain/Evaluator/Store
│                                       RevocationList (+save/load Phase 7)
│                                       DelegationEvaluator (+chain_cache Phase 6)
├── did_key_manager.py                  DIDKeyManager (+sign_delegation_token Phase 2b)
├── secrets_vault.py                    SecretsVault (RevocationList backend Phase 7)
└── policy_audit_log.py                 PolicyAuditLog (Phase 8)
```

---

## 8. Phase Completion Status

| Phase | Description | Status | Session |
|-------|-------------|--------|---------|
| 1 | Core NL→UCAN pipeline | ✅ Complete | v13 |
| 2 | DID-Signed UCAN Tokens | ✅ Complete (2b) | v13/v15 |
| 3 | Grammar-Based NL Parsing | ✅ Complete (3b) | v13/v15 |
| 4 | ZKP→UCAN Bridge | ⚠️ Simulation only | v13 |
| 5 | Import Hygiene & Blessed API | ✅ Complete | v15 |
| 6 | Performance & Caching | ✅ Complete | v15 |
| 7 | Security Hardening | ✅ Complete | v15 |
| 8 | Observability & CI Integration | ✅ Complete | v15 |

---

*Last updated: 2026-02-22. Real Groth16 ZKP (Phase 4b) deferred to when Rust FFI backend is available.*
