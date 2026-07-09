# Production Evidence Intake (Crypto Exchange Security Models)

- Task: `PORTAL-CXTP-085` — Build production evidence intake scaffold
- Status: scaffold complete, ready for production evidence
- Depends on: `PORTAL-CXTP-056` (source/artifact tree recovery), `PORTAL-CXTP-059`
  (frozen proof-boundary and security decision policy), `PORTAL-CXTP-088`
  (supervisor recovery stability)
- Authoritative schema: [`security_ir_artifacts/production/evidence-bundle.schema.json`](../../security_ir_artifacts/production/evidence-bundle.schema.json)
- Authoritative validator: [`scripts/ops/security_verification/validate_production_evidence_bundle.py`](../../scripts/ops/security_verification/validate_production_evidence_bundle.py)
- Validating tests: [`tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py`](../../tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py)

## Purpose

Several production release tasks on this taskboard are marked `blocked`
because they require concrete evidence this repository cannot fabricate:
production source snapshots, deployed environment facts, runtime traces,
named owner signoff, and solver reports for the frozen release-policy claims
(see `docs/security_verification/production_release_decision_policy.md`).

- `PORTAL-CXTP-077` — Collect production environment evidence
- `PORTAL-CXTP-078` — Inventory deployed wallet, exchange, API, and policy sources
- `PORTAL-CXTP-079` — Generate reviewed production `SecurityModelIR` candidate
- `PORTAL-CXTP-080` — Enforce required production domains and claim minimums
- `PORTAL-CXTP-081` — Run production fail-closed proof baseline
- `PORTAL-CXTP-082` — Run production disproof and mutation suite
- `PORTAL-CXTP-083` — Wire production runtime trace evidence
- `PORTAL-CXTP-084` — Refresh production blockers and handoff checklist

This task does **not** supply that evidence — it cannot, since production
wallet/exchange source, environment, and runtime facts are outside this
repository. Instead it builds the **intake mechanism**: a single, versioned,
machine-checked bundle format that the tasks above can be unblocked with once
an accountable owner supplies real evidence. A blocked task's owner fills in
one `production-evidence-bundle/v1` JSON document, runs the validator, and
only proceeds once the validator reports `overall_status: pass`.

## Evidence bundle categories

A bundle is a single JSON document with `schema_version:
"production-evidence-bundle/v1"` and five required, non-empty evidence
categories, each described by the JSON Schema `$defs` in
`evidence-bundle.schema.json`:

| Category | Purpose | Item-specific required fields |
| --- | --- | --- |
| `source_snapshots` | Immutable production source/commit evidence (deployed wallet/exchange source revision, API schemas, custody policy documents). | `repository`, `commit` |
| `environment_evidence` | Deployed compute, custody, network, CI/CD, and monitoring facts. | `environment` (`production` / `staging` / `disaster-recovery`) |
| `runtime_traces` | Sanitized release-window runtime/monitoring traces mapped to model events. | `stream`, `window_start_utc`, `window_end_utc` |
| `owner_signoff` | Named, accountable approvals for a domain or claim. | `scope`, `role`, `decision`, `statement` |
| `solver_reports` | Formal claim outcomes emitted by the theorem provers. | `claim_id`, `solver`, `outcome` |

Every item in `source_snapshots`, `environment_evidence`, `runtime_traces`,
and `solver_reports` also carries: `id`, `path` (repository-relative path to
the durable evidence artifact), optional `sha256` content digest,
`collected_at_utc`, `owner`, and `review_status` (one of `heuristic`,
`machine_extracted`, `human_reviewed`, `trusted_fixture` — the same
vocabulary as
`ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema.EVIDENCE_REVIEW_STATUSES`).
Only `human_reviewed` and `trusted_fixture` count as reviewed evidence; any
other review status blocks acceptance. `owner_signoff` items instead carry
`signed_at_utc` and a `decision` of `approved`, `rejected`, or `pending` —
only `approved` is accepted.

### Freshness metadata

Every bundle declares a top-level `freshness_policy`:

```json
{
  "max_age_days": 30,
  "evaluated_at_utc": "2026-07-08T00:00:00Z"
}
```

The validator computes the age of every item's timestamp (`collected_at_utc`,
plus `window_end_utc` for runtime traces, or `signed_at_utc` for owner
signoff) relative to `evaluated_at_utc` (or the validator's current time, or
an operator-supplied `--now` for reproducible checks). Any item older than
`max_age_days`, with an unparseable timestamp, or with a timestamp in the
future is a blocker.

### Solver report / release-policy cross-check

`solver_reports.outcome` must be one of the seven frozen outcomes in
`security_ir_artifacts/policies/security-decision-policy.json` (`prove`,
`disprove`, `unknown`, `not-modeled`, `stale-evidence`, `missing-solver`,
`blocked-production`). The validator additionally imports the live release
policy (`release_policy_entries()`) and requires every `blocking` and `high`
release-gate claim to appear in `solver_reports` with the most recent report
for that claim having `outcome: "prove"`. This directly enforces the rule in
`docs/security_verification/production_release_decision_policy.md`: only
`prove` is secure for a blocking or high-risk claim; every other outcome
blocks production.

## Validator usage

```bash
# Generate a self-consistent starting-point bundle (all paths point at real,
# checked-in repository files so it validates as-is; replace every
# REPLACE_WITH_* placeholder and path/owner/timestamp with real evidence
# before using it to unblock a task).
PYTHONPATH=. python scripts/ops/security_verification/validate_production_evidence_bundle.py \
  --write-example security_ir_artifacts/production/evidence-bundle.example.json \
  --example-task-id PORTAL-CXTP-077

# Validate a bundle
PYTHONPATH=. python scripts/ops/security_verification/validate_production_evidence_bundle.py \
  --bundle path/to/bundle.json \
  --out security_ir_artifacts/production/evidence-bundle-report.json
```

The script exits `0` and reports `security_decision:
"PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED"` when the bundle has no blockers. It
exits `2` and reports `security_decision: "BLOCK_PRODUCTION_EVIDENCE_INTAKE"`
whenever any blocker is present — including a missing bundle file, a missing
schema file, or a missing `--bundle` argument. Nothing about this validator
implies the referenced evidence is *true*; it only enforces that the bundle
is structurally complete, internally consistent, references files that
actually exist with matching digests, is fresh, is approved by a named
owner, and reports `prove` for every blocking/high claim. A downstream task
owner is still responsible for the accuracy of the evidence itself.

## Blocker codes

| Code | Meaning |
| --- | --- |
| `BUNDLE_NOT_OBJECT` | The bundle document is not a JSON object. |
| `BUNDLE_SCHEMA_VERSION_MISMATCH` | `schema_version` is not `production-evidence-bundle/v1`. |
| `BUNDLE_FIELD_MISSING` | A required top-level field (`task_id`, `bundle_id`, `generated_at_utc`) is missing or empty. |
| `BUNDLE_FRESHNESS_POLICY_MISSING` | `freshness_policy` is absent or not an object. |
| `BUNDLE_FRESHNESS_POLICY_INVALID` | `freshness_policy.max_age_days` or `evaluated_at_utc` is malformed. |
| `CATEGORY_EMPTY_OR_MISSING` | A required evidence category array is absent or empty. |
| `EVIDENCE_ITEM_NOT_OBJECT` | An item in a category array is not a JSON object. |
| `EVIDENCE_ITEM_FIELD_MISSING` | An item is missing one or more category-required fields. |
| `EVIDENCE_REVIEW_STATUS_INVALID` | `review_status` is not one of the frozen vocabulary values. |
| `EVIDENCE_NOT_REVIEWED` | `review_status` is valid but not `human_reviewed`/`trusted_fixture`. |
| `EVIDENCE_PATH_MISSING` | A category that requires `path` is missing it. |
| `EVIDENCE_FILE_MISSING` | The referenced `path` does not exist under `--repo-root`. |
| `EVIDENCE_DIGEST_MISMATCH` | The file at `path` does not hash to the declared `sha256`. |
| `EVIDENCE_TIMESTAMP_INVALID` | A freshness-relevant timestamp is missing or unparseable. |
| `EVIDENCE_TIMESTAMP_IN_FUTURE` | A freshness-relevant timestamp is after the evaluation instant. |
| `EVIDENCE_STALE` | A freshness-relevant timestamp is older than `max_age_days`. |
| `OWNER_SIGNOFF_NOT_APPROVED` | An `owner_signoff` item's `decision` is not `approved`. |
| `SOLVER_OUTCOME_UNRECOGNIZED` | A `solver_reports` item's `outcome` is not a frozen security decision outcome. |
| `RUNTIME_TRACE_WINDOW_INVERTED` | A runtime trace's `window_start_utc` is after `window_end_utc`. |
| `BLOCKING_CLAIM_NOT_COVERED` | A `blocking`/`high` release-policy claim has no matching `solver_reports` entry. |
| `BLOCKING_CLAIM_NOT_PROVED` | A `blocking`/`high` release-policy claim's latest solver report outcome is not `prove`. |
| `SCHEMA_FILE_MISSING` | `--schema` does not point at an existing file. |
| `BUNDLE_FILE_MISSING` | `--bundle` does not point at an existing file. |
| `BUNDLE_ARGUMENT_MISSING` | `--bundle` was not supplied and `--write-example` was not requested. |
| `NOW_ARGUMENT_INVALID` | `--now` was supplied but could not be parsed as an ISO-8601 timestamp. |

## How this unblocks `PORTAL-CXTP-077`–`PORTAL-CXTP-084`

Each blocked task above lists a `Blocked reason` naming exactly the evidence
categories this bundle format collects. The recommended workflow for a task
owner is:

1. Run `--write-example` to get a starting-point bundle.
2. Replace every placeholder path with a durable, checked-in (or otherwise
   immutable and content-addressed) copy of the real production evidence, and
   every placeholder owner/commit/stream/statement with real, named values.
3. Run the validator. Fix every reported blocker.
4. Attach the accepted bundle (and its validation report) as the evidence
   basis for updating the blocked task's status, `environment-profile.json`,
   `source-inventory.json`, `runtime-trace-report.json`,
   `proof-reports/baseline.json`, `disproof-report.json`, and
   `release-blockers.json` outputs.
5. Because the validator fails closed, an incomplete or stale bundle can
   never be mistaken for acceptance — the blocked task remains blocked until
   `overall_status: pass`.

This scaffold intentionally does not change the `Status: blocked` state of
`PORTAL-CXTP-077`–`PORTAL-CXTP-084` itself; those tasks stay blocked until a
real, accepted evidence bundle exists. What it delivers is the concrete,
testable mechanism referenced by their acceptance criteria.
