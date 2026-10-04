# Xaman Native-Vault iOS Host Preflight

Task: `PORTAL-CXTP-168`

This preflight verifies only the verifier host’s iOS/Xcode tooling and source
presence required for a future native-vault fault-injection run. It does not start
simulators, build Xaman, patch the public source, run tests, or capture runtime
evidence.

The generated record is:

- `security_ir_artifacts/corpora/xaman-app/runtime/native-vault-ios-host-preflight.json`

Generate it with an explicit source root:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_xaman_native_vault_ios_host.py \
  --source-root /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app
```

The record contains command version observations and binary digests for:

- `xcodebuild`
- `xcrun`
- resolved `simctl`

It never stores absolute file paths. It checks only:

- macOS/Darwin host
- explicit `xcodebuild` + `xcrun`
- `xcrun --find simctl`
- simulator availability (counted only)
- at least one iOS runtime
- pinned source commit with clean checkout
- required Xaman Android/iOS source markers used by native rekey fault testing

It is a host-readiness lane only. It does not claim vendor release or production
security.
