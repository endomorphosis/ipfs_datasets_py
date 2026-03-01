# Legal Data Ops Scripts

This directory consolidates legal/formal-logic operational scripts under the
`ipfs_datasets_py` project tree.

Copied from workspace-level `scripts/ops/`:
- `convert_legal_corpus_to_formal_logic.py`
- `analyze_formal_logic_low_tail.py`
- `generate_decoder_preview.py`
- `run_formal_logic_corpus_batches.py`
- `compare_formal_logic_reports.py`
- `build_semantic_drift_dashboard.py`
- `run_formal_logic_regression_check.sh`
- `run_formal_logic_regression_check_baseline.sh`
- `run_formal_logic_regression_check_hybrid.sh`
- `assess_formal_logic_optimizer_benchmark.py`
- `run_formal_logic_optimizer_benchmark.sh`
- `export_proof_certificates_audit.py`
- `run_formal_logic_proof_certificate_audit.sh`
- `run_formal_logic_canary_proof_audit_smoke.sh`
- `run_formal_logic_regression_proof_audit_smoke.sh`
- `run_formal_logic_proof_audit_integration_smoke.sh`
- `run_formal_logic_proof_audit_integration_matrix_smoke.sh`
- `assess_formal_logic_proof_audit_integration_summary.py`

Notes:
- Set `RUN_PROOF_CERT_AUDIT_AFTER_RUN=1` when invoking
	`run_formal_logic_regression_check.sh` to auto-export
	`proof_certificate_audit.json` after conversion/analysis complete.
- `run_formal_logic_canary_mode.sh` now auto-runs proof-certificate audit export
	when the canary decision includes `proof_audit_required=true`
	(toggle with `RUN_PROOF_AUDIT_IF_REQUIRED=1|0`).
- Run `run_formal_logic_canary_proof_audit_smoke.sh` for a fast synthetic
	validation of the canary proof-audit contract and export path.
- Run `run_formal_logic_regression_proof_audit_smoke.sh` for a fast synthetic
	validation of the regression proof-audit hook contract and export path.
- Run `run_formal_logic_proof_audit_integration_smoke.sh` to execute both
	proof-audit smoke paths and emit a consolidated pass/fail summary JSON.
	By default it also emits `triage.json` and `triage.md` in the same temp dir;
	set `RUN_TRIAGE_AFTER_SUMMARY=0` to skip triage generation.
- Run `run_formal_logic_proof_audit_integration_matrix_smoke.sh` to execute
	all integration modes (`full`, `json_only`, `summary_only`) and emit a
	single matrix report at
	`/tmp/formal_logic_proof_audit_integration_matrix_smoke/matrix_report.json`.
- Run `assess_formal_logic_proof_audit_integration_summary.py` to map
	integration-smoke `failure_reasons` to actionable remediation commands.
	Use `--format markdown` to emit a human-readable incident report.
- VS Code tasks are available in workspace root `.vscode/tasks.json`:
	`Legal smoke: proof-audit canary`,
	`Legal smoke: proof-audit regression`,
	`Legal smoke: proof-audit integration`,
	`Legal smoke: proof-audit integration (json triage only)`,
	`Legal smoke: proof-audit integration (summary only)`,
	`Legal smoke: proof-audit integration matrix`,
	`Legal smoke: proof-audit triage`,
	`Legal smoke: proof-audit triage (markdown)`.
