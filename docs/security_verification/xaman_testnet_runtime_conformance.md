# Xaman Testnet Runtime Conformance

Task: `PORTAL-CXTP-150`

This document records the redacted XRPL Testnet lifecycle conformance check for the frozen Xaman public-source Testnet model. It is not a production or vendor-release security decision.

## Artifacts

- Report: `security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json`
- Trace map: `security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-trace-map.json`
- Frozen model: `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json`
- Model CID: `sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`
- Source claim trace map: `security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json`
- Transaction trial: `security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json`

## Decision

- Overall status: `blocked_testnet_runtime_conformance`
- Security decision: `BLOCK_TESTNET_ASSURANCE_RUNTIME_CONFORMANCE_GAPS`
- Production release blocked: `true`
- Assurance block count: `17`

## Runtime Categories

- `fresh_emulator` (fresh-emulator): `observed`; claims `xaman-testnet-claim:account-provenance-is-fresh-testnet-only, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `testnet_only_network` (Testnet-only network): `observed`; claims `xaman-testnet-claim:network-binding-is-testnet-only, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `fresh_account` (fresh-account): `observed`; claims `xaman-testnet-claim:account-provenance-is-fresh-testnet-only, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `review` (review): `observed`; claims `xaman-testnet-claim:review-auth-sequence-observed, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `authentication` (authentication): `observed`; claims `xaman-testnet-claim:review-auth-sequence-observed, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `signing_decision` (signing decision): `observed_with_blocking_boundary`; claims `xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled, xaman-testnet-claim:review-auth-sequence-observed, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `submit_attempt` (submit attempt): `observed_with_blocking_boundary`; claims `xaman-testnet-claim:submission-ui-attempt-and-result-are-observed, xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `submit_result` (submit result): `observed_with_blocking_boundary`; claims `xaman-testnet-claim:submission-ui-attempt-and-result-are-observed, xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `cancellation` (cancellation): `blocked_missing_path`; claims `xaman-testnet-claim:cancellation-path-is-not-modeled`
- `expiry` (expiry): `blocked_missing_path`; claims `xaman-testnet-claim:expiry-path-is-not-modeled`
- `replay` (replay): `blocked_missing_path`; claims `xaman-testnet-claim:replay-controls-are-not-modeled`
- `reconnect` (reconnect): `observed`; claims `xaman-testnet-claim:network-binding-is-testnet-only, xaman-testnet-claim:audit-redaction-boundary-is-preserved`
- `network_change` (network-change): `observed`; claims `xaman-testnet-claim:network-binding-is-testnet-only, xaman-testnet-claim:audit-redaction-boundary-is-preserved`

## Redaction Boundary

The artifacts retain only categories, outcomes, source digests, redaction digests, artifact CIDs, endpoint keys, and endpoint digests. They do not retain seeds, addresses, payloads, transaction blobs, credentials, or raw endpoints.

## Testnet Assurance Blocks

- `RUNTIME_CATEGORY_SIGNING_DECISION_BOUNDARY`: Observed categorical runtime evidence remains bounded by a NOT_MODELED cryptographic, backend, or ledger boundary.
- `RUNTIME_CATEGORY_SUBMIT_ATTEMPT_BOUNDARY`: Observed categorical runtime evidence remains bounded by a NOT_MODELED cryptographic, backend, or ledger boundary.
- `RUNTIME_CATEGORY_SUBMIT_RESULT_BOUNDARY`: Observed categorical runtime evidence remains bounded by a NOT_MODELED cryptographic, backend, or ledger boundary.
- `RUNTIME_CATEGORY_CANCELLATION_BLOCKED`: Required Testnet lifecycle path is not evidenced as an observed runtime path.
- `RUNTIME_CATEGORY_EXPIRY_BLOCKED`: Required Testnet lifecycle path is not evidenced as an observed runtime path.
- `RUNTIME_CATEGORY_REPLAY_BLOCKED`: Required Testnet lifecycle path is not evidenced as an observed runtime path.
- `MODEL_NOT_MODELED_RECORD_ACTIVE`: Raw payloads, request bodies, and transaction blobs were not recorded.
- `MODEL_NOT_MODELED_RECORD_ACTIVE`: Raw signatures and signed transaction blobs were not retained.
- `MODEL_NOT_MODELED_RECORD_ACTIVE`: The Testnet verifier run is not production runtime-equivalence evidence.
- `MODEL_NOT_MODELED_RECORD_ACTIVE`: The reviewed lifecycle event list has no replay or duplicate-submit exercise.
- `MODEL_NOT_MODELED_RECORD_ACTIVE`: Cancellation is present only as a not-exercised reviewed coverage gap.
- `MODEL_NOT_MODELED_RECORD_ACTIVE`: Expiry is present only as a not-exercised reviewed coverage gap.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_runtime_conformance.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/validate_xaman_testnet_runtime_conformance.py --out security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json
```
