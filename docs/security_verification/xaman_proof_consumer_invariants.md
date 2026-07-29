# Xaman Proof-Consumer Invariants

Task: `PORTAL-CXTP-073`

This artifact defines the proof-consumer conditions that must hold before a theorem-prover report can be accepted for Xaman release evidence. The checked kernel is intentionally narrow: it proves that the consumer rejects non-`PROVED` statuses and rejects missing trust, stale assumptions, solver disagreement, counterexamples, unreviewed evidence, and mismatched proof bindings.

## Kernel Artifact

- Lean file: `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean`
- Report: `security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json`
- Bound model CID: `sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d`
- Xaman claim: `xaman-claim:proof-consumer-must-reject-non-proved-results`

The Lean kernel models two records:

- `ProofReport`: claim ID, model CID, proof status, assumption status, evidence review, solver agreement, and counterexample absence.
- `ProofReceipt`: claim ID, model CID, report-CID match, trust anchor, assumption freshness, and prover allowlist status.

`canAccept` returns true only when all proof-critical checks hold.

## Checked Rejection Invariants

The Lean file proves rejection for:

- `DISPROVED` reports.
- `UNKNOWN` reports.
- `NOT_MODELED` reports.
- Uncleared assumptions.
- Unreviewed evidence.
- Solver disagreement.
- Attached or known counterexample evidence.
- Report CID mismatch.
- Missing trusted signature or canonical CID verification.
- Stale accepted assumptions.
- Unsupported prover.

The file also contains a positive example showing that a fully bound, fully reviewed, `PROVED` report can be accepted by the modeled consumer.

## Toolchain Result

The local verifier compiled the Lean file with:

```bash
lean security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean
```

The current report records Lean as compiled and Coq as unavailable because `coqc` is not installed. No production evidence may claim Coq-checked proof-consumer coverage until a Coq artifact is added and compiled.

## Release Interpretation

This kernel does not prove the Xaman app secure. It proves a consumer-side guard: non-proved or incompletely bound proof evidence must be rejected. The release remains blocked until this kernel is wired into the production proof-consumer runtime and the remaining Xaman assumptions are cleared with reviewed evidence.

## Regeneration

After editing the kernel, rerun:

```bash
lean security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_proof_consumer_invariants.py -q
```
