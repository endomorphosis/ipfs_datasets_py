# ADR-004: Fail-closed trust boundaries and allowed degradation

| Field | Value |
| --- | --- |
| Interface | `FailClosedDecision@1` |
| Task | `IPFSDOC-014` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture; logic/admissibility owners; security/policy consumers |
| Consulted | documentation-governance; operators; MCP runtime maintainers |
| Source of truth | `ipfs_datasets_py/logic/proof_corpus/model.py` (`ProofResultStatus`, non-authoritative attestation kinds); `ipfs_datasets_py/logic/admissibility/compose.py` / `gate.py` (allow/reject/abstain, deny-overrides); `ipfs_datasets_py/logic/security_models/crypto_exchange/` (`PROVED` / `DISPROVED` / `UNKNOWN` / `NOT_MODELED`, release gates); [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) §9; [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) §7–8, §11; [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md); [ADR-003-LAYERED-AUTHORITY.md](ADR-003-LAYERED-AUTHORITY.md) |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Cross-cutting product decision paired with layered authority (ADR-003) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The product runs in incomplete environments: optional extras missing, empty git
submodules, absent prover binaries, offline networks, partial IR models, and
best-effort remote caches. **Availability** problems are normal and often
deserve graceful feature degradation (local fallback, soft-disable, structured
error).

**Trust** problems are different. Incomplete evidence, unmodeled obligations,
unknown solver outcomes, and missing validators must not become silent allow,
silent prove, or silent “production ready.” The codebase already fail-closes in
many places:

- Proof envelopes default uncertain statuses and separate non-authoritative
  attestation kinds (`simulation`, `artifact-membership`).
- Intent admissibility maps incomplete evidence to **abstain** / non-allow, hard
  forbid to **reject**, and requires profile resolution that fails closed.
- Authorization composition is closed-world deny-overrides; weak “no deny
  found” shortcuts are not default allow.
- Security-model release gates treat **UNKNOWN** and **NOT_MODELED** as
  non-secure outcomes; blocking claims with those statuses fail release under
  strict policies.
- Dependency lifecycle documentation already states: degrade **features**; fail
  closed on **trust**.

This ADR defines the **outcome vocabulary** (`UNKNOWN`, `NOT_MODELED`,
`unavailable`, `denied` / reject, and related labels) and the rule for when
degradation is allowed versus mandatory fail-closed behavior. It depends on
[ADR-003](ADR-003-LAYERED-AUTHORITY.md) for non-interchangeable layers.

## Decision

We will apply **two distinct policies**:

1. **Graceful feature degradation** — for optional compute, media, backends,
   scrapers, and non-authoritative helpers when dependencies or environment
   capacity are missing.
2. **Fail-closed trust** — for identity integrity, proof/attestation,
   policy admission, authorization, and side-effect dispatch when evidence,
   models, validators, or configuration required for a trust claim are missing,
   indeterminate, or out of scope.

### Decision details

#### 1. Outcome vocabulary (normative meanings)

Statuses may use different casings or wire enums per subsystem. Meanings below
are binding for documentation and for mapping into allow/deny/abstain.

| Outcome | Layer(s) | Meaning | Trust effect |
| --- | --- | --- | --- |
| **PROVED** / proved | Proof (scoped by authority kind) | Property checked successfully under explicit assumptions and backend identity | May feed policy/authorization **only** via allowed authority paths; never auto-dispatch |
| **DISPROVED** / disproved / unsatisfiable (when used as refutation) | Proof / satisfiability | Counterexample or refutation under the model | Blocks claims of security/correctness for that obligation; typically deny or fail gates |
| **SATISFIABLE** / sat | Satisfiability | Model admits a solution (often a counterexample to a safety query depending on encoding) | Interpret only under declared encoding; do not rename to “secure” or “insecure” without the obligation’s polarity |
| **UNKNOWN** | Proof / satisfiability / portfolio | Solver or pipeline did not decide (timeout, resource bound, inconclusive) | **Non-success.** Must not be mapped to PROVED, allow, or “release green.” Prefer abstain / gate fail / explicit unknown tally |
| **NOT_MODELED** | Proof / security IR | Obligation or real-world behavior is outside the formal model or deliberately unencoded | **Non-success for coverage.** Must not be treated as proved safe. Release policies may fail closed on blocking NOT_MODELED |
| **unavailable** | Availability (any layer’s *runtime support*) | Dependency, binary, submodule, network, or service required to run a path is not present or not reachable | Feature off or structured error; **must not** invent proof or allow. Distinct from UNKNOWN (ran but inconclusive) and NOT_MODELED (ran model path but obligation absent from model) |
| **denied** / reject / DENY | Authorization / policy | Explicit negative decision (forbid, deny-overrides hit, hard constraint) | Side effects must not proceed for that action class |
| **abstain** / REVIEW / INDETERMINATE / incomplete evidence | Authorization / admissibility | Cannot allow and cannot assert a definitive deny from available evidence | **Fail-closed relative to allow:** no side-effect grant; may surface for human review |
| **error** / ERROR | Any | Malformed input, internal fault, integrity drift | Fail closed for trust; do not coerce to success |
| **ready** / **not_ready** / **approved** / **rejected** | Evidence readiness / policy (scoped) | Only under their declared `result_authority`; never substitute for theorem proof | Same non-promotion rules as ADR-003 |

**Distinguishing the four names called out by acceptance criteria:**

| Name | Question it answers | Typical signal | Must not be treated as |
| --- | --- | --- | --- |
| **UNKNOWN** | “Did the checker decide?” → no | Timeout, solver UNKNOWN, portfolio inconclusive | PROVED, allow, full coverage |
| **NOT_MODELED** | “Is this obligation in the model?” → no | Explicit not-modeled report, missing semantics boundary | PROVED safe, “N/A so ignore” for blocking claims |
| **unavailable** | “Can we run the path?” → no | Missing binary/extra/submodule/network | Capability complete, proof success, silent skip that looks like pass |
| **denied** | “Is the action forbidden or not granted?” → yes forbid / no grant | Policy deny, hard forbid, reject wire | Soft warning while still executing the side effect |

#### 2. When degradation is **allowed**

Degradation is allowed only when **all** of the following hold:

1. The surface is a **feature/availability** concern (optional backend, media
   converter, accelerate path, best-effort cache, non-authoritative listing,
   stub embedding used only as a documented non-production fallback, etc.).
2. The degraded path is **explicit** in types, status fields, logs, or docs
   (callers can tell they did not get the full trust-bearing path).
3. The degraded path does **not** mint proof authority, policy approval, or
   authorization allow for production side effects.
4. Security-relevant defaults remain fail-closed (for example rollout defaults
   off/audit; Profile G side effects off unless configured).

**Allowed examples** (non-exhaustive):

| Situation | Allowed degradation |
| --- | --- |
| Optional extra / empty submodule | Soft-disable feature; return structured unavailable / empty |
| Accelerate disabled | Local inference fallback |
| Prover binary missing, portfolio has another solver | Skip route; try next member; still report per-route outcomes |
| Remote cache write-through fails | Keep local cache; do not claim remote durability |
| Embedding engine missing | Stub vector **only** if labeled non-production |
| Circuit breaker open | Reject dispatch without calling the tool (control-plane protection) |

#### 3. When behavior must be **fail-closed**

Fail-closed means: **do not allow**, **do not mark proved**, **do not promote
release**, and **do not execute guarded side effects** when required trust
inputs are missing or indeterminate. Prefer deny, reject, abstain, error, or
non-zero gate exit—never soft-success.

Fail-closed is **required** when any of the following hold:

1. The claim is about **proof, attestation, identity integrity, license/trust
   policy, admissibility, or authorization**.
2. Evidence is **UNKNOWN**, **NOT_MODELED** (for blocking/in-scope obligations),
   **unavailable** for a required checker, integrity-mismatched, or revoked.
3. Validators, profiles, or backends required by policy are missing and no
   alternate **equally authoritative** path is configured.
4. Encoding polarity or assumptions are incomplete such that success would be
   ambiguous.
5. Side effects would leave the process (network mutation, production store
   write, remote tool) under a profile that defaults to off/deny.

**Required examples** (non-exhaustive):

| Situation | Fail-closed behavior |
| --- | --- |
| Missing proof for a required obligation | not proved / UNKNOWN / error — never PROVED |
| Simulated or membership-only attestation | Non-authoritative; cannot satisfy theorem authority alone |
| Incomplete admissibility evidence | **abstain** (or equivalent non-allow) |
| Hard legal/security forbid | **reject** / deny |
| Authorization without validators / closed-world grants | deny or abstain; never default allow |
| Blocking security claim NOT_MODELED or UNKNOWN under release gate | Gate fails / non-zero exit |
| Digest/CID drift on envelopes | Integrity error; reject load |
| Unknown schema extensions on trust objects | Reject / fail closed |
| Dispatch when authz required but decision is abstain/deny | Do not execute side effect |

#### 4. Mapping rules (composition)

```text
unavailable dependency
  -> feature path: degrade or structured error
  -> trust path that required that dependency: fail closed (no allow / no PROVED)

UNKNOWN checker outcome
  -> never PROVED, never allow
  -> report UNKNOWN; gates/policies decide fail vs review

NOT_MODELED obligation
  -> never "vacuously secure"
  -> blocking scope: fail closed at release / authorization as configured

denied / reject
  -> no dispatch of guarded side effects

abstain / incomplete
  -> no allow; may record receipt for review; may degrade *features* only
```

Wire mapping used by admissibility compose (illustrative, binding in spirit):

| Internal / rich status | Legacy wire | Side-effect grant? |
| --- | --- | --- |
| ALLOW | `allow` | Yes (only for configured action class) |
| DENY | `reject` | No |
| REVIEW / INDETERMINATE / ERROR | `abstain` | No |

#### 5. Receipts and monitoring under fail-closed policy

- **Receipts** must record the true outcome (including UNKNOWN, NOT_MODELED,
  unavailable, denied, abstain). A receipt **must not** be rewritten later to
  imply success without a new envelope and supersession/revocation links.
- **Monitoring** may alert on elevated UNKNOWN/unavailable rates; alerts do not
  create proof or allow.
- **Audit logs** are evidence of process, not theorem authority (ADR-003).

#### 6. Rule of thumb

> **Degrade features; fail closed on trust.**  
> If unsure whether a path is feature or trust, **fail closed** and document an
> explicit ADR exception before opening it.

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Always degrade (best effort everywhere) | High availability | Silent false security and false authorization | Rejected — unsafe for IR/authz/proof |
| Always hard-fail entire product when any optional dep missing | Simple mental model | Unusable library import and CI hermeticity | Rejected — conflicts with lazy optional capabilities |
| Map UNKNOWN → allow with low confidence | Keeps pipelines “moving” | Confidence is not a security control | Rejected |
| Treat NOT_MODELED as out-of-scope pass | Smaller gate surface | Hides real coverage gaps on blocking claims | Rejected for blocking/in-scope obligations |
| Operator override without receipt | Fast incident response | Unauditable privilege | Rejected — overrides must be explicit, logged, and scoped if ever introduced by a future ADR |

## Consequences

### Positive

- Clear operator and agent guidance: optional stacks may soft-fail; trust paths
  may not.
- Aligns docs with security-model release gates and admissibility defaults.
- Makes test writing straightforward: assert non-allow on UNKNOWN / NOT_MODELED
  / unavailable for trust paths.

### Negative

- More abstain/error outcomes surface to users and MCP clients.
- Portfolios and installers need good diagnostics so fail-closed is not mistaken
  for a product crash.
- Historical “success” reports that ignored incomplete evidence become invalid
  as authority (correctly demoted to history).

### Neutral / deferred

- Exact numeric timeouts, breaker thresholds, and release-gate flag names remain
  in domain configs and CLIs.
- Lazy install and hermetic import mechanics are detailed in
  [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) and
  related capability ADRs.
- Human override / break-glass procedures, if productized, require a dedicated
  superseding or companion ADR with audit requirements.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. **UNKNOWN is never success** for proof or authorization allow.
2. **NOT_MODELED is never proved-safe** for in-scope or blocking obligations.
3. **unavailable is never capability-complete** and never silent pass on a
   required trust checker.
4. **denied/reject blocks side effects** for the denied action class.
5. **abstain/incomplete never promotes to allow.**
6. **Feature degradation must remain labeled** and must not mint trust outcomes.
7. **Simulated and membership attestations** never alone satisfy theorem
   authority requirements.
8. **Integrity failures fail closed** (digest/CID/schema drift ⇒ error/reject).
9. **Default production posture for guarded side effects is off/deny/abstain**
   until validators and grants are configured.
10. **Changing a fail-closed default to fail-open** requires a new ADR and
    explicit tests—not a config drive-by.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

```bash
# ADR present and non-empty
test -s docs/architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md

# Fail-closed statuses in security model release path
rg -n 'NOT_MODELED|UNKNOWN|DIFFERENTIAL_FAIL_CLOSED|fail-closed|fail_closed' \
  ipfs_datasets_py/logic/security_models/crypto_exchange/prove_all.py \
  ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py

# Proof corpus non-authoritative kinds and UNKNOWN default
rg -n 'NON_AUTHORITATIVE_ATTESTATION|ProofResultStatus.UNKNOWN|simulation' \
  ipfs_datasets_py/logic/proof_corpus/model.py

# Admissibility non-allow mapping
rg -n 'abstain|deny_overrides|accept_no_retrieved_deny|is_allow' \
  ipfs_datasets_py/logic/admissibility/compose.py

# Architecture guidance remains consistent
rg -n 'degrade \*\*features\*\*|fail closed on \*\*trust\*\*|Graceful feature degradation' \
  docs/architecture/DEPENDENCY_AND_INITIALIZATION.md
```

Narrative compliance criteria:

1. New optional features document unavailable behavior without claiming proof or
   authz success.
2. New trust APIs define explicit non-success statuses and tests for missing
   deps, timeouts, and unmodeled obligations.
3. Release/promotion docs cite fail-closed gates rather than “all green
   monitors.”
4. MCP tool errors for missing engines return structured failure, not fabricated
   domain success payloads.

## Scope

### Applies to

- Proof, security-model, admissibility, authorization, identity, and release
  gates across `ipfs_datasets_py/logic/` and related facades.
- MCP/HTTP dispatch paths that gate side effects.
- Operator and agent documentation describing offline, optional, and partial
  environments.
- Cross-links from dependency lifecycle and integration boundary guides.

### Does not apply to

- Pure unit-test fakes **explicitly labeled** non-production (still must not be
  documented as production-authoritative).
- Best-effort analytics that never claim security or authorization (should still
  avoid lying about completeness).
- Upstream third-party product defaults outside this repository’s adapters.

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR-003-LAYERED-AUTHORITY.md](ADR-003-LAYERED-AUTHORITY.md) | Sister decision: non-interchangeable layers |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Feature degradation vs trust; offline matrix |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Submodule/unavailable integration behavior |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flow-level failure/degradation notes |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | System invariants (proof ≠ authorization, …) |
| `logic/proof_corpus/model.py` | Envelope statuses and attestation kinds |
| `logic/admissibility/*` | Gate and authorization compose |
| `logic/security_models/crypto_exchange/` | UNKNOWN / NOT_MODELED release practice |

## Notes / errata

- Numbering: backlog **IPFSDOC-014** assigns fail-closed degradation to
  **ADR-004**. An older objective sketch used ADR-005 for this topic; the
  backlog and this file path are authoritative for implementers.
- Subsystem-specific status enums (for example FLogic `UNKNOWN`, Leanstral
  `unavailable`, JobVerdict `DENIED`) must map into this vocabulary without
  inventing a success class.
- “Denied” in natural language covers both explicit policy forbid and closed-world
  failure to obtain an allow; wire labels may say `reject` or `DENY`.

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted for IPFSDOC-014 (`FailClosedDecision@1`) |
