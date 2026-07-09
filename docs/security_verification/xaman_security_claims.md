# Xaman XRPL Security Claims And Assumptions

Task: `PORTAL-CXTP-067`

This document defines the blocking and high-risk Xaman XRPL security claims
derived from the reviewed dependency artifacts:

- `PORTAL-CXTP-064`: `security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json`
- `PORTAL-CXTP-065`: `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json`
- `PORTAL-CXTP-066`: `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json`

The machine-readable claims artifact is
`security_ir_artifacts/corpora/xaman-app/security-claims.json`.

## Source Boundary

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Coverage artifact: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`

This task does not assert that the production Xaman app is secure. It defines
the claims, assumptions, and fail-closed production policy needed by the next
SecurityModelIR task. A claim can only become production-accepted after every
consumed assumption is evidenced, accepted, current, and bound to a proof
packet whose model, report, receipt or signature, environment profile,
disproof report, and runtime traces all validate.

## Claim Summary

The claims artifact defines nine blocking or high-risk claims:

| Category | Gate | Claim status |
| --- | --- | --- |
| Custody | blocking | `BLOCKED_BY_ASSUMPTIONS` |
| Authentication | blocking | `BLOCKED_BY_ASSUMPTIONS` |
| Payload integrity | high | `BLOCKED_BY_ASSUMPTIONS` |
| Replay prevention | blocking | `BLOCKED_BY_ASSUMPTIONS` |
| Network binding | high | `BLOCKED_BY_ASSUMPTIONS` |
| Transaction semantics | high | `BLOCKED_BY_ASSUMPTIONS` |
| Backend trust | blocking | `BLOCKED_BY_ASSUMPTIONS` |
| Runtime equivalence | blocking | `BLOCKED_BY_ASSUMPTIONS` |
| Proof-consumer policy | blocking | `BLOCKED_BY_ASSUMPTIONS` |

The aggregate production decision is therefore `blocked-production`.

## Custody

Claim:

Software private keys cannot be used for XRPL signing unless the selected
account reaches an authorized vault or Tangem signing path for the same
reviewed transaction.

Evidence from `PORTAL-CXTP-064` supports the client-side custody shape:
full-access software account secrets are stored through the vault facade,
readonly and Tangem accounts do not store software private keys on add, and
software signing requires a vault-open path. This is not enough for production
acceptance because native vault cryptographic behavior, third-party signing
correctness, Tangem SDK or firmware behavior, and deployed runtime equivalence
are explicitly blocking assumptions.

## Authentication

Claim:

Passcode, passphrase, biometric-assisted passcode, or physical-card
authentication gates every software or Tangem signing path before a signed
transaction can be produced.

Reviewed source facts support the application-level path through the
authentication overlay, passcode throttling, vault overlay, and pre-vault
signing checks. The claim remains blocked because passcode KDF strength,
stored passcode-secret protection, native biometric binding, and deployed
runtime equivalence are not evidenced.

## Payload Integrity

Claim:

The transaction reviewed and signed by the user is the transaction JSON fetched
for the payload reference after digest verification and immediate pre-sign
revalidation.

Evidence from `PORTAL-CXTP-065` supports client-side digest verification,
resolved or expired payload rejection, visible review, and pre-sign remote
revalidation for non-generated payloads. The claim remains high-risk and
blocked until native or OS intake integrity, backend payload authorization and
single-use behavior, and runtime equivalence are evidenced.

## Replay Prevention

Claim:

A payload cannot be signed or submitted more than once across local state,
devices, and backend resolution races.

The reviewed client has local replay controls: resolved and expired payload
checks, pre-sign revalidation, already-signed and aborted transaction checks,
signed-blob checks, in-progress submit state, and prior-submit guards. The
production claim is blocking because backend atomic single-use resolution,
cross-device replay resistance, expiration enforcement, and PATCH conflict
handling are not modeled.

## Network Binding

Claim:

A payload intended for one XRPL network cannot be reviewed, signed, patched, or
submitted on a different configured network.

The client-side model covers forced-network review checks, template mismatch
rejection, unsupported transaction-type rejection for the connected network,
and `NetworkID` population for non-legacy networks. The high-risk claim remains
blocked until deployed network definitions, node endpoint configuration,
payload patch environment binding, and runtime trace equivalence are evidenced.

## Transaction Semantics

Claim:

The XRPL transaction fields signed by the user match the reviewed account,
destination, amount, fee, sequence, network, memo, issued-currency, trustline,
multisign, and transaction-type semantics.

Evidence from `PORTAL-CXTP-066` covers the reviewed field model and many
payment, issued-currency, trustline, network, fee, sequence, multisign, and
transaction-type constraints. The claim remains blocked because
`TrustSetValidation` and `SignerListSetValidation` are stubs, authoritative
XRPL server-side rule enforcement and consensus are not modeled, external
multisign collection is not modeled, third-party signing correctness is not
evidenced, and runtime equivalence is absent.

## Backend Trust

Claim:

The backend payload service cannot cause an unauthorized, stale, replayed, or
conflicting transaction to be signed or accepted as resolved.

The client model documents signed-payload patching, rejection patching, and
dispatch-result patching. The backend trust claim is blocking because backend
payload creation authorization, signer-constraint binding, single-use
resolution, expiration enforcement, and PATCH conflict handling require backend
source, deployment, and trace evidence that is not in the reviewed client
corpus.

## Runtime Equivalence

Claim:

The source and environment profile reviewed for Xaman claims are equivalent to
the mobile binaries, native modules, backend services, and runtime traces
consumed by a production proof packet.

All three dependency artifacts explicitly mark deployed runtime equivalence as
not modeled. Production acceptance requires binary provenance or reproducible
build evidence, native module and backend deployment digests, node
configuration evidence, and release-window runtime traces for authentication,
payload review, signing, patch, network, and submit transitions.

## Proof-Consumer Policy

Claim:

No proof consumer may treat a Xaman blocking or high-risk claim as secure
unless the claim outcome is `prove` and the proof packet validates model
binding, assumption acceptance, evidence review, solver support, runtime
freshness, and receipt or signature binding.

This is evidenced by
`docs/security_verification/production_release_decision_policy.md`,
`docs/security_verification/proof_receipt_consumer_policy.md`, and
`security_ir_artifacts/policies/security-decision-policy.json`. The Xaman
claim remains blocked until the production consumer can recompute canonical
report CIDs byte-for-byte or verify a trusted signature over the selected
proof report or receipt bundle.

## Assumption Rule

Every assumption in `security-claims.json` is one of:

- `EVIDENCED`: backed by reviewed dependency facts, manifest evidence, or
  frozen proof-consumer policy artifacts.
- `BLOCKING`: explicitly tied to a reviewed `NOT_MODELED` gap or policy
  blocker and accompanied by required evidence to accept it later.

No blocking or high-risk claim may be consumed as secure while it references a
`BLOCKING` assumption.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py -q
```

The tests validate the schema, dependency bindings, required claim categories,
assumption evidence/blocker coverage, dependency fact and gap references,
fail-closed proof-consumer policy, and documentation coverage.
