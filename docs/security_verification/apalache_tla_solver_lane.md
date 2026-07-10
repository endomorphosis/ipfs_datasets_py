# Apalache TLA Solver Lane

Task: `PORTAL-CXTP-091`

This lane records whether the Xaman TLA signing workflow can be checked by Apalache. It depends on the TLA model from `PORTAL-CXTP-071` and converts missing Apalache tooling into explicit solver evidence rather than silent acceptance.

## Inputs

- TLA model: `security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla`
- TLA workflow report: `security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json`
- Probe script: `scripts/ops/security_verification/probe_apalache_solver_lane.py`
- Lane report: `security_ir_artifacts/environment/apalache-solver-lane-report.json`

## Current Expected State

The local environment does not currently expose `apalache-mc` or `apalache` on `PATH`. The lane report should therefore use:

- `overall_status: blocked_optional_lane`
- `security_decision: BLOCK_APALACHE_SOLVER_LANE_UNAVAILABLE`

The TLA model exists, but no Xaman proof evidence may claim Apalache model-check coverage until the solver is installed and the check is rerun.

## Remediation

Install Apalache through a reviewed path:

```bash
cs install apalache
nix profile install nixpkgs#apalache
docker pull ghcr.io/apalache-mc/apalache:latest
```

Then run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_apalache_solver_lane.py \
  --run-model-check \
  --out security_ir_artifacts/environment/apalache-solver-lane-report.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py -q
```

## Release Interpretation

This lane can only support the signing workflow claims after Apalache actually checks `SigningGateInvariant`. A report file with `blocked_optional_lane` is useful blocker evidence, not a proof.
