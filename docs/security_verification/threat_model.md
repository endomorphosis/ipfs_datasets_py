# Threat Model

Default assumptions carried into the initial framework:

- `A1` cryptographic primitives are unbroken
- `A2` private keys are generated with sufficient entropy
- `A3` signing code signs only approved canonical transaction bytes
- `A4` database commits are serializable
- `A5` nonce reservation is atomic
- `A6` blockchain finality threshold `k` is sufficient
- `A7` admin identities are not all compromised
- `A8` HSM/key manager obeys its interface contract
- `A9` external RPC providers may lie, delay, or censor within modeled bounds
- `A10` audit logs are append-only or tamper-evident

Default operational owners:

| Assumption | Owner |
| --- | --- |
| `A1` | `security-architecture` |
| `A2` | `wallet-key-management` |
| `A3` | `wallet-transaction-signing` |
| `A4` | `exchange-ledger-database` |
| `A5` | `withdrawal-nonce-service` |
| `A6` | `chain-risk-management` |
| `A7` | `security-governance` |
| `A8` | `custody-platform` |
| `A9` | `blockchain-infrastructure` |
| `A10` | `audit-compliance` |

Each structured assumption entry can carry `owner`, `evidence_refs`, `last_reviewed_at`, and `evidence_expires_at`. Production assurance runs should use `prove_all --require-current-assumptions` so stale or unevidenced assumptions are treated as non-secure.

Prioritized attack classes carried in the example threat model metadata:

- `T1` stolen API token
- `T2` compromised exchange employee
- `T3` replayed withdrawal request
- `T4` stale blockchain RPC data
- `T5` chain reorg after deposit credit
- `T6` race condition between withdrawals
- `T7` hot wallet key compromise
- `T8` malicious dependency or build artifact
- `T9` prompt injection against the policy compiler
- `T10` simulated proof mode used in production

`UNKNOWN` must never be treated as secure. Unsupported or incomplete proof paths stay fail-closed.

## Soundness boundary

- These proofs are bounded by the assumption registry (`A1`-`A10`) and the modeled event, capability, and ledger facts in the IR.
- Assumption owners and evidence freshness are operational controls, not theorem-prover facts; stale assumption evidence must block production release until re-reviewed.
- Heuristic source-code autoformalization is not production-trustworthy until its evidence references move beyond `heuristic` review status.
- `PROVED` means the implemented Z3 backend discharged the modeled claim; it does not mean an arbitrary exchange codebase is absolutely secure.
- `UNKNOWN` and `NOT_MODELED` must remain fail-closed.
