# Xaman / XRPL migration fixtures

Frozen assurance links and offline ledger sample shapes for **WALPROC-G020**.

## Boundary

| Layer | Location | Role |
| --- | --- | --- |
| Formal assurance / IR | `logic/security_ir/xaman`, `logic/security_models/crypto_exchange` | Analysis, disproof, release decision artifacts |
| Runtime processor (planned) | `processors/wallets/xaman`, `processors/wallets/xrpl` | Public-ledger ingest/normalize/export |

These fixtures freeze the **links and projection contract** between layers.
They deliberately do **not** claim that formal assurance proves runtime
processor correctness.

## Files

- `assurance_links.json` — typed map from formal assets to future runtime projections
- `runtime_projection_boundary.json` — import/coupling rules
- `sample_ledger_records.json` — offline XRPL-shaped records for future conformance
