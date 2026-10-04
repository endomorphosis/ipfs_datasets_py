#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

LIMIT_SEGMENTS="${LIMIT_SEGMENTS:-50}"
BASELINE_PATH="${BASELINE_PATH:-artifacts/formal_logic_tmp_verify/federal/report.pre_phase1_cleanup.json}"
OPTIMIZER_OFF_REPORT="${OPTIMIZER_OFF_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.optimizer_off.json}"
OPTIMIZER_ON_REPORT="${OPTIMIZER_ON_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.optimizer_on.json}"
OPTIMIZER_BENCHMARK_PATH="${OPTIMIZER_BENCHMARK_PATH:-artifacts/formal_logic_tmp_verify/federal/optimizer_onoff_benchmark.json}"

echo "[optimizer-benchmark 1/4] Running optimizer-off regression..."
LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
BASELINE_PATH="$BASELINE_PATH" \
REPORT_PATH="$OPTIMIZER_OFF_REPORT" \
ENABLE_HYBRID_IR=1 \
HYBRID_IR_JURISDICTION_FALLBACK=Federal \
ENABLE_POST_PARSE_OPTIMIZERS=0 \
ENABLE_POST_COMPILE_OPTIMIZERS=0 \
ENABLE_LLM_DECODER_PASS=0 \
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check.sh

echo "[optimizer-benchmark 2/4] Running optimizer-on regression..."
LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
BASELINE_PATH="$BASELINE_PATH" \
REPORT_PATH="$OPTIMIZER_ON_REPORT" \
ENABLE_HYBRID_IR=1 \
HYBRID_IR_JURISDICTION_FALLBACK=Federal \
ENABLE_POST_PARSE_OPTIMIZERS=1 \
ENABLE_POST_COMPILE_OPTIMIZERS=1 \
ENABLE_LLM_DECODER_PASS=0 \
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check.sh

echo "[optimizer-benchmark 3/4] Building benchmark artifact..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_optimizer_benchmark.py \
  --optimizer-off "$OPTIMIZER_OFF_REPORT" \
  --optimizer-on "$OPTIMIZER_ON_REPORT" \
  --output "$OPTIMIZER_BENCHMARK_PATH"

echo "[optimizer-benchmark 4/4] Printing side-by-side metric comparison..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/compare_formal_logic_reports.py \
  --baseline "$OPTIMIZER_OFF_REPORT" \
  --candidate "$OPTIMIZER_ON_REPORT"

echo "[optimizer-benchmark] Complete. Benchmark: $OPTIMIZER_BENCHMARK_PATH"
