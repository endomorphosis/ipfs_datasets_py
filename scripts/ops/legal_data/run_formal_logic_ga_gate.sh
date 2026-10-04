#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

RUN_CANARY_FIRST="${RUN_CANARY_FIRST:-1}"
RISK_LEVEL="${RISK_LEVEL:-low}"
REQUIRE_SHADOW_READY="${REQUIRE_SHADOW_READY:-1}"
LIMIT_SEGMENTS="${LIMIT_SEGMENTS:-50}"

SHADOW_AUDIT_PATH="${SHADOW_AUDIT_PATH:-artifacts/formal_logic_tmp_verify/federal/shadow_mode_audit.json}"
CANARY_DECISION_PATH="${CANARY_DECISION_PATH:-artifacts/formal_logic_tmp_verify/federal/canary_mode_decision.json}"
CANDIDATE_REPORT="${CANDIDATE_REPORT:-artifacts/formal_logic_tmp_verify/federal/report.hybrid.json}"
RUNTIME_STATS_PATH="${RUNTIME_STATS_PATH:-}"
GA_GATE_OUTPUT_PATH="${GA_GATE_OUTPUT_PATH:-artifacts/formal_logic_tmp_verify/federal/ga_gate_assessment.json}"

if [[ "$RUN_CANARY_FIRST" == "1" ]]; then
  echo "[ga 1/2] Running canary mode pipeline..."
  LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
  RISK_LEVEL="$RISK_LEVEL" \
  REQUIRE_SHADOW_READY="$REQUIRE_SHADOW_READY" \
  bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh
fi

echo "[ga 2/2] Assessing GA gate thresholds..."
GA_ARGS=(
  --shadow-audit "$SHADOW_AUDIT_PATH"
  --canary-decision "$CANARY_DECISION_PATH"
  --candidate-report "$CANDIDATE_REPORT"
  --output "$GA_GATE_OUTPUT_PATH"
)
if [[ -n "$RUNTIME_STATS_PATH" ]]; then
  GA_ARGS+=(--runtime-stats "$RUNTIME_STATS_PATH")
else
  GA_ARGS+=(--allow-missing-runtime-stats)
fi

PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_ga_gate.py \
  "${GA_ARGS[@]}"

echo "[ga] Complete. Assessment: $GA_GATE_OUTPUT_PATH"
