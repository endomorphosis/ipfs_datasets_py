# Wallet Processor Optional Dependencies

Status: selected for WALPROC-G050 / WALPROC-010  
Package: `ipfs_datasets_py`  
Authority: `pyproject.toml` `[project.optional-dependencies]` and `setup.py`
`extras_require` (must stay synchronized)  
Do not auto-install anything from this document at import time.

## Goal

Select minimal reviewed dependencies and extras for:

| Extra | Purpose |
| --- | --- |
| `wallets` | Shared multi-chain processor kernel |
| `wallets-worldcoin` | World ID / IDKit protocol crypto and Worldcoin processor surface |
| `wallets-ethereum` | Ethereum / EVM public-ledger ingestion |
| `wallets-xrpl` | XRPL public-ledger ingestion |
| `wallets-xaman` | Xaman payload/account processing composed on XRPL |
| `wallets-bitcoin` | Bitcoin public-ledger ingestion |
| `wallets-solana` | Solana public-ledger ingestion |
| `wallets-all` | Union of every wallet extra above |

Install examples (never run by processors themselves):

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

Missing optional packages must raise an explicit error that names the extra.
Processors must not call `pip`, package managers, or network installers.

## Selection policy

1. **Minimal by default.** Prefer the standard library and packages already in
   the `ipfs_datasets_py` base install when they already satisfy a vector.
2. **Raw REST / JSON-RPC first.** Ledger and API clients use bounded HTTP
   transport (stdlib `urllib` or the shared wallet provider stack). Full chain
   SDKs are rejected unless they earn inclusion by unique protocol necessity,
   license/SBOM clearance, and a maintenance owner—not by convenience alone.
3. **Optional only.** No wallet chain extra becomes a mandatory base dependency.
4. **No auto-install.** Import and runtime paths never install missing extras.
5. **License and SBOM review before pin.** Every selected package records
   license class, provenance, and SBOM notes below.
6. **Hash and signing decided by golden vectors.** Cryptographic choices are
   accepted only when they reproduce
   `tests/fixtures/wallets/worldcoin/golden_vectors.json`.

## Python version contract (211-AI vs ipfs_datasets_py)

| Surface | Declared support | Source |
| --- | --- | --- |
| 211-AI monorepo root | `requires-python = ">=3.11"` | repository root `pyproject.toml` |
| `ipfs_datasets_py` | `requires-python = ">=3.12"` / `python_requires='>=3.12'` | `ipfs_datasets_py/pyproject.toml`, `ipfs_datasets_py/setup.py` |

**Resolution:** Wallet processors are owned by `ipfs_datasets_py` and require
**Python 3.12+**. Environments that install or execute wallet processors
(including the thin `wallet_interface.world_id` wrapper after cutover) must use
a 3.12+ interpreter. The 211-AI root may remain `>=3.11` for non-wallet
surfaces, but wallet migration CI, cutover, and operator runbooks treat 3.12+
as the supported runtime for this track.

Do **not** lower `ipfs_datasets_py` to 3.11 as part of this goal. Raising the
211-AI root to 3.12 is a separate monorepo packaging decision outside the
wallet-extra edit surface.

## Crypto decision: eth-hash / eth-keys vs coincurve / pycryptodome

Legacy `wallet_interface/world_id.py` optional-imports:

| Legacy import | Package hint | Role |
| --- | --- | --- |
| `Crypto.Hash.keccak` | `pycryptodome` | Keccak-256 / hash-to-field |
| `coincurve.PrivateKey` | `coincurve` | secp256k1 RP request signing |

`ipfs_datasets_py` already declares **base** dependencies:

- `eth-hash>=0.3.2`
- `eth-keys>=0.5.0`

### Decision (vector-backed)

| Capability | Selected stack | Rejected as required extra |
| --- | --- | --- |
| Keccak-256 | `eth-hash` with the **`pycryptodome` backend** (`eth-hash[pycryptodome]`) | Direct application code depending only on `Crypto.Hash` without eth-hash |
| secp256k1 sign / recover id | **`eth-keys` pure-Python backend** | **`coincurve` as a required pin** |

Evidence against golden fixtures under
`ipfs_datasets_py/tests/fixtures/wallets/worldcoin/golden_vectors.json`:

- `hash_to_field` cases match `eth_hash.auto.keccak` with the field shift
  `(int.from_bytes(digest, "big") >> 8)`.
- RP signing cases match `eth_keys.PrivateKey.sign_msg_hash` on the EIP-191
  digest when the recovery id is encoded as Ethereum `v = recid + 27`
  (fixture signatures end in `1b` for recid `0`).
- Side-by-side checks show `coincurve` and `eth-keys` produce identical `r||s`
  for the same key and message hash; `eth-keys` alone is sufficient.

### Why not require coincurve

- `eth-keys` already implements the needed signatures without a native
  extension.
- Vectors match without coincurve.
- coincurve remains an **operator-optional** native accelerator
  (`eth-keys[coincurve]`) for environments that want it; it is not declared in
  wallet extras and must not become mandatory for import success.

### Role of pycryptodome

`pycryptodome` is selected **only as the eth-hash Keccak backend**
(`eth-hash[pycryptodome]`), not as a parallel application crypto API.
Worldcoin processor code should prefer `eth_hash` / `eth_keys` so the package
has one cryptographic surface. The `pycryptodome` pin is therefore an
implementation detail of the eth-hash extra, not a license to reintroduce
`from Crypto.Hash import keccak` in new target code.

## Extra pin tables

### `wallets` — shared kernel

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| _(none)_ | — | — | — | Shared models, protocols, checkpoints, finality, pipeline, and provider transport are implemented with the standard library plus base `ipfs_datasets_py` dependencies. No chain SDK. |

### `wallets-worldcoin`

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| `eth-hash[pycryptodome]` | `>=0.3.2,<1.0.0` | MIT (`eth-hash`); BSD / Public Domain (`pycryptodome`) | PyPI; already a base package dep of `ipfs_datasets_py` | Keccak for World ID hash-to-field and EIP-191 digests. Backend explicit so installs do not depend on ambient transitive pycryptodome. |
| `eth-keys` | `>=0.5.0,<1.0.0` | MIT | PyPI; already a base package dep of `ipfs_datasets_py` | secp256k1 RP signing matching golden vectors without requiring coincurve. |

### `wallets-ethereum`

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| _(none)_ | — | — | — | Public EVM ledger ingestion uses raw JSON-RPC (`eth_getLogs`, `eth_getBlockByNumber`, receipts, traces only when explicitly required). **`web3.py` is not selected.** |

### `wallets-xrpl`

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| _(none)_ | — | — | — | XRPL account/tx pagination and ledger reads use raw HTTP JSON-RPC/WebSocket-optional REST. **`xrpl-py` is not selected.** |

### `wallets-xaman`

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| _(none)_ | — | — | — | Xaman payload lifecycle (created/opened/signed/rejected/expired/cancelled/submitted/validated/failed/unknown) over raw HTTP. Composes XRPL ledger paths logically; does not pull Firebase, mobile vault SDKs, or `xumm-sdk`. |

### `wallets-bitcoin`

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| _(none)_ | — | — | — | Bitcoin address/tx/UTXO ingestion via raw REST/JSON-RPC to configured providers. **`python-bitcoinlib` / `bitcoinlib` are not selected.** Script classification uses pure-Python helpers and fixtures. |

### `wallets-solana`

| Package | Bound | License | Provenance | SBOM / rationale |
| --- | --- | --- | --- | --- |
| _(none)_ | — | — | — | Solana transaction and token balance ingestion via raw JSON-RPC. **`solana` / `solders` SDKs are not selected.** |

### `wallets-all`

Union of every wallet extra pin (currently the Worldcoin crypto pair only).
Installing `wallets-all` does not auto-enable signing, broadcasting, or network
access; those remain separate denied capabilities.

## Explicitly rejected or deferred packages

| Package | Status | Reason |
| --- | --- | --- |
| `web3` / `web3.py` | Rejected for extras | SDK convenience; raw JSON-RPC covers ingestion. Revisit only with a protocol gap report. |
| `solana` / `solders` | Rejected for extras | Same; raw JSON-RPC sufficient for first release. |
| `xrpl-py` | Rejected for extras | Same; raw REST/JSON-RPC sufficient. |
| `xumm-sdk` / Xaman mobile SDKs | Rejected | Runtime processing must not couple to device or vendor SDK. |
| `python-bitcoinlib` / `bitcoinlib` | Rejected for extras | Not required for bounded public-ledger normalization. |
| `coincurve` (required) | Rejected as required | Vectors pass with `eth-keys` pure Python; keep optional for operators only. |
| Direct mandatory `pycryptodome` app API | Rejected | Prefer `eth-hash[pycryptodome]` as the single keccak path. |
| Any signing/broadcast wallet SDK | Denied capability | Non-custodial data processors only; separate objective required to enable. |

## Import and absence contract

- Minimal / shared imports must succeed when every chain extra package is
  absent beyond the base install (and without installing `wallets-*` extras).
- Chain providers load lazily; missing optional crypto for World ID signing
  must name `wallets-worldcoin` (or the documented extra) in the error path
  once that module exists.
- Root processor package imports remain free of network side effects and free
  of auto-install.
- Contract tests:
  `ipfs_datasets_py/tests/contract/processors/wallets/test_optional_dependencies.py`.

## Synchronization rules

When changing wallet extras:

1. Update **both** `ipfs_datasets_py/pyproject.toml` and
   `ipfs_datasets_py/setup.py` with identical package sets and compatible
   version bounds.
2. Update this document's pin tables and rejection list.
3. Extend the contract tests if a new package is admitted.
4. Do not add wallet chain packages to the base `install_requires` unless a
   later objective proves they are universal and mandatory.

## Validation

```bash
python -m pytest -q ipfs_datasets_py/tests/contract/processors/wallets/test_optional_dependencies.py
```

## Change log

| Date | Change |
| --- | --- |
| 2026-07-28 | Initial selection for WALPROC-G050: declare eight extras; choose eth-hash/eth-keys over required coincurve; raw REST/JSON-RPC for all ledger chains; document Python 3.12+ wallet runtime vs 211-AI `>=3.11` root. |
