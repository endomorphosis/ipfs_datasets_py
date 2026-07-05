# Security IR Specification

`SecurityModelIR` is the shared, language-neutral artifact for wallet and exchange security verification.

Required top-level fields:

- `schema_version`
- `model_id`
- `entities`
- `assets`
- `wallets`
- `accounts`
- `roles`
- `principals`
- `capabilities`
- `policies`
- `events`
- `state_machines`
- `invariants`
- `assumptions` (either stable assumption IDs or `{id, description}` entries)
- `prover_targets`

Canonicalization uses stable JSON with sorted keys and compact separators so the same semantic model produces the same bytes and CID.

The default exchange model ships with a bounded assumption registry (`A1`-`A10`) and threat-model metadata (`T1`-`T10`) so proof reports can name exactly which assumptions each claim consumes.

## Python side

- heavy NLP and GraphRAG-assisted model extraction
- seed autoformalization of Python, JavaScript, TypeScript, Go, Java, and Rust codebases into reviewable security IR facts
- prover orchestration and counterexample discovery
- external prover runners (TLA+, Z3, Tamarin, ProVerif, HyperLTL, Lean, Coq) and proof report generation
- runtime monitor prototyping

## TypeScript/WASM side

- future runtime security kernel
- branded money, nonce, and capability types
- schema validation and capability evaluation
- proof receipt checking
- WASM Lean/Coq proof checking
- deterministic runtime temporal monitors and chain-adjacent predicates
