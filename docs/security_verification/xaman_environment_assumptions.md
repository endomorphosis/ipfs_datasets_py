# Xaman Environment Assumptions

This document records the reproducible dependency and build-environment
assumptions probed for the pinned Xaman-App corpus (PORTAL-CXTP-060) so that
downstream Xaman security-model tasks share one evidence-backed baseline. It
is source and host-environment evidence only; it does not claim that any
deployed Xaman build, signing environment, app-store binary, backend
service, or operational control is secure.

- Probe script: `scripts/ops/security_verification/probe_xaman_environment.py`
- Probe report: `security_ir_artifacts/corpora/xaman-app/environment-probe.json`
- Report schema: `xaman-environment-probe/v1`
- Task: `PORTAL-CXTP-061`
- Depends on: `PORTAL-CXTP-058` (solver dependency probe), `PORTAL-CXTP-060`
  (pinned Xaman corpus manifest), `PORTAL-CXTP-089` (required TypeScript
  compiler remediation)

## What The Probe Does

The pinned Xaman-App source manifest
(`security_ir_artifacts/corpora/xaman-app/source-manifest.json`) already
records path, size, and SHA-256 digest metadata for every tracked file at
commit `942f43876265a7af44f233288ad2b1d00841d5fa`, but not file *content*.
Recording Node/npm requirements, React Native build assumptions, TypeScript
configuration, and Detox/e2e availability requires reading a small number of
pinned configuration files.

The probe therefore performs a narrow, best-effort live `git` sparse
checkout restricted to:

`package.json`, `tsconfig.json`, `tsconfig.jest.json`, `.detoxrc.js`,
`jest.config.js`, `android/build.gradle`, `android/app/build.gradle`,
`android/gradle.properties`, `ios/Podfile`, `.ruby-version`, and
`.watchmanconfig`.

It verifies the checked-out commit resolves to the exact commit pinned in
the manifest, then parses each file: `package.json`/`tsconfig.json` as
comment-tolerant JSON (JSONC, stripping `//`/`/* */` comments and trailing
commas with a string-boundary-aware scanner so glob values such as
`"src/**/*.ts"` are never mistaken for comment markers), `.detoxrc.js` via
targeted regular expressions for `apps`/`configurations`, Gradle files via
regular expressions after dropping fully-commented lines (so a stray
unterminated quote in a commented-out line cannot corrupt later matches),
and `ios/Podfile` similarly.

`e2e/*.feature` file counts and every dependency-lockfile digest are read
directly from the already-hashed corpus manifest; they never require live
content.

If the live checkout cannot be reproduced (no network, no git, or a
resolved commit mismatch), the probe fails closed: it still writes a
report, but every content-derived section is marked
`"status": "content_unavailable"` and a blocking evidence entry
(`XAMAN_CORPUS_CONTENT_UNAVAILABLE`) is recorded so downstream tasks cannot
silently treat an unverified environment as ready.

## Node And NPM Requirements

Read from `package.json`:

- `engines.node`: `>=18`
- `engines.npm`: not declared (no npm engine pin in the pinned commit)
- App name/version: `xaman` / `4.1.3`

The probe cross references `engines.node` against the Node.js version
resolved by the solver dependency probe (PORTAL-CXTP-058). A local Node.js
version that does not satisfy the declared range is recorded as a blocking
`NODE_ENGINE_REQUIREMENT_NOT_SATISFIED` entry.

## React Native Build Assumptions

Read from `package.json` dependencies/devDependencies and
`android/gradle.properties`:

- React Native: `0.74.2`
- React: `18.2.0`
- Hermes engine: enabled (`hermesEnabled=true`)
- New Architecture (Fabric/TurboModules): disabled
  (`newArchEnabled=false`)
- Detox devDependency: `20.32.0`
- TypeScript devDependency: `5.4.3`
- `@react-native/babel-preset` / `@react-native/metro-config`: `0.74.84`
  (Babel and Metro configuration files, `babel.config.js` and
  `metro.config.js`, are part of the pinned sparse checkout scope)

## iOS Native Assumptions

Read from `ios/Podfile`, `.ruby-version`, and the corpus manifest:

- iOS deployment target: `platform :ios, '13.4'`
- CocoaPods `use_frameworks!` referenced: yes
- Ruby version pin (`.ruby-version`): `2.7.4`
- `ios/Podfile.lock` present with a recorded SHA-256 digest
  (dependency lockfile evidence, not live-fetched)
- `ios/security.txt` present (security disclosure evidence)
- Build host requirement: macOS with Xcode command line tools; iOS builds
  and Detox iOS e2e binaries are **not reproducible on Linux hosts** and are
  recorded as capability gaps, not blockers, for this proof pipeline.

## Android Native Assumptions

Read from `android/build.gradle`, `android/app/build.gradle`, and
`android/gradle.properties`:

- `compileSdkVersion`: `34`
- `minSdkVersion`: `26`
- `targetSdkVersion`: `35`
- `ndkVersion`: `26.1.10909125`
- Kotlin version: `1.9.24`
- Android Gradle Plugin: `7.4.0` (commented-out prior pin `7.3.1` is
  correctly ignored by dropping full-line `//` comments before matching)
- Canonical app version: `4.2.1` (version code `123`)
- `android/app/src/main/assets/security.txt` present (security disclosure
  evidence)
- Build host requirement: JDK and Android SDK/NDK; the Gradle wrapper is
  vendored at `android/gradlew`.

## Dependency Lockfile Digests

Recorded directly from the pinned corpus manifest (no live fetch required):

- `package-lock.json`
- `Gemfile.lock`
- `ios/Podfile.lock`

Each entry's SHA-256 digest and byte size are copied verbatim from
`security_ir_artifacts/corpora/xaman-app/source-manifest.json` so lockfile
evidence stays bound to the exact pinned commit.

## TypeScript Config

Read from `tsconfig.json` `compilerOptions` (JSONC, comments and trailing
commas stripped) and cross referenced against the locally resolved
TypeScript compiler:

- `target`: `esnext`, `module`: `es2015`, `jsx`: `react-native`
- `strict`: `true`, `moduleResolution`: `bundler`, `baseUrl`: `src`
- `paths` alias count: `14` (`@components`, `@common`, `@locale`,
  `@screens`, `@services`, `@store`, `@theme`, each with a `*` variant)
- Pinned `typescript` devDependency: `5.4.3`
- Locally resolved `tsc` (from the PORTAL-CXTP-089 repo-scoped toolchain):
  `5.6.3`

A pinned/local TypeScript version difference is recorded for visibility but
is not treated as a blocker here: PORTAL-CXTP-089 already remediated the
*required* `tsc` dependency for this repository's own schema type-checking,
which is a distinct concern from compiling the Xaman app itself.

## Detox Or E2E Availability

Read from `.detoxrc.js`, `package.json`, and the corpus manifest's `e2e/`
entries:

- `.detoxrc.js` present with `apps` (`xaman.ios`, `xaman.android`) and
  `configurations` (`ios.simulator+xaman.ios`, `android.emulator+xaman.android`,
  `android.attached+xaman.android`)
- Detox devDependency: `20.32.0`; `@cucumber/cucumber` devDependency:
  `10.3.1` (feature-file step runner)
- Pinned e2e feature files: `6`
  (`01_setup`, `02_generate_account`, `03_import_account`,
  `04_upgrade_account`, `05_auth`, `06_linking`)
- `e2e/support`, `e2e/step_definitions`, and `e2e/helpers` all present

Running Detox e2e itself requires a macOS/Xcode or Android SDK host with the
Detox CLI, `adb`, and (for iOS) `xcodebuild`; these are recorded as
capability gaps, not blockers, because building or executing the Xaman app
is out of scope for this static, source-and-manifest-driven proof pipeline
(runtime/e2e trace *ingestion* is instead handled by PORTAL-CXTP-074, which
explicitly blocks on absent real-device traces).

## Solver Paths

The probe embeds the resolved `python`, `node`, `npm`, `typescript`, `z3`,
and `cvc5` executables and versions from
`security_ir_artifacts/environment/solver-dependency-probe.json`
(PORTAL-CXTP-058) and the pinned TypeScript toolchain metadata from
`security_ir_artifacts/environment/typescript-remediation-report.json`
(PORTAL-CXTP-089), so Xaman-specific proof and disproof work can reference
one consistent set of tool paths without re-probing the host.

## Missing Dependency Blockers

The probe records two tiers of missing-dependency evidence:

1. **Blocking** (flips `overall_status` to `blocked` and
   `proof_acceptance_blocked` to `true`):
   - `XAMAN_CORPUS_CONTENT_UNAVAILABLE` — the narrow live checkout of
     pinned configuration files could not be reproduced.
   - `SOLVER_DEPENDENCY_PROBE_MISSING` — the PORTAL-CXTP-058 solver
     dependency probe report is absent.
   - `INHERITED_SOLVER_DEPENDENCY_BLOCKER` — the solver dependency probe
     itself reports `proof_acceptance_blocked: true`.
   - `NODE_ENGINE_REQUIREMENT_NOT_SATISFIED` — the locally resolved Node.js
     version does not satisfy `package.json` `engines.node`.
2. **Non-blocking capability gaps** — missing native build/e2e toolchain
   dependencies (`ruby`, `pod`, `java`, `xcodebuild`, `watchman`, `adb`,
   `detox_cli`), each tagged with the capability it would enable
   (`ios_pod_install`, `android_build`, `ios_build`, `ios_detox_e2e`,
   `metro_bundler`, `android_detox_e2e`, `detox_e2e_orchestration`).

## Reproduction Command

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_xaman_environment.py \
  --corpus-manifest security_ir_artifacts/corpora/xaman-app/source-manifest.json \
  --out security_ir_artifacts/corpora/xaman-app/environment-probe.json
```

Rerunning this command overwrites deterministic JSON. A changed report
after rerun without a corresponding host, corpus pin, or upstream probe
change should block downstream Xaman release-security claims until
reviewed.

## Security Boundary

Accepted uses:

- Evidence input for Xaman-specific proof obligations that depend on the
  declared Node/npm, TypeScript, React Native, iOS, and Android build
  configuration.
- Cross-reference for solver and TypeScript compiler tool paths already
  probed and remediated by PORTAL-CXTP-058 and PORTAL-CXTP-089.
- Documentation of native mobile toolchain capability gaps for later e2e
  and runtime-trace ingestion tasks (PORTAL-CXTP-074).

Rejected uses:

- Treating recorded build assumptions as proof that the Xaman app was
  actually compiled, packaged, or run in this pipeline.
- Treating a missing native toolchain (Xcode, Android SDK, CocoaPods,
  Detox CLI) as a blocking failure of the security-verification proof
  pipeline; those are documented capability gaps for future tasks, not this
  one.
- Accepting a probe report generated against an unpinned branch, tag, or
  short commit SHA as equivalent evidence.
- Accepting a report where content-derived sections are marked
  `content_unavailable` as equivalent to a verified, live-checked-out
  report.
