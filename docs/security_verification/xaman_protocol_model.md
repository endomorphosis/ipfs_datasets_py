# Xaman Payload Protocol Model

Task: `PORTAL-CXTP-072`

This artifact projects the Xaman payload lifecycle into a symbolic protocol model for Tamarin and later ProVerif checking. It focuses on whether payload signing and broadcast can occur without backend issue, digest validation, user review, authentication, vault unlock, or nonce consumption.

## Artifacts

- Tamarin model: `security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy`
- Protocol report: `security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json`

## Modeled Events

The model includes:

- `PayloadIssued`
- `PayloadReceived`
- `DigestChecked`
- `UserReviewed`
- `UserApproved`
- `AuthPassed`
- `VaultOpened`
- `PayloadSigned`
- `PayloadBroadcast`
- `PayloadRejected`
- `NonceConsumed`

## Lemmas

The Tamarin model declares:

- `sign_requires_digest_check`
- `sign_requires_user_approval`
- `sign_requires_auth_and_vault`
- `broadcast_requires_signature`
- `rejected_payload_not_broadcast`
- `nonce_consumed_at_most_once`

These lemmas cover the Xaman payload-integrity, replay-control, signing-gate, and backend-trust claims.

## Current Solver Status

Tamarin and ProVerif are not currently available on `PATH`, so the report is intentionally:

- `overall_status: blocked_optional_lane`
- `security_decision: BLOCK_PROTOCOL_SOLVERS_UNAVAILABLE`

This is blocker evidence, not proof evidence. No production release packet may claim protocol-solver coverage until at least Tamarin is run successfully and ProVerif coverage is either supplied or explicitly scoped out.

## Remediation

Install solvers through reviewed routes:

```bash
nix profile install nixpkgs#tamarin-prover
stack install tamarin-prover
opam install proverif
nix profile install nixpkgs#proverif
```

Then run:

```bash
tamarin-prover --prove security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_protocol_projection.py -q
```
