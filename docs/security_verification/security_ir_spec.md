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
- deterministic feature-loop projection so auto-ingested codebases, proof generation, and proof-regression tests share the same extracted security facts
- prover orchestration and counterexample discovery
- implemented Z3 runner plus proof report generation
- runtime monitor prototyping

## TypeScript/WASM side

- future runtime security kernel
- branded money, nonce, and capability types
- schema validation and capability evaluation
- proof receipt checking
- WASM Lean/Coq proof checking
- deterministic runtime temporal monitors and chain-adjacent predicates

## Soundness boundary

- The current Z3 backend proves only bounded properties of the modeled `SecurityModelIR`; it is not an absolute proof that a deployed exchange is secure.
- `PROVED` means the implemented backend checked this specific IR under the listed assumptions and did not find a violation within that model boundary.
- Heuristic or machine-extracted autoformalization remains non-authoritative until its `evidence_refs` have been reviewed and a proof consumer explicitly accepts the assumptions used by the report.
- `UNKNOWN` and `NOT_MODELED` are never secure outcomes.
- Disabled or unimplemented prover families remain planning targets only until this package ships end-to-end compiler and runner support for them.
- TypeScript/WASM artifacts emitted from this package are strict proof-consumer validation helpers; they must verify schema versions, report/receipt identity, and explicit assumption acceptance before treating a proof as consumable.
