# Crypto IR Threat Model

Status: normative companion for CRYPTOIR-G010 / CRYPTOIR-001  
Repair: CRYPTOIR-036 objective validation repair  
Authority policy: [`AUTHORITY_AND_POLICY.md`](AUTHORITY_AND_POLICY.md)  
Machine policy id: `crypto-ir-authority-policy-v1` (version `1.0.0`)  
Evidence test: `ipfs_datasets_py/tests/unit/logic/crypto_ir/test_policy_baseline.py`

This threat model freezes the trusted computing base, adversaries, assets,
trust boundaries, and fail-closed outcomes for Crypto IR, smart-contract
acquisition, sanctions/flow analysis, and transaction preflight **before**
schemas or gates are implemented. It is not a legal opinion and does not
authorize signing, broadcast, custody, or external enforcement filings.

## 1. Mission and claim boundary

Crypto IR provides a chain-neutral intermediate representation and analysis
surface for:

- public wallet and account observations;
- unsigned transaction intents and exact serialized candidates;
- deployed contracts, programs, scripts, and code epochs;
- security obligations and bounded analysis results; and
- sanctions snapshots, flow-graph exposure, and explainable policy decisions.

**Claim rule.** Report only claims justified by the named model, bound
assumptions, current inputs, complete coverage, and the authority kind of the
checked evidence. Narrow evidence-bound claims are preferable to broad claims
that the current models cannot prove.

**Universal security claims are prohibited.** The strongest permissible claim is
that named obligations were `PROVED` under named assumptions for an exact code
epoch and toolchain—not that a contract, wallet, or counterparty is “secure” or
“lawful.”

**Fail closed.** Unsupported or stale critical inputs cannot produce automated
`ALLOW`. For production signing and broadcast, every `TransactionVerdict` other
than a current `ALLOW` blocks automation.

## 2. Pinned repository baseline

Threat and authority documents bind these reviewed revisions. Silent drift to a
moving tip is out of policy.

| Component | Pinned revision |
| --- | --- |
| 211-AI tree | `34b536b59bfb7fcb4c7772b7078fe04709e92fc8` |
| `ipfs_datasets_py` | `75ae1de0fd5d8bc3625d26de3ccdd65f3a070dc9` |
| `ipfs_accelerate_py` | `c3988ec5e4c55edf8ce541825d82c10e11318745` |
| `ipfs_kit_py` | `276d766b8076b725a5a9e53bcf0c057f067acd10` |

## 3. Conceptual interfaces (authority surface)

These interfaces are defined fully in `AUTHORITY_AND_POLICY.md` and must appear
consistently in later receipts:

| Interface | Role |
| --- | --- |
| `AnalysisAuthority` | Terminal analysis outcomes: `PROVED`, `DISPROVED`, `UNKNOWN`, `UNSUPPORTED`, `INCONCLUSIVE`, `STALE`, `ERROR` |
| `PolicyAuthority` | Legal/risk policy evaluation; non-escalating authority kinds |
| `TransactionVerdict` | `ALLOW`, `REVIEW`, `DENY`, plus fail-closed `INCONCLUSIVE`, `STALE`, `ERROR` |
| `EvidenceFreshness` | Currency of sanctions, graph, code epoch, policy, capability, and receipt bindings |

Authority kinds remain non-interchangeable: `observation`, `evidence`, `proof`,
`monitor`, `heuristic`, `designation`, `policy`, and `authorization`.

## 4. Trusted computing base (TCB)

Soundness and policy guarantees assume correct operation of:

1. Git object and submodule identity readers for pinned baselines.
2. Canonical encoding, multihash, and content-addressed identity code.
3. Strict schema validators and immutable record construction.
4. Bounded network transport, DNS/redirect policy, and allowlisted endpoints.
5. Artifact acquisition, archive limits, and CAS storage.
6. Chain frontends and coverage frontier accounting.
7. Obligation generators and soundness-documented formal lowerings.
8. Solvers, deterministic rule engines, simulators, and counterexample checkers
   that actually execute before claiming backend authority.
9. Sanctions snapshot parsers and digital-currency identifier validators.
10. Flow-graph builders with explicit completeness and finality.
11. Policy combiners that preserve authority kinds and freshness.
12. Admissibility/preflight capability issuance, live revalidation, and atomic
    consumption.
13. Receipt serialization, integrity, and expiry verification.
14. Sandbox, resource budgets, and offline-by-default configuration.

**Compromise rule.** A compromised or incorrectly reviewed TCB component is
outside the guarantee. Detected identity, integrity, configuration, or execution
failures produce `STALE` or `ERROR` and fail closed.

Conditional TCB elements (only when a claim uses them): cryptographic libraries,
proving backends, verification-key registries, reviewed circuits, and injected
secret managers for provider credentials (never for custody keys inside
processors).

## 5. Assets

| Asset | Sensitivity | Notes |
| --- | --- | --- |
| Provider credentials / secret references | Critical | Opaque references only; never inline secrets |
| Exact serialized transaction candidates | Critical | Bind digests; prevent substitution and TOCTOU |
| Private keys / seeds / custody material | Critical | Out of scope; processors must not accept custody |
| Sanctions snapshots and designation records | High | Official source bytes, hashes, effective times |
| Flow-graph and ownership evidence | High | Separate from public observations; access controlled |
| Deployed code epochs, proxies, upgrade authorities | High | Epoch changes invalidate dependent decisions |
| Analysis and policy receipts | High | Immutable audit; no silent mutation |
| Free-form memos, calldata, proofs, nullifiers | High | Default redact; privacy-sensitive |
| Public addresses, amounts, finality metadata | Medium | Required for integrity; profiling risk in aggregate |

## 6. Adversaries and trust boundaries

### Adversaries

- Malicious or buggy RPC/explorer/source providers (lies, split views, SSRF bait,
  oversized payloads, secret-bearing errors).
- Artifact and list poisoning (truncation, rollback, schema drift, count drops).
- Transaction substitution and fee/nonce/UTXO mutation between intent and sign.
- Proxy/upgrade and code-epoch races.
- Graph coverage games (incomplete hops, reorgs, mixer/bridge ambiguity).
- Heuristic and model abuse seeking designation or `ALLOW` elevation.
- Supply-chain compromise of toolchains, solvers, or policy documents.
- Insider misuse of override workflows without separation of duties.
- Resource exhaustion against parsers, solvers, and graph traversal.

### Trust boundaries

1. **Operator / legal owner** — sole authority for jurisdiction, enforcement
   enablement, licenses, and human `REVIEW` outcomes.
2. **Secret manager** — materializes provider credentials; processors hold
   references only.
3. **Untrusted network and providers** — all remote data is hostile until
   schema-validated and provenance-bound.
4. **Analysis backends** — authority only after successful execution under
   bound configuration; timeouts remain `UNKNOWN` / `ERROR`.
5. **Custody signer / broadcaster** — external to `ipfs_datasets_py` processors;
   consumes one-use capabilities, never bare booleans.
6. **Export / CLI / MCP consumers** — cannot bypass policy, freshness, or
   receipts.

## 7. Threat catalog and fail-closed outcomes

### T1 — Authority elevation / silent coercion

**Threat.** Observation, monitor, satisfiability, heuristic, GraphRAG, or risk
score is relabeled as proof, designation, or `ALLOW`.

**Control.** Non-escalation rules in `AUTHORITY_AND_POLICY.md`; distinct
vocabularies for `AnalysisAuthority` and `TransactionVerdict`.

**Outcome.** Reject fixture; block automation.

### T2 — Stale or cross-epoch decisions

**Threat.** Expired sanctions snapshot, reorged graph edge, upgraded proxy, or
old receipt still used for `ALLOW`.

**Control.** `EvidenceFreshness` critical-input list; material change invalidates
decisions; pre-sign and pre-broadcast revalidation.

**Outcome.** `STALE` or re-evaluation; never stale `ALLOW`.

### T3 — Unsupported semantics treated as safe

**Threat.** Missing frontend coverage, opaque JSON “verification conditions,” or
unmodeled chain behavior reported as proved or allowed.

**Control.** Explicit `UNSUPPORTED` / `INCONCLUSIVE`; soundness-documented
lowering required before proof backend authority.

**Outcome.** Fail closed for required obligations.

### T4 — Unbounded guilt by association

**Threat.** Graph distance, shared infrastructure, mixers, bridges, or fuzzy
names treated as designation or hard block without policy authority.

**Control.** Match-authority levels; heuristics limited to review priority;
prohibition on unbounded guilt by association.

**Outcome.** At most `REVIEW` under versioned risk policy; never invented
designation.

### T5 — Transaction substitution / TOCTOU

**Threat.** Candidate bytes, fees, nonce/sequence, UTXOs, or calldata change
after analysis.

**Control.** Exact candidate digest binding; short-lived one-use capability;
live revalidation at sign and broadcast.

**Outcome.** Capability invalid; new decision required.

### T6 — Provider, list, and artifact poisoning

**Threat.** Truncation, rollback, DNS rebinding, decompression bombs, forged
“verified source,” or split RPC views.

**Control.** Allowlisted endpoints, byte/page budgets, content-addressed raw
bytes, provider disagreement preserved, offline fixtures default.

**Outcome.** `ERROR`, `INCONCLUSIVE`, or `STALE` — no permissive resolution.

### T7 — Universal or overstated security claims

**Threat.** Marketing-grade “contract is secure” or absence of findings treated
as `PROVED`.

**Control.** Claim boundary; absence of findings is not proof; narrow
obligation-scoped claims only.

**Outcome.** Reject universal claims; require named obligation bindings.

### T8 — Custody and signing creep

**Threat.** Processors grow sign/submit/broadcast surfaces or accept seeds.

**Control.** Non-custodial mission boundary; signing remains external; existing
hotspots (for example `logic/zkp/eth_integration.py`) must route through the
exact-candidate gate or stay disabled for production cutover.

**Outcome.** Capability denied; fail closed.

### T9 — Override abuse

**Threat.** Human override converts failed proof into proof or refreshes stale
evidence.

**Control.** Overrides may hold, reject, request evidence, or attach scoped
licenses with audit; they cannot rewrite proof status or freshness.

**Outcome.** Immutable audit of the original failing result.

### T10 — Resource exhaustion

**Threat.** Pathological sources, unbounded graph depth, or solver bombs.

**Control.** Hard budgets on time, memory, bytes, depth, items, and retries;
timeouts surface as `UNKNOWN` / `ERROR`.

**Outcome.** Fail closed; no partial silent success.

## 8. Analysis and policy outcome matrix (summary)

| Vocabulary | Outcomes | Automation note |
| --- | --- | --- |
| Analysis (`AnalysisAuthority`) | `PROVED`, `DISPROVED`, `UNKNOWN`, `UNSUPPORTED`, `INCONCLUSIVE`, `STALE`, `ERROR` | `PROVED` is not transaction authorization |
| Transaction (`TransactionVerdict`) | `ALLOW`, `REVIEW`, `DENY`, `INCONCLUSIVE`, `STALE`, `ERROR` | Only current `ALLOW` permits automated sign/broadcast |

Positive path: all required obligations pass, no hard designation hit, critical
inputs fresh, authorization authority emits `ALLOW` with one-use capability.

Rejection path examples (machine-checked in the authority policy fixtures):

- exact listed identifier → `DENY`
- required obligation `DISPROVED` → `DENY`
- heuristic-only “designation” → rejected
- heuristic-only `ALLOW` → rejected
- stale or unsupported critical inputs → no `ALLOW`
- proof alone without authorization combiner → no `ALLOW`
- guilt-by-association as designation → rejected
- universal security claim → rejected

## 9. Non-goals

Unless a later reviewed objective adds authority, Crypto IR does not:

- hold private keys, seeds, HSMs, or MPC shares;
- sign, approve, submit, or broadcast inside read-only processors;
- auto-file with OFAC or law enforcement;
- treat explorer “verified source” as source/bytecode equality;
- treat static analyzers, GraphRAG, monitors, ZK envelopes, or satisfiability as
  theorem proofs;
- silently install dependencies, use ambient credentials, or perform
  import-time network activity;
- claim completeness of the global blockchain beyond a bound completeness
  receipt.

## 10. Acceptance evidence

| CRYPTOIR-G010 acceptance term | Evidence |
| --- | --- |
| Documents bind reviewed git revisions | Section 2 and matching pins in `AUTHORITY_AND_POLICY.md` |
| Distinguish observation, evidence, proof, monitor, heuristic, designation, policy, authorization | Section 3 and authority lattice in companion |
| Exact `PROVED`…`DENY` semantics | Section 8 and companion §§4–5 |
| Prohibit unbounded guilt by association and universal security claims | T4, T7, claim boundary |
| Unsupported or stale critical inputs fail closed | T2, T3, freshness rules |
| Machine-checked positive and rejection fixtures | `crypto-ir-authority-policy-v1` JSON fixtures + `test_policy_baseline.py` |
| Interfaces `AnalysisAuthority`, `PolicyAuthority`, `TransactionVerdict`, `EvidenceFreshness` | Section 3 and companion §2 |
| objective validation repair | CRYPTOIR-036 re-proof in `test_policy_baseline.py` (`test_objective_validation_repair_proves_g010_acceptance`) and acceptance block in companion policy JSON |

## 11. Related documents

- Plan: `docs/planning/CRYPTO_IR_COMPLIANCE_PLAN.md` (read-only operator pin)
- Objectives: `docs/planning/CRYPTO_IR_COMPLIANCE_OBJECTIVES.md` (CRYPTOIR-G010)
- Wallet processor threat model: `docs/security/WALLET_PROCESSOR_THREAT_MODEL.md`
- Software-contract soundness: `docs/software_contracts/SOUNDNESS_AND_THREAT_MODEL.md`
