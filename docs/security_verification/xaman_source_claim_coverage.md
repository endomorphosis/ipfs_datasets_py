# Xaman Source Claim Coverage

Task: `PORTAL-CXTP-145`

This report binds modeled Xaman wallet-auth, payload review, signing decision,
deep-link, QR, network-selection, receipt-consumer, and native-bridge claims to
immutable source locations from the pinned public corpus.

## Source Pin

- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Coverage: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`
- Source-claim map: `security_ir_artifacts/corpora/xaman-app/source-claim-map.json`
- Native-boundary coverage: `security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json`

The map is not a production release approval. It preserves the public-source
assessment decision and keeps release blocked while formal claims remain
non-proved or depend on uncleared assumptions.

## Boundary Coverage

| Boundary | Modeled source claims | Formal claims | Status |
| --- | ---: | ---: | --- |
| `deep_link` | 1 | 0 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `native_bridge` | 2 | 1 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `network_selection` | 3 | 1 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `payload_review` | 13 | 3 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `qr` | 1 | 0 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `receipt_consumer` | 0 | 1 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `signing_decision` | 14 | 3 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |
| `wallet_auth` | 20 | 1 | `COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS` |

## Required NOT_MODELED Boundaries

| Boundary | Status |
| --- | --- |
| `backend_behavior` | `NOT_MODELED` |
| `biometrics` | `NOT_MODELED` |
| `native_keystore_behavior` | `NOT_MODELED` |
| `vault_cryptography` | `NOT_MODELED` |

Vault cryptography, biometrics, native keystore behavior, and backend behavior
remain `NOT_MODELED` because the public source evidence only supports client
facades and call sites, not the native or backend implementations.

## Formal Claim Bindings

| Claim | Boundary | Status | Evidence locations |
| --- | --- | --- | ---: |
| `xaman-claim:backend-payload-service-is-trusted-not-proved` | `payload_review` | `NOT_PROVED_BLOCKING` | 3 |
| `xaman-claim:client-replay-controls-exist-but-backend-single-use-is-blocking` | `payload_review` | `PARTIAL_CLIENT_CONTROL_BACKEND_BLOCKING` | 5 |
| `xaman-claim:network-binding-prevents-wrong-network-signing` | `network_selection` | `SUPPORTED_BY_SOURCE_WITH_BLOCKING_ASSUMPTIONS` | 9 |
| `xaman-claim:payload-integrity-is-digest-checked-and-revalidated` | `payload_review` | `SUPPORTED_BY_SOURCE_WITH_BLOCKING_ASSUMPTIONS` | 7 |
| `xaman-claim:payment-semantics-check-amount-balance-and-trustlines` | `signing_decision` | `SUPPORTED_FOR_PAYMENT_WITH_ASSUMPTIONS` | 3 |
| `xaman-claim:proof-consumer-must-reject-non-proved-results` | `receipt_consumer` | `POLICY_DEFINED_NOT_YET_KERNEL_PROVED` | 5 |
| `xaman-claim:runtime-equivalence-is-blocked-without-device-traces` | `native_bridge` | `NOT_PROVED_BLOCKING` | 1 |
| `xaman-claim:signing-is-gated-by-auth-and-vault-overlay` | `signing_decision` | `SUPPORTED_BY_SOURCE_WITH_BLOCKING_ASSUMPTIONS` | 7 |
| `xaman-claim:software-custody-requires-vault-authentication` | `wallet_auth` | `SUPPORTED_BY_SOURCE_WITH_BLOCKING_ASSUMPTIONS` | 5 |
| `xaman-claim:transaction-validation-is-incomplete-for-selected-classes` | `signing_decision` | `NOT_PROVED_BLOCKING` | 5 |

## Native Boundary Coverage

| Boundary | Status | Summary |
| --- | --- | --- |
| `xaman-native-boundary:backend-payload-service` | `NOT_MODELED` | Client fetch, validate, patch, and reject calls are modeled, but backend authorization, atomic single-use, replay races, and PATCH conflict behavior are not proved. |
| `xaman-native-boundary:biometric-policy` | `NOT_MODELED` | The app models calls into the biometric helper, not platform prompt policy, enrollment binding, secure-enclave behavior, or spoof resistance. |
| `xaman-native-boundary:native-firebase-packaging` | `BLOCKED_NATIVE_PACKAGING_PRESENT` | JavaScript Firebase calls may be stubbed, but the inspected APK or startup evidence still shows native Firebase initialization and/or Crashlytics artifacts; the Testnet device trial cannot be labeled fully Firebase-disabled. |
| `xaman-native-boundary:native-keystore-behavior` | `NOT_MODELED` | Native keychain and Android keystore storage class, accessibility, hardware-backed settings, and migration behavior are not modeled. |
| `xaman-native-boundary:qr-camera-and-os-link-dispatch` | `NOT_MODELED` | Client dispatch after decoder output is modeled, but native camera parsing, OS link dispatch, clipboard, and decoder correctness are not proved. |
| `xaman-native-boundary:third-party-signing-and-tangem` | `NOT_MODELED` | Source facts record when signing libraries are called, but do not prove accountlib signing correctness, Tangem firmware behavior, or SDK attestation. |
| `xaman-native-boundary:vault-cryptography` | `NOT_MODELED` | Cipher mode, hardware backing, key migration, keychain/keystore accessibility, and memory handling are not proved by the TypeScript facade. |
| `xaman-native-boundary:vault-manager-js-bridge` | `MODELED_JS_BRIDGE_NATIVE_IMPLEMENTATION_NOT_MODELED` | The TypeScript vault facade calls VaultManagerModule, but the Android/iOS native implementation is outside the public source model. |

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_source_claim_coverage.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/build_xaman_source_claim_coverage.py --out security_ir_artifacts/corpora/xaman-app/source-claim-map.json
```
