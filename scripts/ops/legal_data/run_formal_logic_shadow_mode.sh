#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

export LIMIT_SEGMENTS="${LIMIT_SEGMENTS:-50}"

BASELINE_REPORT="${BASELINE_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.baseline.json}"
HYBRID_REPORT="${HYBRID_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.hybrid.json}"
SHADOW_AUDIT_PATH="${SHADOW_AUDIT_PATH:-artifacts/formal_logic_tmp_verify/federal/shadow_mode_audit.json}"

echo "[shadow 1/4] Running baseline formal logic regression..."
LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
  bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check_baseline.sh

echo "[shadow 2/4] Running hybrid formal logic regression..."
LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
  bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check_hybrid.sh

echo "[shadow 3/4] Printing side-by-side metric comparison..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/compare_formal_logic_reports.py \
  --baseline "$BASELINE_REPORT" \
  --candidate "$HYBRID_REPORT"

echo "[shadow 4/4] Building machine-readable shadow mode audit..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/build_shadow_mode_audit.py \
  --baseline "$BASELINE_REPORT" \
  --candidate "$HYBRID_REPORT" \
  --output "$SHADOW_AUDIT_PATH"

echo "[shadow] Complete. Audit: $SHADOW_AUDIT_PATH"
