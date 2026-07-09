# Taskboard Preflight CI

- Task: `PORTAL-CXTP-087`
- Script: `scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py`
- Workflow: `.github/workflows/crypto-exchange-security-verification.yml`
- Report schema: `crypto-exchange-taskboard-preflight/v1`

## Purpose

The crypto-exchange theorem-prover taskboard is a supervisor control plane. CI
and supervisor workers must fail before downstream proof work starts when the
taskboard cannot be parsed, protected source paths disappear, required artifacts
are absent, task statuses contradict evidence, or release policy text would let a
production blocker look acceptable.

The preflight intentionally separates two decisions:

- `overall_status` / `ci_gate`: taskboard integrity. `blocked` exits nonzero.
- `production_release_acceptable`: release readiness. This remains `false`
  while production evidence tasks are explicitly blocked, even when taskboard
  integrity passes.

## Checks

The script performs these fail-closed checks:

1. Parse `## PORTAL-CXTP-...` task entries and required metadata fields.
2. Load the `PORTAL-CXTP-057` retention baseline and verify protected files are
   still present, including taskboard, source files, release-policy documents,
   solver artifacts, assurance packets, Xaman manifests, model facts, and
   recovery artifacts.
3. Require every `completed` task output path listed in `- Outputs:` to exist.
4. Require every `blocked` task to carry `- Blocked reason:`.
5. Reject completed tasks that still carry a blocked reason.
6. Reject blocked production tasks that contain release-acceptable metadata.
7. Verify `security_ir_artifacts/policies/security-decision-policy.json` keeps
   every non-`prove` blocking outcome non-secure and `blocked-production`.

## Local use

Run the same command used by CI:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py \
  --out taskboard-preflight-report.json
```

Exit code `0` means the taskboard is parseable and internally consistent. Exit
code `2` means supervisor and CI gates must stop.

When the report shows retained artifacts missing, run the recovery preflight
first:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/restore_crypto_exchange_security_tree.py \
  --verify-only \
  --report security_ir_artifacts/recovery/supervisor-stability-report.json
```

Use restore mode only when the supervisor is allowed to recover missing files
from durable git history.

## Report fields

- `overall_status`: `pass` or `blocked`.
- `ci_gate`: `pass` or `fail`.
- `supervisor_preflight_gate`: `allowed` or `blocked`.
- `production_release_acceptable`: `false` whenever production blocker tasks
  remain blocked or integrity failed.
- `production_release_decision`: `eligible-for-acceptance` only when integrity
  passes and no production blocker tasks remain.
- `blockers`: machine-readable fail-closed findings with stable `code` values.

CI writes these fields to the GitHub step summary and preserves the JSON report
as a workflow artifact for supervisor handoff.

