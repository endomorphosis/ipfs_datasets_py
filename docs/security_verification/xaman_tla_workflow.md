# Xaman TLA Signing Workflow

Task: `PORTAL-CXTP-071`

This artifact projects the Xaman signing workflow into a small TLA+ model for later Apalache checking. It focuses on the release-critical ordering property: signing and broadcast must not happen unless digest, authentication, vault, and network-binding gates have succeeded.

## Artifacts

- TLA model: `security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla`
- Apalache report: `security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json`

## Modeled Workflow

The model begins in `received`, moves through review, and can then set independent guard facts:

- `digestChecked`
- `authPassed`
- `vaultOpened`
- `networkBound`

`Sign` requires all four guard facts. `Broadcast` requires `signed`. `Reject` is available before signing and must prevent later broadcast.

## Invariants

The TLA model defines:

- `NoSignWithoutDigest`
- `NoSignWithoutAuthentication`
- `NoSignWithoutVault`
- `NoSignWithoutNetworkBinding`
- `NoBroadcastWithoutSignature`
- `NoBroadcastAfterReject`
- `SigningGateInvariant`

These map to the Xaman custody, signing, payload-integrity, and network-binding claims.

## Current Solver Status

Apalache is not currently available on `PATH`, so the report is intentionally:

- `overall_status: blocked_optional_lane`
- `security_decision: BLOCK_TLA_APALACHE_MISSING_SOLVER`

This means the workflow model is present, but no production evidence may claim TLA/Apalache model-check coverage yet.

## Remediation

Install Apalache through one reviewed route:

```bash
cs install apalache
nix profile install nixpkgs#apalache
docker pull ghcr.io/apalache-mc/apalache:latest
```

Then run:

```bash
apalache-mc check --inv=SigningGateInvariant security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py -q
```
