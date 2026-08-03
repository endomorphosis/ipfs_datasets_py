# Wallet Processors — Chain and Identity Distinctions

Companion to [README.md](./README.md). This page expands the non-interchangeable
identities that consumers must not conflate.

## World ID, World Chain, and WLD

### World ID (protocol)

- **Domain:** proof-of-personhood verification (IDKit payloads, RP request
  signing, nullifier commitments, developer-portal verify responses).
- **Registry family:** `worldcoin` (aliases `world-id`, `worldid`, `wld-id`).
- **Extra:** `wallets-worldcoin`.
- **Modules:** `config`, `idkit`, `signing`, `proofs`, `bindings`,
  `developer_portal`, `challenges`, `snapshots`.
- **Not a public-ledger scanner.** Prefer family `world-chain` for wallet
  history on the World Chain L2.
- **Privacy:** raw nullifiers, proofs, JWTs, and signatures are redacted or
  commitment-wrapped before public export. Secrets are opaque references only.

### World Chain (ledger)

- **Domain:** OP-Stack EVM L2 public ledger.
- **Chain ids:** mainnet `480`, Sepolia `4801`.
- **Registry family:** `world-chain` (aliases `worldchain`, `wld-chain`).
- **Composition:** Ethereum/EVM normalizer and finality primitives
  (`composes_ethereum: true`).
- **Finality:** block depth alone is **not** finality
  (`block_depth_alone_is_not_finality: true`).
- **SIWE:** bootstrap not supported in the current capability metadata.

### WLD (asset)

- **Domain:** ERC-20 token identity on World Chain, **not** a protocol and
  **not** a chain.
- **Catalog:** `ipfs_datasets_py.processors.wallets.worldcoin.assets`.
- **Mainnet binding:** chain id `480` only; Sepolia must supply an explicit
  reviewed contract address and must never silently substitute mainnet WLD.

```text
World ID  ── protocol (identity / proofs)
World Chain ── ledger (eip155 / chain 480|4801)
WLD         ── asset on World Chain mainnet
```

## Xaman and XRPL

### XRPL (ledger)

- **Domain:** XRP Ledger classic accounts, payments, issued currencies, trust
  lines, ledger ranges.
- **Registry family:** `xrpl` (aliases `xrp`, `ripple`).
- **Extra:** `wallets-xrpl`.
- **Capabilities:** wallet history, ledger range, balances, token transfers,
  reorg recovery, dataset export, finality.
- **Privacy:** destination tags and memos are sensitive; free-form memo
  retention is opt-in and size-bounded.

### Xaman (payload application surface)

- **Domain:** Xaman (formerly Xumm) payload lifecycle, user instructions, and
  assurance linkage; settlement is correlated on XRPL.
- **Registry family:** `xaman` (alias `xumm`).
- **Extra:** `wallets-xaman`.
- **Composition:** `composes: xrpl` / `settlement_via: xrpl`.
- **Denied:** approve, sign, and submit remain false — this package never
  becomes a signing oracle for Xaman payloads.
- **Gap:** not a full XRPL ledger-range scanner; use family `xrpl` for that.

```text
XRPL   ── public ledger processor
Xaman  ── payload processor composed over XRPL settlement
```

### Disambiguation

Network selectors such as `xrpl-mainnet` match both families. Always pass an
explicit `family=` when constructing processors through the registry.

## Other chains (brief)

| Family | Namespace | Distinctive model |
| --- | --- | --- |
| bitcoin | `bip122` | UTXO, script descriptors, RBF/replacement |
| ethereum | `eip155` | Accounts, logs, token transfers, contract events |
| solana | `solana` | Accounts, signatures, token program ids |

All families share the same normalized record models and export manifests.
Chain-specific fields live only in versioned extensions.
