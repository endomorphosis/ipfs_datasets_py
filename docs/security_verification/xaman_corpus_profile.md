# Xaman App Corpus Profile

This profile binds the theorem-prover onboarding corpus for the Xaman XRPL wallet
to a reproducible source manifest. It is source evidence only; it does not claim
that any deployed Xaman build, signing environment, runtime trace, app-store
binary, backend service, or operational control is secure.

## Source Pin

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Required commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest schema: `xaman-corpus-source-manifest/v1`
- Sparse checkout mode: `git sparse-checkout cone`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Manifest file count: `3444`
- Manifest byte count: `73943160`

The fetcher requires `--ref` to be an exact 40-character lowercase commit SHA.
A branch, tag, short SHA, missing sparse path, dirty checkout, missing required
lockfile, missing license file, or missing security disclosure file is a
fail-closed reproduction error.

## Sparse Checkout Scope

The pinned corpus includes the React Native TypeScript source and the build,
test, native-platform, dependency, and disclosure files needed for later
environment probing:

`src`, `android`, `ios`, `e2e`, `scripts`, `patches`, `typings`, `docs`,
`.github`, `.buckconfig`, `.detoxrc.js`, `.eslintrc`, `.prettierrc`,
`.ruby-version`, `.watchmanconfig`, `Gemfile`, `Gemfile.lock`, `LICENSE`,
`Makefile`, `README.md`, `RESPONSIBLE-DISCLOSURE.md`, `Xaman.xctestplan`,
`babel.config.js`, `debug.ts`, `global.ts`, `index.js`, `jest.config.js`,
`jest.setup.js`, `metro.config.js`, `package-lock.json`, `package.json`,
`tsconfig.jest.json`, and `tsconfig.json`.

The manifest records each materialized tracked file with path, size, SHA-256,
Git blob SHA-1, Git mode, and index stage. Root files materialized by cone-mode
sparse checkout, such as `.gitattributes` and `.gitignore`, are also hashed.

## Dependency And Disclosure Evidence

Required dependency lockfile:

- `package-lock.json`

Additional lockfiles found in the sparse corpus:

- `Gemfile.lock`
- `ios/Podfile.lock`

Required license file:

- `LICENSE`

Security disclosure evidence:

- `RESPONSIBLE-DISCLOSURE.md`
- `android/app/src/main/assets/security.txt`
- `ios/security.txt`

Later build-environment probes must treat these files as source evidence inputs,
not as proof that the exact mobile binaries or dependency installation are
reproducible. Native toolchain versions, Node/npm versions, CocoaPods, Gradle,
and e2e runner availability remain separate gates.

## Reproduction Command

Run the pinned reproduction command from the repository root:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/fetch_xaman_corpus.py \
  --repo https://github.com/XRPL-Labs/Xaman-App \
  --ref 942f43876265a7af44f233288ad2b1d00841d5fa \
  --out security_ir_artifacts/corpora/xaman-app/source-manifest.json
```

The command rewrites deterministic JSON. A changed manifest after rerun means
the corpus pin, sparse path set, Git behavior, or remote source has diverged and
must block downstream release-security claims until reviewed.

## Security Boundary

Accepted uses:

- Source-code extractor input for Xaman-specific IR modeling.
- Evidence reference for dependency and build-environment probing.
- Digest-bound source attachment for proof reports, disproof reports, and
  release packets.

Rejected uses:

- Treating source presence as proof of production deployment behavior.
- Accepting a branch, tag, short SHA, or unpinned archive as equivalent evidence.
- Accepting a manifest that lacks file digests, dependency lockfiles, license
  files, or security disclosure files.
- Treating missing optional theorem-prover or mobile-build dependencies as
  success in downstream gates.
