# Lean Proof-Consumer Solver Lane

Task: `PORTAL-CXTP-090`

This lane checks whether the Xaman proof-consumer kernel can be validated by the local Lean toolchain. It is a dependency lane for later Leanstral and production handoff work; it is not itself a production release approval.

## Inputs

- Kernel: `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean`
- Kernel report: `security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json`
- Probe script: `scripts/ops/security_verification/probe_lean_solver_lane.py`
- Lane report: `security_ir_artifacts/environment/lean-solver-lane-report.json`

## Required Checks

The probe records:

- `lean` executable presence and version.
- `lake` executable presence and version.
- A live `lean XamanReceipt.lean` compile result.
- The proof-consumer report status and kernel artifact CID.
- Explicit blockers when the kernel is missing, Lean/Lake is missing, compilation fails, or the proof-consumer report does not record a compiled Lean kernel.

## Current Interpretation

`overall_status: ready` means the Lean lane can compile the current proof-consumer kernel and can support downstream proof-engineering work. It does not mean Xaman is secure or release-ready. The proof-consumer report still blocks production release until the kernel is integrated into a production consumer and the broader Xaman assumptions are cleared.

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_lean_solver_lane.py \
  --out security_ir_artifacts/environment/lean-solver-lane-report.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py -q
```

## Fail-Closed Behavior

The probe writes a report even when the lane is blocked. Downstream tasks must inspect `overall_status`, `security_decision`, and `blockers`; they must not treat a report file by itself as evidence that the Lean lane is ready.
