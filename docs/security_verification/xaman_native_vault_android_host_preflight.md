# Xaman Native-Vault Android Host Preflight

Task: `PORTAL-CXTP-166`

This preflight verifies only the verifier host's Android tooling and the
prepared `xaman-testnet-api34` AVD. It does not start an emulator, build the
wallet, patch the public source, run a fault-injection test, or capture runtime
evidence.

The generated record is:

- `security_ir_artifacts/corpora/xaman-app/runtime/native-vault-android-host-preflight.json`

Generate it with an explicit local SDK root:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_xaman_native_vault_android_host.py \
  --android-sdk /path/to/android-sdk \
  --java-home /path/to/jdk-17
```

The record contains command versions and binary/configuration digests, but no
absolute host paths, account data, network endpoints, or wallet material. It
requires Android command-line tools, `adb`, the emulator binary, and an
API-34/x86_64/google-APIs AVD with Play Store disabled.
When command-line tools require it, supply the locked JDK 17 with
`--java-home`; its path is not retained in the artifact.

It removes only the Android-tooling uncertainty for `PORTAL-CXTP-163`.
Reviewed runtime capture still requires the independent decision from
`PORTAL-CXTP-156`; the iOS single and batch cases require a separate
macOS/Xcode XCTest host.
