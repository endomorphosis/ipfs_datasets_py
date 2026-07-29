# Solana wallet fixtures

Synthetic, offline-only Solana JSON-RPC vectors for WALPROC-G500. The session
covers overlapping signature pages, versioned account lookup resolution,
legacy and failed transactions, outer/inner parsed instructions, bounded
program logs, large exact lamport/SPL quantities, token-account balances,
commitment heads, a finalized slot/blockhash checkpoint anchor, and a skipped
slot. It contains no real wallet activity, secrets, signing material, or
network endpoint.

NFT metadata is intentionally absent. Tests may inject optional token metadata
to project a token record as an NFT, while the core fixture remains sufficient
for ingestion and export.
