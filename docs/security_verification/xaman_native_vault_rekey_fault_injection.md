# Xaman Native-Vault Rekey Fault-Injection Contract

Preparation task: `PORTAL-CXTP-165`
Runtime task: `PORTAL-CXTP-163`

The public Android and iOS sources create an old-key recovery vault, delete the
primary vault, create the replacement under the new key, and then remove the
recovery vault. The source model therefore requires controlled failure at both
the replacement creation call after primary deletion and the final recovery
cleanup. Existing public tests exercise successful rekey and recovery, but not
these intermediate failure paths.

The prepared artifacts are:

- `security_ir_artifacts/corpora/xaman-app/native-vault/fault-injection-plan.json`
- `security_ir_artifacts/corpora/xaman-app/runtime/native-vault-rekey-fault-injection-template.json`

Generate them only from the content-addressed public-source assessment:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/prepare_xaman_native_vault_fault_injection.py
```

## Required Runtime Cases

The actual evidence report must cover twelve test-only cases. Each platform
must cover two single-rekey failures plus first- and later-vault failures for
both fault phases in a batch rekey. This distinction is required because the
public batch implementation replaces each vault in sequence after all recovery
snapshots are written. Replacement-write failure after primary deletion must
record an absent primary, recovery present, old-key recovery, and no new-key
primary access. Recovery-cleanup failure after a successful replacement must
record a rejected operation, a new-key primary, and retained old-key recovery.
In every case the new key must not open the old-key recovery vault.

The tests must use ephemeral non-wallet fixtures. Reports must retain only
SHA-256 evidence digests; no passcodes, key material, account identifiers,
payloads, transaction blobs, credentials, raw endpoints, raw logs, or unsafe
screenshots are allowed.

## Execution Gate

`PORTAL-CXTP-156` must provide a valid, unexpired independent decision of
`ALLOW_VERIFIER_ONLY_RUNTIME_CAPTURE`. Android execution additionally requires
a fresh verifier-only debug emulator and working `adb`, `emulator`, and
`sdkmanager`. iOS execution requires an isolated macOS/Xcode XCTest host.

`PORTAL-CXTP-166` records the prepared Android host with explicitly supplied
SDK and locked-JDK paths; the tools are not assumed to be on global `PATH`. This
Linux host cannot run iOS XCTest. The contract is deliberately prepared without
treating platform readiness as a fault-injection result.

## Boundary

A completed report is limited to the reviewed public-source verifier build. It
does not prove vendor-release equivalence, production wallet security, native
cryptographic primitive correctness, hardware-backed key availability, Secure
Enclave behavior, or recovery behavior under a compromised device. A retained
old-key recovery vault after cleanup failure is a runtime test outcome to
triage, not a vulnerability finding by itself.
