#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

TMP_DIR="${TMP_DIR:-/tmp/formal_logic_proof_audit_integration_smoke}"
mkdir -p "$TMP_DIR"

SUMMARY_PATH="${SUMMARY_PATH:-$TMP_DIR/summary.json}"
TRIAGE_JSON_PATH="${TRIAGE_JSON_PATH:-$TMP_DIR/triage.json}"
TRIAGE_MARKDOWN_PATH="${TRIAGE_MARKDOWN_PATH:-$TMP_DIR/triage.md}"
CANARY_LOG_PATH="${CANARY_LOG_PATH:-$TMP_DIR/canary_smoke.log}"
REGRESSION_LOG_PATH="${REGRESSION_LOG_PATH:-$TMP_DIR/regression_smoke.log}"

RUN_TRIAGE_AFTER_SUMMARY="${RUN_TRIAGE_AFTER_SUMMARY:-1}"
RUN_TRIAGE_MARKDOWN="${RUN_TRIAGE_MARKDOWN:-1}"

CANARY_ARTIFACT="${CANARY_ARTIFACT:-/tmp/formal_logic_canary_proof_audit_smoke/proof_certificate_audit.smoke.json}"
REGRESSION_ARTIFACT="${REGRESSION_ARTIFACT:-/tmp/formal_logic_regression_proof_audit_smoke/proof_certificate_audit.smoke.json}"

echo "[integration-smoke 1/3] Running canary proof-audit smoke..."
set +e
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh >"$CANARY_LOG_PATH" 2>&1
CANARY_STATUS=$?
set -e

echo "[integration-smoke 2/3] Running regression proof-audit smoke..."
set +e
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh >"$REGRESSION_LOG_PATH" 2>&1
REGRESSION_STATUS=$?
set -e

CANARY_ARTIFACT_EXISTS=0
REGRESSION_ARTIFACT_EXISTS=0
if [[ -f "$CANARY_ARTIFACT" ]]; then
  CANARY_ARTIFACT_EXISTS=1
fi
if [[ -f "$REGRESSION_ARTIFACT" ]]; then
  REGRESSION_ARTIFACT_EXISTS=1
fi

PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' \
  "$SUMMARY_PATH" "$CANARY_STATUS" "$REGRESSION_STATUS" "$CANARY_ARTIFACT_EXISTS" "$REGRESSION_ARTIFACT_EXISTS" \
  "$CANARY_ARTIFACT" "$REGRESSION_ARTIFACT" "$CANARY_LOG_PATH" "$REGRESSION_LOG_PATH"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    summary_path,
    canary_status,
    regression_status,
    canary_artifact_exists,
    regression_artifact_exists,
    canary_artifact,
    regression_artifact,
    canary_log,
    regression_log,
) = sys.argv[1:]

canary_status_i = int(canary_status)
regression_status_i = int(regression_status)
canary_artifact_ok = bool(int(canary_artifact_exists))
regression_artifact_ok = bool(int(regression_artifact_exists))

overall_passed = (
    canary_status_i == 0
    and regression_status_i == 0
    and canary_artifact_ok
    and regression_artifact_ok
)

failure_reasons = []
if canary_status_i != 0:
  failure_reasons.append("canary_exit_nonzero")
if regression_status_i != 0:
  failure_reasons.append("regression_exit_nonzero")
if not canary_artifact_ok:
  failure_reasons.append("canary_artifact_missing")
if not regression_artifact_ok:
  failure_reasons.append("regression_artifact_missing")

error_code = "OK" if overall_passed else "INTEGRATION_SMOKE_FAILED"

payload = {
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "overall_passed": overall_passed,
  "error_code": error_code,
  "failure_reasons": failure_reasons,
    "checks": {
        "canary_smoke": {
            "exit_code": canary_status_i,
            "artifact_exists": canary_artifact_ok,
            "artifact_path": canary_artifact,
            "log_path": canary_log,
        },
        "regression_smoke": {
            "exit_code": regression_status_i,
            "artifact_exists": regression_artifact_ok,
            "artifact_path": regression_artifact,
            "log_path": regression_log,
        },
    },
}

p = Path(summary_path)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(summary_path)
PY

echo "[integration-smoke 3/3] Wrote summary: $SUMMARY_PATH"

if [[ "$RUN_TRIAGE_AFTER_SUMMARY" == "1" ]]; then
  echo "[integration-smoke] Generating triage JSON: $TRIAGE_JSON_PATH"
  if ! PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
    ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_proof_audit_integration_summary.py \
    --summary "$SUMMARY_PATH" \
    --output "$TRIAGE_JSON_PATH"; then
    echo "[integration-smoke] WARNING: triage JSON generation failed"
  fi

  if [[ "$RUN_TRIAGE_MARKDOWN" == "1" ]]; then
    echo "[integration-smoke] Generating triage markdown: $TRIAGE_MARKDOWN_PATH"
    if ! PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
      ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_proof_audit_integration_summary.py \
      --summary "$SUMMARY_PATH" \
      --format markdown \
      --output "$TRIAGE_MARKDOWN_PATH"; then
      echo "[integration-smoke] WARNING: triage markdown generation failed"
    fi
  fi
fi

if [[ "$CANARY_STATUS" -eq 0 && "$REGRESSION_STATUS" -eq 0 && "$CANARY_ARTIFACT_EXISTS" -eq 1 && "$REGRESSION_ARTIFACT_EXISTS" -eq 1 ]]; then
  echo "[integration-smoke] PASS"
  if [[ "$RUN_TRIAGE_AFTER_SUMMARY" == "1" ]]; then
    echo "[integration-smoke] Triage JSON: $TRIAGE_JSON_PATH"
    if [[ "$RUN_TRIAGE_MARKDOWN" == "1" ]]; then
      echo "[integration-smoke] Triage markdown: $TRIAGE_MARKDOWN_PATH"
    fi
  fi
  exit 0
fi

echo "[integration-smoke] FAIL"
echo "[integration-smoke] Summary: $SUMMARY_PATH"
if [[ "$RUN_TRIAGE_AFTER_SUMMARY" == "1" ]]; then
  echo "[integration-smoke] Triage JSON: $TRIAGE_JSON_PATH"
  if [[ "$RUN_TRIAGE_MARKDOWN" == "1" ]]; then
    echo "[integration-smoke] Triage markdown: $TRIAGE_MARKDOWN_PATH"
  fi
fi
echo "[integration-smoke] Canary log: $CANARY_LOG_PATH"
echo "[integration-smoke] Regression log: $REGRESSION_LOG_PATH"
echo "[integration-smoke] --- canary log tail ---"
tail -n 20 "$CANARY_LOG_PATH" || true
echo "[integration-smoke] --- regression log tail ---"
tail -n 20 "$REGRESSION_LOG_PATH" || true
exit 1
