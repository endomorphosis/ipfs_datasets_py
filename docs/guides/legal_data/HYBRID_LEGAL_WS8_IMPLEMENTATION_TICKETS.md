# Hybrid Legal WS8 Implementation Tickets

## 1. Purpose

This document translates the completed WS1-WS7 architecture into issue-ready implementation tickets for sustained delivery.

Scope assumptions:

1. WS1-WS7 baseline is complete and green.
2. Hybrid V2 suite remains the release gate.
3. All tickets preserve deterministic IDs, provenance, and policy rejection semantics.

## 2. How To Use This Backlog

1. Create one GitHub issue per ticket ID (`HL-WS8-XX`).
2. Keep PRs single-ticket when possible.
3. Require green result for `Legal V2 Reasoner CI` before merge.

Issue body templates:
- `templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_01_05.md`
- `templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_06_15.md`

## 3. Ticket Backlog

## HL-WS8-01: Contract Snapshot Lockfile

Goal:
- Add machine-readable snapshot of V2 API/proof envelope schemas for drift detection.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json`

Acceptance criteria:
1. Snapshot fixture includes `check_compliance`, `find_violations`, `explain_proof` envelopes.
2. Test fails when keys or types drift unexpectedly.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## HL-WS8-02: IR Contract Error Code Registry

Goal:
- Standardize all V2 contract errors into stable code strings for API consumers.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `docs/guides/legal_data/HYBRID_LEGAL_MASTER_INTEGRATION_PLAN.md`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. Contract validator emits structured error codes and keeps readable text.
2. Existing strict/non-strict behavior remains intact.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS8-03: Parser Paraphrase Equivalence Corpus

Goal:
- Add a small paraphrase corpus that must normalize to equivalent IR semantics.

Target files:
- `tests/reasoner/fixtures/cnl_parse_paraphrase_equivalence_v2.json`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. Equivalent paraphrases yield same norm operator, target frame semantics, and temporal relation.
2. Non-equivalent paraphrases are explicitly marked and rejected from equivalence assertions.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS8-04: Temporal Guard Conformance Expansion

Goal:
- Expand compiler parity fixture set for boundary temporal cases (`within`, `by`, `before`, `after`, `during`).

Target files:
- `tests/reasoner/fixtures/compiler_parity_v2_cases.json`
- `tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. At least 2 additional cases per temporal relation class.
2. Parity report remains inconsistency-free for expected-good corpus.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS8-05: Optimizer Rejection Telemetry Envelope

Goal:
- Introduce normalized telemetry section for optimizer rejection diagnostics.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. `optimizer_report` includes deterministic telemetry fields (`decision_id`, `rejected_reason_codes`, `failure_count`).
2. Boundary tests confirm stable telemetry shape.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS8-06: KG Enrichment Explainability Summary

Goal:
- Add normalized KG summary fields for debugging and audit.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py`
- `tests/reasoner/test_kg_enrichment_adapter.py`

Acceptance criteria:
1. `kg_report` includes stable summary counts for entity links and relation writes.
2. Rejected KG path includes summary with zero writes.

Test gate:
- `pytest tests/reasoner/test_kg_enrichment_adapter.py tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS8-07: Prover Envelope Compatibility Table

Goal:
- Add a compatibility matrix documenting backend-specific certificate payload differences.

Target files:
- `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`
- `tests/reasoner/test_prover_backend_registry.py`

Acceptance criteria:
1. Docs include matrix for `mock_smt`, `mock_fol`, `smt_style`, `first_order`.
2. Tests assert mandatory certificate keys per backend.

Test gate:
- `pytest tests/reasoner/test_prover_backend_registry.py -q`

## HL-WS8-08: Query API JSON Schema Export

Goal:
- Export JSON schema docs for V2 query API responses.

Target files:
- `docs/guides/legal_data/schemas/v2_check_compliance.schema.json`
- `docs/guides/legal_data/schemas/v2_find_violations.schema.json`
- `docs/guides/legal_data/schemas/v2_explain_proof.schema.json`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`

Acceptance criteria:
1. Schemas match runtime envelope fields and required keys.
2. Docs reference schema paths.

Test gate:
- Add schema-shape assertion test in `tests/reasoner/test_hybrid_v2_query_api_matrix.py`.

## HL-WS8-09: Batch CLI Summary Contract

Goal:
- Stabilize CLI batch summary contract for reporting pipelines.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/v2_cli.py`
- `tests/reasoner/test_hybrid_v2_cli.py`

Acceptance criteria:
1. CLI summary includes deterministic fields (`total`, `ok`, `error`, hook toggles, backend id).
2. Error rows include machine-readable error code field.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_cli.py -q`

## HL-WS8-10: Proof Store Retention Policy

Goal:
- Add bounded in-memory proof retention policy for long-running API sessions.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. Configurable max proof entries with deterministic eviction order.
2. `explain_proof` behavior on evicted proofs is explicit and stable.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS8-11: CNL Lexicon Extension Hooks

Goal:
- Add optional lexicon override input for domain-specific synonyms without changing semantic IDs.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. Lexicon overrides affect NL rendering only, not canonical frame IDs.
2. Replay determinism remains green.

Test gate:
- `pytest tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS8-12: CI Workflow Matrix for Prover Backends

Goal:
- Expand CI workflow to run V2 suite over `mock_smt` and `mock_fol` matrix smoke.

Target files:
- `.github/workflows/legal-v2-reasoner-ci.yml`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

Acceptance criteria:
1. Workflow runs primary full suite once plus lightweight backend matrix smoke.
2. Failure logs remain uploaded for failing jobs.

Test gate:
- Workflow validation and at least one successful dispatch run.

## HL-WS8-13: Performance Baseline Snapshot

Goal:
- Capture stable baseline timings for parse, compile, reason operations on fixture corpus.

Target files:
- `scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py` (new)
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_EXECUTION_PLAYBOOK.md`

Acceptance criteria:
1. Script emits JSON baseline artifact with per-stage timing.
2. Playbook includes interpretation and threshold guidance.

Test gate:
- Script smoke run in CI or local ops task.

## HL-WS8-14: Ticket-to-Test Traceability Table

Goal:
- Add explicit matrix mapping each WS ticket to test files and CI gates.

Target files:
- `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md`
- `docs/guides/legal_data/HYBRID_LEGAL_WS8_IMPLEMENTATION_TICKETS.md`

Acceptance criteria:
1. Every ticket has at least one listed test gate.
2. Matrix is easy to copy into issue templates.

Test gate:
- Documentation review plus lint/diagnostics clean.

## HL-WS8-15: Release Readiness Checklist v2

Goal:
- Create release checklist for shipping Hybrid V2 as a stable subsystem.

Target files:
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

Acceptance criteria:
1. Checklist includes contracts, tests, CI, observability, rollback.
2. Completion requires links to generated artifacts.

Test gate:
- Dry-run checklist walkthrough in PR description.

## 4. Suggested Priority Order

1. `HL-WS8-01` and `HL-WS8-02` (contract drift prevention).
2. `HL-WS8-04`, `HL-WS8-05`, `HL-WS8-06` (semantic safety).
3. `HL-WS8-08`, `HL-WS8-09`, `HL-WS8-10` (API/runtime hardening).
4. `HL-WS8-12`, `HL-WS8-13` (operational maturity).
5. Remaining documentation and release items.

## 5. Done Definition For WS8 Program

WS8 is complete when:

1. All high-priority tickets (`01`, `02`, `04`, `05`, `06`, `08`, `09`, `10`, `12`) are closed.
2. `Legal V2 Reasoner CI` is green on `main` for 7 consecutive days.
3. No unresolved schema drift in query/proof envelopes.
