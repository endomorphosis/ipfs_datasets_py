# Xaman Testnet Public Build Reproduction

Task: PORTAL-CXTP-149

This record reproduces the public Android Testnet verifier build evidence in a locked, fail-closed form. It is not a vendor release reproduction, not a production release approval, and not a production security decision.

## Source Pin

- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Environment: `security_ir_artifacts/corpora/xaman-app/testnet/public-build-environment.json`
- Reproduction report: `security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json`

## Locked Environment

- Java: `17.0.18+8` at `/home/barberb/.local/jdks/jdk-17.0.18+8`
- Android SDK: `/home/barberb/lift_coding/.tools/android-sdk`
- Gradle: wrapper-pinned by `android/gradlew` and `android/gradle/wrapper/gradle-wrapper.properties`
- Node: `24.18.0`
- npm: `11.16.0`

## Build Outcome

The checked-in CLI records the build plan and prior verifier evidence without performing network clone, dependency download, or Gradle execution. The current result is `blocked` with decision `BLOCK_PUBLIC_TESTNET_BUILD_REPRODUCTION_NOT_VENDOR_RELEASE_EQUIVALENT`.

The recorded Testnet debug verifier APK digest is `c22cd33b580dd0ecd8b8c5529b42169dccb79676ac396cda8af448d31810a41d` for `android/app/build/outputs/apk/debug/app-x86_64-debug.apk`. This digest is verifier evidence only and is marked `production_usable: false`.

## Verifier-Only Patches

- `firebase_gradle_tasks_disabled`: Avoid requiring absent vendor Firebase configuration while producing a Testnet verifier APK.
- `firebase_js_module_stubs`: verifier_only
- `react_native_navigation_compatibility_overlay`: verifier_only
- `mlkit_dependency_resolution_strategy`: verifier_only_release_r8

## Missing Credentials And Services

- `production_android_signing_keystore` (credential): vendor release equivalence and production distribution signing
- `production_android_signing_passwords` (credential): unlocking the vendor signing key and proving signing lineage
- `android_google_services_json` (credential_or_service_config): Google Services Gradle processing against the vendor Firebase project
- `crashlytics_upload_mapping_credentials` (credential_or_service_config): Crashlytics mapping upload and release crash reporting integration
- `firebase_analytics_messaging_crashlytics_project` (service_dependency): runtime equivalence for Firebase-backed analytics, messaging, installation, and crash reporting components
- `xaman_backend_payload_api` (service_dependency): payload creation, payload status, backend single-use, expiry, and submission semantics
- `vendor_ci_release_environment` (service_dependency): proving the public checkout was built with the same CI variables, caches, secrets, and release orchestration as the vendor release
- `vendor_release_binary_or_store_bundle` (evidence_dependency): byte or signature comparison against a distributed vendor APK/AAB
- `xrpl_testnet_public_endpoint_availability` (service_dependency): runtime Testnet network probing and transaction lifecycle observations

## Non-Equivalence Policy

`public_build_equivalent_to_vendor_release` is `false`. The build lacks vendor signing keys, vendor Firebase configuration, backend service evidence, vendor CI provenance, and a vendor release binary for byte/signature comparison. It must never be promoted to `vendor_release_equivalent`, `production_release_approved`, or `app_store_binary_reproduced`.
