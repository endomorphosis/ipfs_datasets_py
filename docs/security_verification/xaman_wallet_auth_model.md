# Xaman Wallet Authentication Model

Task: `PORTAL-CXTP-064`

This model records reviewed account, vault, storage, authentication, custody, and signing facts for the pinned Xaman React Native source corpus. The machine-readable artifact is `security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json`.

## Source Boundary

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Coverage artifact: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`

The checked-in coverage artifact is manifest-only for this corpus, so this task reviewed the manifest-pinned source files directly at the exact commit and bound each modeled fact to path, line range, and SHA-256 evidence. Native module internals, third-party cryptographic libraries, Tangem firmware, deployed binaries, backend behavior, and runtime traces are not proved by this artifact.

## Modeled Facts

### Account Storage

`src/store/repositories/account.ts` models the main account custody split:

- Full-access software accounts require a private key, an encryption key, and an account public key before creation.
- The private key is stored through `Vault.create(account.publicKey, privateKey, encryptionKey)` before the Realm account record is created.
- Readonly and Tangem accounts are created without storing a software private key through this repository path.
- Downgrading to readonly purges the account vault entry when present and changes the account to `Readonly` with `EncryptionLevels.None`.
- Purging a full-access account purges its vault entry before deleting the account object.

`src/store/models/objects/account.ts` and `src/store/models/objects/accountDetails.ts` store public and ledger-derived account state: address, label, public key, access level, encryption level, optional additional metadata, balance, sequence, regular key, flags, and trust lines. The reviewed model did not find private key material in those account model fields.

### Vault And Storage

`src/common/libs/vault.ts` is a TypeScript facade over React Native `VaultManagerModule`. The modeled operations include vault create, open, existence check, storage encryption key check/fetch, rekey, purge, and clear storage.

`src/store/storage.ts` opens Realm with an encryption key obtained from `Vault.getStorageEncryptionKey()`. If a Realm file exists but the vault does not have the encryption key, storage initialization fails with `Realm file decryption failed`. The vault facade checks that the returned storage key is a 128-character hex string decoded to 64 bytes before returning it to Realm.

### Authentication Overlays

`src/services/AuthenticationService.ts` tracks lock state, passcode authentication, biometric authentication, auto-lock checks, and brute-force reset behavior.

- Passcode authentication checks backoff state, hashes the entered passcode with `CoreRepository.hashPasscode`, compares it to stored settings, unlocks on success, and increments failed-attempt state on failure.
- Failed attempts are throttled starting at attempt 6, with backoff values up to 120 minutes.
- If purge-on-bruteforce is enabled, attempt 10 warns the user and attempts greater than 10 reset the app by clearing vault storage, wiping Realm storage, and exiting.
- Auto-lock shows the lock overlay and changes state to `LOCKED` when last-unlock state is missing, elapsed realtime moves backward, or the configured auto-lock interval has elapsed.
- Biometric availability requires a non-`None` biometric method and a successful device sensor check. Biometric authentication is rejected while the app is not active, and biometric enrollment-change errors disable the stored biometric method.

`src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx` presents a six-digit passcode input and exposes biometric authorization only when biometrics are available and the caller passed `canAuthorizeBiometrics`.

`src/screens/Overlay/PassphraseAuthentication/PassphraseAuthenticationOverlay.tsx` verifies an account passphrase by calling `Vault.open(account.publicKey, passphrase)`. It calls success only after a private key is returned, and it clears the local `privateKey` variable before success.

### Signing Preconditions

`src/common/libs/ledger/mixin/Sign.mixin.ts` performs pre-vault signing checks:

- Rejects missing account, duplicate signing, unsupported transaction type for the current network, missing fee, inability to set account sequence, and aborted transactions.
- Shows `AppScreens.Overlay.Vault` after the preconditions pass.
- Rejects signed callback results that lack signed transaction data, signer public key, sign method, or a transaction id for non-pseudo transactions.
- Requires a `SignedBlob`, no prior submit result, no in-progress submit flag, and no abort flag before ledger submission.

`src/screens/Overlay/Vault/VaultOverlay.tsx` selects usable signers and authentication method:

- Readonly accounts without usable regular-key signing are rejected.
- Full-access accounts can sign directly.
- Readonly accounts can sign only through an imported full-access regular-key account.
- If both master and regular-key signers are available, the user is routed through signer selection.
- `EncryptionLevels.Passcode` routes to `PasscodeMethod`, `Passphrase` routes to `PassphraseMethod`, and `Physical` routes to `TangemMethod`.

`PasscodeMethod` passes the computed passcode hash as the vault encryption key after passcode success. After biometric success it passes the stored passcode hash as the vault encryption key. `PassphraseMethod` requires a nonempty passphrase and passes it as the vault encryption key. `TangemMethod` obtains Tangem card metadata from account additional info and signs through the Tangem SDK path instead of opening the software vault.

## NOT_MODELED Gaps

The artifact marks the following as `NOT_MODELED`:

- Native `VaultManagerModule` implementation details: platform keychain/keystore policy, cipher mode, hardware backing, migration, and memory-zeroization behavior.
- Native biometric security properties: prompt policy, enrollment binding, secure hardware behavior, and spoof resistance.
- Passcode KDF strength: `CoreRepository.hashPasscode` algorithm, salt handling, parameter strength, and stored-passcode protection.
- Third-party signing correctness: `xrpl-accountlib`, Tangem SDK, Tangem firmware, raw signing completion, and XRPL signing test-vector coverage.
- Source coverage extractor completeness for `src/screens/Overlay/Vault/**`: the wallet-auth model reviewed these manifest-pinned files directly, but the prior coverage extractor does not classify that root.
- Runtime and deployed binary equivalence: no app-store binary, native runtime trace, backend service, or reproducible build evidence is modeled here.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_wallet_auth_model.py -q
```

The tests validate required fact categories, manifest-bound evidence hashes, source-input coverage, explicit `NOT_MODELED` gaps, and documentation references.
