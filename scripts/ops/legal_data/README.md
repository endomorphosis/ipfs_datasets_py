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
- `analyze_formal_logic_entropy.py`
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
- `collect_legal_v2_ci_soak_snapshot.py`
- `run_legal_v2_ci_soak_snapshot.sh`
- `create_ws11_github_issues.py`
- `create_ws11_github_issues.sh`

Notes:
- Packaged docket bundle inspection/read workflow:
	Use `ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py` with `--input-type packaged`
	to inspect bundle metadata without rebuilding the full packaged dataset object.
	Examples:
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --summary-only --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --summary-only --fields dataset_id,document_count,proof_store_count --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --inspect-packaged --fields latest_routing_reason,top_routing_citation --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --load-packaged-report --report-format parsed --fields latest_routing_reason,top_routing_citation`
	These packaged read-only modes do not require `--output` and use the lightweight
	manifest/provenance/report loaders instead of a full packaged docket rebuild.
- Run `run_all_state_legal_corpora_agentic.py` to drive the agentic daemon across
	state laws, state court rules, and state administrative rules with shared fetch
	caching and IPFS-backed page reuse enabled by default.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/run_all_state_legal_corpora_agentic.py --states all --max-cycles 1`
	`.venv/bin/python scripts/ops/legal_data/run_all_state_legal_corpora_agentic.py --states RI,OR --corpora laws,court --max-cycles 2 --stop-on-target-score`
	`.venv/bin/python scripts/ops/legal_data/run_all_state_legal_corpora_agentic.py --states all --skip-passed --output-root /tmp/all_state_legal_corpora_agentic`
	The runner writes `aggregated_summary.json` under the output root and emits a
	`patch_backlog` section when any corpus still fails after its cycle.
- Run `run_state_laws_agentic_full.sh` for end-to-end autonomous state-law
	collection via the actor/critic loop.
	Examples:
	`bash scripts/ops/legal_data/run_state_laws_agentic_full.sh`
	`STATES=OR MAX_ROUNDS=1 ACTORS_PER_ROUND=1 ACTOR_CONCURRENCY=1 MAX_STATUTES=0 bash scripts/ops/legal_data/run_state_laws_agentic_full.sh`
	`STATES=all MAX_ROUNDS=1 ACTORS_PER_ROUND=2 ACTOR_CONCURRENCY=2 bash scripts/ops/legal_data/run_state_laws_agentic_full.sh`
- Oregon-specific procedural/local-rules controls (used by OR scraper):
	`OREGON_CRIMINAL_PROCEDURE_CHAPTERS=131-136`
	`OREGON_LOCAL_RULE_COUNTIES=Multnomah,Washington,Lane`
	`OREGON_LOCAL_RULE_MAX_COUNTIES=10`
- Run `check_state_law_coverage.py` to enforce state-law file completeness and
	minimum per-state depth from local JSON-LD outputs.
	Examples:
	`python3 scripts/ops/legal_data/check_state_law_coverage.py`
	`python3 scripts/ops/legal_data/check_state_law_coverage.py --min-records 20`
	`python3 scripts/ops/legal_data/check_state_law_coverage.py --states AL,CT,GA,NM --min-records 5`
- `refresh_state_jsonld_quality.py` now emits structured JSON even on failures
	(interrupt/exception) so loop wrappers can persist diagnostics to `*.refresh.json`.
	Exit codes: `0` success, `1` generic error, `130` interrupt.
- Run `cleanup_procedural_rules_merged.py` to remove obvious non-substantive
	rows from merged procedural-rules JSONL and emit a cleanup report.
	Examples:
	`python3 scripts/ops/legal_data/cleanup_procedural_rules_merged.py`
	`python3 scripts/ops/legal_data/cleanup_procedural_rules_merged.py --in-place --backup ~/.ipfs_datasets/state_laws/procedural_rules/us_state_procedural_rules_merged_with_rjina.pre_cleanup_backup.jsonl`
	`python3 scripts/ops/legal_data/cleanup_procedural_rules_merged.py --require-equal-coverage`
	When `--in-place` is used, coverage-regression protection is enforced automatically and replacement is blocked if `full_both` decreases or `partial`/`none` increase.
- `supplement_procedural_rules_via_rjina.py` can run cleanup automatically after merge:
	`python3 scripts/ops/legal_data/supplement_procedural_rules_via_rjina.py --states HI KY MI --post-cleanup-merged`
	By default this enforces equal-or-better coverage during cleanup; override only for diagnostics with `--no-post-cleanup-require-equal-coverage`.
	The supplement run fails fast on nonzero post-cleanup exit by default; use `--no-fail-on-post-cleanup-error` only when you need diagnostics without failing the run.
- Run `run_procedural_rules_guarded_smoke.sh` for a one-command safety check that executes:
	1) compile checks, 2) focused unit tests, 3) guarded supplement smoke run, and 4) state-law coverage check.
	Coverage defaults to the harness target states to avoid unrelated global drift; set `COVERAGE_SCOPE=all` for full all-state coverage gating.
	Examples:
	`bash scripts/ops/legal_data/run_procedural_rules_guarded_smoke.sh`
	`STATES="MI" MIN_RECORDS=20 bash scripts/ops/legal_data/run_procedural_rules_guarded_smoke.sh`
	`COVERAGE_SCOPE=all MIN_RECORDS=20 bash scripts/ops/legal_data/run_procedural_rules_guarded_smoke.sh`
- Run `run_procedural_rules_guarded_matrix.sh` to execute multiple guarded smoke sets in parallel and write a consolidated `summary.json` under a temp matrix output dir.
	Examples:
	`bash scripts/ops/legal_data/run_procedural_rules_guarded_matrix.sh`
	`MATRIX_SETS="MI;KY MI;IN MO NH" MIN_RECORDS=20 bash scripts/ops/legal_data/run_procedural_rules_guarded_matrix.sh`
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
- Run `run_legal_v2_ci_soak_snapshot.sh` to collect Legal V2 workflow runs,
	compute consecutive green-day streak, and emit JSON/markdown soak summaries
	under `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/`.
- Run `create_ws11_github_issues.sh` to open WS11 GitHub issues from template
	bodies (dry-run by default; pass `--create` to create issues).
	`--create` requires GitHub CLI (`gh`) installed and authenticated.
	The wrapper auto-includes `~/.local/bin` in `PATH` for user-space `gh` installs.
	Example: `gh auth status && bash scripts/ops/legal_data/create_ws11_github_issues.sh --create`.
- VS Code tasks are canonical in `ipfs_datasets_py/.vscode/tasks.json`:
	`Legal smoke: proof-audit canary`,
	`Legal smoke: proof-audit regression`,
	`Legal smoke: proof-audit integration`,
	`Legal smoke: proof-audit integration (json triage only)`,
	`Legal smoke: proof-audit integration (summary only)`,
	`Legal smoke: proof-audit integration matrix`,
	`Legal smoke: proof-audit triage`,
	`Legal smoke: proof-audit triage (markdown)`.
	Workspace-root `scripts/ops/*` wrappers remain compatibility entrypoints.
