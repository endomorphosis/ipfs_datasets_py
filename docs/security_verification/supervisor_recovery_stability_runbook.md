# Supervisor Recovery Stability Runbook

Status: active
Task: `PORTAL-CXTP-088`
Date: 2026-07-08

## Purpose

The crypto exchange theorem-prover workflow must not depend on untracked
taskboard, source, or evidence files surviving supervisor cleanup. Before any
downstream PORTAL-CXTP task runs, the supervisor must verify that the recovered
security tree is present and semantically usable.

The operational gate is:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/restore_crypto_exchange_security_tree.py --verify-only --report security_ir_artifacts/recovery/supervisor-stability-report.json
```

The gate writes
`security_ir_artifacts/recovery/supervisor-stability-report.json`. Downstream
tasks may run only when the report has:

- `overall_status: "pass"`
- `downstream_task_gate: "allowed"`
- `proof_acceptance_blocked: false`
- no `blockers`

## Protected Preflight Groups

The stability gate protects these groups before downstream proof, extraction,
or release tasks run:

- `taskboard`: `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md`
- `source_files`: Python source under
  `ipfs_datasets_py/logic/security_models/crypto_exchange`
- `xaman_artifacts`: Xaman manifest, source coverage, wallet-auth facts, and
  payload-lifecycle facts pinned to
  `942f43876265a7af44f233288ad2b1d00841d5fa`
- `retention_baseline`: PORTAL-CXTP-057 policy, checker, and baseline
- `solver_probe`: PORTAL-CXTP-058 runbook, probe script, and probe artifact
- `stability_controls`: this runbook and the restore/verify script
- `downstream_tests`: crypto exchange regression tests discovered in the tree
  or durable history

The script also checks artifact semantics. For example, the taskboard must
contain PORTAL-CXTP-088 metadata, the Xaman manifest must name the pinned repo
and commit, the retention baseline must identify PORTAL-CXTP-057, and the
solver probe must identify PORTAL-CXTP-058 with required dependency records.

## Self-Healing Mode

When files are missing, run the script without `--verify-only`:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/restore_crypto_exchange_security_tree.py --report security_ir_artifacts/recovery/supervisor-stability-report.json
```

Self-healing restores missing files only from durable git objects. The default
durable refs are `HEAD` and the PORTAL-CXTP-056 source recovery commit
`5a9ce484a`. Additional refs can be supplied when a supervisor archive or
integration branch is the reviewed recovery source:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/restore_crypto_exchange_security_tree.py --durable-ref HEAD --durable-ref 5a9ce484a --durable-ref reviewed-security-artifacts
```

Existing files are not overwritten. Missing files are restored, then the full
preflight is re-run in the same process. The report records every restored path
under `restored_artifacts`.

## Fail-Closed Handling

If the report is blocked, the supervisor must stop the downstream task and
preserve the report. Do not accept proof, disproof, runtime, extraction, Xaman,
or release evidence from that checkout.

Common blocker handling:

- `REQUIRED_STABILITY_ARTIFACT_MISSING`: restore the listed path from durable
  history, then rerun the gate.
- `DURABLE_RECOVERY_UNAVAILABLE`: the configured refs do not contain the
  missing path. Recover a supervisor archive or rerun the dependency tasks that
  originally produced the artifact.
- `REQUIRED_STABILITY_ARTIFACT_INVALID`: the file exists but no longer matches
  the required semantic contract. Restore the reviewed copy or rerun the
  owning task before continuing.

If durable recovery is unavailable:

1. Preserve `security_ir_artifacts/recovery/supervisor-stability-report.json`.
2. Recover the latest reviewed supervisor worktree archive, if one exists.
3. Rerun PORTAL-CXTP-056 for source-tree recovery when package files are
   missing.
4. Rerun PORTAL-CXTP-057 when the taskboard retention policy, checker, or
   baseline is missing.
5. Rerun PORTAL-CXTP-058 when the solver probe script or probe artifact is
   missing.
6. Regenerate or restore Xaman artifacts from the pinned Xaman-App commit when
   corpus artifacts are missing.
7. Rerun the stability gate with `--verify-only`.

The task remains blocked until all required groups pass.

## Supervisor Integration Contract

Run this gate before selecting any task that depends on PORTAL-CXTP-088 or on
crypto exchange theorem-prover evidence. Treat a nonzero exit code as a hard
preflight failure. The script returns exit code `2` when
`proof_acceptance_blocked` is true.

Recommended supervisor sequence:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/restore_crypto_exchange_security_tree.py --report security_ir_artifacts/recovery/supervisor-stability-report.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/restore_crypto_exchange_security_tree.py --verify-only --report security_ir_artifacts/recovery/supervisor-stability-report.json
```

The first command gives the supervisor a chance to self-heal from durable git
history. The second command verifies the post-restore tree without changing it.
