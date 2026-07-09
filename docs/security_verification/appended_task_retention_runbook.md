# Appended CXTP Task Retention Runbook

Status: active
Task: `PORTAL-CXTP-096`
Date: 2026-07-08

## Purpose

`PORTAL-CXTP-090` through `PORTAL-CXTP-095` were appended to preserve solver
lane remediation and production unblocker work after the original crypto
exchange taskboard was restored. Supervisor cleanup must not silently remove
those tasks, strip their dependency chain, remove validation commands, or mark
them complete without evidence.

The retention gate is:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_appended_cxtp_tasks.py --taskboard docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md --out security_ir_artifacts/recovery/appended-task-retention-report.json
```

The command exits with status `2` when the appended work is unsafe to use. A
passing report has:

- `overall_status: "pass"`
- `downstream_task_gate: "allowed"`
- `proof_acceptance_blocked: false`
- no `blockers`

## Protected Tasks

The checker protects these task definitions:

- `PORTAL-CXTP-090`: Lean proof-consumer solver lane.
- `PORTAL-CXTP-091`: Apalache TLA model-checker lane.
- `PORTAL-CXTP-092`: Tamarin and ProVerif protocol solver lanes.
- `PORTAL-CXTP-093`: Coq proof-kernel solver lane.
- `PORTAL-CXTP-094`: production blocker evidence packets.
- `PORTAL-CXTP-095`: guarded production blocker status updater.

For each task, the checker verifies the title, priority, track, dependencies,
outputs, and exact validation commands recorded in the taskboard. The solver
lane tasks must retain their dependency on `PORTAL-CXTP-096`, and the
production unblocker tasks must retain the production evidence dependencies
that prevent them from reclassifying blockers prematurely.

## Completed Task Evidence

A protected appended task may be marked `completed` only after concrete
evidence is recorded in the same task block. Use one of these fields:

- `Completion evidence`
- `Completed evidence`
- `Completion proof`
- `Evidence`
- `Verification evidence`

The evidence must name at least one produced output or validation command, and
all outputs declared for that task must exist in the checkout. Placeholder
evidence such as `none`, `n/a`, `todo`, `pending`, or `missing` is treated as
no evidence.

## Fail-Closed Handling

When `security_ir_artifacts/recovery/appended-task-retention-report.json` is
blocked, do not run or complete `PORTAL-CXTP-090` through `PORTAL-CXTP-095`.
Do not accept solver reports, production blocker packets, or blocker status
updates from that checkout.

Restore in this order:

1. Restore
   `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md`
   from reviewed durable history or the latest supervisor archive.
2. Confirm the protected range `PORTAL-CXTP-090` through `PORTAL-CXTP-095` is
   present and in order.
3. Restore each task's `Depends on`, `Outputs`, and `Validation` lines from
   the reviewed taskboard.
4. If a task was intentionally completed, restore or regenerate all declared
   outputs and add concrete completion evidence in the task block.
5. Rerun the appended-task retention gate.

If durable history does not contain the appended task range, preserve the
blocked report and rerun the supervisor task that created the appended work
before continuing. The blocked report is the evidence that cleanup would have
dropped theorem-prover unblocker work.

## Supervisor Contract

Run this gate after the PORTAL-CXTP-088 stability gate and before selecting any
of the protected tasks. A nonzero exit code is a hard preflight failure. The
supervisor may continue only after the report is passing and checked into the
recovery artifacts.
