#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
MODEL_NAME="${MODEL_NAME:-gpt-5.5}"
PROVIDER="${PROVIDER:-codex_cli}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
RESTART_DELAY_SECONDS="${RESTART_DELAY_SECONDS:-0}"
LLM_TIMEOUT_SECONDS="${LLM_TIMEOUT_SECONDS:-300}"
COMMAND_TIMEOUT_SECONDS="${COMMAND_TIMEOUT_SECONDS:-300}"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-30}"
SUPERVISOR_HEARTBEAT_SECONDS="${SUPERVISOR_HEARTBEAT_SECONDS:-30}"
MAX_TASK_FAILURES="${MAX_TASK_FAILURES:-6}"
PROPOSAL_ATTEMPTS="${PROPOSAL_ATTEMPTS:-3}"
FILE_REPAIR_ATTEMPTS="${FILE_REPAIR_ATTEMPTS:-1}"
VALIDATION_REPAIR_ATTEMPTS="${VALIDATION_REPAIR_ATTEMPTS:-1}"
BLOCKED_BACKLOG_LIMIT="${BLOCKED_BACKLOG_LIMIT:-10}"
BLOCKED_TASK_STRATEGY="${BLOCKED_TASK_STRATEGY:-fewest-failures}"
PLAN_REPLENISHMENT_LIMIT="${PLAN_REPLENISHMENT_LIMIT:-12}"

STATUS_PATH="${STATUS_PATH:-$DAEMON_DIR/logic-port-daemon.status.json}"
PROGRESS_PATH="${PROGRESS_PATH:-$DAEMON_DIR/logic-port-daemon.progress.json}"
RESULT_LOG_PATH="${RESULT_LOG_PATH:-$DAEMON_DIR/logic-port-daemon.jsonl}"
SUPERVISOR_STATUS_PATH="${SUPERVISOR_STATUS_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.status.json}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.pid}"
LATEST_LOG_PATH="${LATEST_LOG_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.latest.log}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"

if [[ ! -f "$REPO_ROOT/package.json" ]] || [[ ! -d "$REPO_ROOT/ipfs_datasets_py" ]]; then
  echo "REPO_ROOT must point at the outer project root containing package.json and ipfs_datasets_py/: $REPO_ROOT" >&2
  exit 2
fi

if [[ -f "$REPO_ROOT/$SUPERVISOR_PID_PATH" ]]; then
  existing_pid="$(tr -dc '0-9' < "$REPO_ROOT/$SUPERVISOR_PID_PATH" 2>/dev/null || true)"
  if [[ -n "$existing_pid" ]] && [[ "$existing_pid" != "$$" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "logic-port daemon supervisor is already running with PID $existing_pid"
    exit 0
  fi
fi

printf '%s\n' "$$" > "$REPO_ROOT/$SUPERVISOR_PID_PATH"

child_pid=""
restart_count=0

write_supervisor_status() {
  local status="$1"
  local run_id="${2:-}"
  local log_path="${3:-}"
  local last_exit_code="${4:-null}"
  local daemon_pid_json="null"
  if [[ -n "${child_pid:-}" ]]; then
    daemon_pid_json="$child_pid"
  fi
  cat > "$REPO_ROOT/$SUPERVISOR_STATUS_PATH" <<JSON
{
  "schema": "ipfs_datasets_py.logic_port_daemon.supervisor",
  "status": "$status",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo_root": "$REPO_ROOT",
  "supervisor_pid": $$,
  "daemon_pid": $daemon_pid_json,
  "restart_count": $restart_count,
  "restart_delay_seconds": $RESTART_DELAY_SECONDS,
  "supervisor_heartbeat_seconds": $SUPERVISOR_HEARTBEAT_SECONDS,
  "run_id": "$run_id",
  "log_path": "$log_path",
  "status_path": "$STATUS_PATH",
  "progress_path": "$PROGRESS_PATH",
  "result_log_path": "$RESULT_LOG_PATH",
  "model_name": "$MODEL_NAME",
  "provider": "$PROVIDER",
  "llm_timeout_seconds": $LLM_TIMEOUT_SECONDS,
  "command_timeout_seconds": $COMMAND_TIMEOUT_SECONDS,
  "last_exit_code": $last_exit_code
}
JSON
}

stop_child() {
  if [[ -n "${child_pid:-}" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
}

cleanup() {
  stop_child
  write_supervisor_status "stopped" "" "" null
  if [[ -f "$REPO_ROOT/$SUPERVISOR_PID_PATH" ]] && [[ "$(cat "$REPO_ROOT/$SUPERVISOR_PID_PATH" 2>/dev/null)" == "$$" ]]; then
    rm -f "$REPO_ROOT/$SUPERVISOR_PID_PATH"
  fi
}

trap 'cleanup; exit 143' TERM INT
trap 'cleanup' EXIT

while true; do
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  run_log="$DAEMON_DIR/logic-port-daemon-supervised_${run_id}.log"
  ln -sfn "$(basename "$run_log")" "$REPO_ROOT/$LATEST_LOG_PATH"
  write_supervisor_status "starting" "$run_id" "$run_log" null

  (
    cd "$REPO_ROOT" || exit 2
    export PYTHONUNBUFFERED=1
    export PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}"
    export IPFS_DATASETS_PY_CODEX_CLI_MODEL="$MODEL_NAME"
    python3 -u -m ipfs_datasets_py.optimizers.logic_port_daemon \
      --repo-root . \
      --model "$MODEL_NAME" \
      --provider "$PROVIDER" \
      --apply \
      --watch \
      --cycles 0 \
      --retry-interval 0 \
      --llm-timeout "$LLM_TIMEOUT_SECONDS" \
      --command-timeout "$COMMAND_TIMEOUT_SECONDS" \
      --heartbeat-interval "$HEARTBEAT_INTERVAL_SECONDS" \
      --max-task-failures "$MAX_TASK_FAILURES" \
      --proposal-attempts "$PROPOSAL_ATTEMPTS" \
      --file-repair-attempts "$FILE_REPAIR_ATTEMPTS" \
      --validation-repair-attempts "$VALIDATION_REPAIR_ATTEMPTS" \
      --revisit-blocked-tasks \
      --blocked-backlog-limit "$BLOCKED_BACKLOG_LIMIT" \
      --blocked-task-strategy "$BLOCKED_TASK_STRATEGY" \
      --plan-replenishment-limit "$PLAN_REPLENISHMENT_LIMIT" \
      --status-file "$STATUS_PATH" \
      --progress-file "$PROGRESS_PATH" \
      --log-file "$RESULT_LOG_PATH"
  ) >> "$REPO_ROOT/$run_log" 2>&1 &
  child_pid=$!

  while kill -0 "$child_pid" 2>/dev/null; do
    write_supervisor_status "running" "$run_id" "$run_log" null
    sleep "$SUPERVISOR_HEARTBEAT_SECONDS"
  done

  wait "$child_pid"
  rc=$?
  child_pid=""
  restart_count=$((restart_count + 1))
  write_supervisor_status "restarting" "$run_id" "$run_log" "$rc"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) logic-port daemon exited with code $rc; restarting in ${RESTART_DELAY_SECONDS}s" >> "$REPO_ROOT/$run_log"
  if [[ "$RESTART_DELAY_SECONDS" != "0" ]]; then
    sleep "$RESTART_DELAY_SECONDS"
  fi
done
