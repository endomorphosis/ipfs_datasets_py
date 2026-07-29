# Ethereum/EVM wallet fixtures

Synthetic, offline JSON-RPC vectors for WALPROC-G300. They cover:

- `eth_chainId` plus block-zero genesis identity;
- a legacy transaction, reverted EIP-1559 transaction, and contract creation;
- exact native value and gas-fee quantities;
- ERC-20, ERC-721, ERC-1155 single/batch logs, including a removed log;
- explicit `safe`/`finalized` tags and confirmation fallback;
- optional trace availability and a shallow canonical-history replacement.

Token metadata is intentionally absent for one ERC-20 vector. The transfer must
still ingest with exact base units and an explicit incomplete-metadata label.
