# Xaman Tamarin/ProVerif Payload Protocol Model

Date: 2026-07-08

Scope: PORTAL-CXTP-072 protocol checks for the Xaman payload flow.

This artifact adds a source-backed symbolic protocol projection for remote
payload intake, fetch, review, approval, pre-sign revalidation, vault signing,
signed payload patching, replay blocking, rejection, expiration, and optional
ledger broadcast. It is intentionally fail-closed: Tamarin and ProVerif are not
available in the local verification environment, so the modeled lemmas are
`BLOCKED` and stronger claims with unavailable evidence are
`REJECTED_UNAVAILABLE_EVIDENCE`.

## Artifacts

- Tamarin theory: `security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy`
- Protocol report: `security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json`
- Generator: `scripts/ops/security_verification/generate_xaman_protocol_projection.py`
- Report builder: `ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_protocol_projection`

The report is generated from:

- `security_ir_artifacts/corpora/xaman-app/security-model-ir.json`
- `security_ir_artifacts/corpora/xaman-app/security-model-ir.cid`
- `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json`
- `security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json`

## Protocol Surface

`XamanPayloadProtocol` models:

- session identity and payload UUID creation
- requester binding across backend registration, intake, fetch, and review
- QR, deep-link, push-notification, and event-list intake after a decoded
  payload reference is available
- backend-authorized remote fetch and request JSON digest verification
- review, approval, and pre-sign revalidation
- vault secret storage as a source-level facade fact, authenticated vault open,
  and signature emission
- signed payload PATCH crossing an explicit backend trust boundary
- replay blocking after local UUID consumption
- rejection, expiration, and optional ledger broadcast after signed PATCH

The backend authorization fact is a trust-boundary precondition, not proof that
the backend is correct.

## Lemmas

The checked report records these Tamarin lemmas:

- `review_requires_verified_payload`
- `requester_binding_precedes_review`
- `qr_and_deep_link_intake_preserve_requester`
- `signing_requires_auth_revalidation_and_network`
- `modeled_vault_secret_not_revealed`
- `signed_patch_requires_backend_trust`
- `broadcast_requires_signed_patch`
- `local_replay_after_signing_is_blocked`

Each report property links the lemma to reviewed payload-lifecycle or
wallet-auth evidence and to the related Xaman claim and assumption IDs.

## Rejected Claims

The report rejects stronger claims that require evidence not present in the
source-backed protocol projection:

- backend global single-use, authorization, and PATCH conflict behavior
- native QR/parser/deep-link/push delivery integrity
- native vault cryptographic secrecy, KDF strength, and biometric binding
- third-party signing library, Tangem SDK/firmware, and XRPL server-rule
  correctness
- deployed runtime, app binary, backend deployment, and production network
  equivalence

These entries are `REJECTED_UNAVAILABLE_EVIDENCE` and are not submitted to a
solver as proof obligations.

## Solver Blocker

`protocol-report.json` records:

- `solvers.tamarin.available: false`
- `solvers.proverif.available: false`
- `summary.checked_property_count: 0`
- `summary.blocked_property_count: 9`
- every modeled property `classification: BLOCKED`
- every unavailable-evidence claim `classification: REJECTED_UNAVAILABLE_EVIDENCE`

This is a blocking artifact, not a proof. A proof consumer must not promote any
protocol claim to `PROVED` until Tamarin or ProVerif is installed, the checks
are rerun, and unavailable-evidence claims receive reviewed evidence.

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/generate_xaman_protocol_projection.py
```

Validate:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_protocol_projection.py -q
```

## Promotion Rule

Protocol checks can be promoted only when a regenerated report records an
available Tamarin or ProVerif executable, all required properties have accepted
solver output, and the rejected unavailable-evidence entries are resolved by
reviewed backend, native, signing-library, XRPL, and deployed-runtime evidence.
Until then, the protocol lane remains fail-closed for the Xaman release
decision.
