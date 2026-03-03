# Hybrid Legal WS12 Issue Bodies (05-08)

Use the sections below as copy/paste issue bodies for GitHub.

## HL-WS12-05: Conflict Triage Report Builder (JSON + Markdown)

Title:
`HL-WS12-05: Conflict Triage Report Builder (JSON + Markdown)`

Body:

```markdown
## Summary
Generate deterministic conflict-triage artifacts in JSON and markdown for operator workflows.

## Scope
- Implement triage builder producing JSON + markdown outputs.
- Include remediation hints mapped to reason-code taxonomy.
- Ensure artifact generation is deterministic on same input.

## Target Files
- `ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_legal_conflict_triage.py`
- `ipfs_datasets_py/tests/reasoner/test_conflict_triage_report_builder.py`

## Acceptance Criteria
1. JSON and markdown contracts are stable.
2. Reports include remediation hints and references.
3. Repeated generation on same input is byte-stable.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_conflict_triage_report_builder.py -q`

## Notes
Keep output ordering deterministic for diff-friendly incident workflows.
```

## HL-WS12-06: Performance Budget Sentinel

Title:
`HL-WS12-06: Performance Budget Sentinel`

Body:

```markdown
## Summary
Enforce p95 latency budget gates for parse/compile/prover/explain phases.

## Scope
- Define versioned budget policy thresholds.
- Add sentinel that fails when phase budgets regress beyond tolerance.
- Emit machine-readable over-budget diagnostics for CI triage.

## Target Files
- `ipfs_datasets_py/scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py`
- `ipfs_datasets_py/scripts/ops/legal_data/assert_hybrid_v2_perf_budgets.py`
- `ipfs_datasets_py/tests/reasoner/test_perf_budget_sentinel.py`

## Acceptance Criteria
1. Budget policy is explicit and versioned.
2. Sentinel deterministically fails on threshold violations.
3. Diagnostics identify over-budget phases and deltas.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_perf_budget_sentinel.py -q`

## Notes
Keep baseline artifacts and threshold policy under source control.
```

## HL-WS12-07: Unified Release Evidence Pack v2

Title:
`HL-WS12-07: Unified Release Evidence Pack v2`

Body:

```markdown
## Summary
Ship a single-command evidence bundle combining tests, replay matrix, conflict triage, and performance budgets.

## Scope
- Extend release evidence script to include WS12 artifact set.
- Build deterministic manifest with contract snapshots + hashes.
- Validate required artifact presence and fail on missing outputs.

## Target Files
- `ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_release_evidence_pack.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_v2_evidence_manifest.py`
- `ipfs_datasets_py/tests/reasoner/test_release_evidence_pack_v2.py`

## Acceptance Criteria
1. One command emits complete WS12 evidence pack.
2. Manifest includes hashes and contract snapshot references.
3. Missing artifacts fail validation deterministically.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_release_evidence_pack_v2.py -q`

## Notes
Retain backward compatibility with existing WS10/WS11 evidence directory conventions.
```

## HL-WS12-08: Runbook + TODO Operational Closure

Title:
`HL-WS12-08: Runbook + TODO Operational Closure`

Body:

```markdown
## Summary
Close WS12 with runbook/TODO/checklist updates reflecting new commands, artifacts, and promotion gates.

## Scope
- Update runbook with WS12 command paths and artifact expectations.
- Update TODO board with WS12 backlog + evidence references.
- Extend release checklist template to include WS12 quality/latency/triage requirements.

## Target Files
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`
- `ipfs_datasets_py/docs/guides/legal_data/templates/HYBRID_LEGAL_RELEASE_CHECKLIST_TEMPLATE.md`

## Acceptance Criteria
1. Runbook reflects WS12 commands and artifacts.
2. TODO board reflects WS12 execution tracking.
3. Checklist template includes WS12-specific gate checks.

## Test Gate
`python3 -m pytest -q` on touched WS12 test modules and smoke command execution.

## Notes
Keep links and command snippets executable from workspace root.
```
