# groth16_backend wire format (authoritative)

This crate exposes a CLI binary `groth16` used by Python via subprocess.

## CLI

- Prove:
  - `groth16 prove --input /dev/stdin --output /dev/stdout`
- Verify:
  - `groth16 verify --proof /dev/stdin`

## Exit codes

- `prove`:
  - `0` success
  - `2` operational error (including invalid JSON / invalid witness)
- `verify`:
  - `0` valid
  - `1` invalid
  - `2` operational error (including invalid JSON)

## JSON schemas

Schemas are stored in `schemas/`:

- `schemas/witness_v1.schema.json`
- `schemas/proof_v1.schema.json`
- `schemas/error_envelope_v1.schema.json`

Notes:
- Witness input is forward-compatible: unknown fields are allowed.
- Proof output is forward-compatible: unknown fields are allowed.
- Error envelope is intentionally strict.

## Public input ordering

`ProofOutput.public_inputs` is a 4-element array with ordering:

1. `theorem_hash_hex`
2. `axioms_commitment_hex`
3. `circuit_version` (string or number; consumers should compare via `str()`)
4. `ruleset_id`

This ordering is locked by golden vectors in Python tests.

## Determinism

For tests/reproducibility, setting `GROTH16_BACKEND_DETERMINISTIC=1` forces `timestamp=0`.
