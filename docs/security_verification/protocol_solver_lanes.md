# Protocol Solver Lanes

Task: `PORTAL-CXTP-092`

This lane records whether Tamarin and ProVerif can check the Xaman payload-flow protocol model. It depends on `PORTAL-CXTP-072` and must remain fail-closed while solvers or model projections are missing.

## Inputs

- Tamarin model: `security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy`
- Expected ProVerif model: `security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.pv`
- Protocol projection report: `security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json`
- Probe script: `scripts/ops/security_verification/probe_protocol_solver_lanes.py`
- Lane report: `security_ir_artifacts/environment/protocol-solver-lane-report.json`

## Current Expected State

The current environment does not expose `tamarin-prover` or `proverif`, and no ProVerif projection has been reviewed. The lane report should therefore use:

- `overall_status: blocked_optional_lane`
- `security_decision: BLOCK_PROTOCOL_SOLVER_LANES_UNAVAILABLE`

This is blocker evidence. It is not a protocol proof.

## Remediation

Install solvers and add a reviewed ProVerif projection:

```bash
nix profile install nixpkgs#tamarin-prover
stack install tamarin-prover
opam install proverif
nix profile install nixpkgs#proverif
```

Then run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_protocol_solver_lanes.py \
  --run-protocol-checks \
  --out security_ir_artifacts/environment/protocol-solver-lane-report.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py -q
```

## Release Interpretation

No Xaman or production packet may claim Tamarin/ProVerif coverage while this lane is `blocked_optional_lane`. Missing protocol solvers should be propagated as proof gaps, not treated as acceptable unknowns.
