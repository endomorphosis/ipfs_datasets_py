# Xaman / XRPL wallet processor fixtures

Fixtures for **WALPROC-G210** (runtime Xaman payload processing over XRPL) and
the **WALPROC-G020** assurance-boundary freeze.

## Boundary

| Layer | Location | Role |
| --- | --- | --- |
| Formal assurance / IR | `logic/security_ir/xaman`, `logic/security_models/crypto_exchange` | Analysis, disproof, release decision artifacts |
| Runtime processor | `processors/wallets/xaman`, `processors/wallets/xrpl` | Public-ledger ingest/normalize/export; payload lifecycle |

Runtime processors must **not** import formal report generators. Formal
assurance is **not** proof of runtime correctness.

## Acceptance invariants

- Lifecycle states remain distinct: created, opened, signed, rejected, expired,
  cancelled, submitted, validated, failed, unknown.
- Xaman API success is **never** settlement.
- Transaction facts are verified through XRPL evidence only.
- Network / account / payload identity is bound at normalize time.
- Memos and custom instructions follow redaction and size policy.
- Processor cannot approve, sign, or submit.

## Files

- `assurance_links.json` — typed map from formal assets to runtime projections
- `runtime_projection_boundary.json` — import/coupling rules
- `sample_ledger_records.json` — offline XRPL-shaped ledger samples
- `payload_lifecycle_states.json` — one document per distinct lifecycle status
- `settlement_correlation.json` — API success vs XRPL settlement cases
- `redaction_cases.json` — instruction redaction and size bounds
- `network_binding.json` — network/account/payload identity binding
- `manifest.json` — inventory and acceptance keys
