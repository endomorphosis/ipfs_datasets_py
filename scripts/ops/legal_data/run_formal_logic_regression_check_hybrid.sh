#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# Keep hybrid regression artifacts isolated from default runs.
export ENABLE_HYBRID_IR="${ENABLE_HYBRID_IR:-1}"
export HYBRID_IR_JURISDICTION_FALLBACK="${HYBRID_IR_JURISDICTION_FALLBACK:-Federal}"

export REPORT_PATH="${REPORT_PATH:-artifacts/formal_logic_tmp_verify/federal/report.hybrid.json}"
export RECORDS_PATH="${RECORDS_PATH:-artifacts/formal_logic_tmp_verify/federal/records.hybrid.jsonl}"
export LOGIC_PATH="${LOGIC_PATH:-artifacts/formal_logic_tmp_verify/federal/logic.hybrid.jsonld}"

# Optional positional baseline override remains supported by delegated script.
bash scripts/ops/run_formal_logic_regression_check.sh "$@"
