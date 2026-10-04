# Xaman TLA Signing Workflow

Task: `PORTAL-CXTP-140`

This artifact reconciles the generated TLA+ source, the checked-in
`XamanSigning.tla` file, and Apalache output. The accepted scope statement is
`bounded_model_only`: the evidence is bounded model-checking of the finite
workflow model, not an unbounded proof of the wallet, backend, XRPL network, or
cryptographic implementation.

## Artifacts

- Generator: `scripts/ops/security_verification/generate_xaman_tla_workflow.py`
- Source of truth: `ipfs_datasets_py/logic/security_models/crypto_exchange/reports/xaman_tla_workflow.py`
- TLA model: `security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla`
- Apalache report: `security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json`
- Environment lane report: `security_ir_artifacts/environment/apalache-solver-lane-report.json`

## Reconciled Model

The model starts in `received`, moves through review, and records the guard facts
that must be true before signing:

- `digestChecked`
- `authPassed`
- `vaultOpened`
- `networkBound`

`Sign` requires all four guards. `Broadcast` requires `signed`. `Reject` is only
available before signing and is checked by `NoBroadcastAfterReject`.

The checked invariants are:

- `NoSignWithoutDigest`
- `NoSignWithoutAuthentication`
- `NoSignWithoutVault`
- `NoSignWithoutNetworkBinding`
- `NoBroadcastWithoutSignature`
- `NoBroadcastAfterReject`
- `SigningGateInvariant`

## Current Evidence

Apalache `0.58.3` checked every required invariant with `--no-deadlock`.
The report binds:

- the SHA-256 of the exact checked `XamanSigning.tla` source
- the SHA-256 of the generator output
- normalized Apalache output markers including `# APALACHE version: 0.58.3`,
  `The outcome is: NoError`, and `EXITCODE: OK`
- `scope.statement: bounded_model_only`

Current report status:

- `overall_status: checked_bounded_model_only`
- `security_decision: ACCEPT_BOUNDED_MODEL_EVIDENCE_ONLY`

## Fail-Closed Rule

A report, generator, and checked TLA source mismatch is a blocker rather than
proof evidence. Any mismatch must produce `TLA_GENERATOR_SOURCE_MISMATCH` or
`XAMAN_TLA_REPORT_SOURCE_SHA_MISMATCH` before the evidence can be consumed.

Regenerate with:

```bash
PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/generate_xaman_tla_workflow.py
```
