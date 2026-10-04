# Xaman Public-Source Native Vault Assessment

Task: `PORTAL-CXTP-162`

This assessment binds public Android, iOS, and TypeScript vault-related source
to the corpus commit `942f43876265a7af44f233288ad2b1d00841d5fa`. Its generated
artifact is:

- `security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json`
- `security_ir_artifacts/corpora/xaman-app/native-vault/rekey-recovery.smt2`

Generate it from a separately pinned source checkout:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_native_vault_assessment.py \
  --source-root /path/to/pinned/xaman-app
```

## Source-Supported Findings

The checked public source contains Android and iOS V2 vault cipher paths using
PBKDF2-derived material and AES-GCM, an Android KeyStore AES-GCM configuration
with randomized encryption, and an iOS keychain record configured as
`WhenUnlockedThisDeviceOnly`. It also contains normal recovery and rekey tests
on both platforms.

The TypeScript passcode helper visibly computes a SHA-512 value and passes it
with a device identifier to `HMAC256`. This is source visibility only. The
assessment does not quantify passcode entropy, offline-guessing resistance, or
the primitive implementations.

## Rekey Model

The public Android and iOS rekey methods create an old-key recovery vault,
delete the primary vault, create a new-key primary vault, and delete recovery
on the success path. The model records three checks, independently executed by
Z3 and CVC5:

1. A successful replacement leaves a primary vault and no recovery vault.
2. A failed replacement after a written snapshot leaves old-key recovery state.
3. The post-delete, recovery-only state is an expected satisfiable witness.

The third result is not a vulnerability finding. It identifies the exact state
that needs Android and iOS fault injection: failure after primary deletion and
before replacement creation must retain an accessible, old-key recovery path.

## Boundaries

This is not a production or vendor-release security result. It does not prove
native primitive correctness, hardware-backed KeyStore availability, Secure
Enclave behavior, OS backup/migration policy, device compromise resistance,
Tangem firmware behavior, or deployed-binary equivalence.

`PORTAL-CXTP-163` remains required to run reviewed Android and iOS fault
injection before this abstract model can support a stronger runtime assumption.
