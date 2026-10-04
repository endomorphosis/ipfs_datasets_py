# Apalache TLA Solver Lane

Task: `PORTAL-CXTP-140`

This lane records the Apalache evidence for the Xaman signing TLA workflow and
keeps it tied to the same source SHA-256 as
`security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json`.

## Inputs

- TLA model: `security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla`
- TLA workflow report: `security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json`
- Generator: `scripts/ops/security_verification/generate_xaman_tla_workflow.py`
- Probe script: `scripts/ops/security_verification/probe_apalache_solver_lane.py`
- Lane report: `security_ir_artifacts/environment/apalache-solver-lane-report.json`

## Current State

The pinned local wrapper is `/home/barberb/.local/bin/apalache-mc`, which reports
Apalache `0.58.3`. The lane report records seven successful bounded checks and
the shared `bounded_model_only` scope statement.

Current lane status:

- `overall_status: ready_bounded_model_only`
- `security_decision: APALACHE_0583_BOUNDED_MODEL_OUTPUT_BOUND`

This is bounded model evidence only. It is not a proof of source/runtime
equivalence, backend single-use semantics, XRPL ledger behavior, or wallet
cryptographic implementation.

## Required Checks

Each Apalache command uses:

```bash
apalache-mc check --no-deadlock --init=Init --next=Next --inv=<invariant> \
  security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla
```

The checked invariants are `NoSignWithoutDigest`,
`NoSignWithoutAuthentication`, `NoSignWithoutVault`,
`NoSignWithoutNetworkBinding`, `NoBroadcastWithoutSignature`,
`NoBroadcastAfterReject`, and `SigningGateInvariant`.

## Fail-Closed Policy

The solver lane is blocked if:

- Apalache is missing or does not report `0.58.3`
- any required invariant is missing or fails
- any run is bound to a different TLA SHA-256
- the generator output and checked source differ
- the corpus TLA report is missing or binds a different source SHA-256

In those cases the report is blocker evidence, not proof evidence.
