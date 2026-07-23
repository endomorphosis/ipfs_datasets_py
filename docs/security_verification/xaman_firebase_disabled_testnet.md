# Xaman Firebase-Disabled Testnet Lane

Tasks: `PORTAL-CXTP-119`, `PORTAL-CXTP-120`, `PORTAL-CXTP-127`

## Scope

This verifier-only lane preserves the Xaman wallet and XRPL code paths while disabling Firebase Cloud Messaging, Analytics, and Crashlytics. It must never be used for a production build or as evidence that Xaman production behavior is secure.

The generated kit is external to the Xaman checkout. It disables Google Services and Crashlytics Gradle tasks, uses Metro's explicit resolver hook to route Firebase JavaScript imports to stubs, overlays a reviewed two-line React Native Navigation compatibility fix without touching `node_modules`, and runs with `CI=1` so Metro does not allocate host file watchers.

## Prepare a Testnet Build

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/xaman_firebase_disabled_testnet.py prepare \
  --xaman-root /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app \
  --out-dir /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit \
  --run-id xaman-testnet-001 \
  --tangem-maven /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/tangem-maven \
  --react-native-debug-aar /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/react-native-maven/com/facebook/react/react-android/0.74.2/react-android-0.74.2-debug.aar
```

Run the generated `build-xaman-testnet.sh` with the local JDK, Android SDK, and Node runtime exported. It deliberately invokes `app:assembleDebug`, producing a CI/debug-signed, Firebase-disabled test artifact. It is not a production release candidate.

The pinned source's release build currently stops in R8 because `react-native-camera` references removed ML Kit barcode and text APIs. That release-only dependency issue is tracked independently and must not be masked with broad `-dontwarn` rules; the debug build remains the approved artifact for the isolated Testnet trial.

The build kit removes Xaman's missing local `ReactAndroid-debug.aar` dependency at Gradle configuration time and uses the supplied original React Native 0.74.2 debug AAR. Record the artifact's SHA-256 in the generated kit manifest; do not add an AAR or symlink to the Xaman checkout.

## Capture Local Telemetry

The Metro stubs emit `XAMAN_TESTNET_TELEMETRY:` JSON records to device logs. Capture only matching lines, then ingest them locally:

```bash
adb logcat -d -v brief | rg 'XAMAN_TESTNET_TELEMETRY:' > testnet-events.log

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/xaman_firebase_disabled_testnet.py ingest \
  --database /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-telemetry.duckdb \
  --events testnet-events.log \
  --run-id xaman-testnet-001 \
  --build-provenance-sha256 <apk-sha256> \
  --ledger-endpoint wss://s.altnet.rippletest.net:51233 \
  --out security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json
```

The collector accepts only categorical operation names, counts, build labels, error classes, source labels, and reason codes. It rejects keys or nested values associated with secrets, seeds, passcodes, tokens, payloads, raw account addresses, or raw transaction data.

The endpoint field binds the capture to the intended Testnet target, but Firebase-stub events do not establish that the wallet connected to that endpoint. The report therefore records the target as declared and the runtime connection as unverified until a separate reviewed XRPL request trace exists.

## DuckDB Firebase Mock

For direct capture, the verifier provides a local HTTP mock that implements the narrow Firebase-stub boundary and writes accepted events directly to DuckDB. It binds only to host loopback. Android emulators reach that service through `10.0.2.2`; the generated stubs reject any non-loopback mock URL at kit-generation time.

The mock run is bound to the debug APK digest. First assemble the external debug artifact and calculate its SHA-256, then start the mock. The mock endpoint affects the Metro JavaScript bundle, not the debug APK; regenerate the kit with that endpoint before launching Metro. The service must remain running while the emulator starts the app:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/xaman_firebase_disabled_testnet.py mock-server \
  --database /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-firebase-mock.duckdb \
  --run-id xaman-testnet-firebase-mock-001 \
  --build-provenance-sha256 <apk-sha256> \
  --ledger-endpoint wss://s.altnet.rippletest.net:51233 \
  --bind-host 127.0.0.1 \
  --port 43127
```

Prepare the external kit with the emitted emulator endpoint:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/xaman_firebase_disabled_testnet.py prepare \
  --xaman-root /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app \
  --out-dir /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit \
  --run-id xaman-testnet-firebase-mock-001 \
  --tangem-maven /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/tangem-maven \
  --react-native-debug-aar /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/react-native-maven/com/facebook/react/react-android/0.74.2/react-android-0.74.2-debug.aar \
  --firebase-mock-endpoint http://10.0.2.2:43127/v1/events
```

Each request is validated before storage. The mock accepts only the existing categorical schema, stores a request SHA-256 rather than the raw request body, and returns HTTP 422 for a secret-bearing or malformed event. The stubs fall back to the `XAMAN_TESTNET_TELEMETRY:` device-log marker only if this loopback mock cannot be reached.

After the mock server has stopped, create the evidence report:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/xaman_firebase_disabled_testnet.py mock-report \
  --database /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-firebase-mock.duckdb \
  --run-id xaman-testnet-firebase-mock-001 \
  --out security_ir_artifacts/corpora/xaman-app/runtime/testnet-firebase-mock-report.json
```

`duckdb_firebase_mock` is an observability replacement for Firebase JavaScript calls, not Firebase emulation and not a substitute for native Firebase removal. It records no wallet, account, signing, or XRPL request bodies.

## Recorded Startup Capture

On 2026-07-10, the isolated API 34 x86_64 emulator installed the verifier APK at Xaman commit `942f43876265a7af44f233288ad2b1d00841d5fa`. The debug APK digest was `c22cd33b580dd0ecd8b8c5529b42169dccb79676ac396cda8af448d31810a41d`. The external Metro bundle contained the verifier stubs and emitted four accepted categorical events into the local DuckDB database; the redacted report is `security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json`.

This is a Firebase-disabled JavaScript startup capture, not a wallet transaction, account-creation, or runtime Testnet-connection result. Native Firebase classes and an initialization provider still exist in the APK and are tracked as a separate blocker.

## Evidence Boundary

`TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE` and `TESTNET_DUCKDB_FIREBASE_MOCK_CAPTURED_NOT_PRODUCTION_EVIDENCE` mean redacted Testnet telemetry reached a local DuckDB sink. Neither clears `RUNTIME_EQUIVALENCE_NOT_PROVED`, proves device equivalence, or removes any production release blocker.

The generated React Native Navigation overlay replaces two stale references to `ReactTextShadowNode.UNSET` with the module's own `ReactTypefaceUtils.UNSET`. It is limited to the pinned Testnet verifier environment and must be reviewed separately before any upstream or production use.
