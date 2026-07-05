# Threat Model

Default assumptions carried into the initial framework:

- cryptographic primitives are unbroken
- private keys are generated with sufficient entropy
- HSM/key manager obeys its interface contract
- database commits are serializable
- nonce reservation is atomic
- blockchain finality threshold `k` is sufficient
- external RPC providers may lie, delay, or censor within modeled bounds
- audit logs are append-only or tamper-evident
- production must not depend on simulated proof, ZKP, or F-logic mode

`UNKNOWN` must never be treated as secure. Unsupported or incomplete proof paths stay fail-closed.
