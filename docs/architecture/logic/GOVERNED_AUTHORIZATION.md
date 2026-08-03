# Governed intent authorization (side-effect-free evaluation to pre-dispatch)

| Field | Value |
| --- | --- |
| Interface | `GovernedAuthorizationArchitecture@1` |
| Task | `IPFSDOC-044` |
| Status | `canonical` |
| Owner | architecture / logic-policy |
| Source of truth | `ipfs_datasets_py/logic/admissibility/` (`service`, `compose`, `portfolio`, `receipt`, `enforcement`, `runtime`, `gate`, `profiles`, `telemetry`, `api`); `ipfs_datasets_py/logic/intent_ir/invocation/`; `ipfs_datasets_py/logic/proof_corpus/`; [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md); [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md); [RESULT_AUTHORITY.md](./RESULT_AUTHORITY.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, operator, release owner |
| Related | [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow D–E, [INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md](../INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md), [mcp/SERVER_AND_DISPATCH.md](../mcp/SERVER_AND_DISPATCH.md) |
| Review cadence | when authorization pipeline stages, receipt/capability contracts, pre-dispatch consumption, rollout policy, or telemetry labels change |

## 1. Purpose

This guide answers: **how a proposed SkillCenter skill, prompt, or MCP tool
invocation is converted into an immutable intent envelope, how applicable
Legal/Security constraints and proof-corpus evidence are selected and
verified, how obligations and a deterministic portfolio produce a
fail-closed decision, how that decision stays side-effect-free until an
exact-context pre-dispatch revalidation atomically consumes a one-time
capability, and how revocation, cache, telemetry, and receipts remain
separate from execution.**

It is the **governed authorization composition** leaf for the logic-policy
track. Constraint compilation and hard applicability are owned by
[LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md).
Attestation algebra, independent verification, and ZKP profiles are owned by
[PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md). Typed
result-authority kinds and non-substitution rules are owned by
[RESULT_AUTHORITY.md](./RESULT_AUTHORITY.md).

**Core inequality:** proof (or any earlier authority layer) alone **does not**
grant execution. Prompts, skill bodies, and MCP tool bodies remain **data**
during evaluation; they are never executed by the authorization service.

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place gate, service, receipt, and enforcement work without collapsing evaluate into dispatch |
| **Authorization integrator** | Wire `IntentAuthorizationService@1` and `PreInvocationEnforcement@1` with exact roots |
| **Security / policy reviewer** | Confirm deny-overrides, simulation rejection, and one-time consumption |
| **Operator / release owner** | Interpret rollout stages, telemetry, rollback, and receipt consumption disable |
| **MCP / dispatcher author** | Consume capabilities only after pre-dispatch revalidation; never invent allow from proof |

## 3. Scope and non-goals

### In scope

- **Immutable invocation intent** (`InvocationIntentEnvelope@1`) from skill,
  prompt, or MCP sources without executing bodies.
- **Constraint applicability** composition into an authorization query
  (Legal + Security hard filters; Intent formalization).
- **Proof-corpus query and independent verification** under pinned corpus,
  revocation, and trust-policy roots.
- **Obligation jobs and portfolio decision** (`AuthorizationQueryComposer@1`,
  `AuthorizationPortfolio@1`, `AuthorizationDecisionPolicy@1`).
- **Side-effect-free authorization** (`IntentAuthorizationService@1`).
- **Decision receipts and one-time capabilities** (`DecisionReceipt@1`,
  `AuthorizationCapability@1`).
- **Exact-context pre-dispatch revalidation** and **atomic one-time
  capability consumption** (`PreInvocationEnforcement@1`,
  `CapabilityConsumptionStore@1`).
- **Separate dispatch** observation (never promoted to authorization).
- **Tenant-safe decision cache**, **revocation root binding**, **redacted
  telemetry**, and **staged rollout policy**.

### Non-goals

- Legal/Security hard-filter dimension catalogs (owned by
  [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md)).
- Attestation-kind algebra and ZKP circuit/VK details (owned by
  [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md)).
- Result-authority taxonomy deep dive (owned by
  [RESULT_AUTHORITY.md](./RESULT_AUTHORITY.md)).
- Real tool execution, network skill install, or solver package install during
  evaluation.
- Providing legal advice or replacing human review for unmodeled jurisdictions.
- Treating retrieval rank, model confidence, cache hits, membership proofs,
  simulation, or green monitors as production allow.

## 4. Mental model

```text
  SkillCenter skill · prompt · MCP tool request
           │
           │  adapters (bodies are data; never executed here)
           ▼
  InvocationIntentEnvelope@1  (immutable · content-addressed)
           │
           ▼
  normalize / formalize Intent  ──► obligations + action scope
           │
           ├──── Legal hard applicability ────┐
           ├──── Security hard applicability ─┤
           └──── proof-corpus query + verify ─┘
           │
           ▼
  AuthorizationQueryBundle@1  (proof jobs per action/effect)
           │
           ▼
  portfolio run (deterministic · no install side effects)
           │
           ▼
  AuthorizationDecision@1  ──wire──► allow | reject | abstain
           │
           ▼
  DecisionReceipt@1  (+ optional one-time AuthorizationCapability@1)
           │
           │  ── evaluation ends here (side-effect-free) ──
           │
           ▼
  PreInvocationEnforcement@1
  · revalidate exact context / roots / environment
  · atomic compare-and-consume capability
           │
           ▼
  separate dispatcher  ──► DispatchObservation (not authorization)
```

**Evaluation answers “may this invocation be authorized under this profile
and roots?” Dispatch answers “did a control plane invoke a tool once under a
consumed capability?” Those questions must never share a single boolean.**

## 5. Package and interface map

| Package / path | Role | Primary interfaces |
| --- | --- | --- |
| `logic.intent_ir.invocation` | Source adapters → immutable envelope | `InvocationIntentEnvelope@1`, skill/prompt/MCP adapters |
| `logic.admissibility.gate` | Composite admissibility join | `IntentAdmissibilityGate`, `AdmissibilityDecision` |
| `logic.admissibility.compose` | Jobs + deny-overrides decision policy | `AuthorizationQueryComposer@1`, `AuthorizationDecisionPolicy@1`, `AuthorizationDecision@1` |
| `logic.admissibility.portfolio` | Deterministic portfolio selection | `AuthorizationPortfolio@1` |
| `logic.admissibility.service` | End-to-end side-effect-free service | `IntentAuthorizationService@1` |
| `logic.admissibility.receipt` | Receipt + capability codecs | `DecisionReceipt@1`, `AuthorizationCapability@1` |
| `logic.admissibility.enforcement` | Pre-dispatch boundary | `PreInvocationEnforcement@1`, `CapabilityConsumptionStore@1` |
| `logic.admissibility.runtime` | Tenant-safe cache + runtime glue | `DecisionCacheKey@1`, `TenantSafeDecisionCache@1`, `AuthorizationRuntime@1` |
| `logic.admissibility.profiles` | Fail-closed profile registry | `AdmissibilityProfile@1` |
| `logic.admissibility.telemetry` | Redacted metrics + rollout stages | `AuthorizationTelemetry@1`, `AuthorizationRolloutPolicy@1` |
| `logic.proof_corpus` | Corpus, trust, revocation, verifier | see proof-attestation leaf |

```python
from ipfs_datasets_py.logic.admissibility import (
    IntentAuthorizationService,
    DecisionReceipt,
    AuthorizationCapability,
    PreInvocationEnforcement,
    AuthorizationRolloutPolicy,
    evaluate_authorization,
)
from ipfs_datasets_py.logic.submodule_registry import logic_submodule_spec

logic_submodule_spec("admissibility")
logic_submodule_spec("proof_corpus")
logic_submodule_spec("intent_ir.invocation")
```

Leaf modules remain authoritative for field-level contracts; package roots
re-export reviewed symbols only. Plain imports stay dependency-light: they
**do not** load optional solvers, network clients, or circuit tooling.

## 6. Immutable invocation intent

### 6.1 Envelope role

`InvocationIntentEnvelope@1` is the **only** upstream input the authorization
service trusts for evaluation. Source-specific adapters project:

| Source | Adapter role |
| --- | --- |
| Pinned SkillCenter skill | Observe skill identity, version, arguments commitment, effects — **do not** run the skill |
| User / agent prompt | Capture prompt commitment and requested effects — **do not** execute prompt instructions as tools |
| MCP tool call | Capture server/tool/version/arguments — **do not** invoke the tool |

Adapters **do not** grant permission. They produce grounded Intent structure
and digests so later stages can bind receipts and capabilities.

### 6.2 Required identity and scope (representative)

Evaluation identity binds (at minimum):

- schema/version and invocation kind;
- tenant, actor, delegator chain, audience, trust domain;
- tool / skill / prompt identity and version;
- argument and effect commitments (content digests, not raw secrets);
- environment snapshot digest;
- policy, corpus, and revocation roots;
- nonce, issued time, and expiry bounds;
- redaction commitments for telemetry/audit.

Mutating any security-relevant field after issuance produces a **different**
envelope digest. Receipts and capabilities reject mismatched digests
fail-closed.

### 6.3 Bodies remain data

| Artifact | During authorization evaluation |
| --- | --- |
| Prompt text / instructions | Data: hashed or redacted; never tool-executed by the service |
| Skill implementation body | Data: not imported for side effects; not run |
| MCP tool handler | Data: not dispatched; not networked for effect |
| Solver / prover binaries | Optional portfolio probes only; PATH lookup **does not** install packages |

Offline golden fixtures under `tests/fixtures/logic/attested_authorization/`
encode skill / prompt / MCP **equivalent** cases with bound expected
decisions and **never** execute bodies.

## 7. Constraint applicability in the authorization path

Authorization **reuses** Legal and Security hard applicability; it does not
invent a second kernel.

1. From the invocation envelope, compose domain queries
   (`LegalConstraintQuery@1`, `SecurityConstraintQuery@1`) and shared
   `ApplicabilityEvidence@1`.
2. Hard filters always run **before** ranking or budgeted selection
   ([LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md) §7).
3. Retrieval, GraphRAG, and learned ranks may order candidates only after
   hard-filter admission; they never select authority.
4. Missing required domains under the active profile → reject or abstain,
   never unconstrained allow (`allow_without_constraints` is forbidden on
   every profile).

Applicability evidence is an input to composition. It is **not** a policy
allow and **not** a theorem.

## 8. Proof-corpus query and verification

### 8.1 Query under exact roots

The service selects candidate `AttestedProofEnvelope@1` rows from
`ProofCorpusStore@1` under:

- pinned **corpus manifest root**;
- pinned **revocation snapshot root**;
- **trust / coverage policy** digests;
- tenant, jurisdiction, temporal, and scope filters;
- required attestation kinds and result-authority families.

Hard rejections (revoked, superseded, root mismatch, authority mismatch,
trust-policy reject) outrank soft ranking.

### 8.2 Independent consumer verification

Cache presence and producer claims are **not** authority. Before evidence may
feed obligation discharge:

1. `AttestedProofVerifier@1` re-checks bindings under exact roots;
2. attestation kinds remain non-substitutable (`simulation` and
   `artifact-membership` cannot become direct proof verification);
3. production profiles reject simulated ZKP (`accept_simulated_zkp=false`
   outside `dev-offline`);
4. incomplete coverage under required domains cannot allow.

Details: [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md).

### 8.3 Revocation at evaluation time

A target present in the active `ProofRevocationSnapshot@1` is hard-rejected at
applicability. Evaluation records the revocation root on the decision receipt.
**Never** mark old receipts valid under a new policy, corpus, or revocation
root—re-evaluate or fail closed.

## 9. Obligations and portfolio decision

### 9.1 Query composition

`AuthorizationQueryComposer@1` emits per-action / per-effect **proof jobs**
that preserve native logic families and typed cross-view links. Silent
cross-family formula concatenation is forbidden.

Closed-profile required job kinds (`CLOSED_PROFILE_REQUIRED_JOBS`) include:

| Job kind | Purpose |
| --- | --- |
| `applicability` | Selected constraints hard-apply to this invocation |
| `positive_grant` | Explicit applicable permission (not absence of deny) |
| `non_conflict` | Proved non-conflict with applicable forbids / exceptions |
| `security_invariant` | Hard Security invariants hold for requested effects |
| `obligation_pre` | Pre-dispatch residual duties discharged or bound |
| `coverage` | Required corpus / domain coverage complete under profile |
| `context_binding` | Actor, audience, tool, args, env, roots bind consistently |

Additional jobs (`obligation_during` / `post`, `consistency`, `translation`,
`reconstruction`) may be required by profile or action class.

### 9.2 Decision policy (deny-overrides)

`AuthorizationDecisionPolicy@1` is **closed-world deny-overrides**:

- An applicable hard **deny** / forbid wins over grants.
- **ALLOW** requires every configured positive gate: applicable positive
  grant **and** proved non-conflict **and** discharged mandatory jobs
  **and** coverage **and** context binding.
- Absence of a retrieved prohibition **does not** become permission.
- Unknown, unsupported, contradictory, unavailable, timeout, SAT-only,
  monitor-only, evidence-only, policy-only, and **simulation** paths are
  listed in `NON_ALLOWING_AUTHORITY_PATHS` and can never authorize allow.

Internal multi-status vocabulary:

| Internal | Meaning |
| --- | --- |
| `allow` | All mandatory gates proved under profile |
| `deny` | Hard conflict or explicit forbid |
| `review` | Human / policy review required |
| `indeterminate` | Incomplete evidence; not allow |
| `error` | Evaluation failure; not allow |

### 9.3 Wire mapping

Internal statuses map to the closed wire set **`allow` | `reject` | `abstain`**
without reverse inference:

| Internal | Wire |
| --- | --- |
| `allow` | `allow` |
| `deny` | `reject` |
| `review` / `indeterminate` / `error` | `abstain` (or reject when profile maps errors that way) |

**Abstain never promotes to allow.** Compatibility maps are one-way.

### 9.4 Portfolio execution

`AuthorizationPortfolio@1` runs emitted jobs with:

- explicit backend capability and logic support;
- PATH probes **without installation**;
- recorded attempts, timeouts, translations, assumptions, reconstruction;
- **deterministic, order-independent** result selection;
- contradictory authoritative backend results → fail closed / review;
- unavailable backends never recorded as successful proves.

Authority paths that **cannot** allow (portfolio and compose agreement):
unsupported, unknown, contradictory, unavailable, SAT-only, model, monitor,
evidence, policy, simulation.

## 10. Side-effect-free authorization service

`IntentAuthorizationService@1` composes normalize → evidence → compose →
portfolio → decide → receipt (→ optional capability) as one deterministic
source-to-decision API.

### 10.1 Purity invariants

Evaluation is pure with respect to corpus and environment:

| Forbidden side effect during evaluation | Enforcement |
| --- | --- |
| Execute skill / prompt / MCP bodies | Service never dispatches tools |
| Install prover packages | Portfolio PATH-probes only |
| Mutate proof corpus | Read-only query + verify |
| Authorize simulated evidence under production profiles | Profile + trust policy reject |
| Derive capability from non-allow | `derive_capability` requires allow receipt |
| Convert exceptions into allow | Fail closed to reject / abstain / error |

Trace stages (`AuthorizationStage`): `validate`, `normalize`, `lower`,
`evidence`, `compose`, `portfolio`, `decide`, `receipt`, `capability`,
`complete` (plus `error` / `cancelled`).

### 10.2 Budgets and cancellation

Budgets bound job counts, wall time, and evidence selection. Exceeding budget
or cancellation mid-pipeline **does not** yield allow. Offline unit tests
inject normalizers, selectors, verifiers, solvers, and clocks through
dependency seams without real network or install.

### 10.3 Public gate join

`IntentAdmissibilityGate` / `evaluate_admissibility` remain available for
profile-scoped composite checks. The full authorization service is the
production path when receipts and capabilities are required. Both share:
no unconstrained allow; unknown profile → reject (`invalid_profile`).

## 11. Decision receipts

`DecisionReceipt@1` is an immutable, content-addressed binding of the
decision to its full evaluation context. Minimum bindings:

| Group | Representative fields |
| --- | --- |
| Request | envelope / request digests, action scope, effect commitments |
| Principal | actor, delegation, audience, tenant |
| Tool | tool/skill identity and version |
| Evidence | selected evidence pack digests, obligation and job results |
| Roots | policy, corpus, revocation, circuit/VK as required |
| Outcome | internal + wire status, reason codes, residual duties |
| Time | issued, deadline, expiry; nonce |
| Producer | producer id, identity algorithm (`sha256-canonical-json/v1`) |

Receipt verification rejects: mutation, widening of effects, wrong audience,
stale roots, expired times, unknown schema/algorithm, and all non-allow
claims presented as allow.

**Receipt presence does not mean the action ran.** Receipts are authorization
artifacts for consumers and auditors, not dispatch logs.

## 12. One-time capabilities

### 12.1 Derivation

`AuthorizationCapability@1` is derived **only** from an `allow`
`DecisionReceipt@1` under **strict subset attenuation**:

- audience-bound;
- short-lived (capability TTL ≤ receipt expiry);
- effect and tool scope ⊆ receipt scope (never widened);
- one-time marker required for pre-dispatch consumption;
- identity algorithm closed-set.

Non-allow decisions **cannot** derive capabilities. Widening attenuation
fails closed.

### 12.2 What a capability is not

| Misread | Correct treatment |
| --- | --- |
| Capability = already executed | Separate dispatch observation only after consumption |
| Capability = reusable API key | One-time compare-and-consume; second use rejects |
| Capability = theorem proof | Policy authorization only; authority kinds stay separate |
| Capability from reject/abstain | Forbidden |

## 13. Exact-context pre-dispatch revalidation

`PreInvocationEnforcement@1` sits at the **dispatch boundary**, after
evaluation. It:

1. Rejects every non-allow receipt / missing capability.
2. **Revalidates exact current context** immediately before side effect:
   actor, audience, tenant, tool version, argument commitments, effects,
   environment snapshot, policy/corpus/revocation roots, nonce, expiry.
3. Verifies receipt and capability integrity (`verify_decision_receipt`,
   `verify_capability`).
4. **Atomically compare-and-consumes** the one-time capability via
   `CapabilityConsumptionStore@1` (race-safe; concurrent losers get
   `ConsumptionRaceError` / already-consumed rejection).
5. Only then optionally invokes a side-effect dispatcher **once**.
6. Emits `DispatchObservation` / enforcement result **separate** from the
   authorization receipt.

### 13.1 TOCTOU protection

Evaluation-time roots and environment can drift before dispatch. Pre-dispatch
revalidation is mandatory: a still-valid-looking cached allow **does not**
bypass fresh root, environment, expiry, or consumption checks.

### 13.2 Atomic one-time consumption

| Property | Rule |
| --- | --- |
| Atomicity | Compare-and-consume is single-winner under races |
| Tenant scope | Store keys are tenant-isolated; cross-tenant reuse fails |
| Replay | Consumed capability id never re-authorizes |
| Non-allow | Never enters consumption path as success |

Reference implementation: in-memory store for tests; production stores must
preserve the same fail-closed race semantics.

## 14. Separate dispatch

Dispatch is **layer 8** in [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md):

- Hierarchical MCP tool discovery and `tools_dispatch` are control-plane
  execution, not proof or authorization.
- Successful tool execution **does not** establish Legal compliance, theorem
  proof, or that authorization was sound.
- Failed dispatch after consume must not resurrect the capability (one-time
  is one-time); residual duties and incidents are operational, not automatic
  re-allow.
- Fake / test dispatchers exist for race and enforcement tests; they **do
  not** connect to real tools from the enforcement leaf.

Optional MCP pre-dispatch pipelines
([mcp/SERVER_AND_DISPATCH.md](../mcp/SERVER_AND_DISPATCH.md)) may consult this
stack; they must not invent a parallel allow path.

## 15. Tenant-safe decision cache

`DecisionCacheKey@1` / `TenantSafeDecisionCache@1` (`runtime.py`):

- Domain-separated key over the **complete** security-relevant context
  (actor, delegation, audience, tool version, argument commitments, policy /
  corpus / revocation roots, environment, evidence-coverage profile).
- Keys never embed secrets, raw prompts, or free-form CIDs as label dumps.
- Cache **does not** cross tenant or audience boundaries.
- Positive-TTL allow cache only under exact key match; unsafe reuse of
  negative / unknown results is forbidden unless a profile **explicitly**
  proves monotonicity (default: no).
- Cache hit **does not** skip pre-dispatch revalidation or one-time
  consumption.
- Cache hit **does not** substitute for independent proof verification on
  first evaluation.

Legacy family proof caches and IPFS proof helpers are migration sources only;
they are not authorization authority by themselves.

## 16. Telemetry and rollout

### 16.1 Redacted telemetry (`AuthorizationTelemetry@1`)

Metrics use a **closed, bounded label vocabulary**: source kind, outcome
class, policy profile, authority class, latency buckets, cache/filter
classes. **Rejected** as labels: raw prompts, arguments, formulas, witnesses,
secrets, free-form CIDs, passwords, API keys.

Telemetry **does not** authorize and **does not** carry theorem evidence.

### 16.2 Staged rollout (`AuthorizationRolloutPolicy@1`)

Ordered stages (skipped transitions rejected):

```text
off → audit → shadow → deny-canary → allow-token-canary → enforce
```

| Stage | Behavior |
| --- | --- |
| `off` / `audit` | Observe or log; no consumption enforcement |
| `shadow` | Full evaluation; no live deny of traffic by gate |
| `deny-canary` | Enforce deny for allowlisted cohort; measure false-deny |
| `allow-token-canary` | Short-lived one-time receipts for **reversible** effects only; zero simulated-ZKP allows |
| `enforce` | Full pre-dispatch consumption under approvals |

Receipt consumption defaults **off**. Immediate disable:
`AuthorizationRolloutPolicy.immediate_disable_receipt_consumption()` (or
config `receipt_consumption_enabled=false`). Prefer disabling consumption
before deleting evidence. Production observation default remains shadow until
enforce is explicitly approved.

Operator detail:
[guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md).

## 17. End-to-end invariants (normative)

1. **Source grounding is mandatory** — ungrounded semantics are assumptions or
   fail closed.
2. **Bodies remain data** — prompts, skills, MCP handlers are not executed by
   evaluation.
3. **Retrieval is never proof** — hard filters first.
4. **Cache hit is never self-authenticating** — consumer verifies.
5. **Simulation cannot authorize** production allow paths.
6. **Unknown is not allow** — missing evidence, timeout, unsupported
   semantics, incomplete coverage → reject/abstain.
7. **SAT / monitor / evidence / policy alone do not allow** — see
   [RESULT_AUTHORITY.md](./RESULT_AUTHORITY.md).
8. **Deny overrides** — absence of deny is not grant.
9. **Proof does not grant execution** — only allow + valid capability +
   pre-dispatch revalidation + consumption.
10. **Decisions are context-bound** — actor, audience, nonce, tool, args,
    roots, environment, times are part of the receipt.
11. **Dispatch revalidates and consumes once** — TOCTOU and race safe.
12. **Revocation and root promotion** require re-evaluation under new roots;
    old receipts are not retroactively valid.
13. **Telemetry and rollout** never invent authority.

## 18. Failure modes and fail-closed matrix

| Condition | Outcome |
| --- | --- |
| Unknown / invalid profile | reject (`invalid_profile`) |
| Envelope schema / digest invalid | reject / error (not allow) |
| Required Legal/Security constraints missing | reject or abstain |
| Hard Legal forbid / Security deny applicable | reject |
| Simulation or membership used as theorem under production | cannot allow |
| Proof verified but positive grant missing | cannot allow |
| Portfolio contradiction / timeout / unavailable | abstain / reject / review |
| Non-allow decision | no capability derivation |
| Receipt mutation / expiry / root drift | verification fail; pre-dispatch reject |
| Capability already consumed | reject (`consumption_race` / already consumed) |
| Context mismatch at pre-dispatch | reject |
| Receipt consumption disabled by rollout | no live enforce; evaluation may still run |
| Exception in service | never mapped to allow |

## 19. Extension guide

1. **New invocation source** — add an adapter that emits
   `InvocationIntentEnvelope@1` without executing the source body; add golden
   fixtures.
2. **New proof job kind** — extend compose/portfolio with schema discipline;
   decide whether it is mandatory under closed profiles; never auto-allow on
   advisory jobs.
3. **New dispatcher** — implement behind `PreInvocationEnforcement` only after
   atomic consumption; emit separate observation records.
4. **New cache backend** — preserve domain-separated keys and tenant isolation;
   never skip revalidation.
5. **New telemetry label** — add only to the closed vocabulary; reject secrets
   and free-form CIDs.
6. **Do not** add a path that allows without constraints, derives capability
   from non-allow, reuses a consumed capability, or treats proof/simulation as
   execution rights.

## 20. Validation

Structural guide check:

```bash
test -s docs/architecture/logic/GOVERNED_AUTHORIZATION.md
test -s docs/architecture/logic/RESULT_AUTHORITY.md
rg -n 'side-effect-free|pre-dispatch|one-time|deny|simulation|does not' \
  docs/architecture/logic/GOVERNED_AUTHORIZATION.md \
  docs/architecture/logic/RESULT_AUTHORITY.md
```

Representative implementation suites (when available):

```bash
python -m pytest \
  tests/unit/logic/admissibility/test_attested_golden_contract.py \
  tests/integration/logic/test_attested_intent_authorization.py \
  tests/integration/logic/test_intent_admissibility_gate.py \
  -q
```

Fixtures: `tests/fixtures/logic/attested_authorization/`.

## 21. Related documents

| Document | Relationship |
| --- | --- |
| [RESULT_AUTHORITY.md](./RESULT_AUTHORITY.md) | Non-interchangeable result-authority kinds; proof ≠ authorization |
| [LEGAL_AND_SECURITY_CONSTRAINTS.md](./LEGAL_AND_SECURITY_CONSTRAINTS.md) | Constraint compilation and hard applicability |
| [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md) | Attestation, verifier, simulation rejection, ZKP profiles |
| [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) | Kernel identity; authority kinds enumeration |
| [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md) | Solver lifecycle; SAT is not theorem permission |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Layered authority stack |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Fail-closed degradation |
| [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md) | Operator surface, rollout, rollback |
| [INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md](../INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md) | Historical/active plan (not runtime authority) |
| [mcp/SERVER_AND_DISPATCH.md](../mcp/SERVER_AND_DISPATCH.md) | Dispatch control plane; optional pre-dispatch hooks |
