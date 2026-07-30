# Wallet Processor Examples

Offline-first examples for `ipfs_datasets_py.processors.wallets`
(WALPROC-G700).

## Safety contract

| Rule | Enforcement |
| --- | --- |
| Offline by default | Scripts refuse network unless **both** `WALLET_PROCESSORS_ALLOW_NETWORK=1` and `--allow-network` are set |
| No signing / broadcast | Scripts never call sign, broadcast, submit, approve, send, or transfer helpers |
| No real keys or production addresses | Only synthetic fixture addresses (`0x11…`, `0x22…`, fixture digests) |
| No auto-install | Missing extras raise errors; examples do not invoke `pip` |

## Scripts

| Script | What it demonstrates |
| --- | --- |
| `offline_registry_catalog.py` | Lazy registry families, extras, World ID vs World Chain vs WLD labels, Xaman vs XRPL |
| `offline_normalize_and_export.py` | Build synthetic normalized records and export JSONL + manifest |
| `offline_fixture_export_roundtrip.py` | Load shared wallet fixtures and round-trip through export helpers |
| `offline_identity_distinctions.py` | Print explicit World ID / World Chain / WLD and Xaman / XRPL distinctions |

## Run

From the monorepo root (or any cwd; scripts locate the package via imports):

```bash
python ipfs_datasets_py/examples/wallet_processors/offline_registry_catalog.py
python ipfs_datasets_py/examples/wallet_processors/offline_normalize_and_export.py
python ipfs_datasets_py/examples/wallet_processors/offline_fixture_export_roundtrip.py
python ipfs_datasets_py/examples/wallet_processors/offline_identity_distinctions.py
```

Live network is intentionally unsupported in these scripts. Passing
`--allow-network` without the environment variable (or the reverse) still
keeps the process offline and exits with a clear message.

## Validation

```bash
python -m pytest -q ipfs_datasets_py/tests/contract/processors/wallets/test_documented_examples.py
```

## Related docs

- [docs/wallet_processors/README.md](../../docs/wallet_processors/README.md)
- [docs/wallet_processors/CHAINS.md](../../docs/wallet_processors/CHAINS.md)
