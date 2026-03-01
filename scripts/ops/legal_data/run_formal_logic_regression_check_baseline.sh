#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# Keep baseline regression artifacts isolated from hybrid runs.
export ENABLE_HYBRID_IR="${ENABLE_HYBRID_IR:-0}"
export HYBRID_IR_JURISDICTION_FALLBACK="${HYBRID_IR_JURISDICTION_FALLBACK:-}"

export REPORT_PATH="${REPORT_PATH:-artifacts/formal_logic_tmp_verify/federal/report.baseline.json}"
export RECORDS_PATH="${RECORDS_PATH:-artifacts/formal_logic_tmp_verify/federal/records.baseline.jsonl}"
export LOGIC_PATH="${LOGIC_PATH:-artifacts/formal_logic_tmp_verify/federal/logic.baseline.jsonld}"
export BASELINE_PATH="${BASELINE_PATH:-artifacts/formal_logic_tmp_verify/federal/report.pre_phase1_cleanup.json}"

# Optional positional baseline override remains supported by delegated script.
bash scripts/ops/run_formal_logic_regression_check.sh "$@"
