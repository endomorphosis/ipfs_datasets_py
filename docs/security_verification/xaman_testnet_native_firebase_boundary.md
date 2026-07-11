# Xaman Testnet Native Firebase Boundary

Task: `PORTAL-CXTP-126`

## Scope

This audit classifies native Android Firebase behavior in the Xaman Testnet verifier APK. It is separate from `PORTAL-CXTP-119` and `PORTAL-CXTP-120`, which disable and capture JavaScript calls through Metro stubs.

The result is a hard boundary: the inspected Testnet APK may be described as `firebase_js_stubbed_only`, but it must not be labeled fully Firebase-disabled while native Firebase providers, component registrars, DEX classes, packaged Firebase resources, Crashlytics native libraries, or native Firebase startup-log indicators remain.

## Reproducible Audit

Run the audit against the generated debug APK, the plain Gradle merged manifest, and the startup logcat capture:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/audit_xaman_native_firebase_boundary.py \
  --apk /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app/android/app/build/outputs/apk/debug/app-x86_64-debug.apk \
  --merged-manifest /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app/android/app/build/intermediates/merged_manifests/debug/x86_64/AndroidManifest.xml \
  --startup-log /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-testnet-firebase-disabled-events.log \
  --build-kit-manifest /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/testnet-build-manifest.json \
  --telemetry-report security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json \
  --run-id xaman-native-firebase-boundary-20260710 \
  --generated-at-utc 2026-07-10T21:00:00Z \
  --out security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json
```

The script stores only file digests, component names, APK binary-manifest indicator counts, DEX entry digests, native library names, resource names, categorical startup indicators, and per-line SHA-256 hashes. It scans the APK manifest for UTF-8, UTF-16LE, and UTF-16BE class strings because Android binary XML may not expose provider names as plain UTF-8 text. It omits raw startup log lines and records JavaScript stub markers separately from native startup indicators such as `FirebaseInitProvider`, `FirebaseApp initialization`, `Crashlytics`, or component discovery.

The required evidence set is the APK, the Gradle merged manifest, and a startup log. If the manifest or startup log is missing, `required_evidence.complete` is false, the report remains `blocked`, and the device-trial label is `not_allowed_missing_native_firebase_evidence` even when the APK ZIP scan itself is clean.

## Current Finding

The checked-in report is `security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json`. For the x86_64 debug verifier APK at Xaman commit `942f43876265a7af44f233288ad2b1d00841d5fa`, the report is `blocked` with decision `BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED`.

Merged-manifest and APK binary-manifest evidence includes:

- `ReactNativeFirebaseInitProvider` class-family indicators
- `io.invertase.firebase.app.ReactNativeFirebaseAppInitProvider`
- `io.invertase.firebase.crashlytics.ReactNativeFirebaseCrashlyticsInitProvider`
- `com.google.firebase.provider.FirebaseInitProvider`
- `com.google.firebase.components.ComponentDiscoveryService`
- Firebase Messaging services and receivers
- Firebase component registrars for App, Messaging, Crashlytics, Crashlytics NDK, Analytics, Sessions, Installations, Data Transport, and ML Kit

APK evidence includes Firebase or React Native Firebase indicators in DEX entries and Crashlytics native libraries:

- `lib/x86_64/libcrashlytics-common.so`
- `lib/x86_64/libcrashlytics-handler.so`
- `lib/x86_64/libcrashlytics-trampoline.so`
- `lib/x86_64/libcrashlytics.so`

Packaged Firebase resources also remain, including Firebase properties files and `res/raw/firebase_common_keep.xml` plus `res/raw/firebase_crashlytics_keep.xml`.

The supplied startup log contains four redacted `XAMAN_TESTNET_TELEMETRY:` JavaScript stub events and zero native startup-log indicators. That does not clear the boundary because manifest, DEX, resources, and native libraries still contain Firebase artifacts.

## JavaScript Versus Native Boundary

The build kit disables Google Services and Crashlytics Gradle tasks and routes `@react-native-firebase/analytics`, `@react-native-firebase/crashlytics`, and `@react-native-firebase/messaging` JavaScript imports to verifier stubs. The startup capture contains four accepted `XAMAN_TESTNET_TELEMETRY:` stub events.

That evidence proves only that JavaScript calls were routed to stubs during the captured startup path. It does not prove native Firebase initialization is absent, because the APK manifest, DEX, resources, and native libraries still contain Firebase artifacts.

## Removal Proof Requirement

An external verifier-only manifest or dependency overlay may clear this boundary only if the same audit returns:

- zero native Firebase manifest indicators;
- zero native Firebase APK binary-manifest indicators;
- zero Firebase component registrars;
- zero DEX entries matching Firebase or React Native Firebase indicators;
- zero packaged Firebase resources;
- zero Crashlytics native libraries;
- a supplied startup log with no native Firebase initialization indicators.

When such an overlay exists, pass its redacted verifier-only inputs to the audit with `--manifest-removal-overlay` and/or `--dependency-removal-overlay`. Those files are recorded by path, size, and SHA-256 only. Overlay evidence is not accepted by itself: `external_removal_assessment.status` becomes `verified_absent_after_external_overlay` only when the same generated APK, merged manifest, DEX scan, native library scan, packaged resource scan, and startup log are clean.

The current report has no removal overlay evidence and still contains native Firebase packaging, so `external_removal_assessment.status` is `not_effective_or_not_supplied`. Until a clean report exists, the Testnet device trial remains blocked from any `fully Firebase-disabled` label.
