# Proof attestation, corpus verification, and ZKP profiles

| Field | Value |
| --- | --- |
| Interface | `ProofAttestationArchitecture@1` |
| Task | `IPFSDOC-043` |
| Status | `canonical` |
| Owner | architecture / logic-policy |
| Source of truth | `ipfs_datasets_py/logic/proof_corpus/` (`model`, `policy`, `manifest`, `revocation`, `applicability`, `verifier`, `attest`, `store`, `audit`, `query`); `ipfs_datasets_py/logic/zkp/` (backends, statement, circuits, VK registry, legal theorem statements); `ipfs_datasets_py/logic/admissibility/profiles.py`; `ipfs_datasets_py/logic/ir_core/protocols.py`; [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md); [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, release owner, operator |
| Related | [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow D, [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md), [logic/zkp/SECURITY_CONSIDERATIONS.md](../../logic/zkp/SECURITY_CONSIDERATIONS.md) |
| Review cadence | when attestation kinds, trust policy, circuit/VK bindings, verifier reasons, or ZKP backend authority rules change |

## 1. Purpose

This guide answers: **how proof evidence is attested and stored, how
non-substitutable attestation kinds (direct proof, verifier execution,
membership, signature, simulation) remain distinct, how ZKP and admissibility
profiles bind circuits and verification keys, how modeled assumptions and
UNKNOWN statuses fail closed, how audit redaction works, and what release
assurance must pin.**

It is the companion leaf to
[LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md)
(constraint compilation and applicability). This document owns **attestation
algebra**, **corpus integrity for proof evidence**, **independent consumer
verification**, **ZKP profile and backend boundaries**, **redaction**, and
**release assurance**. It does not redefine Legal/Security hard filters or
governed pre-dispatch enforcement.

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place attestation and ZKP work without collapsing evidence classes |
| **Verifier / corpus author** | Implement consumer checks against exact roots and bindings |
| **Security reviewer** | Confirm simulation and membership cannot authorize production |
| **Release owner** | Know which roots, circuits, VKs, and approvals a release must bind |
| **Operator** | Interpret redacted audit receipts and disable paths safely |

## 3. Scope and non-goals

### In scope

- **`AttestedProofEnvelope@1`** identity: statement/assumption/obligation
  digests, pipeline, scope, temporal, circuit, coverage, parents, revocation.
- **Attestation kinds** and non-substitutability rules.
- **Proof corpus store**, manifests, indexes, and cache integrity.
- **Trust policy**, coverage policy, and **revocation** snapshots for proof
  evidence.
- **Independent consumer verification** (`AttestedProofVerifier@1`) and
  selected evidence packs.
- **ZKP backends** (production-oriented vs simulated), public inputs, circuit
  and VK registry bindings.
- **Admissibility profile** interaction with ZKP requirements.
- **Modeled assumptions**, `UNKNOWN` result statuses, and non-admission of
  heuristic artifacts.
- **Redacted audit receipts** (`ProofQueryAuditReceipt@1`).
- **Release assurance** bindings for corpus, revocation, policy, circuit/VK,
  and golden fixtures.

### Non-goals

- Legal/Security hard-filter dimension catalogs (owned by
  [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md)).
- External prover install and hammer reconstruction details (owned by
  [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md)).
- Intent invocation adapters and pre-dispatch enforcement mechanics (operator
  guide + later governed-authorization leaf).
- On-chain deployment runbooks for every chain (module-specific docs under
  `docs/logic/zkp/`).
- Treating historical ZKP demos or simulated backends as production theorem
  authority.

## 4. Mental model

```text
  formal artifact + obligation digests
           │
           ▼
  native proof attempt and/or ZKP prove
           │
           ▼
  AttestedProofEnvelope@1
  (attestation_kind · result_authority · roots · circuit/VK)
           │
           ▼
  ProofCorpusStore / Manifest  ──► RevocationSnapshot
           │
           ▼
  hard applicability + ProofTrustPolicy
           │
           ▼
  AttestedProofVerifier (consumer re-check)
           │
           ▼
  selected evidence pack + verification receipt
           │
           ▼
  admissibility / authorization inputs
  (allow only under profile; never unconstrained)
```

**Producer claims and cache hits are not authority. Consumer verification under
exact roots is.** Simulated ZKP may appear only where profiles explicitly
accept labeled simulation—and never under production `legal-strict` /
`zkp-required` allow paths.

## 5. Package and interface map

| Package / path | Role | Primary interfaces |
| --- | --- | --- |
| `logic.proof_corpus.model` | Authority-grade envelope model | `AttestedProofEnvelope@1` |
| `logic.proof_corpus.policy` | Trust and coverage policy | `ProofTrustPolicy@1`, `CorpusCoveragePolicy@1` |
| `logic.proof_corpus.manifest` | Exact-root corpus snapshot | `ProofCorpusManifest@1` |
| `logic.proof_corpus.revocation` | Append-only revocation chain | `ProofRevocationSnapshot@1` |
| `logic.proof_corpus.applicability` | Hard filters + ranking over envelopes | Proof applicability query/result |
| `logic.proof_corpus.verifier` | Independent consumer verification | `AttestedProofVerifier@1`, `SelectedEvidencePack@1` |
| `logic.proof_corpus.store` / `schemas` | Multi-family content-addressed store | `ProofCorpusStore@1` |
| `logic.proof_corpus.attest` | Attestation helpers / builders | attest composition (non-authoritative alone) |
| `logic.proof_corpus.audit` | Redacted query audit receipts | `ProofQueryAuditReceipt@1` |
| `logic.zkp` | Circuits, statements, backends, VK registry | backend protocol; prove/verify APIs |
| `logic.admissibility.profiles` | Profile ZKP knobs | `AdmissibilityProfile@1` |

```python
from ipfs_datasets_py.logic.proof_corpus import (
    AttestedProofEnvelope,
    AttestationKind,
    ProofCorpusStore,
    ProofTrustPolicy,
    AttestedProofVerifier,
    ProofRevocationSnapshot,
)
from ipfs_datasets_py.logic.admissibility import evaluate_admissibility
```

## 6. Attested proof envelope

`AttestedProofEnvelope@1` is the immutable proof-cache identity later leaves
consume. Minimum authority-relevant bindings:

| Group | Fields (representative) |
| --- | --- |
| Identity | `content_cid` / `content_digest`, `envelope_cid`, schema/interface |
| Statement | `statement_digest`, `assumption_digest`, `obligation_digest` |
| Authority | `result_authority` (`AuthorityKind`), `result_status`, `attestation_kind` |
| Pipeline | `compiler_id`, `solver_id`, `translation_id`, `reconstruction_id`, `adapter_id`, `producer_id` |
| Artifacts | `proof_artifact_cid`, `proof_bytes_digest`, `build_manifest_cid`, `source_snapshot_cid`, `source_map_cid` |
| Roots | `corpus_root_cid`, `revocation_root_cid`, `policy_id` |
| Circuit / ZKP | `circuit` (id, digest, `vk_id`, `vk_digest`, public inputs), `backend_id`, `public_inputs`, `security_profile` |
| Scope / time | tenant, jurisdiction, subject/resource scope; effective/expiry windows |
| Lineage | `parent_cids`, supersession / revocation CIDs, coverage declaration |
| Signatures | optional detached signatures (never theorem authority alone) |

Status is **scoped by** `result_authority`. Setting `result_status=proved` does
not upgrade a membership or simulation envelope into theorem authority.

## 7. Direct proof vs verifier execution vs membership vs signature vs simulation

Attestation kinds form a **closed, non-hierarchical** vocabulary
(`AttestationKind`). Policy treats them as distinct evidence classes
(`NON_SUBSTITUTABLE_EVIDENCE_KINDS`).

| Kind (wire) | What it establishes | May claim theorem authority alone? | Production allow evidence? |
| --- | --- | --- | --- |
| `direct-proof-verification` | Independent check of a native or ZK proof object against the bound statement/assumptions/obligations under declared algorithms | **Yes** (when `result_authority` is theorem and checks pass) | Yes, under trust policy + profile |
| `verifier-execution` | A trusted-execution or remote-verifier voucher that a verifier ran | **No** — never silently upgrades to direct verification | Only if policy explicitly allowlists the kind for a non-theorem authority; not a substitute for direct theorem proof |
| `artifact-membership` | Content is a member of a corpus/manifest set | **No** | Evidence readiness only; cannot authorize as theorem proof |
| `signature` (evidence class) | Detached signature over bytes or digests | **No** | Integrity/authenticity adjunct; not theorem proof |
| `simulation` | Demo/test proof material without cryptographic soundness | **No** | **Never** under production profiles; `dev-offline` may accept only when labeled and profile `accept_simulated_zkp=true` |

### 7.1 Non-substitution rules (fail-closed)

| Forbidden promotion | Correct handling |
| --- | --- |
| Membership → theorem proved | Keep `artifact-membership`; gate may treat as evidence readiness only |
| Signature → theorem proved | Keep signature evidence; require direct verification for theorem authority |
| Simulation → production ZKP | Reject (`zk_simulated_rejected` / `simulation_not_authority`) |
| Verifier-execution → direct-proof-verification | Distinct kind; no silent upgrade |
| Real backend → simulated fallback on failure | Reject (`real_to_simulation_fallback`) |
| Cache hit → verified | Consumer must re-check bindings (`cache_hit_not_authority`) |
| Producer claim alone → verified | Reject (`producer_claim_not_authority`) |
| Partial fetch → partial allow | Reject (`partial_fetch`) |
| Cross-tenant envelope reuse | Reject (`cross_tenant_substitution`) |

`attestation_kind_is_theorem_authoritative` returns true only for
`direct-proof-verification`. Non-authoritative kinds include
`artifact-membership` and `simulation` by construction.

### 7.2 Result authority remains separate

Envelope `result_authority` uses `ir_core.protocols.AuthorityKind` (for example
`theorem_proof`, `satisfiability`, `runtime_monitor`, `evidence_readiness`,
`policy_approval`). Attestation kind and authority kind are **orthogonal**:

- A direct-verified SMT unsat result may be `satisfiability` authority, not
  ITP `theorem_proof`.
- A policy approval envelope is not a theorem proof even if signed.
- SAT/SMT success is never policy `allow` by itself
  ([EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md)).

## 8. Proof corpus and cache integrity

### 8.1 Store (`ProofCorpusStore@1`)

Unified multi-family store for Intent, Legal, and Security formal artifacts:

- immutable `proof-corpus-envelope/v1` rows;
- rehash on load; digest/CID drift fails closed;
- family must match artifact domain;
- secondary indexes rebuild from envelopes (indexes are not authority).

### 8.2 Manifest (`ProofCorpusManifest@1`)

Exact-root, append-only corpus snapshot binding:

- domain/namespace/schema and generation / parent lineage;
- ordered body entries (`kind=body`) separate from index manifest refs;
- compiler / solver / circuit / VK registries;
- revocation root, coverage/licensing/privacy/tenant policy bindings;
- producer identity and promotion receipt.

Rejects: mutable `latest` aliases, path traversal, duplicate/missing/unbound
bodies, oversize content, hash/CID drift, parent cycles, rollback/downgrade,
unapproved registry roots.

### 8.3 Cache identity

Proof-object cache keys include **statement**, **assumptions**, **obligation**,
source/build/compiler/solver/translation/reconstruction, proof bytes digest,
corpus root, and policy identifiers. A hit returns a stored typed envelope; it
does not install missing verifiers or upgrade attestation kind.

## 9. Trust and revocation policy

### 9.1 Trust policy evaluation

`ProofTrustPolicy@1` evaluates envelopes to `accept` | `reject` | `abstain`
under:

- exact root requirements;
- allowlisted attestation kinds and backends;
- minimum authority / coverage rules;
- finite budgets;
- open/closed world mode;
- conflict rules (`fail_closed`, `deny_overrides`, `review`, `indeterminate`).

Production helper `default_production_trust_policy` is fail-closed: direct
proof verification for theorem paths; membership/signature/simulation cannot
be allowlisted as theorem authority. Policy mutations that would permit a
forbidden substitution raise at construction or evaluation time.

### 9.2 Revocation

`ProofRevocationSnapshot@1` binds corpus root, parent lineage, generation, and
ordered unique revocation entries. Applicability and verifier treat targets in
the active revoked set as hard failures (`envelope_revoked`). Supersession is
similarly fail-closed (`envelope_superseded`).

Never mark old receipts valid under a **new** policy or corpus root. Promotion
of roots requires human legal/security/release approval (see §14).

## 10. Independent consumer verification

`AttestedProofVerifier@1` re-checks selected evidence against exact corpus and
revocation roots. It does **not** trust producer claims or cache hits alone.

### 10.1 Required authority bindings

Representative closed set (`REQUIRED_AUTHORITY_BINDINGS`):

statement/assumption/obligation digests; source and build CIDs; compiler,
solver, translation, reconstruction ids; proof artifact CID and bytes digest;
corpus and revocation roots; policy id; attestation kind and result authority;
circuit id/digest, VK id/digest, public inputs; tenant/jurisdiction; temporal
effective/expiry; coverage; parents; security profile; backend id.

### 10.2 Evidence kinds presented to the verifier

| `ProofEvidenceKind` | Meaning |
| --- | --- |
| `native` | Native proof object (ITP/SMT artifact) |
| `zk` | Zero-knowledge proof bytes under bound circuit/VK |
| `both` | Native and ZK both required by selection |
| `none` | No proof material — cannot pass authoritative verify |

### 10.3 Stable rejection reasons (vocabulary)

Including: `producer_claim_not_authority`, `cache_hit_not_authority`,
`unknown_algorithm`, `algorithm_downgraded`, `malformed_proof`,
`underconstrained_proof`, `forged_proof`, `real_to_simulation_fallback`,
`membership_as_theorem`, `partial_fetch`, `cross_tenant_substitution`,
`root_mismatch`, `missing_binding`, `envelope_revoked`, `envelope_superseded`,
`envelope_not_effective`, `integrity_failure`, `public_input_mismatch`,
`circuit_vk_mismatch`, `native_proof_digest_mismatch`, `zk_verification_failed`,
`zk_simulated_rejected`, `missing_proof_evidence`, `trust_policy_rejected`,
`simulation_not_authority`, parent/coverage/backend failures.

Default approved production proof systems include `groth16`, `plonk`,
`native-smt`, `native-lean`, `native-z3` (closed allowlist; unknown algorithms
reject). Simulated algorithm markers (`simulated`, `mock`, `fake`, …) never
authorize production.

## 11. ZKP and attestation profiles

### 11.1 Admissibility profiles (ZKP knobs)

| Profile | `require_zkp_verify` | `accept_simulated_zkp` | Notes |
| --- | --- | --- | --- |
| `dev-offline` | false | **true** (labeled only) | Still never allows without constraints |
| `security-lite` | false | false | Security constraints required |
| `legal-strict` | false | false | Production default |
| `zkp-required` | **true** | **false** (construction forbids both true) | Missing ZKP → abstain/reject; never allow |

Unknown profiles fail closed. Profile `config_digest` is part of release
binding.

### 11.2 Circuit and public-input binding

ZKP attestations must bind:

- `circuit_id` and `circuit_digest`;
- `vk_id` and `vk_digest` (verification key registry entry);
- public inputs that include statement/assumption digests and, when required,
  corpus/policy roots and scope commitments;
- backend id (`provekit`, `groth16`, `native`, …) on the approved list.

Public-input mismatch or VK drift → reject. Trusted-setup / ceremony material
is identified by registry ids; secrets never appear in telemetry or audit
labels.

### 11.3 Backend authority classes

| Backend class | Example | Production theorem / ZKP authority |
| --- | --- | --- |
| Cryptographic ZK | provekit / groth16 paths with real proving systems when provisioned | Only when verify passes under bound VK and profile requires/accepts ZK |
| Native checkers | Lean/Z3 native proof objects under direct verification | Per native algorithm allowlist |
| **Simulated** | `logic.zkp.backends.simulated.SimulatedBackend` | **Never** production; educational / fixture only |

Historical module documentation under
[docs/logic/zkp/SECURITY_CONSIDERATIONS.md](../../logic/zkp/SECURITY_CONSIDERATIONS.md)
states that default simulation is **not cryptographically secure**. The
attested-authorization stack encodes that fact: simulated receipts cannot
authorize production dispatch. Prefer real backends for `zkp-required`; use
simulation only in `dev-offline` fixtures with explicit labels.

### 11.4 Legal theorem and constraint statements

ZKP statement modules (for example `logic.zkp.statements.legal_constraint`,
legal-theorem semantics) bind theorem/constraint digests into circuits. They
do not replace Legal applicability or Security hard filters; they attest that a
**pinned statement** was proved under a pinned circuit.

## 12. Modeled assumptions, UNKNOWN, and heuristic non-admission

### 12.1 Assumptions in proof identity

Every authoritative envelope binds `assumption_digest`. Changing assumptions
changes identity. Verification re-checks assumption digest equality with the
selected statement. Undeclared ambient assumptions are a modeling defect, not
an implicit wildcard.

### 12.2 UNKNOWN statuses

`ProofResultStatus.UNKNOWN` (and related error/absent/not_ready statuses) never
promote authority. Portfolio and compose layers map inconclusive jobs to
non-allow outcomes. Under `zkp-required`, missing verify → **cannot allow**.

### 12.3 Heuristic extraction

Heuristic or LLM-produced formulas, premises, and “proof sketches” remain
non-authoritative until:

1. admitted under explicit `review_state` / promotion receipt;
2. stored with a declared attestation kind;
3. independently verified when used as theorem evidence;
4. accepted by trust policy and profile.

Until then they may appear only as diagnostics, advisor outputs, or fixture
proposals. Golden attested-authorization fixtures encode **bound expected
decisions** and treat simulated/non-authoritative kinds as cannot-allow under
production profiles.

## 13. Redaction

### 13.1 Proof query audit receipts

`ProofQueryAuditReceipt@1` records considered / filtered / ranked / selected /
rejected counts, reason labels, budgets, and coverage gaps **without** raw
prompts, tool arguments, secrets, witnesses, private formulas, or unbounded
free-form labels.

Redaction rules (`proof_corpus.audit`):

- secret key fragments (password, token, private_key, witness, …) never as raw
  values;
- private payload keys replaced with redaction placeholders that preserve
  length and content digests for forensic correlation;
- unbounded text keys replaced with digests;
- metric labels restricted to bounded vocabularies (source kind, outcome class,
  policy profile, authority class, latency/cache buckets).

### 13.2 Telemetry and retention

Authorization telemetry follows the same redaction vocabulary. Fixture corpora
use `privacy_class=public_synthetic` where declared. Production tenant data
must not be committed to golden trees. On incident rollback: disable receipt
consumption first; preserve redacted decision observations and canary
receipts.

## 14. Release assurance

A release that depends on attested constraints or ZKP is not complete when a
task board is green. Fresh evidence must bind:

| Binding | Example |
| --- | --- |
| Exact code tree | git commit SHA / tree id for `ipfs_datasets_py` (and accelerate if bridge-touched) |
| Corpus root | manifest CID / content digest |
| Revocation root | snapshot CID |
| Trust / coverage policy | policy id + digest |
| Circuit / VK / keys | circuit_id, vk_id, key material id (**not** secrets) |
| Admissibility / rollout config | profile id + `config_digest`; rollout JSON digest |
| Golden / fixture corpus | revision used for release gates |
| Optional capability matrix | which real ZK/native backends were available |
| Selected tests | unit + integration paths below |
| Known gaps | deferred optional coverage |
| Approvals | release owner, legal, security (+ timestamps) |
| Rollback drill | disable consumption; re-run suite; record identities |

Promotion of **any** of corpus root, revocation root, trust policy, circuit/VK
set, admissibility/rollout config, or golden corpus requires human legal and
security review plus release-owner approval, bound to exact roots.

**Never** mark old decision receipts valid under a new policy or corpus root.

Representative validation (when suites are present):

```bash
test -s docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md
test -s docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md

python -m pytest \
  tests/unit/logic/proof_corpus/ \
  tests/unit/logic/admissibility/test_attested_golden_contract.py \
  tests/integration/logic/test_attested_intent_authorization.py \
  tests/integration/logic/test_intent_admissibility_gate.py \
  -q
```

Interface names for automation / evidence packs:

- `AttestedProofEnvelope@1`
- `ProofTrustPolicy@1`
- `ProofCorpusManifest@1`
- `ProofRevocationSnapshot@1`
- `AttestedProofVerifier@1`
- `SelectedEvidencePack@1`
- `ProofQueryAuditReceipt@1`
- `AdmissibilityProfile@1`
- `AttestedAuthorizationGoldenCorpus@1` / `AttestedAuthorizationConformance@1`
  (operator guide)

## 15. Failure modes and fail-closed matrix

| Condition | Outcome |
| --- | --- |
| Simulated ZKP under production profile | reject / cannot allow |
| Membership used as theorem | reject (`membership_as_theorem`) |
| Unknown or downgraded algorithm | reject |
| Root or VK mismatch | reject |
| Revoked or superseded envelope | reject |
| Expired / not-yet-effective temporal window | reject |
| Partial evidence pack | reject |
| Trust policy reject | reject |
| Trust policy abstain / incomplete coverage | abstain (never promote to allow) |
| Heuristic-only artifact | non-authoritative |
| Profile `zkp-required` without verify | cannot allow |
| Real-to-simulation fallback | reject |

## 16. Extension guide

1. **New attestation kind** — requires interface version bump, policy
   non-substitution update, verifier reasons, and explicit docs; default deny
   until allowlisted.
2. **New ZK backend** — implement backend protocol; add to approved backend and
   algorithm allowlists only after security review; never alias as `simulated`
   for production.
3. **New circuit** — registry entry with digest, VK id/digest, public-input
   schema; promotion receipt required.
4. **New trust-policy knob** — must not enable forbidden substitutions; update
   `default_production_trust_policy` tests.
5. **Do not** document simulation as production-safe, or cache presence as
   verification.

## 17. Related documents

| Document | Relationship |
| --- | --- |
| [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md) | Constraint compilation, applicability, heuristic admission |
| [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md) | Solver/ITP lifecycle and authority separation |
| [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) | Kernel identity and `AuthorityKind` |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flow D hops D3–D5 |
| [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md) | Operator package map, rollout, incidents |
| [logic/zkp/SECURITY_CONSIDERATIONS.md](../../logic/zkp/SECURITY_CONSIDERATIONS.md) | Historical simulation warning for default ZKP demo backend |
| [LOGIC_INTENT_LEGAL_GATE_PLAN.md](../LOGIC_INTENT_LEGAL_GATE_PLAN.md) / [INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md](../INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md) | Program design history |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) / [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Layered authority and fail-closed rules |
