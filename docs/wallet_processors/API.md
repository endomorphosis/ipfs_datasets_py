# Wallet Processors — API Reference Summary

Quick reference for the verified public surfaces used by package docs and
offline examples. For protocol contracts see
[WALLET_PROCESSOR_PROTOCOL_ADR.md](../architecture/WALLET_PROCESSOR_PROTOCOL_ADR.md).

## Registry

```python
from ipfs_datasets_py.processors.wallets import (
    default_registry,
    get_wallet_processor,
    OptionalDependencyError,
    UnknownProcessorError,
    AmbiguousNetworkError,
)

reg = default_registry()
reg.list_families()                 # tuple[str, ...]
reg.list_specs()                    # ProcessorFamilySpec rows
reg.get_spec("ethereum")            # static spec (no chain import)
reg.capabilities_for("bitcoin")     # Capabilities without loading package
reg.required_extra("xaman")         # "wallets-xaman"
# get_wallet_processor("xrpl", network="xrpl-mainnet")  # loads extra
```

## Models (construct offline)

```python
from datetime import datetime, timezone
from ipfs_datasets_py.processors.wallets.models import (
    ChainRef, AccountRef, AccountKind, AssetRef, AssetKind,
    ExactAmount, LedgerPosition, Provenance, Finality,
    TransactionRecord, TransferRecord, TransferKind, TransactionStatus,
)

chain = ChainRef(
    namespace="eip155",
    network="ethereum-mainnet",
    chain_id="1",
    genesis_hash="0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",
)
```

Addresses in documentation and examples use **synthetic** fixtures only
(for example repeating `0x11…` / `0x22…` patterns). Never paste production
keys, seed phrases, or live mainnet addresses into examples.

## Export

```python
from pathlib import Path
from ipfs_datasets_py.processors.wallets.export import (
    write_jsonl, read_jsonl, build_export_manifest, verify_manifest,
)

partition = write_jsonl(records, Path("part-000.jsonl"))
# build_export_manifest(...) → ExportManifest
```

## Bounded API facade

```python
from ipfs_datasets_py.processors.wallets.api import (
    WalletProcessorAPI,
    ScanBounds,
    ExportMode,
    WalletExportRequest,
)
# WalletProcessorAPI methods: ingest wallet scope, ledger range, export, status.
# Forbidden verbs (sign/broadcast/submit/...) are rejected at the boundary.
```

## World ID helpers (protocol only)

```python
from ipfs_datasets_py.processors.wallets.worldcoin import (
    normalize_idkit_response,
    redact_world_id_payload,
    hash_to_field_hex,
)
# Signing helpers exist for RP request vectors in tests/fixtures; examples
# must not demonstrate live signing with real keys.
```

## Network opt-in

Live provider calls are out of scope for the documented examples. Any future
live demo must require **both**:

- environment variable `WALLET_PROCESSORS_ALLOW_NETWORK=1`
- CLI flag `--allow-network`

Without both, examples stay offline.
