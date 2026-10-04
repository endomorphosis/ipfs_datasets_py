# Hybrid Legal WS10 Post-WS9 Stabilization Tickets

## 1. Purpose

This backlog defines the immediate stabilization sprint after WS9 closure.
It focuses on release confidence, drift detection, and repeatable operational evidence.

Scope assumptions:
1. WS9 implementation and local evidence pack are complete.
2. `Legal V2 Reasoner CI` remains the authoritative gate.
3. No semantic contract regressions are allowed during stabilization.

## 2. Tickets

## HL-WS10-01: CI Soak Tracking for Release Gate

Goal:
- Record and enforce the 7-day CI green requirement in a repeatable operator workflow.

Target files:
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

Acceptance criteria:
1. Runbook documents how to collect 7-day CI gate evidence.
2. TODO references explicit artifact/log path for CI soak tracking.
3. Manual status updates are deterministic and auditable.

Test gate:
- Documentation consistency review + evidence path verification.

## HL-WS10-02: Schema Drift Sentinel Regression Gate

Goal:
- Add a single deterministic gate command that checks query/proof schema stability against snapshots.

Target files:
- `tests/reasoner/test_hybrid_v2_cli.py`
- `tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json`
- `.github/workflows/legal-v2-reasoner-ci.yml`

Acceptance criteria:
1. Drift check fails with actionable diagnostics.
2. CI runs the drift gate on relevant reasoner/schema changes.
3. Local runbook command matches CI behavior.

Test gate:
- `PYTHONPATH=src:${PWD} python -m pytest tests/reasoner/test_hybrid_v2_cli.py -q`

## HL-WS10-03: Release Evidence Pack Automation

Goal:
- Provide a single script entrypoint to produce WS-style evidence bundles.

Target files:
- `scripts/ops/legal_data/`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

Acceptance criteria:
1. Script emits pytest log, backend smoke JSONs, and batch smoke JSON.
2. Output directory is parameterized by release label/date.
3. Runbook includes command and expected artifacts.

Test gate:
- Script dry run creating artifacts under `/tmp` and project `artifacts/` path.

## HL-WS10-04: Release Checklist Canonical Template

Goal:
- Standardize WS release checklist format to avoid drift across WS8/WS9/next sprints.

Target files:
- `docs/guides/legal_data/`
- `artifacts/formal_logic_tmp_verify/federal/`

Acceptance criteria:
1. Canonical checklist template exists in docs.
2. Existing WS8/WS9 checklist artifacts align to template fields.
3. Required evidence fields are explicitly enumerated.

Test gate:
- Template/doc review and path validation.

## 3. Recommended Order

1. `HL-WS10-01`
2. `HL-WS10-02`
3. `HL-WS10-03`
4. `HL-WS10-04`

## 4. Definition of Done (WS10)

1. CI soak tracking process documented and active.
2. Schema drift gate runs in CI and locally.
3. Evidence pack generation is one-command repeatable.
4. Checklist template is canonical and reused for new releases.
