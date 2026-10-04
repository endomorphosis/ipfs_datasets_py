# Xaman Public-Testnet Device Trial

Task: `PORTAL-CXTP-121`

The device-trial report is:

`security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json`

It binds the pinned Xaman commit, x86_64 debug APK digest, debug-signing evidence, isolated local AVD profile, verified Testnet network-selection report, fresh Testnet account boundary, XRPL `server_info` request/response digests, and the local DuckDB telemetry database.

## Regeneration

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/capture_xaman_testnet_device_trial.py \
  --generated-at-utc 2026-07-10T22:00:00Z
```

The command also writes the local APK digest packet to:

`/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-device-apk-digest.json`

## Boundary

The trial is public-Testnet only. The report stores event categories, network key, endpoint key, file digests, request/response digests, aggregate counts, and non-secret local paths. It rejects raw XRPL endpoints, seeds, account addresses, credentials, payloads, transaction blobs, raw request bodies, and raw `server_info` responses.

The inspected APK is classified as `firebase_js_stubbed_only` because `PORTAL-CXTP-126` found native Firebase and Crashlytics packaging. Production acceptance, full Firebase-disabled labeling, transaction-lifecycle coverage, and runtime equivalence remain blocked.

## Validation

```bash
test -f security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json
test -f security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_testnet_device_trial.py -q
```
