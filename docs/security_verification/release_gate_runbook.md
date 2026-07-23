# Crypto Exchange Release Gate Runbook

Date: 2026-07-07

Scope: operational procedure for running the crypto-exchange theorem-prover, disproof, runtime-monitor, receipt, and CI gates before a wallet/exchange release.

This runbook is fail-closed. If a step is missing, inconclusive, or cannot be reproduced, the release is not accepted.

## Required Inputs

Before running the production gate, collect:

- Production `SecurityModelIR`: `security_ir_artifacts/production/production-security-model.json`
- Production environment profile: `docs/security_verification/production_environment_profile.md`
- Assumption evidence bundle: `security_ir_artifacts/production/assumption-evidence.json`
- Accepted assumptions file: `security_ir_artifacts/production/accepted-assumptions.json`
- Evidence review summary: `security_ir_artifacts/production/evidence-review.json`
- Runtime trace export for the release window.
- Deployed source revision and build provenance.
- Prover dependency versions.

## Local Preflight

Run from `external/ipfs_datasets`:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange -q
```

Expected result: the focused crypto-exchange suite passes. Any failure blocks release.

## Built-In CI Baseline

Run the fixture baseline:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_assurance_baseline.py \
  --example \
  --out-dir security_ir_artifacts/assurance-run \
  --fuzz-rounds 8 \
  --fuzz-exhaustive-max-mutators 2 \
  --fuzz-max-scenarios 512 \
  --seed 7 \
  --min-modeled-blocking-claims 3 \
  --min-proved-blocking-claims 3
```

Expected result:

- Proof baseline exits zero.
- Disproof baseline exits zero.
- `security_ir_artifacts/assurance-run/assurance-baseline.md` is generated.

This validates the verifier surface, not the production exchange.

## Production Proof Gate

Run:

```bash
PYTHONPATH=. python -m ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all \
  --model security_ir_artifacts/production/production-security-model.json \
  --out security_ir_artifacts/production/proof-report.json \
  --strict-validation \
  --release-gate \
  --require-current-assumptions \
  --require-reviewed-evidence \
  --require-domain withdrawals \
  --require-domain deposits \
  --require-domain ledger \
  --require-domain capabilities \
  --require-domain hsm \
  --require-domain audit \
  --min-modeled-blocking-claims 3 \
  --min-proved-blocking-claims 3 \
  --emit-counterexamples-dir security_ir_artifacts/production/counterexamples \
  --emit-proof-receipts \
  --accepted-assumptions-file security_ir_artifacts/production/accepted-assumptions.json \
  --explain-soundness
```

Expected result: exit code `0`. Any nonzero exit code blocks release.

## Production Disproof Gate

Run:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_disproof_suite.py \
  --model security_ir_artifacts/production/production-security-model.json \
  --out security_ir_artifacts/production/disproof-report.json \
  --fuzz-rounds 128 \
  --fuzz-exhaustive-max-mutators 2 \
  --fuzz-max-scenarios 512 \
  --seed 7 \
  --emit-counterexamples-dir security_ir_artifacts/production/counterexample-vectors
```

Expected result:

- `scenario_failures` is `0`.
- Known-bad scenarios produce expected `DISPROVED` claims.
- Any mutant that still proves is triaged as a model or claim weakness.

## Production Assurance Bundle

Run:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_assurance_baseline.py \
  --model security_ir_artifacts/production/production-security-model.json \
  --out-dir security_ir_artifacts/production-baseline \
  --fuzz-rounds 64 \
  --fuzz-exhaustive-max-mutators 2 \
  --fuzz-max-scenarios 512 \
  --seed 7 \
  --min-modeled-blocking-claims 3 \
  --min-proved-blocking-claims 3
```

Archive:

- `security_ir_artifacts/production-baseline/proof-baseline.json`
- `security_ir_artifacts/production-baseline/disproof-baseline.json`
- `security_ir_artifacts/production-baseline/assurance-baseline.md`
- counterexamples and proof receipts
- production model CID and environment profile

## Runtime Monitor Gate

Run the production runtime monitor over the release-window trace export.

The release is blocked when:

- a withdrawal broadcasts without the modeled request, approval, nonce reservation, balance reservation, and wallet state checks;
- a deposit is credited before finality or after an unresolved reorg;
- a frozen wallet emits a signing request;
- a revoked capability authorizes a privileged action;
- a critical transition lacks audit evidence.

Runtime violations must be stored as counterexample evidence.

## Bounded Fuzz Coverage

The disproof suite runs every named attack mutation once and can add seeded random combinations with `--fuzz-rounds`. `--fuzz-exhaustive-max-mutators N` additionally executes every combination of the selected registered mutation grammar from size one through `N`; it fails before execution if the full finite matrix exceeds `--fuzz-max-scenarios`.

This is exhaustive only for the declared, finite SecurityModelIR mutation grammar. It does not establish coverage of unbounded production requests, unmodeled ledger semantics, native wallet code, or code paths absent from the source-to-IR mapping. Preserve those limits in the release evidence and treat missing model coverage as a blocker rather than an implicit pass.

## Proof Receipt Consumer Gate

Verify downstream consumers using `docs/security_verification/proof_receipt_consumer_policy.md`.

Production consumers must reject:

- invalid schemas;
- `DISPROVED`, `UNKNOWN`, and `NOT_MODELED`;
- model CID mismatch;
- claim mismatch;
- report CID mismatch;
- missing accepted assumptions;
- unsupported prover names;
- stale assumptions;
- unreviewed blocking/high evidence;
- missing trusted signature when canonical CID recomputation is unavailable.

## CI Gate

The GitHub workflow `.github/workflows/security-logic-ci.yml` must pass.

The workflow checks:

- hidden Unicode and newline normalization;
- Python compilation of security verifier sources;
- workflow YAML parse;
- focused crypto-exchange pytest suite;
- strict proof CLI;
- reviewed-evidence proof CLI;
- fail-closed proof CLI;
- built-in assurance baseline;
- disproof suite with counterexample vectors;
- TypeScript schema emission;
- TypeScript compile and runtime verifier tests;
- artifact upload and merge readiness summary.

## Failure Triage

| Failure | Required Response |
| --- | --- |
| `DISPROVED` | Attach counterexample, assign owning domain, reject release. |
| blocking/high `UNKNOWN` | Reject release unless claim scope is formally changed. |
| blocking/high `NOT_MODELED` | Extend production IR or remove claim through reviewed policy change. |
| stale assumption | Refresh evidence or reject release. |
| unreviewed evidence | Complete review or quarantine fact from production proof. |
| disproof scenario failure | Treat as claim/model weakness and reject release. |
| runtime violation | Treat trace as counterexample until reconciled. |
| receipt validation failure | Reject release and fix consumer or artifact packet. |

## Release Decision

Use `docs/security_verification/production_release_decision_policy.md` as the authoritative decision policy. The release is accepted only when every blocking and high-risk production gate passes and all required artifacts are archived.
