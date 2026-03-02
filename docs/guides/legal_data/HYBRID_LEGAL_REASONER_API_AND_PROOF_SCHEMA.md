# Hybrid Legal Reasoner API and Proof Schema

This document defines the operational API payloads and proof schema used by the hybrid legal reasoner.

Related implementation modules:
- `src/municipal_scrape_workspace/cli.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/engine.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/models.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/serialization.py`

## 1) Query APIs

V2 query response schema artifacts:
- `docs/guides/legal_data/schemas/v2_check_compliance.schema.json`
- `docs/guides/legal_data/schemas/v2_find_violations.schema.json`
- `docs/guides/legal_data/schemas/v2_explain_proof.schema.json`

### `check_compliance(query, time_context) -> result`

Input `query`:
- `actor_ref`: string entity reference (`ent:...`)
- `frame_ref`: string frame reference (`frm:...`)
- `events`: list of event objects
- `facts`: map of fact flags

Input `time_context`:
- `start`: ISO-8601 timestamp
- `end`: ISO-8601 timestamp
- `at_time`: ISO-8601 timestamp

Output:
- `status`: `compliant | non_compliant | inconclusive`
- `obligations_checked`: list of norm refs
- `violations`: list of violation objects
- `exceptions_applied`: list of norm refs
- `conflicts`: list of conflict objects
- `proof_id`: stable proof identifier (`pf_<12 hex>`)

### `find_violations(state, time_range) -> result`

Input `state`:
- `events`: list of event objects
- `facts`: map of fact flags

Input `time_range`:
- tuple/list `[start, end]` ISO-8601 timestamps

Output:
- `violations`: list of violation objects
- `conflicting_obligations`: list of conflict objects
- `summary`: `{start, end, violation_count, conflict_count}`
- `proof_id`: stable proof identifier

### `explain_proof(proof_id, format="nl") -> result`

Inputs:
- `proof_id`: existing proof ID
- `format`: `nl | json | graph`

`format="nl"` output fields:
- `proof_id`
- `format`
- `status`
- `root_conclusion`
- `query_summary`
- `renderer_version` (currently `1.0`)
- `explanation`
- `steps`
- `reconstructed_nl`

## 2) Proof Object Schema

`ProofObject` fields:
- `proof_id`: deterministic ID derived from canonical proof hash (`pf_<first12(sha256)>`)
- `query`: query envelope used to produce the proof
- `root_conclusion`: top-level conclusion string
- `steps`: ordered `ProofStep` list
- `status`: `proved | refuted | inconclusive`
- `schema_version`: currently `1.0`
- `proof_hash`: full SHA-256 hash of canonical proof payload
- `created_at`: ISO-8601 timestamp

`ProofStep` fields:
- `step_id`
- `rule_id`
- `premises`: upstream step IDs
- `conclusion`
- `ir_refs`: list of `{kind, id}`
- `provenance`: list of `{source_path, source_id, source_span?}`
- `timestamp`
- `confidence`

## 3) Determinism and Replay Contract

Determinism guarantees:
- `proof_id` and `proof_hash` are deterministic for identical query + KB + reasoning outputs.
- `reconstructed_nl` in `explain_proof(..., format="nl")` is deterministic for identical proof objects.

Replay validation:
- Use `validate_proof_replay(proof_id)` to recompute canonical hash/ID.
- Expected fields in validation result:
  - `proof_id`
  - `expected_proof_id`
  - `proof_hash`
  - `expected_proof_hash`
  - `replay_match`

## 4) Serialization Contract

Use:
- `proof_to_dict(proof)` for persistence
- `proof_from_dict(payload)` for recovery

Roundtrip requirements:
- Preserve `schema_version`, `proof_hash`, `created_at`
- Preserve full `steps`, including `ir_refs` and provenance

## 5) Operational Artifacts

Common artifact paths:
- proof JSON outputs written by CLI `--proof-out`
- proof stores managed by `append_proof_to_store` / `load_proof_store`

Recommended checks for consumers:
- reject proofs where `schema_version` is unsupported
- require non-empty `ir_refs` and provenance in every proof step
- run replay validation before accepting imported proofs
