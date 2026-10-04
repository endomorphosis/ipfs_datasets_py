#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

BASELINE_REPORT="${BASELINE_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.baseline.json}"
CANDIDATE_REPORT="${CANDIDATE_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.hybrid.json}"
OPTIMIZER_POLICY_DECISION_PATH="${OPTIMIZER_POLICY_DECISION_PATH:-artifacts/formal_logic_tmp_verify/federal/optimizer_policy_decision.json}"
OPTIMIZER_CHAIN_PLAN_PATH="${OPTIMIZER_CHAIN_PLAN_PATH:-artifacts/formal_logic_tmp_verify/federal/optimizer_chain_plan.json}"
LIMIT_SEGMENTS="${LIMIT_SEGMENTS:-50}"

echo "[optimizer-chain 1/3] Assessing optimizer acceptance policy..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_optimizer_policy.py \
  --baseline "$BASELINE_REPORT" \
  --candidate "$CANDIDATE_REPORT" \
  --output "$OPTIMIZER_POLICY_DECISION_PATH"

echo "[optimizer-chain 2/3] Selecting stage orchestration plan..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/select_formal_logic_optimizer_chain.py \
  --decision "$OPTIMIZER_POLICY_DECISION_PATH" \
  --output "$OPTIMIZER_CHAIN_PLAN_PATH"

echo "[optimizer-chain 3/3] Running regression check with selected optimizer chain..."
LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
OPTIMIZER_CHAIN_PLAN="$OPTIMIZER_CHAIN_PLAN_PATH" \
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check.sh

echo "[optimizer-chain] Complete. Plan: $OPTIMIZER_CHAIN_PLAN_PATH"
