# Production Environment Profile

Date: 2026-07-07

Profile ID: `production-wallet-exchange/env-profile/v0`

Status: `blocked_missing_production_evidence`

This profile records the operational facts needed before the crypto-exchange theorem-prover results can support a production wallet/exchange release decision. The current file is a fail-closed scaffold: it captures the local verifier environment and lists every production fact that must be supplied, reviewed, and linked into `SecurityModelIR` assumptions before `PROVED` can be interpreted as release-supporting evidence.

## Current Release Position

The production release is not formally accepted by this profile.

Reasons:

- The deployed wallet/exchange source revision is not recorded.
- Database isolation and transaction behavior are not recorded.
- Nonce reservation behavior is not evidenced.
- Chain and asset finality thresholds are not evidenced.
- HSM or key-manager behavior is not evidenced.
- RPC provider trust and failure bounds are not evidenced.
- Audit-log tamper evidence is not evidenced.
- Runtime event stream mappings are not recorded.
- Downstream proof receipt consumer behavior is not recorded.

## Local Verifier Snapshot

These are local verifier facts captured for reproducibility. They are not production deployment evidence.

| Field | Value |
| --- | --- |
| Workspace root revision | `8fa7cf1f643a3fdf6af7441462ac51f265ed13bd` |
| `external/ipfs_datasets` revision | `16f346d05778b3efea043c12a6b5a955bb359f32` |
| Python executable | `/home/barberb/miniforge3/bin/python` |
| Python version | `3.12.12` |
| Z3 Python bindings | `4.16.0` |
| Profile evidence bundle | `security_ir_artifacts/production/assumption-evidence.json` |

The working tree contains untracked security verification artifacts. Release evidence must use a committed or otherwise immutable revision before it can be accepted.

## Required Production Facts

| Assumption | Required production fact | Evidence owner | Current state | Release effect |
| --- | --- | --- | --- | --- |
| `A1` | Cryptographic primitive set, library versions, algorithm choices, disabled algorithms, and cryptographic review evidence. | `security-architecture` | Missing | Fail closed |
| `A2` | Key generation entropy source, seed custody, key lifecycle controls, and key-generation audit evidence. | `wallet-key-management` | Missing | Fail closed |
| `A3` | Signing code path, transaction canonicalization, approval binding, policy checks, and deployed source digest. | `wallet-transaction-signing` | Missing | Fail closed |
| `A4` | Database isolation level, transaction boundaries, retry behavior, ledger write semantics, and reservation consistency evidence. | `exchange-ledger-database` | Missing | Fail closed |
| `A5` | Nonce reservation implementation, uniqueness guarantees, idempotency model, mempool replacement policy, and conflict handling. | `withdrawal-nonce-service` | Missing | Fail closed |
| `A6` | Finality thresholds per chain and asset, reorg handling, rollback behavior, and risk approval evidence. | `chain-risk-management` | Missing | Fail closed |
| `A7` | Admin identity model, quorum rules, privileged action boundaries, break-glass controls, and compromise assumptions. | `security-governance` | Missing | Fail closed |
| `A8` | HSM or key-manager interface contract, attestation, policy enforcement, signing approval semantics, and failure behavior. | `custody-platform` | Missing | Fail closed |
| `A9` | RPC provider trust model, provider quorum or fallback policy, censorship/delay/lying bounds, and oracle freshness policy. | `blockchain-infrastructure` | Missing | Fail closed |
| `A10` | Audit-log append-only or tamper-evidence mechanism, retention policy, critical transition coverage, and verification procedure. | `audit-compliance` | Missing | Fail closed |

## Required Domain Coverage

The production `SecurityModelIR` must model every required domain before the release gate can be accepted:

- `withdrawals`: request, approval, balance reservation, nonce reservation, broadcast, cancellation, settlement, and rollback.
- `deposits`: observation, confirmations, finality, credit, reorg, rollback, and RPC disagreement.
- `ledger`: balances, liabilities, reservations, pending settlements, fees, hot/cold movement, and asset conservation.
- `capabilities`: delegation, caveats, revocation, reinstatement, expiration, privileged actions, and authority monotonicity.
- `hsm`: signing request, policy check, approval binding, attestation, failure, and refusal.
- `audit`: critical transition emission, append-only or tamper-evident persistence, retention, and retrieval.

## Evidence File Contract

`security_ir_artifacts/production/assumption-evidence.json` contains two sections:

- `ir_assumption_entries`: assumption entries with only fields compatible with `SecurityModelIR.assumptions`.
- `assumption_evidence_requirements`: operational evidence requirements and fail-closed status for each assumption.

Before a production proof run, each `ir_assumption_entries` item must have:

- `owner`: non-empty operational owner.
- `evidence_refs`: one or more reviewed evidence references.
- `last_reviewed_at`: ISO timestamp tied to the production evidence review, not the scaffold generation time.
- `evidence_expires_at`: ISO timestamp that is still current at proof time.

The scaffold uses a valid but stale review window so the IR parser can load the entries and the assumption registry still fails closed until real production evidence is supplied.

The proof gate must then run with:

```bash
PYTHONPATH=. python -m ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all \
  --model security_ir_artifacts/production/production-security-model.json \
  --strict-validation \
  --release-gate \
  --require-current-assumptions \
  --require-reviewed-evidence \
  --require-domain withdrawals \
  --require-domain deposits \
  --require-domain ledger \
  --require-domain capabilities \
  --require-domain hsm \
  --require-domain audit
```

## Next Evidence To Collect

1. Deployed wallet/exchange source repository URL, revision, and build provenance.
2. Database engine, isolation level, transaction retry policy, and ledger schema migration revision.
3. Nonce reservation service code path, table/key design, unique constraint, and idempotency behavior.
4. Per-chain and per-asset finality policy with incident-response handling for reorgs.
5. HSM/key-manager interface specification, attestation method, policy engine configuration, and signing refusal behavior.
6. Admin identity provider, quorum configuration, emergency access procedure, and audit trail.
7. RPC provider set, provider selection logic, fallback behavior, and stale data threshold.
8. Audit-log storage backend, append-only/tamper-evidence mechanism, and critical event coverage query.
9. Runtime event stream names, schemas, retention, and trace export command for release windows.
10. Proof receipt consumer code path and deployment location for TypeScript/WASM validation.
