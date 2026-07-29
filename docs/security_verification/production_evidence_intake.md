# Production Evidence Intake

Task: `PORTAL-CXTP-085`

This scaffold defines the fail-closed evidence intake path needed before
`PORTAL-CXTP-077` through `PORTAL-CXTP-084` can be unblocked.

The production evidence bundle schema is:

```text
security_ir_artifacts/production/evidence-bundle.schema.json
```

The validator is:

```text
scripts/ops/security_verification/validate_production_evidence_bundle.py
```

## Required Bundle Categories

Every `production-evidence-bundle/v1` document must contain non-empty arrays for:

- `source_snapshots`: production wallet, exchange, API, policy, schema, custody,
  and deployment source snapshots.
- `environment_evidence`: production compute, custody, network, chain-node,
  CI/CD, monitoring, and operational configuration evidence.
- `runtime_traces`: release-window traces mapped to formal model events.
- `owner_signoff`: named accountable owner approvals.
- `solver_reports`: formal outcomes for every blocking and high release-policy
  claim.

Evidence with `review_status: heuristic` or `machine_extracted` is not enough
to unblock production. The validator accepts only `human_reviewed` and
`trusted_fixture` evidence statuses, plus `owner_signoff.decision: approved`.

## Fail-Closed Rules

The validator blocks on:

- missing bundle or schema;
- missing required categories or fields;
- missing referenced files;
- digest mismatches;
- stale or future timestamps;
- unreviewed evidence;
- unapproved owner signoff;
- missing solver reports for blocking or high claims;
- any blocking or high claim whose latest outcome is not `prove`.

This validator does not prove production is secure. It only determines whether
the supplied evidence bundle is structurally complete, fresh, reviewed, bound to
durable files, and sufficient to start downstream production-model tasks.

## Commands

Generate an example bundle:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/validate_production_evidence_bundle.py \
  --write-example security_ir_artifacts/production/evidence-bundle.example.json \
  --example-task-id PORTAL-CXTP-077
```

Validate the real production bundle:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/validate_production_evidence_bundle.py \
  --bundle security_ir_artifacts/production/evidence-bundle.json \
  --out security_ir_artifacts/production/evidence-bundle-report.json
```

`overall_status: pass` and `security_decision:
PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED` are required before a production blocker
can be considered for manual status update.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py -q
```
