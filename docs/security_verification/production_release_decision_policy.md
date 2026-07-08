# Production Release Decision Policy (Crypto Exchange Security Models)

- Task: `PORTAL-CXTP-059` — Freeze proof-boundary and security decision policy
- Status: frozen, effective `2026-07-08`
- Authoritative artifact: [`security_ir_artifacts/policies/security-decision-policy.json`](../../security_ir_artifacts/policies/security-decision-policy.json)
- Authoritative builder: `ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy.build_security_decision_policy`
- Validating tests: [`tests/logic/security_models/crypto_exchange/test_release_decision_policy.py`](../../tests/logic/security_models/crypto_exchange/test_release_decision_policy.py)

## Purpose

This document freezes the proof boundary and the security decision policy for
every production release consumer that reads crypto-exchange formal proof
reports (`ProofReport`), proof receipts, assumption/evidence registries,
solver dependency probes, disproof suites, and runtime monitor reports. It
defines the complete, closed set of outcomes a release consumer may observe
for a formal claim, and the single rule every consumer must apply when
deciding whether a release is safe to ship.

The policy is **frozen**: the set of outcomes, their security semantics, and
the default consumer rule below may not be silently changed. Any change to
this document requires updating `build_security_decision_policy()`, the
checked-in JSON artifact, and this document together, plus review by a
release-owner (see [Maintenance triggers](#maintenance-triggers)).

## Proof boundary

The proof boundary is the set of claims, domains, and input artifacts that a
production release decision is scoped to. Anything outside this boundary is
explicitly out of scope for automated proof-based release gating.

### Required domains

`audit`, `capabilities`, `deposits`, `hsm`, `ledger`, `withdrawals`

### Blocking claims (must be `prove` or the release is blocked)

- `no_unauthorized_withdrawal`
- `no_over_reserved_internal_account`
- `global_asset_conservation`

### High-risk claims (must be `prove` or the release is blocked)

- `no_deposit_before_finality`
- `no_signing_request_after_wallet_freeze`
- `capability_delegation_no_authority_increase`
- `revoked_capability_no_future_authorization`

Every blocking and high-risk claim, along with its required assumptions,
release gate, and rationale, is enumerated in
`proof_boundary.required_release_claims` in the frozen artifact and in
`release_policy_entries()` in code — these two representations are validated
to stay in sync by `test_release_decision_policy.py`.

### Required input artifacts

A release decision consumer must have all of the following before it may
render a `prove` outcome for any blocking claim:

1. Production `SecurityModelIR` and its model CID
2. Proof report JSON for every required claim
3. Proof receipt or trusted signature validation output
4. Accepted assumptions file
5. Current assumption and evidence registry
6. Solver dependency probe
7. Production environment profile
8. Disproof suite report and counterexample vectors
9. Runtime monitor report for the release window

### Out of scope

- Claims absent from the production `SecurityModelIR`
- Optional prover coverage not present in the solver dependency probe
- Runtime behavior outside collected release-window traces
- Cryptographic primitive breakage beyond listed assumptions

## Outcomes

Every formal claim evaluation resolves to exactly one of the following seven
frozen outcomes. This is a closed set: a release consumer that observes a
signal not covered here must fail closed into `blocked-production`.

| Outcome | Secure for blocking claims? | Production release effect |
| --- | --- | --- |
| `prove` | **Yes** | `eligible-for-acceptance` |
| `disprove` | No | `blocked-production` |
| `unknown` | No | `blocked-production` |
| `not-modeled` | No | `blocked-production` |
| `stale-evidence` | No | `blocked-production` |
| `missing-solver` | No | `blocked-production` |
| `blocked-production` | No | `blocked-production` |

### `prove`

The claim is modeled, the authoritative solver returned a proof-producing
success result (`ProofReport.status == PROVED`), required assumptions and
evidence are current, and all consumer validation checks pass (model
binding, assumptions, reviewed evidence, receipt/signature policy, solver
allowlist, release packet freshness). A blocking claim may be treated as
secure **only** in this outcome, and only after those validation checks pass.

### `disprove`

The solver found a satisfiable counterexample to the claim
(`ProofReport.status == DISPROVED`). The release consumer must reject the
release and preserve the counterexample as blocking security evidence.

### `unknown`

The prover did not establish the claim and did not return a concrete,
accepted counterexample (`ProofReport.status == UNKNOWN`, solver timeout,
unsupported theory, or solver-reported unknown). The release consumer must
reject blocking claims and must not downgrade `unknown` to a warning or a
manual-approval state.

### `not-modeled`

The production IR does not model the claim, domain, or facts required to
evaluate it (`ProofReport.status == NOT_MODELED`, missing domain, or missing
claim model). The release consumer must reject blocking claims until the
production IR or formal claim scope is updated.

### `stale-evidence`

A required assumption, source fact, model CID, environment profile, or
reviewed evidence item is missing, expired, ownerless, unevidenced,
unaccepted, or no longer bound to the release packet. The release consumer
must reject blocking claims until evidence is refreshed and accepted.

### `missing-solver`

A required prover, compiler, runtime, or differential solver dependency is
missing or unusable for the release gate (see the solver dependency probe,
`PORTAL-CXTP-058`). The release consumer must reject proof acceptance until
the dependency probe reports no required blockers.

### `blocked-production`

The aggregate release decision whenever any blocking (or required high-risk)
claim is not `prove`, a proof report is missing entirely, or any
release-packet gate (receipt validation, runtime monitor, disproof suite)
fails closed. This is also the outcome returned when no proof report exists
for a claim that is required for release.

## Default consumer rule

> Only outcome `prove` may be consumed as secure for a blocking claim; every
> non-`prove` outcome for a blocking claim is non-secure and blocks
> production.

Equivalently: release consumers must treat every non-`prove` outcome for a blocking claim as non-secure, and must report the aggregate release
decision as `blocked-production` whenever this happens. This includes
`disprove`, `unknown`, `not-modeled`, `stale-evidence`, `missing-solver`, and
`blocked-production` itself — none of these may ever be interpreted as
"secure enough to ship." The same rule applies to high-risk claims.

### Consumer requirements

- Release consumers must fail closed by default.
- Release consumers must not infer security from missing proof reports.
- Release consumers must not accept `UNKNOWN`, `NOT_MODELED`, `DISPROVED`,
  stale evidence, or missing-solver states for blocking claims.
- Release consumers must report `blocked-production` when any blocking claim
  is non-proved.
- Dashboards may display non-proved states but must label them non-secure for
  production release.

## Release readiness rule

**Accepted** (release may proceed) requires all of:

- Every blocking claim outcome is `prove`.
- Every high-risk claim outcome is `prove`.
- Required assumptions are owned, evidenced, accepted, and current.
- Required solver dependencies are present.
- Proof receipts or trusted signatures validate against the release packet.
- Disproof and runtime monitor gates have no unexplained blockers.

**Blocked** (release must not proceed) if any of:

- Any blocking claim outcome is not `prove`.
- Any required high-risk claim outcome is not `prove`.
- Any `stale-evidence` outcome affects a required claim or release packet
  artifact.
- Any `missing-solver` outcome affects required proof acceptance.
- Any proof receipt, model CID, report CID, or environment binding fails
  validation.

## Using the policy in code

```python
from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
    classify_release_consumer_outcome,
    decision_outcome_for_proof_status,
    blocking_claim_is_secure_outcome,
    build_security_decision_policy,
    security_decision_outcomes,
)

decision = classify_release_consumer_outcome(proof_report, release_gate='blocking')
if not decision['secure_for_release']:
    # decision['outcome'] is one of disprove/unknown/not-modeled/stale-evidence/
    # missing-solver/blocked-production; treat the claim as non-secure.
    reject_release(decision['reasons'])
```

`classify_release_consumer_outcome` fails closed: a missing proof report
always resolves to `blocked-production`; an unavailable required solver
dependency always resolves to `missing-solver`; stale or unaccepted evidence
always resolves to `stale-evidence`; otherwise the outcome is derived from
the proof report's `status` via `decision_outcome_for_proof_status`.

## Maintenance triggers

This policy, the checked-in artifact, and the builder function must be
reviewed and updated together whenever any of the following occur:

- Claim severity changes.
- A new blocking or high-risk claim is introduced.
- Required assumption changes.
- Solver allowlist or dependency changes.
- Proof receipt validation changes.
- Runtime monitor release-gate changes.

## Change control

Because this is a frozen policy, any pull request that changes
`build_security_decision_policy()`, the checked-in
`security-decision-policy.json` artifact, or this document must change all
three together and must keep
`tests/logic/security_models/crypto_exchange/test_release_decision_policy.py`
passing, including the invariant that the checked-in artifact is byte-for-byte
equal (as a JSON structure) to the output of `build_security_decision_policy()`.
