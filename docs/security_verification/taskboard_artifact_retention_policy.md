# Crypto Exchange Taskboard Artifact Retention Policy

Status: active
Task: `PORTAL-CXTP-057`
Date: 2026-07-08

## Purpose

The crypto exchange theorem-prover workflow is fail-closed. A proof,
disproof, receipt, runtime monitor result, or release decision is not
acceptable when the taskboard, security plan, source files, Xaman corpus
manifests, model facts, tests, solver artifacts, implementation logs, or
assurance packets have disappeared from the checkout.

This policy protects the evidence restored by `PORTAL-CXTP-056` and records
the restoration path for the agent supervisor.

## Retention Baseline

The authoritative machine-readable baseline is:

`security_ir_artifacts/recovery/artifact-retention-baseline.json`

The baseline is validated by:

`scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py`

The checker exits with status `2` and sets
`proof_acceptance_blocked: true` when a required artifact is missing, the
baseline is malformed, or a content-hashed artifact differs from the reviewed
baseline. Implementation logs are checked for presence because active
supervisor logs can grow while the daemon is running.

## Protected Evidence Classes

The baseline protects these groups:

- `taskboard`: the theorem-prover taskboard that defines PORTAL-CXTP work.
- `plans_and_release_policy`: proof boundary, verification plan, release
  policy, receipt policy, runbook, security IR spec, and threat model.
- `retention_controls`: this policy, the checker, and the retention baseline.
- `source_files`: reviewable `.py` files under
  `ipfs_datasets_py/logic/security_models/crypto_exchange`.
- `xaman_manifests`: Xaman corpus profile, pinned source manifest, and source
  coverage artifact.
- `model_facts`: production assumptions, Xaman wallet-auth facts, Xaman
  payload-lifecycle facts, and model coverage docs.
- `tests`: crypto exchange security model regression tests.
- `solver_artifacts`: proof and disproof baselines, SMT-LIB manifests and
  files, CVC5 differential results, and scripts that regenerate solver
  evidence.
- `implementation_logs`: supervisor event streams, task state, strategy, and
  per-task implementation logs.
- `assurance_packets`: assurance baseline, reviewed evidence packet, proof
  reports, disproof reports, and promotion docs.
- `recovery_artifacts`: PORTAL-CXTP-056 recovery report, source audit, and
  source-tree gate script.

## Supervisor Restoration Path

When the retention checker blocks, the agent supervisor must not accept any
theorem-prover result from the checkout. Restore the missing or changed
evidence before retrying.

1. Read the checker output and identify each blocked group and path.
2. Restore missing source, docs, scripts, and artifacts from durable repository
   history. The PORTAL-CXTP-056 recovery source was commit `5a9ce484a`.
3. If the crypto exchange package is source-empty or bytecode-only, run:
   `PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/audit_crypto_exchange_source_tree.py --out security_ir_artifacts/recovery/crypto-exchange-source-audit.json`
4. If Xaman corpus artifacts are missing, regenerate or restore the pinned
   corpus manifest at commit
   `942f43876265a7af44f233288ad2b1d00841d5fa`, then rerun the Xaman coverage
   and fact extraction tasks before accepting dependent models.
5. If model facts, solver artifacts, or assurance packets are missing, rerun
   the corresponding proof, disproof, CVC5 differential, coverage, and
   assurance baseline scripts. Treat all prior proof receipts as stale until
   the regenerated artifacts are present and reviewed.
6. If implementation logs are missing, recover the supervisor state directory
   from the durable agent run archive. If no archive exists, preserve the
   retention failure and require manual supervisor review before continuing.
7. Rerun:
   `PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py --baseline security_ir_artifacts/recovery/artifact-retention-baseline.json`

Only update the baseline after a reviewed, intentional artifact replacement.
Use:

`PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py --baseline security_ir_artifacts/recovery/artifact-retention-baseline.json --write-baseline`

Do not update the baseline to hide missing evidence.
