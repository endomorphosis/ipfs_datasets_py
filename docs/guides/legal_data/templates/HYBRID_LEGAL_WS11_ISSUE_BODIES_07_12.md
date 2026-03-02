# Hybrid Legal WS11 Issue Bodies (07-12)

Use the sections below as copy/paste issue bodies for GitHub.

## HL-WS11-07: Optimizer Hook Semantic-Drift Gate v3

Title:
`HL-WS11-07: Enforce V3 Optimizer Semantic-Drift Gate and Decision Envelope`

Body:

```markdown
## Summary
Enforce V3 optimizer governance so only semantically equivalent transformations are accepted.

## Scope
- Enforce decision envelope fields (`equivalence_ok`, `drift_score`, reason codes).
- Block any optimizer mutation of modality operators or target frame identity.
- Ensure acceptance/rejection results are replay-stable.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/optimizer_policy.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`

## Acceptance Criteria
1. Modality and target-frame identity are immutable under optimizer passes.
2. Drift-threshold breaches are rejected with deterministic telemetry.
3. Decision outputs are deterministic across replay runs.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## Notes
Avoid non-deterministic telemetry fields in policy decisions.
```

## HL-WS11-08: KG Hook Additive Enrichment Policy v3

Title:
`HL-WS11-08: Enforce Additive/Reversible KG Enrichment Policy for V3`

Body:

```markdown
## Summary
Ensure KG enrichment remains additive, confidence-scored, and fully reversible without canonical-ID mutation.

## Scope
- Preserve canonical IDs through enrichment.
- Emit stable enrichment summary counters.
- Confirm rollback removes only adapter-added fields.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py`
- `ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py`

## Acceptance Criteria
1. Enrichment does not mutate canonical IDs or normative operator semantics.
2. Reports include deterministic counters for links/writes/reverts.
3. Rollback path only affects KG-added metadata.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py -q`

## Notes
Prefer explicit confidence thresholds over implicit heuristics.
```

## HL-WS11-09: Prover Certificate Contract v3

Title:
`HL-WS11-09: Normalize V3 Prover Certificate Contract and Proof Traceability`

Body:

```markdown
## Summary
Normalize theorem-prover certificate contracts and enforce proof-step linkage to IR and provenance.

## Scope
- Validate required certificate keys per backend family.
- Enforce proof-step `ir_refs` and provenance presence.
- Confirm deterministic proof hash and replay verification.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/prover_backends.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/serialization.py`
- `ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py`

## Acceptance Criteria
1. Backend-specific certificate payload requirements are enforced.
2. All proof steps include non-empty `ir_refs` and provenance.
3. Deterministic proof hash/replay checks pass.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -q`

## Notes
Keep backend compatibility matrix aligned with docs contract.
```

## HL-WS11-10: API Semantics Expansion (Compliance + Violations + Explain)

Title:
`HL-WS11-10: Expand V3 API Semantics for Compliance/Violations/Explainability`

Body:

```markdown
## Summary
Validate and harden V3 semantics in API outputs for compliance, violations, exceptions, deadlines, and conflicts.

## Scope
- Enforce schema-stable outputs with proof IDs.
- Validate deterministic conflict and exception precedence behavior.
- Ensure `explain_proof` output is reconstructable into natural language.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`

## Acceptance Criteria
1. API envelopes remain schema-stable and include traceable proof references.
2. Deadline/exception/conflict semantics are deterministic.
3. Explanation payload reconstructs consistent NL output.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## Notes
Preserve V2 compatibility for existing consumers while adding V3 semantics.
```

## HL-WS11-11: 10-Example CNL Transformation Regression Pack

Title:
`HL-WS11-11: Add 10-Example V3 CNL Transformation Regression Pack`

Body:

```markdown
## Summary
Add fixture-driven regression for ten canonical V3 transformation chains (`CNL -> IR -> DCEC/TDFOL -> NL`).

## Scope
- Add fixture pack for ten examples.
- Validate first five across both DCEC and TDFOL outputs.
- Ensure strict-mode round-trip NL stability.

## Target Files
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_v3_transformation_cases.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

## Acceptance Criteria
1. All ten transformation chains pass deterministically.
2. First five examples validate DCEC and TDFOL parity expectations.
3. Round-trip NL output remains stable in strict mode.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## Notes
Keep fixture IDs and expected outputs deterministic for clean regression diffs.
```

## HL-WS11-12: 8-Query Proof Matrix Closure + Ops Runbook Update

Title:
`HL-WS11-12: Close 8-Query V3 Proof Matrix and Operationalize WS11 Evidence`

Body:

```markdown
## Summary
Close the V3 8-query proof matrix and document repeatable WS11 evidence collection in runbook/TODO workflows.

## Scope
- Lock expected statuses and proof-root conclusions for 8 query scenarios.
- Update runbook with WS11 local parity commands and artifact paths.
- Add WS11 tracking block in TODO execution board.

## Target Files
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`

## Acceptance Criteria
1. Eight scenarios produce deterministic expected statuses and proof roots.
2. Runbook includes repeatable WS11 evidence instructions and artifact locations.
3. TODO board links WS11 backlog and current-sprint execution status.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## Notes
Treat this ticket as WS11 closure gate for docs+tests operational consistency.
```
