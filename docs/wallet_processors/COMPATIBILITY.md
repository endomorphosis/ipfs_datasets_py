# Wallet Processors — Compatibility, Extras, and Capability Gaps

Companion to [README.md](./README.md).

## Version matrix

| Component | Constraint | Source of truth |
| --- | --- | --- |
| Package version | `0.2.0` | `ipfs_datasets_py/pyproject.toml` |
| Python | `>=3.12` | package `requires-python` |
| Ledger schema major | v1 | `docs/schemas/wallet-ledger-record-v1.schema.json` |
| Export schema major | v1 | `docs/schemas/wallet-export-manifest-v1.schema.json` |
| Wallet extras | `wallets`, `wallets-*`, `wallets-all` | `pyproject.toml` + `setup.py` (must stay synchronized) |
| Outer monorepo gitlink | pin to package commit at cutover | outer `data/wallet_processor_migration/release/cutover-receipt.json` + `docs/runbooks/WALLET_PROCESSOR_CUTOVER.md` |
| Wrapper alias compatibility | package `0.2.0` (inclusive) | outer `wallet_interface.world_id.WRAPPER_ALIAS_COMPATIBILITY_PACKAGE_VERSION` |
| Wrapper alias expiry | package `0.3.0` (removal starts) | outer `wallet_interface.world_id.WRAPPER_ALIAS_EXPIRY_PACKAGE_VERSION` + cutover receipt |

## Optional dependency extras

| Extra | Loads | Notes |
| --- | --- | --- |
| `wallets` | shared kernel | No chain SDK |
| `wallets-worldcoin` | World ID + World Chain package | `eth-hash[pycryptodome]`, `eth-keys` |
| `wallets-ethereum` | EVM ledger | raw JSON-RPC; no `web3.py` |
| `wallets-xrpl` | XRPL ledger | raw HTTP JSON-RPC; no `xrpl-py` |
| `wallets-xaman` | Xaman payloads | composed on XRPL; no `xumm-sdk` |
| `wallets-bitcoin` | Bitcoin UTXO | raw Esplora/REST style; no bitcoinlib |
| `wallets-solana` | Solana | raw JSON-RPC; no `solana`/`solders` |
| `wallets-all` | union | convenience only |

Install documentation and SBOM rationale:
[WALLET_PROCESSOR_DEPENDENCIES.md](../dependencies/WALLET_PROCESSOR_DEPENDENCIES.md).

## Capability gaps (documented, intentional)

These are **capability gaps**, not incomplete TODOs for the first release:

1. **Custody / signing / broadcast** — permanently denied without a new threat
   review and objective. No example or public API exposes sign/broadcast.
2. **World ID ≠ World Chain ≠ WLD** — three distinct concepts; see
   [CHAINS.md](./CHAINS.md).
3. **Xaman ≠ XRPL** — payload surface vs classic ledger; network selectors are
   ambiguous without `family=`.
4. **No SIWE bootstrap** on World Chain in current metadata.
5. **No automatic dependency install** — missing extras raise
   `OptionalDependencyError`.
6. **No live network by default** — examples and benchmarks require explicit
   network opt-in.
7. **Raw payloads omitted by default** — opt-in with bounded custody.
8. **Chain SDKs excluded** from extras to keep the SBOM minimal and transport
   policy uniform.

## Compatibility promises

- Importing the wallets package root does not open sockets or load chain
  extras.
- Normalized v1 records round-trip through JSONL export with stable digests for
  identical content.
- Registry capability catalog is inspectable without constructing processors.
- Rollback restores package version **and** outer gitlink/wrapper (see
  [README.md](./README.md#rollback-procedure)).
