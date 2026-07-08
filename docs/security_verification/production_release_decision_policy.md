# Production Release Decision Policy

Date: 2026-07-07

Scope: crypto-exchange wallet and exchange releases that use `ipfs_datasets_py/logic/security_models/crypto_exchange` proof reports, disproof reports, assumption-registry results, proof receipts, and runtime monitor evidence.

This policy defines the only release outcomes that may be claimed from the current theorem-prover workflow. It is intentionally fail-closed: missing evidence, incomplete modeling, stale assumptions, unreviewed blocking evidence, or unsupported prover behavior cannot be interpreted as security.

## Release Outcomes

### Release Accepted

A release may be described as formally accepted only when all required checks pass:

- Every blocking and high-risk production claim is present in the proof report.
- Every blocking and high-risk production claim has status `PROVED`.
- No blocking or high-risk claim has status `DISPROVED`, `UNKNOWN`, or `NOT_MODELED`.
- Every required domain is modeled: `withdrawals`, `deposits`, `ledger`, `capabilities`, `hsm`, and `audit`.
- Every required assumption has an owner, evidence, review timestamp, expiry timestamp, and current non-stale evidence.
- Every assumption consumed by a proof report is explicitly accepted by the proof consumer.
- Every blocking and high-risk `PROVED` claim is backed by `human_reviewed` or equivalently trusted evidence.
- The production disproof suite still produces expected `DISPROVED` results for known-bad models.
- Runtime monitor evidence for the release window has no unexplained violations.
- Proof reports bind to the exact production model CID, code revision, prover version, and environment profile.
- Proof receipts validate in the downstream consumer path that gates deployment.

### Release Rejected

A release must be rejected when any of these occur:

- A blocking or high-risk claim is `DISPROVED`.
- A blocking or high-risk claim is `UNKNOWN`.
- A blocking or high-risk claim is `NOT_MODELED`.
- A configured blocking or high-risk claim is missing from the proof report.
- A required security domain is not modeled.
- A required assumption is missing, ownerless, unevidenced, stale, expired, or explicitly unaccepted.
- A blocking or high-risk `PROVED` claim is backed only by `heuristic` or `machine_extracted` evidence.
- A disproof scenario does not produce the expected counterexample.
- A runtime monitor violation contradicts the model or proof boundary.
- A model CID, report CID, receipt CID, code revision, or environment profile does not match the release packet.
- A proof report or receipt relies on simulated proof dependencies in production.
- The configured prover is unavailable, unsupported, times out, or returns an unsupported theory result for a critical claim.

### Release Inconclusive

A release is inconclusive, and therefore not accepted, when the team cannot decide whether a failure is real or modeled:

- Production source, API traces, policy documents, logs, or runbooks are unavailable.
- The production `SecurityModelIR` cannot be generated or validated.
- Evidence review is incomplete.
- Runtime traces are unavailable for the release window.
- Proof receipt consumers are not deployed or cannot validate the release packet.
- Independent prover backends are planned but not executable end to end.

Inconclusive is operationally equivalent to rejected for deployment gates.

## Current Claim Gates

| Claim | Domain | Gate | Accepted Status | Fail-Closed Statuses | Required Assumptions |
| --- | --- | --- | --- | --- | --- |
| `no_unauthorized_withdrawal` | `withdrawals` | blocking | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A3`, `A4`, `A5`, `A8` |
| `no_over_reserved_internal_account` | `ledger` | blocking | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A4`, `A5` |
| `global_asset_conservation` | `ledger` | blocking | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A4`, `A10` |
| `no_deposit_before_finality` | `deposits` | high | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A6`, `A9` |
| `no_signing_request_after_wallet_freeze` | `hsm` | high | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A3`, `A8` |
| `capability_delegation_no_authority_increase` | `capabilities` | high | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A1`, `A7` |
| `revoked_capability_no_future_authorization` | `capabilities` | high | `PROVED` | `DISPROVED`, `UNKNOWN`, `NOT_MODELED` | `A10` |
| `audit_event_exists_for_critical_transition` | `audit` | medium | `PROVED` | `DISPROVED` | `A10` |

The audit-linkage claim is medium severity in the current release policy. A concrete audit disproof blocks release. `UNKNOWN` or `NOT_MODELED` audit coverage still requires release triage and must be reconciled with required-domain coverage before acceptance.

## Required Commands

Run the production proof gate:

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

Run the production disproof gate:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_disproof_suite.py \
  --model security_ir_artifacts/production/production-security-model.json \
  --out security_ir_artifacts/production/disproof-report.json \
  --fuzz-rounds 128 \
  --seed 7 \
  --emit-counterexamples-dir security_ir_artifacts/production/counterexample-vectors
```

Run the release baseline:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_assurance_baseline.py \
  --model security_ir_artifacts/production/production-security-model.json \
  --out-dir security_ir_artifacts/production-baseline \
  --fuzz-rounds 64 \
  --seed 7 \
  --min-modeled-blocking-claims 3 \
  --min-proved-blocking-claims 3
```

## Decision Packet

Every accepted release must archive:

- Production `SecurityModelIR` JSON and model CID.
- Production environment profile and assumption evidence bundle.
- Proof report JSON.
- Disproof report JSON.
- Counterexample vectors.
- Runtime monitor report for the release window.
- Proof receipts for blocking and high claims.
- Proof receipt consumer validation output.
- Code revision, build revision, dependency/prover versions, and reviewer approvals.

## Triage Rules

- `DISPROVED`: open a security defect against the owning domain, attach the counterexample, and reject the release until the model or code is fixed.
- Blocking/high `UNKNOWN`: reject the release unless the claim is explicitly removed from production scope through a reviewed policy change.
- Blocking/high `NOT_MODELED`: reject the release and update the production IR or claim scope.
- Stale assumption: refresh operational evidence or reject the release.
- Unreviewed evidence: complete human review or quarantine the fact from production proofs.
- Runtime violation: treat the trace as a counterexample until explained and reconciled.

## Policy Maintenance

This file must be updated whenever:

- A claim changes release severity.
- A new blocking or high-risk claim is added.
- Required assumptions change.
- A new prover backend becomes release-authoritative.
- Proof receipt validation changes.
- Runtime monitor requirements change.
