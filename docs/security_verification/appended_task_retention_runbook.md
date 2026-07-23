# Appended CXTP Task Retention Runbook

Task: `PORTAL-CXTP-096`

The retention checker is `scripts/ops/security_verification/check_appended_cxtp_tasks.py`.

## Protected Task Range

The appended solver and production-unblocker lane is:

- `PORTAL-CXTP-090`
- `PORTAL-CXTP-091`
- `PORTAL-CXTP-092`
- `PORTAL-CXTP-093`
- `PORTAL-CXTP-094`
- `PORTAL-CXTP-095`
- `PORTAL-CXTP-096`
- `PORTAL-CXTP-097`

These tasks must not disappear during supervisor rewrites, conflict resolution, or taskboard cleanup.

## Required Metadata

Each protected task must keep:

- `Status`
- `Completion`
- `Priority`
- `Track`
- `Depends on`
- `Outputs`
- `Validation`
- `Acceptance`

If a protected task is marked `completed`, it must also have `Completion evidence`.

## Dependency Guards

The checker keeps downstream lanes chained to unblocker tasks:

- Lean, Apalache, Tamarin/ProVerif, and Coq lanes depend on `PORTAL-CXTP-086`.
- Production evidence packets depend on `PORTAL-CXTP-085` and the bridge lane.
- Production blocker status updates depend on evidence packets.
- Leanstral remains advisory and depends on the retention guard through `PORTAL-CXTP-096`.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_appended_cxtp_task_retention.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_appended_cxtp_tasks.py \
  --taskboard docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md \
  --out security_ir_artifacts/recovery/appended-task-retention-report.json
```

The generated report is `security_ir_artifacts/recovery/appended-task-retention-report.json`.
