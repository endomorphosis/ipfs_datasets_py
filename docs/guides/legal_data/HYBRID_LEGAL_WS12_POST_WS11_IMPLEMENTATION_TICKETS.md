# Hybrid Legal WS12 Post-WS11 Implementation Tickets

## 1. Purpose

WS12 operationalizes post-WS11 hardening: deterministic policy-pack resolution, cross-jurisdiction replay guarantees, conflict-triage automation, and unified release evidence governance.

Upstream references:
- `HYBRID_LEGAL_COMPREHENSIVE_IMPROVEMENT_PLAN.md` (section `12. Post-WS11 Comprehensive Improvement Plan (WS12)`)
- `HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `HYBRID_LEGAL_REASONING_TODO.md`

Issue body templates:
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS12_ISSUE_BODIES_01_04.md`
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS12_ISSUE_BODIES_05_08.md`

Bulk issue kickoff:
- Dry-run: `bash ipfs_datasets_py/scripts/ops/legal_data/create_ws12_github_issues.sh`
- Create: `bash ipfs_datasets_py/scripts/ops/legal_data/create_ws12_github_issues.sh --create`

Created issues (2026-03-03):
- Meta tracker: https://github.com/endomorphosis/ipfs_datasets_py/issues/1187
- `HL-WS12-01`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1179
- `HL-WS12-02`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1180
- `HL-WS12-03`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1181
- `HL-WS12-04`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1182
- `HL-WS12-05`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1183
- `HL-WS12-06`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1184
- `HL-WS12-07`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1185
- `HL-WS12-08`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1186

Governance status (2026-03-03):
- Milestone `WS12 Post-WS11 Hardening` applied to issues `1179`-`1187`.
- Assignee `@endomorphosis` applied to issues `1179`-`1187`.
- Dependency comment marker `[ws12-dependency-map-v1]` posted on issues `1180`-`1187`.

## 2. Ticket Backlog

## HL-WS12-01: Policy Pack Schema + Validator

Goal:
- Define and enforce canonical policy-pack schema with stable machine-readable validation errors.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/policy_pack.py`
- `ipfs_datasets_py/tests/reasoner/test_policy_pack_schema.py`

Acceptance criteria:
1. Required fields are validated (`jurisdiction`, `effective_date`, `priority_policy`, `exception_policy`, `temporal_policy`).
2. Missing/invalid fields fail with stable error codes.
3. Policy-pack schema version is explicit and regression-locked.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_policy_pack_schema.py -q`

## HL-WS12-02: Deterministic Policy Resolver

Goal:
- Resolve policy-pack selection deterministically for every `(jurisdiction, date, query)` input.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/policy_resolver.py`
- `ipfs_datasets_py/tests/reasoner/test_policy_resolver_determinism.py`

Acceptance criteria:
1. Resolver emits stable selected policy ID across replay.
2. Resolver decision envelope includes deterministic trace fields.
3. Tie-break behavior is explicit and regression-tested.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_policy_resolver_determinism.py -q`

## HL-WS12-03: Multi-Jurisdiction Replay Matrix

Goal:
- Add deterministic replay matrix for Federal + at least two State policy profiles.

Target files:
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/jurisdiction_replay_matrix_v1.json`

Acceptance criteria:
1. Matrix covers required jurisdictions and expected statuses.
2. Proof IDs and reason codes are stable in replay.
3. Drift in expected outputs triggers hard gate failure.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## HL-WS12-04: Proof Conflict Taxonomy + Reason Codes

Goal:
- Enforce standardized conflict taxonomy with reason-code completeness.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_conflict_reason_codes.py`

Acceptance criteria:
1. Conflict classes include modal/temporal/exception precedence.
2. Every conflict path emits exactly one registered reason code.
3. Unknown conflict classes fail with deterministic contract error.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_conflict_reason_codes.py -q`

## HL-WS12-05: Conflict Triage Report Builder (JSON + Markdown)

Goal:
- Generate deterministic triage artifacts from conflict outputs for operator workflows.

Target files:
- `ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_legal_conflict_triage.py`
- `ipfs_datasets_py/tests/reasoner/test_conflict_triage_report_builder.py`

Acceptance criteria:
1. JSON and markdown report formats are contract-stable.
2. Reports include remediation playbook pointers.
3. Regeneration on same input is byte-stable.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_conflict_triage_report_builder.py -q`

## HL-WS12-06: Performance Budget Sentinel

Goal:
- Enforce p95 budget gates for parse, compile, prover, and explanation phases.

Target files:
- `ipfs_datasets_py/scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py`
- `ipfs_datasets_py/scripts/ops/legal_data/assert_hybrid_v2_perf_budgets.py`
- `ipfs_datasets_py/tests/reasoner/test_perf_budget_sentinel.py`

Acceptance criteria:
1. Budget policy is explicit and versioned.
2. Sentinel fails when any phase exceeds configured tolerance.
3. Output includes machine-readable over-budget diagnostics.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_perf_budget_sentinel.py -q`

## HL-WS12-07: Unified Release Evidence Pack v2

Goal:
- Provide single-command evidence bundle combining tests, replay matrix, conflict triage, and performance budgets.

Target files:
- `ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_release_evidence_pack.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_v2_evidence_manifest.py`
- `ipfs_datasets_py/tests/reasoner/test_release_evidence_pack_v2.py`

Acceptance criteria:
1. One command emits full artifact set under deterministic directory structure.
2. Manifest includes contract snapshots and hash summary.
3. Missing required artifacts fail pack validation.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_release_evidence_pack_v2.py -q`

## HL-WS12-08: Runbook + TODO Operational Closure

Goal:
- Close WS12 with updated runbook/TODO instructions and release checklist mappings.

Target files:
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`
- `ipfs_datasets_py/docs/guides/legal_data/templates/HYBRID_LEGAL_RELEASE_CHECKLIST_TEMPLATE.md`

Acceptance criteria:
1. Runbook includes WS12 commands and expected artifacts.
2. TODO board tracks WS12 issues and evidence references.
3. Checklist template reflects WS12 quality/latency/triage requirements.

Test gate:
- `python3 -m pytest -q` on touched WS12 test modules and smoke command execution.

## 3. Dependency Order

Recommended order:
1. `HL-WS12-01` -> `HL-WS12-02`
2. `HL-WS12-03` and `HL-WS12-04`
3. `HL-WS12-05`
4. `HL-WS12-06` and `HL-WS12-07`
5. `HL-WS12-08`

Parallel-safe groups:
- `HL-WS12-03` + `HL-WS12-04` after policy resolver lock.
- `HL-WS12-06` + `HL-WS12-07` after replay matrix is stable.

## 4. Definition of Done (WS12)

1. All WS12 ticket gates pass in local/CI parity.
2. Unified evidence pack v2 is generated and archived.
3. Runbook and TODO references are current and reproducible.