# Xaman Proof-Consumer Invariants

Date: 2026-07-08

Scope: PORTAL-CXTP-073 proof-consumer checks for the Xaman blocking/high-risk
claim set.

This artifact adds a small proof-kernel specification and a checked JSON report
for proof consumers that read Xaman proof receipts. It does not prove the full
Xaman wallet or backend secure. It proves and checks the consumer-side invariant:
a receipt can be accepted only when it binds the exact proof report, model,
claim, solver, assumptions, reviewed evidence, source corpus, and fresh
environment probe.

## Artifacts

- Lean proof kernel: `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean`
- Checked report: `security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json`
- Generator: `scripts/ops/security_verification/generate_xaman_proof_consumer_report.py`
- Runtime checker: `ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_proof_consumer`

The checked report is generated from:

- `security_ir_artifacts/corpora/xaman-app/security-model-ir.json`
- `security_ir_artifacts/corpora/xaman-app/security-model-ir.cid`
- `security_ir_artifacts/corpora/xaman-app/environment-probe.json`
- `security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean`

## Acceptance Predicate

The production proof-consumer predicate accepts only a packet with all of these
properties:

- The report status is `PROVED`.
- The receipt `model_cid` and report `model_cid` equal the selected Xaman
  `SecurityModelIR` CID.
- The receipt `claim_id` and report `claim_id` equal
  `xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims`.
- The receipt `proof_report_cid` equals the report CID.
- The receipt report schema version equals the report schema version.
- The solver identity is complete and present in the fresh environment probe or
  explicit proof-kernel allowlist.
- The report assumptions exactly match the required claim assumptions and the
  receipt accepts exactly those assumptions.
- Every required evidence reference is reviewed and includes the proof kernel,
  source manifest, security claims, proof-consumer policy, release policy, and
  environment probe.
- The receipt metadata binds the corpus commit
  `942f43876265a7af44f233288ad2b1d00841d5fa` and source manifest digest
  `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`.
- The environment probe is `ready`, does not block proof acceptance, and is no
  older than 24 hours at the report release window.

## Fail-Closed Outcomes

The checker rejects these non-secure outcomes:

- `DISPROVED`
- `UNKNOWN`
- `NOT_MODELED`
- missing solver identity or unavailable solver
- stale environment probe
- mismatched model CID, claim ID, report CID, or schema binding
- missing or extra accepted assumptions
- missing or unreviewed source evidence
- mismatched corpus commit or manifest digest

The checked JSON report includes negative fixtures for the required outcome
classes and records the rejection reason for each.

## Lean Kernel

`XamanReceipt.lean` defines:

- `Outcome`
- `ReceiptBindings`
- `Receipt`
- `AllBindings`
- `Accepts`

The theorem set proves acceptance implies the required bindings:

- `acceptedBindsModelCID`
- `acceptedBindsClaimID`
- `acceptedBindsReportCID`
- `acceptedBindsSolverIdentity`
- `acceptedBindsAssumptions`
- `acceptedBindsReviewedEvidence`
- `acceptedBindsCorpusCommit`
- `acceptedBindsFreshEnvironment`

It also proves:

- `rejectsDisprovedUnknownNotModeled`
- `rejectsMissingSolver`

Lean/Coq executables are not required by the current CI path. The checked-in
Lean file is the proof-kernel specification; the Python proof-consumer checker
executes the equivalent predicate against the canonical Xaman artifact packet
and fail-closed mutations.

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/generate_xaman_proof_consumer_report.py
```

Validate:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_proof_consumer_invariants.py -q
```

## Production Boundary

This artifact satisfies the proof-consumer invariant check for PORTAL-CXTP-073.
It does not change the broader Xaman production release decision. The Xaman
security model still remains blocked until the other blocking assumptions
identified in `security_ir_artifacts/corpora/xaman-app/security-claims.json`
receive reviewed production evidence.
