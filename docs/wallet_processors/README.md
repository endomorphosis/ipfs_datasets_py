# Wallet Processors — Package Documentation

**Status:** release documentation for WALPROC-G700  
**Package:** `ipfs_datasets_py`  
**Module root:** `ipfs_datasets_py.processors.wallets`  
**Package version documented here:** `0.2.0`  
**Release owner:** wallet-processors/release (single owner after chain docs land)

This directory is the **package-owned** reference for multi-chain wallet
processors: public APIs, schemas, optional dependency extras, import map,
schema migration windows, privacy guidance, version matrix, and rollback
procedure.

Operator control-plane planning documents under `docs/planning/` in the outer
repository remain operator-owned and are **not** edited by this package release
track.

---

## Table of contents

1. [Mission and safety boundary](#mission-and-safety-boundary)
2. [Install and optional extras](#install-and-optional-extras)
3. [Public API surface](#public-api-surface)
4. [Schemas and record models](#schemas-and-record-models)
5. [Chain identity map (World ID / World Chain / WLD; Xaman / XRPL)](#chain-identity-map)
6. [Capability catalog and gaps](#capability-catalog-and-gaps)
7. [Import map and compatibility](#import-map-and-compatibility)
8. [Schema migration windows](#schema-migration-windows)
9. [Privacy guidance](#privacy-guidance)
10. [Examples (offline-first)](#examples-offline-first)
11. [Version matrix](#version-matrix)
12. [Rollback procedure](#rollback-procedure)
13. [Related documents](#related-documents)

---

## Mission and safety boundary

Wallet processors **ingest, normalize, checkpoint, and export** public-ledger
and identity evidence. They are **read-only data processors**.

| Allowed | Forbidden (denied capabilities) |
| --- | --- |
| Wallet-centric history and finite ledger-range scans | Custody of seeds / private keys |
| Normalization to versioned ledger records | Transaction construction |
| Checkpoint / finality / reorg recovery (where declared) | Approval, signing, submission |
| Dataset export (JSONL / Parquet) with manifests | Broadcast / transfer / send verbs |
| Opaque secret **references** (never inline secrets) | Auto-install of missing extras |

Importing `ipfs_datasets_py.processors.wallets` performs **no network I/O**,
does not resolve secrets, and does not load optional chain SDKs.

---

## Install and optional extras

Base package (Python **3.12+**):

```bash
pip install ipfs_datasets_py
# or, from a checkout:
pip install -e ./ipfs_datasets_py
```

Wallet extras (never auto-installed at import time):

| Extra | Purpose |
| --- | --- |
| `wallets` | Shared multi-chain processor kernel |
| `wallets-worldcoin` | World ID protocol + World Chain composition |
| `wallets-ethereum` | Ethereum / EVM public-ledger ingestion |
| `wallets-xrpl` | XRPL classic-account public-ledger ingestion |
| `wallets-xaman` | Xaman payload processing composed on XRPL |
| `wallets-bitcoin` | Bitcoin UTXO public-ledger ingestion |
| `wallets-solana` | Solana public-ledger ingestion |
| `wallets-all` | Union of every wallet extra above |

```bash
pip install "ipfs_datasets_py[wallets]"
pip install "ipfs_datasets_py[wallets-worldcoin]"
pip install "ipfs_datasets_py[wallets-ethereum]"
pip install "ipfs_datasets_py[wallets-xrpl]"
pip install "ipfs_datasets_py[wallets-xaman]"
pip install "ipfs_datasets_py[wallets-bitcoin]"
pip install "ipfs_datasets_py[wallets-solana]"
pip install "ipfs_datasets_py[wallets-all]"
```

Full pin tables, license/SBOM rationale, and crypto selection live in
[WALLET_PROCESSOR_DEPENDENCIES.md](../dependencies/WALLET_PROCESSOR_DEPENDENCIES.md).

Missing extras raise `OptionalDependencyError` naming the pip extra. Processors
**never** call `pip` or package managers.

---

## Public API surface

### Package root (lazy, dependency-light)

```python
from ipfs_datasets_py.processors.wallets import (
    get_wallet_processor,
    default_registry,
    WalletProcessorRegistry,
    OptionalDependencyError,
    UnknownProcessorError,
    BoundedRequest,
    OperationContext,
    RequestLimits,
    Capability,
)
```

- `default_registry()` / `get_wallet_processor(family, ...)` — lazy factory.
  Chain modules load only when a family is constructed.
- Errors name the missing extra; they do not auto-install.

### Bounded integration facade

```python
from ipfs_datasets_py.processors.wallets.api import (
    WalletProcessorAPI,
    WalletIngestRequest,
    LedgerRangeIngestRequest,
    WalletExportRequest,
    ScanBounds,
    ExportMode,
    TrustPolicy,
    TrustLevel,
)
```

`WalletProcessorAPI` is the shared surface for Python, CLI, and MCP. Every scan
requires finite item/page/request/byte/time/retry bounds. There are **no**
sign, broadcast, submit, approve, send, or transfer verbs on this facade.

### Normalized models and export

```python
from ipfs_datasets_py.processors.wallets.models import (
    ChainRef,
    AccountRef,
    AssetRef,
    TransactionRecord,
    TransferRecord,
    ExportManifest,
    Finality,
)
from ipfs_datasets_py.processors.wallets.export import (
    WalletDatasetExporter,
    write_jsonl,
    read_jsonl,
    build_export_manifest,
    verify_manifest,
    ExportFormat,
)
from ipfs_datasets_py.processors.wallets.canonical import (
    canonical_json,
    content_digest,
    deterministic_id,
)
```

### CLI and MCP (thin wrappers)

- CLI: `ipfs_datasets_py.cli.wallets`
- MCP tools: `ipfs_datasets_py.mcp_server.tools.wallet_processor_tools`

Both wrap the same typed requests and sanitized receipts. Untrusted MCP callers
are constrained by `TrustPolicy` allowlists.

---

## Schemas and record models

JSON Schema artifacts (draft 2020-12):

| Schema file | Role |
| --- | --- |
| [`docs/schemas/wallet-ledger-record-v1.schema.json`](../schemas/wallet-ledger-record-v1.schema.json) | Chain-neutral ledger records (block, tx, transfer, balance, UTXO, token account, contract event) |
| [`docs/schemas/wallet-export-manifest-v1.schema.json`](../schemas/wallet-export-manifest-v1.schema.json) | Export partition manifests and digests |

Python models in `processors.wallets.models` use versioned schema constants
(`wallet-chain-ref-v1`, `wallet-account-ref-v1`, `wallet-ledger-record-v1`,
`wallet-export-manifest-v1`, …). Chain-specific fields belong only inside
`VersionedExtension` namespaces—never as free-form top-level keys that would
break cross-chain consumers.

Canonical encoding (`canonical_json` / `content_digest`) produces deterministic
ids (`urn:wallet:…:sha256:…`) for content-addressed storage and export
integrity.

---

## Chain identity map

### World ID vs World Chain vs WLD

These three names are **not interchangeable**:

| Concept | What it is | Processor family / module | Notes |
| --- | --- | --- | --- |
| **World ID** | Privacy-preserving proof-of-personhood protocol (IDKit credentials, RP signing, nullifier commitments, developer-portal verification) | Family `worldcoin` (`wallets-worldcoin`); modules under `processors.wallets.worldcoin` (`config`, `idkit`, `signing`, `proofs`, `bindings`, `developer_portal`) | No public-ledger scan surface of its own; no unique chain-id networks in the registry. Raw nullifiers and proofs are redacted before public export. |
| **World Chain** | OP-Stack EVM L2 public ledger (chain ids `480` mainnet, `4801` Sepolia) | Family `world-chain` (aliases `worldchain`, `wld-chain`); `processors.wallets.worldcoin.world_chain` | Composes over Ethereum/EVM ledger processing. Block depth alone is **not** finality. |
| **WLD** | ERC-20 asset on World Chain (not an identity protocol and not a chain) | Catalogued in `processors.wallets.worldcoin.assets` | Mainnet WLD contract is bound to chain id `480` only. Sepolia must never silently reuse the mainnet WLD address. |

Registry aliases:

- World ID package: `worldcoin`, `world-id`, `worldid`, `wld-id`
- World Chain ledger: `world-chain`, `worldchain`, `wld-chain`

### Xaman vs XRPL

| Concept | What it is | Processor family | Notes |
| --- | --- | --- | --- |
| **XRPL** | XRP Ledger classic accounts, payments, trust lines, ledgers | Family `xrpl` (`wallets-xrpl`) | Public-ledger history and finite ledger-range scans. Destination tags and memos are privacy-sensitive; free-form memo retention is opt-in and size-bounded. |
| **Xaman** | Wallet application / payload API surface over XRPL settlement | Family `xaman` (alias `xumm`); `wallets-xaman` | Composes XRPL for settlement correlation. Processes payload lifecycle and assurance links. Does **not** approve, sign, or submit payloads. |

Selecting network `xrpl-mainnet` without an explicit family is **ambiguous**
across `xrpl` and `xaman`; pass `family="xrpl"` or `family="xaman"`.

### Other families

| Family | Namespace | Extra | Model |
| --- | --- | --- | --- |
| `bitcoin` | `bip122` | `wallets-bitcoin` | UTXO |
| `ethereum` | `eip155` | `wallets-ethereum` | Account / logs |
| `solana` | `solana` | `wallets-solana` | Account / signatures |

See [CHAINS.md](./CHAINS.md) for expanded per-chain notes.

---

## Capability catalog and gaps

Inspect without loading chain packages:

```python
from ipfs_datasets_py.processors.wallets import default_registry

reg = default_registry()
for family in reg.list_families():
    caps = reg.capabilities_for(family)
    print(family, sorted(f.value for f in caps.features))
```

### Declared features (summary)

| Family | Wallet history | Ledger range | Balances | Token transfers | Reorg recovery | Dataset export | Finality | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bitcoin | yes | yes | yes | — | yes | yes | yes | UTXO model |
| ethereum | yes | yes | yes | yes | — | yes | yes | + contract events, internals, raw payloads |
| solana | yes | yes | yes | yes | — | yes | yes | + raw payloads |
| xrpl | yes | yes | yes | yes | yes | yes | yes | classic accounts |
| xaman | yes | — | — | — | — | yes | yes | payload surface; settlement via XRPL |
| worldcoin | — | — | — | — | — | yes | yes | World ID protocol + package composition |
| world-chain | yes | yes | — | yes | — | yes | yes | composes ethereum; not depth-only finality |

### Explicit capability gaps (not bugs)

1. **No signing / broadcast / submit / approve** on any family (`supports_sign`,
   `supports_broadcast`, `supports_submit`, `supports_approve` remain false).
2. **No SIWE bootstrap** on World Chain metadata
   (`siwe_bootstrap_supported: false`).
3. **World ID is not a ledger scanner** — use `world-chain` for public-ledger
   history on World Chain.
4. **Xaman is not a substitute for XRPL ledger range** — use `xrpl` for
   classic account/ledger pagination; use `xaman` for payload lifecycle.
5. **Chain SDKs are not selected** (`web3.py`, `xrpl-py`, `solana`/`solders`,
   `xumm-sdk`, `python-bitcoinlib` are rejected from wallet extras).
6. **Raw payload custody is omitted by default** — opt-in with explicit
   `RawPayloadPolicy` and finite custody ceilings.
7. **Live provider smoke is disabled by default** — requires endpoint allowlist
   **and** explicit operator network approval.

---

## Import map and compatibility

| Consumer concern | Target import | Notes |
| --- | --- | --- |
| Lazy factory | `ipfs_datasets_py.processors.wallets` | `get_wallet_processor`, registry |
| Typed API | `…processors.wallets.api` | Shared with CLI/MCP |
| Models / schemas | `…processors.wallets.models` | Versioned records |
| Canonical ids | `…processors.wallets.canonical` | Deterministic digests |
| Export | `…processors.wallets.export` | JSONL / Parquet + manifests |
| World ID protocol | `…processors.wallets.worldcoin` | Pure protocol + composition |
| World Chain ledger | `…processors.wallets.worldcoin.world_chain` | Or family `world-chain` |
| XRPL ledger | `…processors.wallets.xrpl` | Classic accounts |
| Xaman payloads | `…processors.wallets.xaman` | Composed on XRPL |
| 211-AI thin wrapper | outer `wallet_interface.world_id` | After cutover: re-exports target package; no dual ownership |

**Import migration window:** for one documented compatibility release after
cutover, outer-repo wrapper aliases may re-export the target package symbols.
New application code must import from `ipfs_datasets_py.processors.wallets`
(or the typed thin wrapper). Dual-implementation paths are not supported after
the alias expiry version stated in the cutover receipt.

Expanded import tables: [MIGRATION.md](./MIGRATION.md).

---

## Schema migration windows

| Artifact | Current major | Compatibility rule |
| --- | --- | --- |
| Ledger records | v1 (`wallet-ledger-record-v1` / Python models) | Additive fields only inside versioned extensions during the v1 window. Breaking field renames require a v2 schema file and dual-read period. |
| Export manifests | v1 (`wallet-export-manifest-v1`) | Partition digests and record counts remain stable. New optional partition fields may appear; consumers must ignore unknown keys. |
| API receipts / status | `wallet-api-receipt-v1`, `wallet-api-status-v1` | Sanitized; no record payloads or secrets. |
| Fixture harness | `tests/fixtures/wallets/**/manifest.json` | Offline golden vectors; digests pinned in `digests.json`. |

**Schema migration window policy:** when a major bumps (v1 → v2), the prior
major remains readable for **at least one package minor release** after the
bump lands. Writers emit only the new major once the dual-write gate closes.
Document the dual-read start/end package versions in this file and
`CHANGELOG.md` when a bump occurs.

No v1 → v2 bump is in flight at package version `0.2.0`.

---

## Privacy guidance

1. Treat public ledger data as **potentially personal**.
2. Prefer opaque digests and commitments over raw nullifiers, proofs, JWTs, and
   signatures in public projections.
3. Omit free-form XRPL memos, Xaman instructions, and calldata by default.
4. Never log secret values, full secret-manager paths, or complete provider URLs
   (use `endpoint_fingerprint`).
5. Export default mode is **finalized**; provisional/raw modes are explicit.
6. See the threat model:
   [WALLET_PROCESSOR_THREAT_MODEL.md](../security/WALLET_PROCESSOR_THREAT_MODEL.md).

---

## Examples (offline-first)

Documented examples live under
[`examples/wallet_processors/`](../../examples/wallet_processors/).

Contract:

- Default execution is **offline** (fixtures + synthetic records only).
- Live network access requires **explicit** opt-in:
  environment `WALLET_PROCESSORS_ALLOW_NETWORK=1` **and** CLI flag
  `--allow-network`.
- Examples **must not** sign, broadcast, submit, or embed real private keys /
  seed phrases / production addresses.

Validate:

```bash
python -m pytest -q ipfs_datasets_py/tests/contract/processors/wallets/test_documented_examples.py
```

---

## Version matrix

| Component | Version / pin | Role |
| --- | --- | --- |
| `ipfs_datasets_py` package | `0.2.0` (see `pyproject.toml`) | Target owner of wallet processors |
| Python | `>=3.12` | Wallet processor runtime |
| Ledger record schema | v1 | Normalized records |
| Export manifest schema | v1 | Dataset export integrity |
| World ID golden vectors | `tests/fixtures/wallets/worldcoin/golden_vectors.json` | Crypto / protocol parity |
| Outer 211-AI monorepo | gitlink / submodule pin to package commit | Cutover surface (operator runbook) |
| Thin wrapper | `wallet_interface.world_id` | Post-cutover re-export only |

---

## Rollback procedure

Rollback is a **two-layer** operation: target package version **and** outer
gitlink / wrapper.

### 1. Target package version

1. Identify the last known-good `ipfs_datasets_py` version or commit recorded in
   the cutover receipt (or prior release tag).
2. Pin the package install to that version:
   ```bash
   pip install "ipfs_datasets_py==<prior-version>"
   # or, for a monorepo checkout, reset the package tree to the prior commit
   git -C ipfs_datasets_py checkout <prior-package-commit>
   ```
3. Re-run offline validation:
   ```bash
   python -m pytest -q ipfs_datasets_py/tests/contract/processors/wallets/
   ```

### 2. Outer gitlink / wrapper

1. Restore the outer repository’s **gitlink / submodule pointer** for
   `ipfs_datasets_py` to the prior commit SHA recorded before cutover.
2. Restore `wallet_interface/world_id.py` (and any related thin-wrapper files)
   to the pre-cutover revision so the application no longer depends on the
   failed target pin.
3. Confirm wrapper ownership tests still pass against the restored layout:
   ```bash
   python -m pytest -q tests/test_world_id_wrapper_ownership.py
   ```
4. Do **not** delete exported datasets during rollback; manifests and partition
   digests remain valid for the schema major they were written under.

### 3. Compatibility aliases

If the failure occurs during the one-release alias window, re-enable the prior
wrapper aliases only at the **documented alias expiry version** boundary—never
silently reintroduce a second full implementation.

Detailed operator cutover steps live in the outer-repo runbook
`docs/runbooks/WALLET_PROCESSOR_CUTOVER.md` (written by the cutover goal). This
package document states the **package + gitlink** rollback contract required by
WALPROC-G700.

---

## Related documents

| Document | Topic |
| --- | --- |
| [CHAINS.md](./CHAINS.md) | Expanded World ID / World Chain / WLD and Xaman / XRPL notes |
| [MIGRATION.md](./MIGRATION.md) | Import map, schema windows, dual-read policy |
| [COMPATIBILITY.md](./COMPATIBILITY.md) | Version matrix, extras, capability gaps |
| [WALLET_PROCESSOR_PROTOCOL_ADR.md](../architecture/WALLET_PROCESSOR_PROTOCOL_ADR.md) | Domain protocol ADR |
| [WALLET_PROCESSOR_DEPENDENCIES.md](../dependencies/WALLET_PROCESSOR_DEPENDENCIES.md) | Optional extras pins |
| [WALLET_PROCESSOR_THREAT_MODEL.md](../security/WALLET_PROCESSOR_THREAT_MODEL.md) | Threat model |
| [WALLET_PROCESSOR_RUNBOOK.md](../operations/WALLET_PROCESSOR_RUNBOOK.md) | Operations / metrics |
| [examples/wallet_processors/](../../examples/wallet_processors/) | Offline examples |
| Package [CHANGELOG.md](../../CHANGELOG.md) | Release notes |

---

*WALPROC-G700 / WALPROC-031 — packaging, schemas, examples, and migration
documentation for multi-chain wallet processors.*
