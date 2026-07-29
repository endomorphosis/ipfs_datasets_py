# Wallet processor fixtures (WALPROC-G090)

Offline, content-addressed fixtures for multi-chain wallet processor
conformance. Every chain lane consumes the shared harness under
`ipfs_datasets_py/tests/contract/processors/wallets/conformance.py` and may
add chain-native golden files under its own subdirectory.

## Layout

| Path | Role |
| --- | --- |
| `manifest.json` | Root inventory: chains, digests lock, provenance |
| `digests.json` | SHA-256 digests of every tracked fixture file |
| `_shared/` | Chain-neutral vectors for the shared conformance suite |
| `worldcoin/`, `xaman/`, `xrpl/`, `ethereum/`, `bitcoin/`, `solana/` | Chain-scoped golden fixtures |

## Integrity

- Fixtures are **immutable** once digested. Content changes require updating
  `digests.json` and the declaring manifest in the same change.
- Every directory has a `manifest.json` with source, license, and provenance.
- Default mode is **offline**. Live network tests stay opt-in elsewhere.

## License / provenance

Synthetic harness vectors under `_shared/` and chain scaffolds are original
test data for this migration (license: Apache-2.0 as the repository default).
Worldcoin and Xaman baselines retain the classification frozen under
WALPROC-G020 (compatibility freeze, offline default).
