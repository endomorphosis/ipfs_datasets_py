# Xaman Security Claims

Task: `PORTAL-CXTP-067`

The claims artifact is `security_ir_artifacts/corpora/xaman-app/security-claims.json`.

## Scope

These claims bind the reviewed Xaman source-model artifacts for wallet auth, payload lifecycle, XRPL transaction semantics, runtime traces, and optional solver lanes. They do not mark the wallet secure. The current release decision is fail-closed:

`BLOCK_SECURITY_CLAIMS_PENDING_PROOFS_AND_ASSUMPTIONS`

## Custody And Authentication

The custody claim states that software-account private-key signing is vault-mediated and authentication-gated. This is source-supported by the wallet-auth model, but it remains blocked by native vault, keychain, biometric, passcode, and deployed-runtime assumptions.

The signing claim states that transaction signing must pass review acceptance, auth/vault overlay, and signed-object callback checks. This also remains blocked until native auth and runtime evidence are supplied.

## Payload Integrity And Replay

The payload-integrity claim records digest verification and pre-sign revalidation for non-generated payloads.

Replay prevention is only partial. Client controls block resolved, expired, already-signed, aborted, and locally submitted states, but backend atomic single-use, authorization, expiration, and PATCH conflict behavior remain blocking assumptions.

## Network And Transaction Semantics

Network binding is source-supported through forced-network checks, transaction-template network checks, active network definitions, and non-legacy `NetworkID` population.

Payment transaction semantics are source-supported for amount, native balance, issued-currency trustline, issuer freeze, sender IOU balance, and issuer obligation-limit checks.

The transaction-semantics surface is still blocked for broader claims because `TrustSet`, `OfferCreate`, and `SignerListSet` validations are TODO pass-throughs.

## Backend And Runtime Blocking Assumptions

The following assumptions are blocking:

- native vault cryptography and biometric security;
- backend payload API auth, single-use, expiration, and PATCH conflict behavior;
- XRPL consensus, node honesty, queue, mempool, and finality;
- deployed runtime equivalence;
- incomplete transaction-class validation.

The runtime trace report currently contains monitor facts but no real-device trace bundle, so runtime equivalence is `NOT_MODELED` for release purposes.

## Proof Consumer Policy

The proof consumer must accept only `proved` results and reject:

- `disproved`;
- `unknown`;
- `not_modelled` or `not_modeled`;
- `stale_evidence`;
- `missing_solver`;
- `blocked_assumption`.

Accepted proof receipts must bind model CID, report CID, claim ID, corpus commit, reviewed source evidence, and a fresh environment probe. This policy still needs Lean or Coq proof-consumer kernel validation before release.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py -q
```
