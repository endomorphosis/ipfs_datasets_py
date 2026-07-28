# Worldcoin / World ID migration fixtures

Frozen golden vectors and structural baselines for **WALPROC-G020**.

## Scope

These fixtures freeze:

- Official-style `hash_to_field` and RP signing vectors
- IDKit v3 legacy, v4 uniqueness, and v4 session payload shapes
- Developer Portal verify success/failure response shapes
- Redaction and public-projection rules
- HTTP route DTO shapes under `wallet_interface/routes/world_id.py`
- Pre-move public import identities from `wallet_interface.world_id`
- Old wallet snapshot binding shapes for import compatibility

They do **not** freeze vulnerabilities. Known security failures are recorded in
`data/wallet_processor_migration/audit/security-baseline.json` with
`classification: failure_to_fix` (not compatibility guarantees).

## Usage

Contract tests load this directory via
`ipfs_datasets_py/tests/contract/processors/wallets/test_migration_baseline.py`.

Offline by default. Optional live recomputation against
`wallet_interface.world_id` runs when that module is importable so differential
checks catch silent crypto drift before ownership moves.
