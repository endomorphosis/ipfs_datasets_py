# Hybrid Legal WS8 Issue Bodies (06-15)

Use the sections below as copy/paste issue bodies for GitHub.

## HL-WS8-06: KG Enrichment Explainability Summary

Title:
`HL-WS8-06: Add KG Enrichment Explainability Summary Contract`

Body:

```markdown
## Summary
Add a normalized KG enrichment summary contract to improve explainability, debugging, and auditability.

## Scope
- Add stable summary fields to `kg_report` for link/write activity.
- Ensure rejected KG paths still emit a complete summary with zero writes.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py`
- `tests/reasoner/test_kg_enrichment_adapter.py`

## Acceptance Criteria
1. `kg_report` includes deterministic summary counts for entity links and relation writes.
2. Rejected KG paths include a summary payload with zero writes.
3. Report shape is stable across accepted/rejected paths.

## Test Gate
`pytest tests/reasoner/test_kg_enrichment_adapter.py tests/reasoner/test_hybrid_v2_blueprint.py -q`

## Notes
Use explicit zero values rather than omitted keys to simplify downstream consumers.
```

## HL-WS8-07: Prover Envelope Compatibility Table

Title:
`HL-WS8-07: Document Prover Envelope Compatibility Matrix`

Body:

```markdown
## Summary
Document backend-specific certificate payload compatibility and enforce required keys in tests.

## Scope
- Add a compatibility table for supported prover backends.
- Add assertions for mandatory certificate keys per backend family.

## Target Files
- `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`
- `tests/reasoner/test_prover_backend_registry.py`

## Acceptance Criteria
1. Docs include matrix coverage for `mock_smt`, `mock_fol`, `smt_style`, `first_order`.
2. Tests assert mandatory certificate keys per backend.
3. Compatibility notes are clear for backend-specific optional fields.

## Test Gate
`pytest tests/reasoner/test_prover_backend_registry.py -q`

## Notes
Keep matrix focused on contract-level compatibility, not implementation internals.
```

## HL-WS8-08: Query API JSON Schema Export

Title:
`HL-WS8-08: Export JSON Schemas for V2 Query APIs`

Body:

```markdown
## Summary
Publish JSON Schema artifacts for Hybrid V2 query APIs and validate schema/runtime alignment.

## Scope
- Add schema files for:
1. `check_compliance`
2. `find_violations`
3. `explain_proof`
- Wire docs to schema paths.
- Add schema-shape assertions in query API tests.

## Target Files
- `docs/guides/legal_data/schemas/v2_check_compliance.schema.json`
- `docs/guides/legal_data/schemas/v2_find_violations.schema.json`
- `docs/guides/legal_data/schemas/v2_explain_proof.schema.json`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`
- `tests/reasoner/test_hybrid_v2_query_api_matrix.py`

## Acceptance Criteria
1. Schema required fields and types match runtime envelopes.
2. Docs reference the schema files and intended usage.
3. Query API tests fail on schema drift.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## Notes
Treat schema exports as versioned contract artifacts and preserve deterministic key ordering.
```

## HL-WS8-09: Batch CLI Summary Contract

Title:
`HL-WS8-09: Stabilize Batch CLI Summary Contract`

Body:

```markdown
## Summary
Harden the Hybrid V2 CLI batch summary output into a stable machine-readable contract.

## Scope
- Normalize summary fields for totals, outcomes, toggles, and backend identity.
- Ensure error rows include machine-readable error codes.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/v2_cli.py`
- `tests/reasoner/test_hybrid_v2_cli.py`

## Acceptance Criteria
1. CLI summary includes deterministic fields: `total`, `ok`, `error`, hook toggles, backend ID.
2. Error rows include stable machine-readable error code field.
3. Existing CLI behavior remains backward-compatible where practical.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_cli.py -q`

## Notes
Prefer additive changes for summary fields to avoid breaking downstream pipeline parsers.
```

## HL-WS8-10: Proof Store Retention Policy

Title:
`HL-WS8-10: Add Deterministic Proof Store Retention Policy`

Body:

```markdown
## Summary
Introduce bounded in-memory proof retention with deterministic eviction behavior for long-running sessions.

## Scope
- Add configurable maximum proof entry retention.
- Define deterministic eviction order.
- Stabilize `explain_proof` response for evicted proofs.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

## Acceptance Criteria
1. Maximum retained proof entries is configurable and enforced.
2. Eviction order is deterministic and test-covered.
3. `explain_proof` has explicit, stable behavior for evicted proof IDs.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`

## Notes
Do not rely on wall-clock timestamps for eviction ordering.
```

## HL-WS8-11: CNL Lexicon Extension Hooks

Title:
`HL-WS8-11: Add CNL Lexicon Override Hooks Without ID Drift`

Body:

```markdown
## Summary
Add optional lexicon overrides for domain synonyms while preserving canonical semantic identifiers.

## Scope
- Support opt-in lexicon override inputs.
- Ensure overrides affect NL rendering only, not canonical frame IDs.
- Preserve replay determinism.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

## Acceptance Criteria
1. Lexicon overrides do not alter canonical frame IDs or proof-critical identifiers.
2. Parsing and replay determinism remain green.
3. Non-override behavior remains unchanged.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## Notes
Separate display-layer synonym handling from semantic normalization paths.
```

## HL-WS8-12: CI Workflow Matrix for Prover Backends

Title:
`HL-WS8-12: Add Prover Backend Matrix Smoke in Legal V2 CI`

Body:

```markdown
## Summary
Expand CI with lightweight backend matrix smoke coverage while preserving the primary full-suite gate.

## Scope
- Keep one full V2 suite run as the canonical gate.
- Add matrix smoke runs for `mock_smt` and `mock_fol`.
- Preserve failure-log artifact upload behavior.

## Target Files
- `.github/workflows/legal-v2-reasoner-ci.yml`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

## Acceptance Criteria
1. Workflow runs one primary full-suite job plus backend smoke matrix jobs.
2. Failing jobs upload failure logs/artifacts consistently.
3. Runbook documents local parity commands for matrix smoke checks.

## Test Gate
Workflow validation plus at least one successful workflow dispatch run.

## Notes
Keep matrix smoke scope small enough to avoid materially increasing CI latency.
```

## HL-WS8-13: Performance Baseline Snapshot

Title:
`HL-WS8-13: Add Hybrid V2 Performance Baseline Snapshot Script`

Body:

```markdown
## Summary
Create a benchmark script and baseline artifact format for parse/compile/reason timing on fixture corpora.

## Scope
- Add benchmark script for stage-level timings.
- Emit JSON baseline artifact with deterministic fields.
- Document interpretation and threshold guidance.

## Target Files
- `scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_EXECUTION_PLAYBOOK.md`

## Acceptance Criteria
1. Script emits JSON baseline with per-stage timing metrics.
2. Playbook documents how to read results and act on regressions.
3. Smoke execution path is reproducible locally and in CI/ops context.

## Test Gate
Script smoke run in CI or via documented local ops task.

## Notes
Include basic environment metadata in artifacts (CPU/model string if available) for better comparability.
```

## HL-WS8-14: Ticket-to-Test Traceability Table

Title:
`HL-WS8-14: Add WS8 Ticket-to-Test Traceability Matrix`

Body:

```markdown
## Summary
Add explicit traceability from WS8 tickets to tests and CI gates to simplify planning and reviews.

## Scope
- Add a matrix mapping each WS8 ticket to test files and CI jobs.
- Keep matrix copy/paste-ready for GitHub issues and PR descriptions.

## Target Files
- `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md`
- `docs/guides/legal_data/HYBRID_LEGAL_WS8_IMPLEMENTATION_TICKETS.md`

## Acceptance Criteria
1. Every ticket has at least one listed test gate.
2. Matrix is readable and easy to copy into issue templates.
3. Docs remain lint/diagnostics clean.

## Test Gate
Documentation review plus lint/diagnostics clean.

## Notes
Use consistent ticket IDs (`HL-WS8-XX`) to keep cross-doc linking stable.
```

## HL-WS8-15: Release Readiness Checklist v2

Title:
`HL-WS8-15: Create Hybrid V2 Release Readiness Checklist`

Body:

```markdown
## Summary
Define a release readiness checklist for shipping Hybrid V2 as a stable subsystem.

## Scope
- Add checklist covering contracts, tests, CI health, observability, and rollback.
- Require links to generated artifacts and validation outputs.

## Target Files
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

## Acceptance Criteria
1. Checklist includes contracts, tests, CI, observability, rollback requirements.
2. Completion criteria require links to concrete artifacts.
3. Checklist can be dry-run in a PR description.

## Test Gate
Dry-run checklist walkthrough in PR description.

## Notes
Prefer concise checklist items with clear pass/fail language.
```
