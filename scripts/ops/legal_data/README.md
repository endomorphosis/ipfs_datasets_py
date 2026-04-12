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
- Run `build_canonical_corpus_semantic_index.py` to generate a semantic sidecar
	for a canonical parquet slice when a corpus is missing an embeddings/FAISS
	index or when you want to rebuild one locally.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/build_canonical_corpus_semantic_index.py --corpus-key state_laws --canonical-parquet ~/.ipfs_datasets/state_laws/state_laws_parquet_cid/STATE-MN.parquet --state MN --json`
	`.venv/bin/python scripts/ops/legal_data/build_canonical_corpus_semantic_index.py --corpus-key federal_register --canonical-parquet ~/.ipfs_datasets/federal_register/federal_register.parquet --no-faiss`
	`.venv/bin/python scripts/ops/legal_data/build_canonical_corpus_semantic_index.py --corpus-key state_laws --canonical-parquet ~/.ipfs_datasets/state_laws/state_laws_parquet_cid/STATE-MN.parquet --state MN --publish-to-hf --hf-token $HF_TOKEN --include-canonical-parquet`
	This writes an `_embeddings.parquet` companion automatically and, when the
	local `faiss` build supports it, also writes a FAISS index plus metadata
	parquet for direct semantic retrieval. When `--publish-to-hf` is used, the
	generated sidecars, and optionally the canonical parquet itself, are uploaded
	back to the target JusticeDAO dataset repo.
- Run `store_huggingface_token.py` to place a Hugging Face token into a usable
	secret backend for this machine.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/store_huggingface_token.py --backend auto --json`
	`HF_TOKEN=... .venv/bin/python scripts/ops/legal_data/store_huggingface_token.py --backend keyring --service huggingface_hub --account endomorphosis`
	`HF_TOKEN=... .venv/bin/python scripts/ops/legal_data/store_huggingface_token.py --backend hf-local --json`
	In `auto` mode the helper tries the system keyring first, but falls back to
	Hugging Face's local token store if the secret-service backend is unavailable
	or noninteractive.
- Run `run_bluebook_linker_fuzz_harness.py` to have `llm_router` generate
	Bluebook-style citations, run them through the linker with Hugging Face
	dataset fallback enabled, and optionally recover/merge unresolved citations
	into the local canonical parquet path that later gets published to HF.
	The harness now supports deterministic stratified seeded sampling across
	corpus/state/source partitions and writes a patch backlog artifact for
	statistically actionable failures.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/run_bluebook_linker_fuzz_harness.py --samples 20 --provider openrouter --model openai/gpt-4.1-mini --states MN,OR,NY --corpora us_code,state_laws,caselaw_access_project --json`
	`.venv/bin/python scripts/ops/legal_data/run_bluebook_linker_fuzz_harness.py --samples 20 --seed-from-corpora --seed-examples-per-corpus 3 --states MN,OR,NY --corpora us_code,state_laws,state_admin_rules,caselaw_access_project --json`
	`.venv/bin/python scripts/ops/legal_data/run_bluebook_linker_fuzz_harness.py --samples 60 --seed-only --seed-from-corpora --states MN,OR,NY --corpora us_code,state_laws,state_admin_rules,state_court_rules,caselaw_access_project --seed-examples-per-corpus 12 --max-seed-examples-per-state 4 --max-seed-examples-per-source 2 --sampling-shuffle-seed 11 --max-acceptable-failure-rate 0.08 --min-actionable-failures 3 --merge-recovered-rows --json`
	`.venv/bin/python scripts/ops/legal_data/run_bluebook_linker_fuzz_harness.py --samples 30 --merge-recovered-rows --output-dir /tmp/bluebook_fuzz_run`
	`HF_TOKEN=... .venv/bin/python scripts/ops/legal_data/run_bluebook_linker_fuzz_harness.py --samples 12 --publish-to-hf --hf-token $HF_TOKEN`
	The run artifact is written to `bluebook_linker_fuzz_run.json` and the
	actionable scraper patch queue is written to
	`bluebook_linker_fuzz_patch_backlog.json` under `--output-dir`.
- Run `export_courtlistener_docket_single_bundle.py` to ingest a CourtListener
	docket, attach public RECAP evidence and optional public filing-page PDFs, and
	export a single parquet bundle with documents, filings, acquisition queue,
	BM25 rows, vector rows, and knowledge-graph rows.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/export_courtlistener_docket_single_bundle.py --docket-id 67658002 --filing-url "https://www.courtlistener.com/docket/67658002/american-alliance-for-equal-rights-v-fearless-fund-management-llc-filing/" --output-parquet /tmp/fearless_single_bundle.parquet --strict-evidence-mode --write-enriched-json /tmp/fearless_enriched.json --json`
	`.venv/bin/python scripts/ops/legal_data/export_courtlistener_docket_single_bundle.py --docket-id 67658002 --output-parquet /tmp/fearless_full.parquet`
	`.venv/bin/python scripts/ops/legal_data/export_courtlistener_docket_single_bundle.py --docket-id 67658002 --input-enriched-json /tmp/fearless_enriched.json --output-parquet /tmp/fearless_from_cache.parquet --strict-evidence-mode`
	Use embeddings_router + chunking by passing embedding flags, for example:
	`.venv/bin/python scripts/ops/legal_data/export_courtlistener_docket_single_bundle.py --docket-id 67658002 --output-parquet /tmp/fearless_embeddings.parquet --embeddings-model "thenlper/gte-small" --embeddings-chunking-strategy sentences --embeddings-batch-size 64 --embeddings-parallel-batches 4`
	Use `--strict-evidence-mode` when you want the bundle built from the
	`plain_text+` subset instead of the full enriched docket payload.
- Run `export_workspace_dataset_single_bundle.py` to ingest a workspace corpus
	(email, Discord, Google Voice, directories, or custom JSON) and export a
	single parquet bundle with documents, collections, BM25 rows, vector rows, and
	knowledge-graph rows. When `--input-path` is used without `--input-type`, the
	script auto-detects supported source shapes for directories, Google Voice
	manifests, Discord exports, email exports, and generic workspace JSON.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-json /tmp/workspace_payload.json --output-parquet /tmp/workspace_bundle.parquet --json`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-directory /tmp/evidence_dir --output-parquet /tmp/workspace_bundle.parquet --workspace-id ws-01 --workspace-name "Evidence Workspace" --source-type directory --glob-pattern "*.txt"`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-json /tmp/workspace.json --output-parquet /tmp/workspace_bundle.parquet --strict-evidence-mode --write-normalized-json /tmp/workspace_dataset.json --json`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-directory /tmp/mailbox --workspace-id mailbox-01 --workspace-name "Consumer Mailbox" --source-type email --output-parquet /tmp/mailbox_bundle.parquet`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-path /tmp/google_voice_manifest.json --output-parquet /tmp/google_voice_bundle.parquet --strict-evidence-mode`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-path /tmp/discord_export.json --output-parquet /tmp/discord_bundle.parquet`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-path /tmp/email_export.json --output-parquet /tmp/email_bundle.parquet`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-path /tmp/imap_snippets_summary.json --output-parquet /tmp/imap_bundle.parquet`
	Explicit typing remains available when you want to pin the route rather than rely on auto-detection:
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-type google-voice-manifest --input-path /tmp/google_voice_manifest.json --output-parquet /tmp/google_voice_bundle.parquet --strict-evidence-mode`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-type discord-export --input-path /tmp/discord_export.json --output-parquet /tmp/discord_bundle.parquet`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-type email-export --input-path /tmp/email_export.json --output-parquet /tmp/email_bundle.parquet`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-type imap-snippet-summary --input-path /tmp/imap_snippets_summary.json --output-parquet /tmp/imap_bundle.parquet`
	To enable real embeddings + chunking:
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_single_bundle.py --input-directory /tmp/mailbox --output-parquet /tmp/mailbox_bundle.parquet --embeddings-model "thenlper/gte-small" --embeddings-chunking-strategy sentences --embeddings-batch-size 64 --embeddings-parallel-batches 4`
	Use `--strict-evidence-mode` when you want the bundle built from the
	`plain_text+` retrieval subset instead of the full normalized workspace payload.
- Run `export_workspace_dataset_bundle.py` to package a workspace dataset into
	chain-loadable parquet (and optional CAR) artifacts similar to docket bundles.
	When `--input-path` is used without `--input-type`, the script auto-detects
	the same supported source shapes as the single-bundle exporter.
	Examples:
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_bundle.py --input-json /tmp/workspace.json --output-dir /tmp/workspace_bundle --package-name workspace_bundle --json`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_bundle.py --input-directory /tmp/mailbox --workspace-id mailbox-01 --workspace-name "Consumer Mailbox" --source-type email --output-dir /tmp/mailbox_bundle --no-car`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_bundle.py --input-path /tmp/email_export.json --output-dir /tmp/email_bundle --package-name email_bundle --no-car --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/workspace_cli.py --action package --input-json /tmp/workspace.json --output-dir /tmp/workspace_bundle --package-name workspace_bundle --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/workspace_cli.py --action package-summary --input-path /tmp/workspace_bundle/bundle_manifest.json --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/workspace_cli.py --action search-bm25 --input-path /tmp/google_voice_bundle.parquet --query inspection --top-k 5`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/workspace_cli.py --action search-vector --input-path /tmp/google_voice_bundle.parquet --query inspection --top-k 5`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/workspace_cli.py --action package-search-bm25 --input-path /tmp/google_voice_bundle/bundle_manifest.json --query inspection --top-k 5 --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/workspace_cli.py --action package-search-vector --input-path /tmp/google_voice_bundle/bundle_manifest.json --query inspection --top-k 5 --json`

- Legal PDF helper CLI
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action validate-manifest --manifest-path /home/barberb/HACC/workspace/combined_state_court_packet_manifest.json --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action count-pages --input-path /tmp/packet.pdf --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action render-binder-title --output-path /tmp/binder_title.pdf --lean-mode`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action merge-pdfs --input-paths /tmp/front.pdf /tmp/table.pdf /tmp/packet_a.pdf --output-path /tmp/binder.pdf`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action build-court-filing-packet --input-paths /tmp/motion.md /tmp/memo.md --output-dir /tmp/filing_pdfs --packet-output-path /tmp/filing_packet.pdf --contact-block "Benjamin Jay Barber, pro se<br/>Defendant" --court-name "IN THE CLACKAMAS COUNTY JUSTICE COURT" --state-name "STATE OF OREGON" --caption-left "PLAINTIFF,<br/>v.<br/>DEFENDANT."`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action build-court-filing-packet-from-manifest --manifest-path /home/barberb/HACC/workspace/combined_state_court_packet_manifest.json --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action build-exhibit-binder-from-manifest --manifest-path /home/barberb/HACC/workspace/exhibit-binder-court-ready/exhibit_binder_manifest.json --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/legal_pdf_cli.py --action build-full-evidence-binder-from-manifest --manifest-path /home/barberb/HACC/workspace/full_evidence_binder_manifest.json --lean-mode --json`
	`.venv/bin/python ipfs_datasets_cli.py legal-pdf --action build-exhibit-binder --front-pdf /tmp/front.pdf --table-pdf /tmp/table.pdf --packet-pdfs /tmp/packet_a.pdf /tmp/packet_b.pdf --output-path /tmp/binder.pdf`
	Manifest format guide: [docs/guides/legal_pdf_manifests.md](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/guides/legal_pdf_manifests.md)
	Explicit typing remains available when you want to pin the route:
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_bundle.py --input-type google-voice-manifest --input-path /tmp/google_voice_manifest.json --output-dir /tmp/google_voice_bundle --package-name google_voice_bundle --no-car`
	`.venv/bin/python scripts/ops/legal_data/export_workspace_dataset_bundle.py --input-type imap-snippet-summary --input-path /tmp/imap_snippets_summary.json --output-dir /tmp/imap_bundle --package-name imap_bundle --no-car`
	Search actions return both flat `results` and grouped bundle-aware `grouped_results`; text mode renders bundle groups inline so Google Voice parent events, enrichments, and readable attachments appear together.
- Packaged docket bundle inspection/read workflow:
	Use `ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py` with `--input-type packaged`
	to inspect bundle metadata without rebuilding the full packaged dataset object.
	Prefer `--packaged-action` for scripted use; the older mode flags remain supported
	for compatibility.
	Examples:
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action summary --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action summary --fields dataset_id,document_count,proof_store_count --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action inspect --fields latest_routing_reason,top_routing_citation --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action report --report-format parsed --fields latest_routing_reason,top_routing_citation`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --citation-source-audit --fields citation_count,matched_citation_count,unmatched_citation_count --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --recover-citation-sources --fields feedback_entry_count,recovery_count --json`
	Compatibility examples:
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --summary-only --json`
	`.venv/bin/python ipfs_datasets_py/ipfs_datasets_py/cli/docket_cli.py --input-type packaged --input-path /path/to/bundle_manifest.json --inspect-packaged --fields latest_routing_reason,top_routing_citation --json`
	These packaged read-only modes do not require `--output` and use the lightweight
	manifest/provenance/report loaders instead of a full packaged docket rebuild.
	Packaged `--citation-source-audit` and `--recover-citation-sources` now also stay on
	the manifest-based path, so they avoid rebuilding the full packaged docket object
	unless you explicitly request an enriched dataset operation such as `--enrich-query`.
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
