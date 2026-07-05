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
