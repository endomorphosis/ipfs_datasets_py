# Hybrid Legal WS12 Issue Bodies (01-04)

Use the sections below as copy/paste issue bodies for GitHub.

## HL-WS12-01: Policy Pack Schema + Validator

Title:
`HL-WS12-01: Policy Pack Schema + Validator`

Body:

```markdown
## Summary
Define and enforce canonical policy-pack schema with stable machine-readable validation errors.

## Scope
- Validate required fields (`jurisdiction`, `effective_date`, `priority_policy`, `exception_policy`, `temporal_policy`).
- Emit stable error-code contracts for missing/invalid fields.
- Freeze and lock policy-pack schema version in regression fixtures.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/policy_pack.py`
- `ipfs_datasets_py/tests/reasoner/test_policy_pack_schema.py`

## Acceptance Criteria
1. Required fields are validated with deterministic errors.
2. Missing/invalid values map to stable reason-code set.
3. Schema version is explicit and snapshot-locked.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_policy_pack_schema.py -q`

## Notes
Keep error envelope shape stable for automation consumers.
```

## HL-WS12-02: Deterministic Policy Resolver

Title:
`HL-WS12-02: Deterministic Policy Resolver`

Body:

```markdown
## Summary
Resolve policy-pack selection deterministically for each `(jurisdiction, date, query)` input.

## Scope
- Implement deterministic resolver with explicit tie-break policy.
- Emit decision envelope with selected policy ID and trace fields.
- Add replay checks to prove selection stability.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/policy_resolver.py`
- `ipfs_datasets_py/tests/reasoner/test_policy_resolver_determinism.py`

## Acceptance Criteria
1. Same inputs always select same policy-pack ID.
2. Decision envelope fields are deterministic across replay.
3. Tie-break behavior is documented and test-covered.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_policy_resolver_determinism.py -q`

## Notes
Avoid implicit precedence rules not represented in resolver output.
```

## HL-WS12-03: Multi-Jurisdiction Replay Matrix

Title:
`HL-WS12-03: Multi-Jurisdiction Replay Matrix`

Body:

```markdown
## Summary
Add deterministic replay matrix coverage for Federal plus at least two State policy profiles.

## Scope
- Add fixture corpus for jurisdiction replay matrix.
- Validate status/proof ID/reason-code determinism across jurisdictions.
- Fail hard on expected-output drift.

## Target Files
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/jurisdiction_replay_matrix_v1.json`

## Acceptance Criteria
1. Required jurisdictions are covered.
2. Replay outputs are deterministic for status/proof/reason.
3. Drift is detected by strict regression lock.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## Notes
Keep matrix fixture IDs stable and append-only where possible.
```

## HL-WS12-04: Proof Conflict Taxonomy + Reason Codes

Title:
`HL-WS12-04: Proof Conflict Taxonomy + Reason Codes`

Body:

```markdown
## Summary
Enforce standardized proof-conflict taxonomy and complete reason-code coverage.

## Scope
- Define conflict classes (`modal_conflict`, `temporal_conflict`, `exception_precedence_conflict`).
- Ensure each conflict path emits exactly one registered reason code.
- Add regression checks for unknown/unregistered conflict classes.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_conflict_reason_codes.py`

## Acceptance Criteria
1. Conflict taxonomy is explicit and test-covered.
2. Reason-code envelope is complete and deterministic.
3. Unknown conflict classes fail with contract-safe errors.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_conflict_reason_codes.py -q`

## Notes
Keep taxonomy and API docs synchronized to avoid consumer drift.
```
