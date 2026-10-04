# Coq Proof-Kernel Solver Lane

Task: `PORTAL-CXTP-093`

This lane records whether a Coq cross-check can contribute proof-kernel evidence for Xaman. It is intentionally fail-closed: absence of `coqc` or a Coq artifact is recorded as blocked optional coverage, not as proof success.

## Inputs

- Expected Coq artifact: `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.v`
- Lean kernel context: `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean`
- Probe script: `scripts/ops/security_verification/probe_coq_solver_lane.py`
- Lane report: `security_ir_artifacts/environment/coq-solver-lane-report.json`

## Current Expected State

The local environment currently has a checked Lean kernel, but no `coqc` executable and no Coq translation artifact. The report should therefore use:

- `overall_status: blocked_optional_lane`
- `security_decision: BLOCK_COQ_SOLVER_LANE_UNAVAILABLE`

Downstream evidence packets must not claim Coq-checked proof-kernel coverage until this lane becomes `ready`.

## Remediation

Install Coq outside the proof task and rerun the probe. Suggested routes:

```bash
sudo apt-get update && sudo apt-get install -y coq
```

or:

```bash
opam init --disable-sandboxing
opam switch create coq-8.20 ocaml-base-compiler.5.2.0
opam install coq
```

After installing Coq, add a reviewed `XamanReceipt.v` translation and run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_coq_solver_lane.py \
  --out security_ir_artifacts/environment/coq-solver-lane-report.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py -q
```

## Release Interpretation

This lane can only add independent Coq proof-kernel evidence. A blocked Coq lane does not invalidate the checked Lean kernel, but it does block any claim that Xaman has Coq-checked proof-consumer coverage.
