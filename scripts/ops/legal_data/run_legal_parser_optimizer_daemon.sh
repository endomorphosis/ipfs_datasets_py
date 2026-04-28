#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/legal_parser_optimizer_daemon}"
MODEL_NAME="${MODEL_NAME:-gpt-5.5}"
PROVIDER="${PROVIDER:-codex_cli}"
RESTART_BACKOFF_SECONDS="${RESTART_BACKOFF_SECONDS:-30}"
LLM_TIMEOUT_SECONDS="${LLM_TIMEOUT_SECONDS:-900}"
TEST_TIMEOUT_SECONDS="${TEST_TIMEOUT_SECONDS:-180}"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-10}"
LLM_PROPOSAL_ATTEMPTS="${LLM_PROPOSAL_ATTEMPTS:-3}"
DAEMON_DIR="${DAEMON_DIR:-.daemon}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"

while true; do
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  log_path="$DAEMON_DIR/legal_parser_daemon_supervised_${run_id}.log"
  latest_log="$DAEMON_DIR/legal_parser_daemon_overnight.log"
  status_path="$DAEMON_DIR/legal_parser_daemon_supervisor.json"
  ln -sf "$(basename "$log_path")" "$REPO_ROOT/$latest_log"
  cat > "$REPO_ROOT/$status_path" <<JSON
{
  "status": "starting",
  "run_id": "$run_id",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "log_path": "$log_path",
  "model_name": "$MODEL_NAME",
  "provider": "$PROVIDER"
}
JSON

  (
    cd "$REPO_ROOT" || exit 2
    PYTHONUNBUFFERED=1 IPFS_DATASETS_PY_CODEX_CLI_MODEL="$MODEL_NAME" python3 -u -m ipfs_datasets_py.optimizers.logic.deontic.parser_daemon \
      --repo-root . \
      --output-dir "$OUTPUT_DIR" \
      --max-cycles 0 \
      --cycle-interval-seconds 0 \
      --error-backoff-seconds "$RESTART_BACKOFF_SECONDS" \
      --llm-timeout-seconds "$LLM_TIMEOUT_SECONDS" \
      --llm-proposal-attempts "$LLM_PROPOSAL_ATTEMPTS" \
      --heartbeat-interval-seconds "$HEARTBEAT_INTERVAL_SECONDS" \
      --test-timeout-seconds "$TEST_TIMEOUT_SECONDS" \
      --apply-patches \
      --commit-accepted-patches \
      --provider "$PROVIDER" \
      --model-name "$MODEL_NAME"
  ) >> "$REPO_ROOT/$log_path" 2>&1
  rc=$?

  cat > "$REPO_ROOT/$status_path" <<JSON
{
  "status": "restarting",
  "run_id": "$run_id",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "last_exit_code": $rc,
  "restart_backoff_seconds": $RESTART_BACKOFF_SECONDS,
  "log_path": "$log_path",
  "model_name": "$MODEL_NAME",
  "provider": "$PROVIDER"
}
JSON
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) daemon exited with code $rc; restarting in ${RESTART_BACKOFF_SECONDS}s" >> "$REPO_ROOT/$log_path"
  sleep "$RESTART_BACKOFF_SECONDS"
done
