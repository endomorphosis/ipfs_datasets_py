# Reviewed-Evidence Promotion Workflow

This workflow defines the machine-checkable path from auto-discovered crypto-exchange
security evidence to release-grade evidence.

Autoformalized facts with `review_status` of `heuristic` or `machine_extracted`
are discovery signals only. Blocking and high-risk proof facts are release
eligible only after a reviewer promotes the evidence to `human_reviewed` or
`trusted_fixture`. Any proof-critical fact that cannot be promoted is quarantined
and blocks release until reviewed evidence is supplied or the fact is removed
from the production model.

## Machine Artifact

Reviews are recorded as JSON using schema version
`crypto-exchange-evidence-promotion/v1`.

Template:
`security_ir_artifacts/assurance-run/evidence-review-template.json`

Validator:
`ipfs_datasets_py.logic.security_models.crypto_exchange.evidence_promotion.evaluate_evidence_promotion_workflow`

The validator returns:

- `release_ready`: `true` only when there are no validation failures and no
  quarantined blocking/high facts.
- `promoted_evidence_refs`: evidence references rewritten with reviewed status,
  reviewer identity, review time, source digest, source span or trace identifier,
  and expiry.
- `quarantined_facts`: unreviewed blocking/high facts that must not feed a
  release claim.
- `failures`: malformed review records or invalid promotion attempts.

## Required Promotion Fields

Each promotion record must include:

- `fact_id`: Stable model fact identifier.
- `claim_id`: Release-policy claim that consumes the fact.
- `release_gate`: `blocking`, `high`, `medium`, or `informational`.
- `source_review_status`: `heuristic` or `machine_extracted`.
- `decision`: `promote`.
- `promoted_review_status`: `human_reviewed` or `trusted_fixture`.
- `reviewer.id`: Stable reviewer identity, such as SSO id, employee id, or
  service-account id for fixture ownership.
- `reviewer.reviewed_at`: ISO timestamp of the review.
- `source_digest`: SHA-256 digest of the exact reviewed source, policy document,
  runtime trace payload, or fixture.
- `expires_at`: ISO timestamp after which the review is stale.
- `evidence_ref.kind`: One of the SecurityModelIR evidence kinds.
- `evidence_ref.path`: Stable path or artifact URI.
- A source locator: either `line_start` and `line_end` for source/policy files,
  or `trace_identifier` for runtime/audit evidence.

The reviewed evidence expires at `expires_at`. A stale review is treated as a
failed promotion and the affected blocking/high fact is quarantined.

## Quarantine Rule

For `blocking` and `high` release gates:

- `heuristic` and `machine_extracted` facts are never release-grade by
  themselves.
- If a fact is not validly promoted, the review artifact must record
  `decision: "quarantine"`.
- The quarantine record must state `blocking_behavior: "release_blocking"`.
- Quarantined facts remain excluded from release evidence until a later review
  supplies a valid promotion or the production model no longer depends on the
  fact.

`medium` and `informational` facts may be triaged without blocking the release,
but they still cannot be represented as reviewed evidence unless they satisfy
the same promotion requirements.

## Operational Use

1. Generate or update the review JSON from discovered evidence.
2. Promote only facts that the reviewer can bind to a digest and exact source
   span or trace identifier.
3. Quarantine every unreviewed blocking/high fact.
4. Run the validator and keep `promoted_evidence_refs` as the only release-grade
   evidence source for proof-critical facts.
5. Re-run the release gate with reviewed evidence required.

This workflow is intentionally fail-closed: malformed promotions, stale reviews,
missing digests, missing reviewer identity, and missing source locators all keep
the affected blocking/high fact out of release evidence.
