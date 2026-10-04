# Production Blocker Status Updater

Task: `PORTAL-CXTP-095`

This updater consumes:

- `security_ir_artifacts/production/blocker-evidence-packets.json`
- `security_ir_artifacts/production/evidence-bundle-report.json`
- `security_ir_artifacts/production/evidence-bundle.json`

It writes:

- `security_ir_artifacts/production/blocker-status-update-report.json`

## Rule

The updater is fail-closed. It never marks the wallet or exchange secure, and it
does not remove production blockers from the taskboard by itself. It only emits
a status update plan. Each packet remains `blocked_missing_production_evidence`
unless all of these are true:

- The production evidence validation report has `overall_status: pass`.
- The production evidence bundle exists.
- Every packet-required evidence domain maps to reviewed bundle evidence.
- Every packet-blocked claim has solver outcome `prove`.
- The packet is still tied to named owner review and deployed-release evidence.

The current Xaman source-corpus packets are review context only. They cannot
remove a production blocker without a deployed-app production evidence bundle.

## Command

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/update_production_blocker_status.py \
  --dry-run \
  --packets security_ir_artifacts/production/blocker-evidence-packets.json \
  --out security_ir_artifacts/production/blocker-status-update-report.json
```

The default bundle path is
`security_ir_artifacts/production/evidence-bundle.json`. A missing bundle keeps
`PORTAL-CXTP-077` through `PORTAL-CXTP-084` blocked and records
`EVIDENCE_BUNDLE_FILE_MISSING` in the report.

## Output Meaning

`overall_status: blocked` means no production blocker status may change.

`overall_status: ready` means the report contains candidate manual status
updates for named owners to review. It is still not a proof of security and it
does not bypass the production release policy.

Each `status_updates[]` entry records:

- packet id and blocker id
- required evidence domains
- packet-specific domain checks
- packet-specific claim outcome checks
- whether a status update is allowed
- the proposed manual status
- the blockers that prevented an update

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_production_blocker_status_updater.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/update_production_blocker_status.py \
  --dry-run \
  --packets security_ir_artifacts/production/blocker-evidence-packets.json \
  --out security_ir_artifacts/production/blocker-status-update-report.json
```
