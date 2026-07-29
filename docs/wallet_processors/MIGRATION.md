# Wallet Processors — Import Map and Schema Migration

Companion to [README.md](./README.md).

## Import map (source → target)

| Legacy / outer concern | Target import path | Status |
| --- | --- | --- |
| Multi-chain processor factory | `ipfs_datasets_py.processors.wallets.get_wallet_processor` | canonical |
| Registry / extras discovery | `ipfs_datasets_py.processors.wallets.default_registry` | canonical |
| Bounded ingest/export API | `ipfs_datasets_py.processors.wallets.api.WalletProcessorAPI` | canonical |
| Normalized records | `ipfs_datasets_py.processors.wallets.models` | canonical |
| Canonical JSON / digests | `ipfs_datasets_py.processors.wallets.canonical` | canonical |
| Dataset export | `ipfs_datasets_py.processors.wallets.export` | canonical |
| World ID pure protocol | `ipfs_datasets_py.processors.wallets.worldcoin` | canonical |
| World Chain ledger | family `world-chain` or `…worldcoin.world_chain` | canonical |
| XRPL ledger | `ipfs_datasets_py.processors.wallets.xrpl` | canonical |
| Xaman payloads | `ipfs_datasets_py.processors.wallets.xaman` | canonical |
| 211-AI application entry | outer `wallet_interface.world_id` thin wrapper | post-cutover re-export |

### Import migration window

1. **Pre-cutover:** application code may still depend on outer-repo ownership;
   target package APIs are available for dual-run validation.
2. **Cutover release:** outer gitlink pins `ipfs_datasets_py` to the released
   commit; wrapper becomes a thin re-export.
3. **Compatibility release (one documented package minor):** wrapper aliases
   remain through package **`0.2.0`** (inclusive); expiry begins at **`0.3.0`**
   as recorded in the outer cutover receipt and
   `WRAPPER_ALIAS_EXPIRY_PACKAGE_VERSION`.
4. **Post-expiry:** aliases removed; imports must use the target package (or
   the non-deprecated thin wrapper surface only).

New code written against this documentation must import the **target** package
paths above. Do not reintroduce a second full World ID implementation in the
outer repository after cutover.

## Schema migration windows

### Ledger records (major v1)

- **Schema id:** `wallet-ledger-record-v1` (+ related ref schemas).
- **Python models:** `ipfs_datasets_py.processors.wallets.models`.
- **JSON Schema:** `docs/schemas/wallet-ledger-record-v1.schema.json`.
- **v1 window rules:**
  - Additive optional fields only via versioned extensions.
  - No renames or type changes of required fields without a major bump.
  - Consumers must ignore unknown extension namespaces they do not understand.

### Export manifests (major v1)

- **Schema id:** `wallet-export-manifest-v1`.
- **JSON Schema:** `docs/schemas/wallet-export-manifest-v1.schema.json`.
- **v1 window rules:**
  - Partition digests (`sha256:…`) and record counts remain authoritative.
  - New optional top-level keys are backward-compatible; unknown keys are ignored.

### Dual-read / dual-write policy

When a future **v2** schema lands:

| Phase | Readers | Writers | Duration |
| --- | --- | --- | --- |
| Dual-read | v1 and v2 | v1 only | Until v2 readers ship |
| Dual-write | v1 and v2 | v1 and v2 | At least one package minor |
| v2-only write | v2 preferred; v1 read retained | v2 | At least one package minor after bump |
| v1 retire | v2 | v2 | After documented deprecation |

At package version **0.2.0** there is **no** v2 bump in flight. The import and
schema migration windows above are stated so consumers can plan against a
stable contract.

## Data migration (exports)

1. Re-export from checkpoints when record shape changes require it.
2. Verify manifests with `verify_manifest` / `load_export_manifest` before
   swapping consumers.
3. Retain prior partition files until the dual-read window closes.
4. Never rewrite historical digests in place; emit new partitions.

## Rollback (summary)

Rollback must restore:

1. **Target package version** (`ipfs_datasets_py` pin or package tree commit).
2. **Outer gitlink / submodule pointer** to the prior package commit.
3. **Wrapper sources** (`wallet_interface.world_id` and related thin-wrapper
   files) to the pre-cutover revision.

Full steps: [README.md § Rollback procedure](./README.md#rollback-procedure).
