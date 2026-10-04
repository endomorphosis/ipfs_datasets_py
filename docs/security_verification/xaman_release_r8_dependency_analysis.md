# Xaman Release R8 Dependency Analysis

Task: `PORTAL-CXTP-124`

## Scope

This analysis covers the Xaman Android release R8 dependency mismatch at pinned commit `942f43876265a7af44f233288ad2b1d00841d5fa`. The machine-readable evidence report is `security_ir_artifacts/corpora/xaman-app/runtime/release-r8-dependency-report.json`.

The required primary plan document, `docs/211_SERVICE_NAVIGATION_PORTAL_PLAN.md`, was not present in this repository. I used the taskboard entry plus nearby Xaman security-verification reports to keep the result aligned with the existing evidence pattern.

This is not a Testnet debug artifact update and it is not a production-release readiness claim. The final APKs were produced from the pinned verifier checkout with a verifier-only release keystore. Google Services and Crashlytics Gradle tasks were disabled because production Firebase configuration and secrets were unavailable in the verifier environment.

## Root Cause

The original release build reached `:app:minifyReleaseWithR8` and failed because the `react-native-camera` `mlkit` flavor references legacy ML Kit classes that were absent from the selected release dependency graph:

- `com.google.mlkit.vision.barcode.Barcode`
- `com.google.mlkit.vision.barcode.Barcode$Address`
- `com.google.mlkit.vision.barcode.Barcode$CalendarDateTime`
- `com.google.mlkit.vision.barcode.Barcode$CalendarEvent`
- `com.google.mlkit.vision.barcode.Barcode$ContactInfo`
- `com.google.mlkit.vision.barcode.Barcode$DriverLicense`
- `com.google.mlkit.vision.barcode.Barcode$Email`
- `com.google.mlkit.vision.barcode.Barcode$GeoPoint`
- `com.google.mlkit.vision.barcode.Barcode$PersonName`
- `com.google.mlkit.vision.barcode.Barcode$Phone`
- `com.google.mlkit.vision.barcode.Barcode$Sms`
- `com.google.mlkit.vision.barcode.Barcode$UrlBookmark`
- `com.google.mlkit.vision.barcode.Barcode$WiFi`
- `com.google.mlkit.vision.text.TextRecognizerOptions`

The app declares newer ML Kit artifacts while `react-native-camera` `4.2.1` requests the older API surface. The observed conflict was:

- `com.google.mlkit:barcode-scanning:17.2.0` pulled `play-services-mlkit-barcode-scanning:18.3.0`, which no longer provides the legacy `Barcode` model class used by `BarcodeFormatUtils`, `RNBarcodeDetector`, and `BarcodeDetectorAsyncTask`.
- `com.google.mlkit:text-recognition:16.0.0` pulled `play-services-mlkit-text-recognition:19.0.0`, where `TextRecognizerOptions` is no longer provided at `com.google.mlkit.vision.text.TextRecognizerOptions`.
- After restoring the legacy barcode/text providers, R8 also required `com.google.mlkit.vision.common.internal.Detector`, which is present in `com.google.mlkit:vision-common:16.5.0`.

Using R8-generated `-dontwarn` rules was rejected because it would hide missing dependency classes without proving that the affected scanner and recognizer paths are unreachable.

## Dependency Restoration

The mismatch was resolved by restoring compatible ML Kit versions for the release verifier build:

- `com.google.mlkit:barcode-scanning:16.2.0`
- `com.google.android.gms:play-services-mlkit-barcode-scanning:16.2.0`
- `com.google.android.gms:play-services-mlkit-text-recognition:16.3.0`
- `com.google.mlkit:vision-common:16.5.0`

The release runtime dependency graph then resolved `com.google.mlkit:barcode-scanning` from the app-declared `17.1.0`/`17.2.0` back to `16.2.0`, `play-services-mlkit-text-recognition` from `19.0.0` back to `16.3.0`, and `vision-common` from `17.x` back to `16.5.0`. `com.google.mlkit:common` remained graph-selected at `18.8.0`; the removed classes were restored by the legacy provider artifacts above.

Class inspection confirmed the restored providers contain the required legacy classes:

- `play-services-mlkit-barcode-scanning:16.2.0` contains `Barcode.class` plus the missing nested barcode payload classes.
- `play-services-mlkit-text-recognition:16.3.0` contains `TextRecognizerOptions.class`.
- `vision-common:16.5.0` contains `Detector.class`.

After the ML Kit classes were restored, release R8 also needed the existing reviewed React Native Navigation compatibility overlay at `/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/react-native-navigation-compat/ReactTypefaceUtils.java` with SHA-256 `c7ea6acd4300e8645644facc9f5c31dd8e601d29b890d6b7c0e55fffcd318f99`. That overlay is not part of the ML Kit mismatch.

## Build Evidence

The release packaging task was run with JDK 17 and the local Android SDK, using a temporary verifier init script that restored the ML Kit dependency versions, added the local Tangem mirror/substitutions, applied the React Native Navigation overlay, disabled Google Services and Crashlytics tasks, and configured a verifier-only release keystore:

```bash
JAVA_HOME=/home/barberb/.local/jdks/jdk-17.0.18+8 \
ANDROID_HOME=/home/barberb/lift_coding/.tools/android-sdk \
./gradlew app:packageRelease \
  --warning-mode=all \
  --stacktrace \
  --init-script /tmp/tmp.MOkdk0ydMv/xaman-release-r8-dependency-restore-assemble-signed.init.gradle
```

Result: `BUILD SUCCESSFUL in 1m 58s`, with `285 actionable tasks: 30 executed, 255 up-to-date`. This run executed `:app:minifyReleaseWithR8` and `:app:packageRelease`.

The full release lifecycle was then run without `CI=1` so Xaman's CI debug-signing substitution did not fire:

```bash
JAVA_HOME=/home/barberb/.local/jdks/jdk-17.0.18+8 \
ANDROID_HOME=/home/barberb/lift_coding/.tools/android-sdk \
./gradlew app:assembleRelease \
  --warning-mode=all \
  --init-script /tmp/tmp.MOkdk0ydMv/xaman-release-r8-dependency-restore-assemble-signed.init.gradle
```

Result: `BUILD SUCCESSFUL in 18s`, with `445 actionable tasks: 16 executed, 429 up-to-date`. `:app:minifyReleaseWithR8` was up to date from the successful package run, and `:app:packageRelease` re-ran under the verifier release signing configuration.

No broad warning suppression was applied. After the successful R8 run, `/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app/android/app/build/outputs/mapping/release/missing_rules.txt` was absent. The final R8 `configuration.txt` has SHA-256 `b1005a7052523b35c03abfd55f6a6e8cfe8db3c65c8a78f76227c06e62bd5958`; the ML Kit search found no `-dontwarn com.google.mlkit...` entries, only the pre-existing keep rule for `com.google.mlkit.vision.common.internal.Detector`.

## Release Outputs

The verifier release build produced APK split metadata for application ID `com.xrpllabs.xumm`, version name `4.2.1`:

| APK | ABI | Version code | Size bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `app-universal-release.apk` | universal | 30123 | 576500929 | `5d485fb0e2cf1fb186455e4c3cefeffb4e0c012cdd72479b485302a1e097dfc8` |
| `app-arm64-v8a-release.apk` | arm64-v8a | 3175851 | 189269112 | `e4a1c142ed65f4ff230dfc8b2341fe79bffe13fef38cdffd7d0e5a13c8056fe4` |
| `app-armeabi-v7a-release.apk` | armeabi-v7a | 1078699 | 158775468 | `fa36681dd5259c7f57186150ed73c98ba569cff0a31d723ec70f50d4a0fd0215` |
| `app-x86-release.apk` | x86 | 2127275 | 177478192 | `6cb9b856cf5d6ed6dc941620fb8bca67e4c9e0515b7e6ae4e768ee884f8f8185` |
| `app-x86_64-release.apk` | x86_64 | 4224427 | 190104596 | `51766dcbcb4965c338c515aca06e283ede7466e9f030d7c2bd8c604d8d73a35b` |

The release mapping outputs include `mapping.txt` SHA-256 `66c18a5f43bc1577c61831921c41932806f30a8232bb2b4d647e0e0c989589dc` and `configuration.txt` SHA-256 `b1005a7052523b35c03abfd55f6a6e8cfe8db3c65c8a78f76227c06e62bd5958`.

## Boundaries

This result resolves the ML Kit dependency mismatch for release R8 by restoring compatible dependencies. It does not rely on a reachability argument for the original missing ML Kit classes and it does not apply generated `-dontwarn` rules.

The Testnet debug artifact and its Firebase/runtime conclusions remain isolated. No production conclusion is derived from this verifier release build because production signing material and production Firebase configuration were not used.
