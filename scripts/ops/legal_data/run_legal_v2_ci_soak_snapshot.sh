#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

DATE_TAG="${DATE_TAG:-$(date +%Y%m%d)}"
SOAK_DIR="${SOAK_DIR:-$ROOT_DIR/artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

mkdir -p "$SOAK_DIR"

RAW_OUT="$SOAK_DIR/ci_soak_runs_${DATE_TAG}.json"
SUMMARY_OUT="$SOAK_DIR/ci_soak_summary_${DATE_TAG}.json"
MARKDOWN_OUT="$SOAK_DIR/CI_SOAK_SUMMARY_${DATE_TAG}.md"

PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR/ipfs_datasets_py" \
  "$PYTHON_BIN" "$ROOT_DIR/ipfs_datasets_py/scripts/ops/legal_data/collect_legal_v2_ci_soak_snapshot.py" \
  --owner endomorphosis \
  --repo ipfs_datasets_py \
  --workflow legal-v2-reasoner-ci.yml \
  --raw-output "$RAW_OUT" \
  --summary-output "$SUMMARY_OUT" \
  --markdown-output "$MARKDOWN_OUT"

echo "[ci-soak] raw=$RAW_OUT"
echo "[ci-soak] summary=$SUMMARY_OUT"
echo "[ci-soak] markdown=$MARKDOWN_OUT"
