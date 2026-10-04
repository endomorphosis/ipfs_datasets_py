# Xaman Payload Lifecycle Model

Task: `PORTAL-CXTP-065`

This model records reviewed payload and sign-request lifecycle facts for the pinned Xaman React Native source corpus. The machine-readable artifact is `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json`.

## Source Boundary

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Coverage artifact: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`

The checked-in coverage artifact is manifest-bound but content-unavailable for several files and does not include all modal roots. This task reviewed the manifest-pinned Xaman source at the exact commit and bound each fact to source path, line range, and SHA-256 evidence.

## Lifecycle Summary

The modeled lifecycle states are:

`created_local -> referenced_remote -> fetched_verified -> review_preflight -> review_displayed -> approved_revalidated -> signed -> patched_signed -> submitted -> dispatch_patched -> result_displayed`

The non-broadcast path stops after `patched_signed -> result_displayed`. The rejection path is `review_displayed -> declined`. Expired or already-resolved remote payloads are blocked before review, and aborted transactions are blocked before signing or submit.

## Modeled Facts

### Payload Creation

`src/common/libs/payload/object.ts` models two creation shapes:

- Remote references are loaded through `Payload.from(uuid, origin)`, which calls `fetch`, assigns the backend object, and preserves the origin.
- In-app payloads are built with `Payload.build(TxJson, custom_instruction, submit, pathfinding)`, which creates a UUID, submit/pathfinding flags, signer constraints from `TxJson.Account`, request JSON, transaction type, timestamps, and the generated flag.

`src/common/libs/payload/types.ts` declares the lifecycle fields modeled here: `resolved`, `signed`, `cancelled`, `expired`, `signers`, `force_network`, `created_at`, `expires_at`, and `hash`.

### QR And Deep-Link Intake

QR intake in `src/screens/Modal/Scan/ScanModal.tsx` detects `StringType.XummPayloadReference`, validates the UUID, fetches with `PayloadOrigin.QR`, and routes to `AppScreens.Modal.ReviewTransaction`.

Deep-link intake in `src/services/LinkingService.ts` registers URL listeners after the default app root is active, checks the initial URL, detects payload references, validates UUIDs, fetches with `PayloadOrigin.DEEP_LINK`, and opens the review modal.

Push-notification intake in `src/services/PushNotificationsService.ts` validates the payload UUID, fetches with `PayloadOrigin.PUSH_NOTIFICATION`, and routes to review. Event-list intake loads pending payloads through `BackendService.getPendingPayloads`, refreshes on sign-request and app foreground events, and sets `PayloadOrigin.EVENT_LIST` when a request row opens review.

### Review UI

Review preflight in `PreflightStep` runs forced-network checks, transaction construction, and signer loading before showing the review step. It enforces `payload.force_network` against the active network and filters available signers against payload signer constraints.

`ReviewStep` displays application info, signer label, account picker, sign-for-account information, transaction-specific detail templates, optional developer JSON, and the `SwipeButton` that invokes approval. The accept control is disabled when the request is not ready.

### Approval And Signing

On acceptance, `ReviewTransactionModal.onAccept` revalidates non-generated payloads with `payload.validate()` before account activation checks, transaction-specific validation, warning overlays, and signing. `Payload.validate()` fetches the payload again, so expired or already-resolved backend state is checked again immediately before signing.

`Sign.mixin.ts` is the signing boundary. It rejects already-signed transactions, unsupported transaction types for the current network, missing fee or sequence setup failures, and aborted transactions before opening the vault overlay. The signed callback must include signed transaction data, signer public key, sign method, and a transaction id for non-pseudo transactions.

### Rejection And Expiration

`Payload.fetch` rejects unverified payloads, already-resolved payloads, and expired payloads before review. `ReviewTransactionModal.onDecline` patches backend rejection through `payload.reject`, using `USER` or `APP` as initiator and including the current payload origin. Generated local payloads do not patch backend rejection.

### Replay Controls

The client replay controls modeled here are:

- request JSON digest verification before remote payload review;
- `resolved_at` and `meta.expired` checks on fetch and pre-sign validation;
- pre-sign revalidation for non-generated payloads;
- local already-signed and aborted transaction checks;
- local signed-blob, in-progress, prior-submit, and abort checks before ledger submit.

Backend atomic single-use enforcement is explicitly `NOT_MODELED`.

### Network Binding

Network binding appears in four places:

- QR and deep-link transaction templates reject mismatched `NetworkID`.
- Review preflight blocks `force_network` mismatch.
- Signing rejects transaction types not in current network definitions.
- Signing populates `NetworkID` for non-legacy networks with network IDs greater than 1024.

### Broadcast Boundaries

After signing, `ReviewTransactionModal.submit` patches the payload backend with `signed_blob`, `tx_id`, `signmethod`, `signpubkey`, optional multisign account, and the current node/network environment before optional ledger submission.

Ledger broadcast only occurs when `payload.shouldSubmit()` is true: `meta.submit` is true, the payload is not pseudo, and the payload is not multisign. After broadcast, the client patches dispatch status with target node, network type, and engine result. `src/common/libs/ledger/types/methods/submit.ts` models the XRPL `submit` request/response boundary as preliminary node state with `accepted`, `applied`, `broadcast`, `kept`, and `queued` fields.

## NOT_MODELED Gaps

The artifact marks the following as `NOT_MODELED`:

- Backend payload creation authorization, atomic single-use resolution, replay resistance across devices, expiration enforcement, and PATCH conflict handling.
- Third-party string decoder behavior, native camera parsing, OS deep-link delivery, clipboard behavior, and malformed QR/deep-link runtime behavior.
- XRPL consensus safety, node honesty, mempool behavior, and final ledger inclusion beyond client submit/verify calls.
- Deployed app binary, backend deployment, node endpoint configuration, and runtime trace equivalence to the reviewed source.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_payload_lifecycle.py -q
```

The tests validate required lifecycle categories, manifest-bound evidence hashes, required modeled facts, expiration and replay controls, network binding, broadcast boundaries, explicit `NOT_MODELED` gaps, and documentation references.
