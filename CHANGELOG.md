# Changelog — ipfs_datasets_py

All notable package-level changes for the `ipfs_datasets_py` distribution are
documented in this file. Detailed historical notes also exist under
`docs/CHANGELOG.md`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-07-29

### Added

#### Wallet processors (WALPROC-G700 / WALPROC-031)

- **Package documentation** under `docs/wallet_processors/`:
  - `README.md` — API/schema reference, extras, import map, schema migration
    windows, privacy guidance, version matrix, and rollback procedure covering
    **target package version** and **outer gitlink/wrapper**.
  - `CHAINS.md` — distinguishes **World ID** (protocol), **World Chain**
    (ledger), and **WLD** (asset); distinguishes **Xaman** (payload surface)
    from **XRPL** (classic ledger).
  - `MIGRATION.md` — import map and schema dual-read windows.
  - `COMPATIBILITY.md` — version matrix, optional extras, intentional
    capability gaps (no signing/broadcast, no SIWE bootstrap, no auto-install).
  - `API.md` — verified public API summary for registry, models, export, and
    bounded facade.
- **Offline examples** under `examples/wallet_processors/`:
  - Registry catalog, synthetic normalize/export, fixture round-trip, and
    identity distinction scripts.
  - Network access requires **both** `WALLET_PROCESSORS_ALLOW_NETWORK=1` and
    `--allow-network`; scripts never sign or broadcast.
- **Contract tests** at
  `tests/contract/processors/wallets/test_documented_examples.py` execute every
  documented example offline and assert acceptance criteria for docs/examples.
- README cross-links for wallet processor docs and extras.

### Compatibility

- Ledger record schema major **v1** and export manifest schema major **v1**
  remain the supported write formats.
- Import migration window: outer thin-wrapper aliases remain through package
  **`0.2.0`** (inclusive) and are scheduled for removal starting at **`0.3.0`**
  (WALPROC-G710 cutover receipt / `WRAPPER_ALIAS_EXPIRY_PACKAGE_VERSION`).
  New code imports `ipfs_datasets_py.processors.wallets`.
- Rollback restores package pin/commit **and** outer gitlink +
  `wallet_interface.world_id` thin wrapper (see
  `docs/wallet_processors/README.md#rollback-procedure` and outer
  `docs/runbooks/WALLET_PROCESSOR_CUTOVER.md`).

### Notes

- Synchronizing outer operator planning docs under `docs/planning/` is
  operator-owned control-plane work and is not part of this package change.
- Historical documentation changelog entries remain in `docs/CHANGELOG.md`.

## Earlier history

See [docs/CHANGELOG.md](docs/CHANGELOG.md) for pre-0.2.0 documentation and
worker session notes.
