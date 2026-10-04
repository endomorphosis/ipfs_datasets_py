# Hybrid Legal Release Checklist Template (Local)

Date: YYYY-MM-DD
Scope: Hybrid Legal V2 WSx closure evidence

## Contracts
- [ ] Query/proof contract snapshots are current and reviewed.
- [ ] IR/parser/prover contract changes are documented where applicable.
- Evidence:
  - `<path-to-hybrid_v2_api_schema_snapshot.json>`
  - `<path-to-v2_check_compliance.schema.json>`
  - `<path-to-v2_find_violations.schema.json>`
  - `<path-to-v2_explain_proof.schema.json>`

## Tests
- [ ] Ticket test gates passed for changed scope.
- [ ] No unresolved schema-drift failures in targeted suite.
- Evidence:
  - `<path-to-pytest-log>`
  - Summary: `<N passed in Xs>`

## CI/Matrix Parity (Local Evidence)
- [ ] Backend smoke matrix for `mock_smt` and `mock_fol` is green.
- [ ] Workflow gate coverage is current for this workstream.
- Evidence:
  - `<path-to-backend_smoke_mock_smt.json>`
  - `<path-to-backend_smoke_mock_fol.json>`
  - `<path-to-.github/workflows/legal-v2-reasoner-ci.yml>`

## End-to-End Pipeline Smoke
- [ ] Fixture/batch smoke succeeded with no errors.
- [ ] Optimizer, KG, and prover hooks remained enabled unless explicitly disabled by scope.
- Evidence:
  - `<path-to-batch-smoke-json>`
  - Summary: `<total=?, ok=?, error=?>`

## Observability (Optional if in scope)
- [ ] Baseline/benchmark artifact captured when performance is in scope.
- [ ] Regressions above threshold are triaged or waived.
- Evidence:
  - `<path-to-observability-artifact-or-N/A>`

## Rollback Readiness
- [ ] Optimizer/KG/prover toggles documented in runbook.
- [ ] Incident-response and rollback conditions documented.
- Evidence:
  - `<path-to-runbook>`

## Result
- [ ] `<ticket-id-1>` complete
- [ ] `<ticket-id-2>` complete
- [ ] Execution board updated with linked local evidence
