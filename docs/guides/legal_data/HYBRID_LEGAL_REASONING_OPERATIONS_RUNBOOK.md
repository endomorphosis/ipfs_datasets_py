# Hybrid Legal Reasoning Operations Runbook

This runbook describes how to operate rollout controls and gates for hybrid legal reasoning.

Related scripts:
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_shadow_mode.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_ga_gate.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_optimizer_benchmark.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_audit_integration_smoke.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_proof_audit_integration_summary.py`
- `ipfs_datasets_py/scripts/ops/legal_data/build_shadow_mode_audit.py`
- `ipfs_datasets_py/scripts/ops/legal_data/select_formal_logic_canary_mode.py`
- `ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_ga_gate.py`
- `ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_optimizer_benchmark.py`
- `ipfs_datasets_py/scripts/ops/legal_data/export_proof_certificates_audit.py`
- `ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.py`
- `ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.sh`

## 0) Hybrid V2 Pipeline CLI

Purpose:
- Execute package-native V2 parse/normalize/compile/reasoning pipeline with default optimizer/KG/prover adapters.

Python entrypoint:
```bash
PYTHONPATH=src:ipfs_datasets_py \
  /home/barberb/municipal_scrape_workspace/.venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.py \
  --sentence "Controller shall report breach within 48 hours." \
  --jurisdiction us/federal \
  --output-json artifacts/formal_logic_tmp_verify/federal/hybrid_v2_run.json \
  --pretty
```

Shell wrapper:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.sh \
  --sentence "Vendor shall not disclose personal data unless consent recorded." \
  --jurisdiction us/federal
```

JSONL batch mode:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.sh \
  --input-jsonl /tmp/v2_sentences.jsonl \
  --sentence-field sentence \
  --output-json /tmp/v2_batch_result.json
```

Repository fixture batch mode:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.sh \
  --input-jsonl ipfs_datasets_py/tests/reasoner/fixtures/hybrid_v2_cli_batch_sentences.jsonl \
  --sentence-field sentence \
  --output-json /tmp/hybrid_v2_pipeline_fixture_batch.json \
  --pretty
```

Hook toggles:
- `--disable-optimizer`
- `--disable-kg`
- `--disable-prover`
- `--prover-backend-id mock_smt|mock_fol|smt_style|first_order`

V2 reasoner test suite:
```bash
PYTHONPATH=src:ipfs_datasets_py \
  /home/barberb/municipal_scrape_workspace/.venv/bin/python -m pytest \
  ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py \
  ipfs_datasets_py/tests/reasoner/test_hybrid_v2_cli.py \
  ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py \
  ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py \
  ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py \
  ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -q
```

GitHub Actions parity snippet:
```yaml
- name: Run Hybrid V2 reasoner suite
  run: |
    python -m pytest \
      tests/reasoner/test_hybrid_v2_blueprint.py \
      tests/reasoner/test_hybrid_v2_cli.py \
      tests/reasoner/test_hybrid_v2_parse_replay.py \
      tests/reasoner/test_hybrid_v2_compiler_parity.py \
      tests/reasoner/test_hybrid_v2_query_api_matrix.py \
      tests/reasoner/test_prover_backend_registry.py -q
  env:
    PYTHONPATH: src:${{ github.workspace }}
```

Dedicated workflow:
- `.github/workflows/legal-v2-reasoner-ci.yml`

Prover backend matrix smoke (local parity):
```bash
for backend in mock_smt mock_fol; do
  BACKEND="$backend" PYTHONPATH=src:ipfs_datasets_py \
    /home/barberb/municipal_scrape_workspace/.venv/bin/python - <<'PY'
import os
from ipfs_datasets_py.processors.legal_data.reasoner.v2_cli import run_v2_cli

backend_id = os.environ["BACKEND"]
payload = run_v2_cli(
    sentences=["Controller shall report breach within 24 hours."],
    jurisdiction="us/federal",
    enable_optimizer=True,
    enable_kg=True,
    enable_prover=True,
    prover_backend_id=backend_id,
)
summary = payload.get("summary") or {}
assert summary.get("total") == 1, summary
assert summary.get("ok") == 1, summary
assert summary.get("error") == 0, summary
assert summary.get("prover_backend_id") == backend_id, summary
assert summary.get("schema_version") == "1.0", summary
print("backend smoke passed", backend_id)
PY
done
```

## 1) Rollout Modes

### Shadow mode
Purpose:
- Run baseline and hybrid in parallel and compare outputs.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_shadow_mode.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/shadow_mode_audit.json`

Interpretation:
- `summary.shadow_ready=true` means audit checks passed.
- `summary.failure_count>0` means not ready for canary/GA promotion.

### Canary mode
Purpose:
- Route low-risk traffic to hybrid only when policy permits.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/canary_mode_decision.json`

Interpretation:
- `route=hybrid` and `hybrid_enabled=true` means hybrid route selected.
- `proof_audit_required=true` means proof audit sampling must run.

### GA gate mode
Purpose:
- Evaluate quality/safety/latency thresholds prior to GA.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_ga_gate.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/ga_gate_assessment.json`

Interpretation:
- `summary.ga_ready=true` means GA gate passed.
- failing checks list exactly which thresholds blocked promotion.

### Optimizer benchmark mode
Purpose:
- Compare quality/safety metrics with optimizers disabled vs enabled.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_optimizer_benchmark.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/optimizer_onoff_benchmark.json`

Interpretation:
- `summary.improvement_count` and `summary.regression_count` summarize directional wins/losses.
- `summary.net_score` is `improvements - regressions` across tracked metrics.

### Proof certificate audit mode
Purpose:
- Export normalized proof-certificate and certificate-to-IR trace-map artifacts for audit/review.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/proof_certificate_audit.json`

Interpretation:
- `summary.duplicate_certificate_id_count=0` indicates no certificate ID collisions in the store.
- `summary.missing_trace_map_count=0` indicates all exported certificates map to at least one IR reference.

### Canary proof-audit smoke mode
Purpose:
- Validate canary decision contract (`route=hybrid`, `proof_audit_required=true`) and proof-audit export path without running full shadow/canary/regression workloads.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh
```

Primary artifact:
- `/tmp/formal_logic_canary_proof_audit_smoke/proof_certificate_audit.smoke.json`

### Regression proof-audit smoke mode
Purpose:
- Validate regression hook contract (`RUN_PROOF_CERT_AUDIT_AFTER_RUN=1`) and proof-audit export path without running full conversion/regression workloads.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh
```

Primary artifact:
- `/tmp/formal_logic_regression_proof_audit_smoke/proof_certificate_audit.smoke.json`

### Proof-audit integration smoke mode
Purpose:
- Run both proof-audit smoke paths (canary + regression hook) and publish a consolidated summary artifact for CI checks.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_audit_integration_smoke.sh
```

Primary artifact:
- `/tmp/formal_logic_proof_audit_integration_smoke/summary.json`

Default companion artifacts:
- `/tmp/formal_logic_proof_audit_integration_smoke/triage.json`
- `/tmp/formal_logic_proof_audit_integration_smoke/triage.md`

Summary contract:
- `overall_passed=true` and `error_code="OK"` indicate full pass.
- `error_code="INTEGRATION_SMOKE_FAILED"` indicates at least one failure.
- `failure_reasons` enumerates machine-readable causes (for example `canary_exit_nonzero`, `regression_artifact_missing`).

Triage command:
```bash
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_proof_audit_integration_summary.py \
  --summary /tmp/formal_logic_proof_audit_integration_smoke/summary.json \
  --output /tmp/formal_logic_proof_audit_integration_smoke/triage.json
```

Markdown triage command:
```bash
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_proof_audit_integration_summary.py \
  --summary /tmp/formal_logic_proof_audit_integration_smoke/summary.json \
  --format markdown \
  --output /tmp/formal_logic_proof_audit_integration_smoke/triage.md
```

Triage artifact:
- `/tmp/formal_logic_proof_audit_integration_smoke/triage.json`
- `/tmp/formal_logic_proof_audit_integration_smoke/triage.md`

Integration smoke triage controls:
- `RUN_TRIAGE_AFTER_SUMMARY=1|0` (default `1`)
- `RUN_TRIAGE_MARKDOWN=1|0` (default `1`; ignored when triage generation is disabled)
- `TRIAGE_JSON_PATH=<path>`
- `TRIAGE_MARKDOWN_PATH=<path>`

## 2) Required Environment Toggles

Shared toggles:
- `LIMIT_SEGMENTS` (default `50`)

Canary toggles:
- `RISK_LEVEL=low|medium|high`
- `REQUIRE_SHADOW_READY=1|0`
- `RUN_SHADOW_FIRST=1|0`
- `RUN_PROOF_AUDIT_IF_REQUIRED=1|0` (default `1`; when decision says `proof_audit_required=true`, export proof-certificate audit artifact)

GA toggles:
- `RUN_CANARY_FIRST=1|0`
- `RUNTIME_STATS_PATH=<path>` (optional; if omitted, latency checks may be skipped by policy)
- `GA_GATE_OUTPUT_PATH=<path>`

Core conversion toggles (from regression runner):
- `ENABLE_HYBRID_IR=0|1`
- `HYBRID_IR_JURISDICTION_FALLBACK=<value>`
- `HYBRID_IR_CANONICAL_PREDICATES=1|0`
- `ALLOW_SOURCE_CONDITIONED_ROUNDTRIP=1|0`
- `ENABLE_LLM_DECODER_PASS=1|0`
- `RUN_PROOF_CERT_AUDIT_AFTER_RUN=1|0` (default `0`; run proof-certificate audit at end of regression run)

Proof certificate audit toggles:
- `PROOF_STORE_PATH=<path>`
- `PROOF_CERT_AUDIT_PATH=<path>`

## 3) Promotion Procedure

Step 1:
- Run shadow mode and inspect `shadow_mode_audit.json`.

Step 2:
- Run canary mode with `RISK_LEVEL=low` and confirm route decision plus proof-audit requirement.

Step 3:
- Run GA gate assessment and inspect failures.

Promotion rule:
- Promote only when:
  - shadow is ready,
  - canary enables hybrid under target risk profile,
  - GA gate reports `ga_ready=true`.

## 4) Failure Triage

When shadow fails:
- Inspect `checks` entries in `shadow_mode_audit.json`.
- Typical issue: quality floor miss (for example enumeration integrity).

When canary routes to baseline unexpectedly:
- Inspect `reason` in `canary_mode_decision.json`.
- Confirm risk level and shadow readiness policy settings.

When GA gate fails:
- Inspect failed `checks` in `ga_gate_assessment.json`.
- Address failures by category:
  - quality floor misses: adjust parser/compiler quality path
  - safety ceiling misses: reduce artifacts/orphans and blocker conditions
  - latency failures: optimize or adjust runtime SLO configuration

## 5) Incident Response and Rollback

Immediate rollback conditions:
- spike in error rate or timeout rate above thresholds
- safety blocker asserted (`theorem_ingestion_blocker=true`)
- shadow/canary divergence with unexplained semantic regression

Rollback actions:
1. Force baseline route (set canary to high risk or disable hybrid route).
2. Keep proof audits active for diagnostics.
3. Capture latest shadow/canary/GA artifacts for postmortem.
4. Re-enable hybrid only after shadow and GA checks pass.

## 6) Operator Checklist

Before rollout:
- [ ] Shadow audit generated and reviewed.
- [ ] Canary decision reviewed for target risk profile.
- [ ] GA assessment generated and reviewed.

After rollout:
- [ ] Archive artifacts for traceability.
- [ ] Record promotion/rollback decision and reason.
- [ ] Update TODO status and execution notes when behavior changes.

## 7) VS Code Task Usage

Use `Tasks: Run Task` in VS Code from the `ipfs_datasets_py` workspace
(`ipfs_datasets_py/.vscode/tasks.json`) and select one of the following labels:

- `Legal smoke: proof-audit canary`
  - Runs: `scripts/ops/run_formal_logic_canary_proof_audit_smoke.sh`
  - Expected artifact: `/tmp/formal_logic_canary_proof_audit_smoke/proof_certificate_audit.smoke.json`

- `Legal smoke: proof-audit regression`
  - Runs: `scripts/ops/run_formal_logic_regression_proof_audit_smoke.sh`
  - Expected artifact: `/tmp/formal_logic_regression_proof_audit_smoke/proof_certificate_audit.smoke.json`

- `Legal smoke: proof-audit integration`
  - Runs: `scripts/ops/run_formal_logic_proof_audit_integration_smoke.sh`
  - Expected artifact: `/tmp/formal_logic_proof_audit_integration_smoke/summary.json`
  - Also emits: `/tmp/formal_logic_proof_audit_integration_smoke/triage.json`, `/tmp/formal_logic_proof_audit_integration_smoke/triage.md`
  - Pass condition: `overall_passed=true` in summary JSON

- `Legal smoke: proof-audit integration (json triage only)`
  - Runs: `RUN_TRIAGE_MARKDOWN=0 scripts/ops/run_formal_logic_proof_audit_integration_smoke.sh`
  - Expected artifact: `/tmp/formal_logic_proof_audit_integration_smoke/summary.json`
  - Also emits: `/tmp/formal_logic_proof_audit_integration_smoke/triage.json`

- `Legal smoke: proof-audit integration (summary only)`
  - Runs: `RUN_TRIAGE_AFTER_SUMMARY=0 scripts/ops/run_formal_logic_proof_audit_integration_smoke.sh`
  - Expected artifact: `/tmp/formal_logic_proof_audit_integration_smoke/summary.json`
  - Does not emit triage artifacts

- `Legal smoke: proof-audit integration matrix`
  - Runs: `scripts/ops/run_formal_logic_proof_audit_integration_matrix_smoke.sh`
  - Expected artifact: `/tmp/formal_logic_proof_audit_integration_matrix_smoke/matrix_report.json`
  - Pass condition: `overall_passed=true` in matrix report JSON

## 8) Smoke Troubleshooting

When `Legal smoke: proof-audit integration` fails:

Step 1:
- Open `/tmp/formal_logic_proof_audit_integration_smoke/summary.json`.

Step 2:
- Check `error_code` and `failure_reasons` first.

Step 3:
- Then inspect `checks.canary_smoke.exit_code` and `checks.regression_smoke.exit_code`.

Step 4:
- If either exit code is non-zero, inspect:
  - `checks.canary_smoke.log_path`
  - `checks.regression_smoke.log_path`

Step 5:
- If exit codes are zero but `artifact_exists=false`, verify artifact paths:
  - `checks.canary_smoke.artifact_path`
  - `checks.regression_smoke.artifact_path`

Step 6:
- Re-run single-path smoke to isolate failures quickly:
  - `bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh`
  - `bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh`

## 9) Release Readiness Checklist v2

Use this checklist in PR descriptions before canary/GA promotion.

Contracts:
- [ ] Query/proof contract snapshots are current and reviewed.
- [ ] IR contract error-code changes are documented when applicable.
- Artifact link:

Tests:
- [ ] WS8 ticket test gates passed for changed scope.
- [ ] No unresolved schema-drift failures.
- Artifact link:

CI:
- [ ] `Legal V2 Reasoner CI` full suite is green.
- [ ] Backend smoke matrix (`mock_smt`, `mock_fol`) is green.
- Artifact link:

Observability:
- [ ] Benchmark baseline artifact generated.
- [ ] Any threshold regressions have a mitigation note.
- Artifact link:

Rollback:
- [ ] Optimizer/KG/prover rollback toggles validated.
- [ ] Incident-response conditions reviewed with release owner.
- Artifact link:

Latest local dry-run evidence (2026-03-02):
- Contracts: `tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json`, `docs/guides/legal_data/schemas/v2_check_compliance.schema.json`, `docs/guides/legal_data/schemas/v2_find_violations.schema.json`, `docs/guides/legal_data/schemas/v2_explain_proof.schema.json`
- Tests: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/pytest_reasoner_ws8.txt` (`52 passed`)
- Backend matrix parity: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_mock_smt.json`, `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_mock_fol.json` (both `passed=true`)
- Observability baseline: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/hybrid_v2_perf_baseline.json`

## 10) WS9 Local Evidence Pack

Purpose:
- Produce repeatable local artifacts proving WS9 regression gates and backend parity.

Commands:
```bash
mkdir -p /home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302

cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src:/home/barberb/municipal_scrape_workspace/ipfs_datasets_py \
  /home/barberb/municipal_scrape_workspace/.venv/bin/python -m pytest \
  tests/reasoner/test_hybrid_v2_blueprint.py \
  tests/reasoner/test_hybrid_v2_cli.py \
  tests/reasoner/test_hybrid_v2_parse_replay.py \
  tests/reasoner/test_hybrid_v2_compiler_parity.py \
  tests/reasoner/test_hybrid_v2_query_api_matrix.py \
  tests/reasoner/test_kg_enrichment_adapter.py \
  tests/reasoner/test_prover_backend_registry.py -q \
  > /home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/pytest_reasoner_ws9.txt

for backend in mock_smt mock_fol; do
  BACKEND="$backend" PYTHONPATH=src:/home/barberb/municipal_scrape_workspace/ipfs_datasets_py \
  /home/barberb/municipal_scrape_workspace/.venv/bin/python - <<'PY' \
  > /home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_${BACKEND}.json
import json
import os
from ipfs_datasets_py.processors.legal_data.reasoner.v2_cli import run_v2_cli

backend = os.environ["BACKEND"]
payload = run_v2_cli(
  sentences=["Controller shall report breach within 24 hours."],
  jurisdiction="us/federal",
  enable_optimizer=True,
  enable_kg=True,
  enable_prover=True,
  prover_backend_id=backend,
)
summary = payload.get("summary") or {}
result = {
  "backend": backend,
  "summary": summary,
  "passed": (
    summary.get("total") == 1
    and summary.get("ok") == 1
    and summary.get("error") == 0
    and summary.get("prover_backend_id") == backend
    and summary.get("schema_version") == "1.0"
  ),
}
print(json.dumps(result, indent=2, sort_keys=True))
if not result["passed"]:
  raise SystemExit(1)
PY
done
```

Expected artifact paths:
- `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/pytest_reasoner_ws9.txt`
- `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_smt.json`
- `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_fol.json`

Latest local dry-run evidence (2026-03-02):
- Tests: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/pytest_reasoner_ws9.txt` (`68 passed`).
- Backend matrix parity: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_smt.json`, `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_fol.json` (both `passed=true`).
- E2E fixture batch smoke: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/hybrid_v2_cli_batch_smoke.json` (`total=4`, `ok=4`, `error=0`).
- Standalone checklist artifact: `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/WS9_RELEASE_CHECKLIST_20260302.md`.

## 11) WS10 CI Soak Tracking

Purpose:
- Track and evidence the `7 consecutive days green` gate for `Legal V2 Reasoner CI`.

Suggested daily snapshot command (GitHub CLI):
```bash
mkdir -p /home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302

gh run list \
  --repo endomorphosis/ipfs_datasets_py \
  --workflow legal-v2-reasoner-ci.yml \
  --limit 30 \
  --json databaseId,displayTitle,conclusion,createdAt,updatedAt,url \
  > /home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_runs_$(date +%Y%m%d).json
```

Fallback when `gh` is unavailable:
```bash
curl -L --max-time 40 -sS \
  "https://api.github.com/repos/endomorphosis/ipfs_datasets_py/actions/workflows/legal-v2-reasoner-ci.yml/runs?per_page=30" \
  > /home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_runs_$(date +%Y%m%d).json
```

Tracking rule:
- Count one day as green only if at least one run for that day has `conclusion=success` and there are no failed required runs for the same day.

Current seed snapshot:
- `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/CI_SOAK_SNAPSHOT_20260302.md`
- `/home/barberb/municipal_scrape_workspace/artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_runs_20260302.json`
