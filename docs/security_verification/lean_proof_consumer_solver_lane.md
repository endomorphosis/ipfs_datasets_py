# Lean Proof-Consumer Solver Lane

Date: 2026-07-08

Scope: PORTAL-CXTP-090, the optional Lean lane for proof-consumer receipt and
invariant checks in the crypto-exchange/Xaman security verification workflow.

## Purpose

The lane id is `lean_proof_consumer_invariants`. It covers Lean-side checking of
the proof-consumer kernel at:

- `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean`
- `security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json`

This lane does not prove the production exchange secure. It records whether
Lean is available to independently compile-check the proof-consumer kernel that
backs the existing Python proof-consumer predicate. Missing Lean or missing Lake
must not become silent proof acceptance.

## Probe

Run from the repository root:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_lean_solver_lane.py \
  --out security_ir_artifacts/environment/lean-solver-lane-report.json
```

The report schema is `crypto-exchange-lean-solver-lane-report/v1`.

The probe records:

- platform support for the Lean lane
- `lean --version`
- `lake --version`
- `elan --version`
- `lean --print-prefix`
- `lean --print-libdir`
- Lake executable path when present
- Lean proof-kernel compile-check result
- proof-consumer report digest and claim binding
- explicit lane status: `ready`, `degraded`, or `blocked`

## Status Policy

`ready` means Lean and Lake are available, exact versions and paths were
recorded, and Lean compile-checked `XamanReceipt.lean`.

`degraded` means the supported host lacks Lean, or Lean can check the standalone
kernel but Lake is missing for project-level checks. The lane records
`missing-solver` and proof-consumer Lean coverage is not claimable.

`blocked` means the platform is unsupported, a discovered Lean/Lake executable
is unusable, or the Lean proof kernel fails to compile-check. The proof-consumer
claim remains blocked until the lane is repaired.

The lane follows the existing optional solver vocabulary:

- lane id: `lean_proof_consumer_invariants`
- release effects: `coverage-available`, `degraded-optional-coverage`,
  `blocked-proof-lane`
- decisions: `OPTIONAL_SOLVER_LANE_READY`,
  `DEGRADE_OPTIONAL_SOLVER_LANE_MISSING_SOLVER`,
  `BLOCK_OPTIONAL_SOLVER_LANE`
- missing solver outcome: `missing-solver`

## Reproducible Installation Guidance

The report emits reviewed command plans instead of installing automatically. The
lane-pinned Lean toolchain is:

```text
leanprover/lean4:v4.31.0
```

Recommended reviewed commands:

```bash
curl -fsSLo /tmp/elan-init.sh \
  https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh
sh /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:v4.31.0
export PATH="$HOME/.elan/bin:$PATH"
printf "%s\n" "leanprover/lean4:v4.31.0" > lean-toolchain
```

Then rerun the probe command above. Do not claim Lean proof-consumer coverage
until `proof_lane.status` is `ready` and `proof_kernel_check.status` is
`checked`.

## Proof-Consumer Claim Handling

The relevant proof-consumer claim is:

```text
xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims
```

Lean absence does not change the accepted proof-report status vocabulary. It is
reported as lane outcome `missing-solver`, while the Xaman negative fixture still
covers the existing `MISSING_SOLVER` rejected outcome.

Required fail-closed behavior:

- no Lean executable on a supported host: keep the lane `degraded`
- unusable Lean executable: keep the lane `blocked`
- missing Lake with working Lean: keep the lane `degraded`
- failed Lean kernel compile check: keep the lane `blocked`
- missing Lean receipt or unready lane: do not accept or promote Lean-backed
  proof-consumer claims

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_lean_solver_lane.py \
  --out security_ir_artifacts/environment/lean-solver-lane-report.json
```

The command exits zero for `ready`, `degraded`, and `blocked` reports so CI and
operators can always capture the environment evidence. Use `--strict` when a
blocked Lean lane should fail a dedicated proof-worker job.
