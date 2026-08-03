# Result authority taxonomy and non-substitution

| Field | Value |
| --- | --- |
| Interface | `ResultAuthorityTaxonomy@1` |
| Task | `IPFSDOC-044` |
| Status | `canonical` |
| Owner | architecture / logic-policy |
| Source of truth | `ipfs_datasets_py/logic/ir_core/protocols.py` (`AuthorityKind`, `ResultAuthority`, `BoundedResult`, proof receipts); `ipfs_datasets_py/logic/proof_corpus/model.py` (`result_authority`, attestation kinds); `ipfs_datasets_py/logic/formalization/constraint_contracts.py` (`reject_result_authority_substitution`); `ipfs_datasets_py/logic/admissibility/compose.py` / `portfolio.py` (`NON_ALLOWING_AUTHORITY_PATHS`); `ipfs_datasets_py/logic/security_ir/results.py`; [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [GOVERNED_AUTHORIZATION.md](./GOVERNED_AUTHORIZATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, documentation author |
| Related | [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md), [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md), [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md), [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md), [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) |
| Review cadence | when `AuthorityKind`, status vocabularies, attestation–authority bindings, or portfolio non-allow paths change |

## 1. Purpose

This guide answers: **what closed, non-hierarchical result-authority kinds
exist, which status values are legal under each kind, why kinds are never
substitutable for each other, how attestation classes interact without
upgrading authority, which paths can never produce authorization allow, and
why proof (or any positive outcome under a non-authorization kind) alone
never grants execution.**

It is the **result-authority taxonomy** leaf for the logic-policy track.
Governed composition, receipts, and pre-dispatch consumption are owned by
[GOVERNED_AUTHORIZATION.md](./GOVERNED_AUTHORIZATION.md). Attestation kinds and
ZKP profiles are owned by
[PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md). Layered product
vocabulary is frozen in [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md).

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material.

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Label claims with the correct authority layer and kind |
| **Backend / prover author** | Emit `ResultAuthority` matching the query kind |
| **Authorization / gate author** | Refuse non-allowing authority paths |
| **Security reviewer** | Confirm simulation and SAT cannot promote to theorem or allow |
| **Documentation author** | Avoid collapsing “proved”, “sat”, “ready”, “approved”, “allowed” |

## 3. Scope and non-goals

### In scope

- Closed **`AuthorityKind`** enumeration and `ResultAuthority` binding.
- Per-kind **status vocabularies** (`ResultStatus`) and mismatch rejection.
- **Query kind ↔ authority kind** lockstep (`QueryKind.authority_kind`).
- **Non-substitution** helpers and portfolio/compose non-allow paths.
- Interaction of **attestation kinds** with `result_authority` on proof
  envelopes.
- Explicit inequalities: SAT ≠ theorem; monitor ≠ proof; evidence gate ≠
  policy; policy ≠ authorization; **proof ≠ execution**.
- How **simulation** and membership **do not** authorize production.

### Non-goals

- Solver install recipes and hammer routing (owned by
  [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md)).
- Pre-dispatch one-time consumption mechanics (owned by
  [GOVERNED_AUTHORIZATION.md](./GOVERNED_AUTHORIZATION.md)).
- Circuit/VK and ZKP backend class details (owned by
  [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md)).
- Documentation source-of-truth ranking for guides themselves (owned by
  [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 4. Mental model

```text
  Backend request (QueryKind)
           │
           │  authority_kind must match exactly
           ▼
  BoundedResult + ResultAuthority(kind, issuer, method, scope_digest, …)
           │
           │  status ∈ kind-allowed set only
           ▼
  Typed family result
  (theorem | sat | monitor | evidence | policy)
           │
           │  never silent promotion across kinds
           ▼
  Optional: AttestedProofEnvelope.result_authority
           │
           ▼
  Admissibility / authorization compose
  (allow only under AuthorizationDecisionPolicy — separate layer)
           │
           ▼
  Dispatch only after allow + capability + pre-dispatch consume
```

**There is no hierarchy among result-authority kinds.** `ResultAuthority.permits`
returns true only for the **exact** kind. Renaming a field or sharing a generic
`status: ok` across kinds is forbidden on trust-bearing paths.

## 5. Package and interface map

| Package / path | Role | Primary symbols |
| --- | --- | --- |
| `logic.ir_core.protocols` | Kernel authority contracts | `AuthorityKind`, `QueryKind`, `ResultStatus`, `ResultAuthority`, `BoundedResult`, `AuthorityMismatchError` |
| `logic.formalization.constraint_contracts` | Cross-domain rejection helper | `reject_result_authority_substitution` |
| `logic.proof_corpus.model` | Envelope-bound authority + attestation | `result_authority`, `AttestationKind`, parse helpers |
| `logic.proof_corpus.policy` | Trust policy required authority | `required_result_authority`, simulation rejection |
| `logic.admissibility.compose` | Decision non-allow paths | `NON_ALLOWING_AUTHORITY_PATHS` |
| `logic.admissibility.portfolio` | Portfolio non-allow verdicts | `_NON_ALLOWING_VERDICTS`, simulation |
| `logic.security_ir.results` | Domain result families | typed Security results; authority checks |

```python
from ipfs_datasets_py.logic.ir_core.protocols import (
    AuthorityKind,
    QueryKind,
    ResultAuthority,
    ResultStatus,
    AuthorityMismatchError,
)
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    reject_result_authority_substitution,
)
```

Schema version: `result-authority/v1` (`RESULT_AUTHORITY_SCHEMA_VERSION`).

## 6. Closed authority kinds

`AuthorityKind` is a closed, intentionally **non-hierarchical** enum:

| Kind value | Semantic question | Does **not** establish |
| --- | --- | --- |
| `theorem_proof` | Was a formal property proved or disproved under declared assumptions? | Authorization to execute; completeness of the unmodeled world |
| `satisfiability` | Does a modeled formula have a model (SAT/UNSAT) under bounds? | Theorem proof under a different encoding; production security |
| `runtime_monitor` | Did a **bounded** runtime trace satisfy/violate a monitor property? | Global safety proof; future traces; policy allow |
| `evidence_readiness` | Is required evidence present and well-formed for a gate? | Truth of the underlying claim; permission |
| `policy_approval` | Did a configured policy process approve/reject an artifact or release step? | Theorem authority; automatic remote side effects |

Descriptive aliases used by adapters (same wire values): `proof` →
`theorem_proof`; `runtime_monitoring` → `runtime_monitor`; `evidence_gate` →
`evidence_readiness`; `policy_decision` → `policy_approval`.

### 6.1 Query kind lockstep

`QueryKind` mirrors the same five values. Every backend request declares a
query kind; its `authority_kind` property returns the matching
`AuthorityKind`. A result whose authority kind differs from the request is
rejected (`AuthorityMismatchError` / scope_digest rules).

**scope_digest** on `ResultAuthority` must equal the request digest on
protocol results that enforce binding — authority is scoped to the exact
question asked, not to a sibling question with a similar status string.

### 6.2 ResultAuthority record

`ResultAuthority` binds:

| Field | Role |
| --- | --- |
| `kind` | Exact `AuthorityKind` |
| `issuer` | Who assigned the authority (verifier / decision process id) |
| `method` | How (algorithm / procedure tag) |
| `scope_digest` | Content binding to the request / scope |
| `evidence_digests` | Unique supporting digests |
| `configuration_digest` | Optional config / profile binding |
| `schema_version` | Must be `result-authority/v1` |

`permits(required)` / `require(required)` enforce **exact** kind equality.
There is no “stronger than” ordering among kinds.

## 7. Status vocabularies (kind-scoped)

`ResultStatus` values are only meaningful **inside** an authority kind.
Statuses allowed per kind (`_AUTHORITY_STATUSES` in `protocols.py`):

| Authority kind | Allowed statuses |
| --- | --- |
| `theorem_proof` | `proved`, `disproved`, `unknown`, `error` |
| `satisfiability` | `satisfiable`, `unsatisfiable`, `unknown`, `error` |
| `runtime_monitor` | `monitor_satisfied`, `monitor_violated`, `unknown`, `error` |
| `evidence_readiness` | `ready`, `not_ready`, `unknown`, `error` |
| `policy_approval` | `approved`, `rejected`, `unknown`, `error` |

### 7.1 Forbidden promotions via status rename

| Illegal collapse | Why it fails closed |
| --- | --- |
| `unsatisfiable` → `proved` | UNSAT of one encoding is not theorem proof of another obligation |
| `monitor_satisfied` → `proved` | Finite trace ≠ universal theorem |
| `ready` → `approved` | Evidence present ≠ policy decision |
| `approved` → wire `allow` | Policy layer ≠ authorization layer (ADR-003) |
| `proved` → tool dispatch | Proof ≠ authorization ≠ dispatch |
| Generic `ok` / `success` across kinds | Erases authority; rejected on trust-bearing codecs |

`UNKNOWN` and `ERROR` never upgrade `result_authority`. They cannot allow
under closed authorization profiles.

## 8. Typed result families

Kernel and domain layers expose **typed** result envelopes rather than a
single boolean:

| Family (representative) | Expected authority | Affirmative status examples |
| --- | --- | --- |
| Theorem / proof result | `theorem_proof` | `proved` (disproof is `disproved`) |
| Satisfiability result | `satisfiability` | `satisfiable` / `unsatisfiable` |
| Monitor result | `runtime_monitor` | `monitor_satisfied` / `monitor_violated` |
| Evidence-gate result | `evidence_readiness` | `ready` / `not_ready` |
| Policy decision | `policy_approval` | `approved` / `rejected` |
| Admissibility / authorization | **policy composition** (separate) | wire `allow` / `reject` / `abstain` |

Proof receipts require the theorem-specific result type, exact theorem
authority, an affirmative verdict, and consistent bindings through claim,
request, backend attempt, and output digest. A positive outcome in another
family **does not** become a theorem proof by changing a status string.

Security IR result modules raise `AuthorityMismatchError` when a consumer
requests a kind the result does not carry — including portfolio selection
that would treat monitor or sat outcomes as theorem discharge.

## 9. Non-substitution rules

### 9.1 Kind substitution

`reject_result_authority_substitution(claimed, required)` raises
`AuthorityMismatchError` when claimed ≠ required:

> Satisfiability, monitoring, evidence readiness, and policy approval are
> never substitutable for theorem proof (or each other).

Call this at adapter and compose boundaries whenever a job declares a required
authority.

### 9.2 Attestation kind vs result authority

On `AttestedProofEnvelope@1`, **attestation kind** and **result authority**
are orthogonal axes:

| Attestation kind (representative) | May support theorem authority? |
| --- | --- |
| Direct proof verification | Yes, when verify passes and authority is `theorem_proof` |
| Verifier execution | Per policy; not a silent upgrade of membership |
| Artifact membership | **No** — membership is not theorem proof |
| Signature | **No** — integrity/authenticity class only |
| **Simulation** | **No** — never production theorem or allow |

Hard envelope rules include: **simulation attestation cannot claim
`theorem_proof` + `proved`**. Trust policy construction forbids listing
simulation as an authoritative attestation for theorem paths. Production
profiles set `accept_simulated_zkp=false` (except labeled `dev-offline`
fixtures that still never allow without constraints).

Attestation algebra detail:
[PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md).

### 9.3 Portfolio and compose non-allow paths

Authorization composition enumerates authority **paths** that can never
produce allow (`NON_ALLOWING_AUTHORITY_PATHS`), including:

`unsupported`, `unknown`, `contradictory`, `unavailable`, `sat_only`,
`satisfiability`, `model`, `monitor`, `runtime_monitor`, `evidence`,
`evidence_readiness`, `policy`, `policy_approval`, `simulation`, `simulated`.

Portfolio job verdicts mirror the same rule: simulation, SAT-only, monitor,
evidence, policy, timeout, and error verdicts are non-allowing. **Deny**
(hard conflict) and missing **positive grant** remain distinct failure modes
under deny-overrides policy.

## 10. Layered authority (product stack)

Result-authority kinds live primarily at the **proof / sat / monitor /
evidence / policy** layers of ADR-003. Authorization and dispatch are later
layers:

| ADR-003 layer | Typical authority artifact | Does **not** establish |
| --- | --- | --- |
| Parsing / validation | schema-valid IR | Truth or permission |
| Retrieval / model | candidates | Proof or allow |
| Satisfiability | `AuthorityKind.SATISFIABILITY` | Theorem or allow |
| Proof | `AuthorityKind.THEOREM_PROOF` | Allow or dispatch |
| Policy | `AuthorityKind.POLICY_APPROVAL` | Theorem or automatic side effects |
| Authorization | `AuthorizationDecision` / receipt | That the action already ran |
| Dispatch | tool invocation observation | That execution was authorized |
| Monitoring | runtime telemetry | Proof or allow |
| Receipts | content-addressed records | Upgrade of weak evidence |

Hard inequalities (normative):

- Discovery ≠ capability ≠ authorization  
- Syntax ≠ semantics ≠ proof  
- Model / retrieval output ≠ proof  
- Satisfiability under a model ≠ production security of the unmodeled system  
- **Proof ≠ authorization**  
- Monitoring ≠ proof  
- UI visibility ≠ execution authority  
- Receipt presence ≠ success of the underlying claim  
- **Simulation does not authorize** production  
- **Proof alone never grants execution**

## 11. Authorization is not a result-authority kind

Wire authorization outcomes (`allow` | `reject` | `abstain`) are produced by
`AuthorizationDecisionPolicy@1` / `IntentAuthorizationService@1`, not by
promoting `ResultStatus.PROVED` or `APPROVED`.

Implications:

1. A fully verified theorem may still yield **reject** (hard Legal forbid) or
   **abstain** (incomplete Security coverage).
2. A policy `approved` release artifact **does not** auto-allow an MCP tool
   call.
3. A `monitor_satisfied` canary **does not** discharge non-conflict obligations.
4. Side-effect-free evaluation may record proved jobs and still refuse
   capability derivation when the composite decision is non-allow.
5. Pre-dispatch consumption requires allow + valid one-time capability +
   exact-context revalidation — none of which are `AuthorityKind` values.

See [GOVERNED_AUTHORIZATION.md](./GOVERNED_AUTHORIZATION.md) for the pipeline.

## 12. Simulation and fixture authority

| Context | Simulation allowed? | Can allow production dispatch? |
| --- | --- | --- |
| Unit / golden fixtures (`dev-offline`) | Labeled simulation may appear | **No** unconstrained allow; profiles still forbid allow-without-constraints |
| `security-lite` / `legal-strict` / `zkp-required` | Simulated ZKP rejected | **No** |
| Educational ZKP demos | Explicit non-production | **No** |
| Portfolio `JobVerdict.SIMULATION` | Recorded as non-allowing | **No** |

Fixtures under `tests/fixtures/logic/attested_authorization/` may set
`result_authority` fields including `simulation` for negative cases; expected
decisions encode **cannot allow** under production profiles.

## 13. Consumer checklist

When reading or emitting a trust-bearing result, verify:

1. **Kind** — Does `result_authority.kind` (or equivalent) match the question
   you are answering?
2. **Status** — Is the status in the kind’s allowed set?
3. **Scope** — Does `scope_digest` / request digest bind to *this* claim?
4. **Attestation** — If attested, is the attestation kind allowed to support
   that authority under trust policy?
5. **Profile** — Does the active admissibility profile accept this evidence
   class (especially simulation / ZKP)?
6. **Layer** — Are you about to use this result as authorization or dispatch?
   If yes, stop and route through the authorization service and pre-dispatch
   enforcement instead.
7. **Substitution** — Call `reject_result_authority_substitution` (or
   equivalent) rather than casting kinds.

## 14. Failure modes and fail-closed matrix

| Condition | Outcome |
| --- | --- |
| Unknown authority kind string | validation error; reject |
| Status not in kind’s allowed set | validation error; reject |
| Claimed kind ≠ required kind | `AuthorityMismatchError` |
| Simulation + theorem_proof proved | envelope / policy reject |
| Membership or signature as sole theorem evidence | trust policy reject |
| SAT-only path in authorization portfolio | non-allow |
| Policy approved without authorization compose | not wire allow |
| Proof receipt without allow capability | no execution |
| Generic success boolean across kinds | forbidden on trust paths |

## 15. Extension guide

1. **New status for an existing kind** — extend `_AUTHORITY_STATUSES` and all
   codecs/tests; do not reuse another kind’s status names.
2. **New authority kind** — requires a deliberate protocol version and ADR;
   never overload `theorem_proof` or `policy_approval` as a grab-bag.
3. **New backend** — declare `QueryKind` and emit matching `ResultAuthority`;
   portfolio must classify non-allow paths explicitly.
4. **New attestation class** — add to non-substitutable sets before any
   production allowlist; default fail closed.
5. **Do not** introduce hierarchy (“theorem implies allow”), silent
   promotion helpers, or documentation that treats `proved` as permission.

## 16. Validation

```bash
test -s docs/architecture/logic/GOVERNED_AUTHORIZATION.md
test -s docs/architecture/logic/RESULT_AUTHORITY.md
rg -n 'side-effect-free|pre-dispatch|one-time|deny|simulation|does not' \
  docs/architecture/logic/GOVERNED_AUTHORIZATION.md \
  docs/architecture/logic/RESULT_AUTHORITY.md
```

Representative code contracts:

```bash
python -m pytest \
  tests/unit/logic/ir_core/ \
  tests/unit/logic/proof_corpus/ \
  tests/unit/logic/admissibility/ \
  -q --collect-only
```

## 17. Related documents

| Document | Relationship |
| --- | --- |
| [GOVERNED_AUTHORIZATION.md](./GOVERNED_AUTHORIZATION.md) | Side-effect-free service, receipts, pre-dispatch, one-time consumption |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Product-wide layered authority decision |
| [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md) | Attestation kinds; simulation never theorem |
| [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md) | Solver results and non-substitution of SAT |
| [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) | Kernel identity and authority enumeration |
| [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md) | Security hard filter on result-authority family |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Kinds of truth for documentation claims |
| [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md) | Operator-facing invariants |
