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
WATCHDOG_STALE_AFTER_SECONDS="${WATCHDOG_STALE_AFTER_SECONDS:-420}"
WATCHDOG_STARTUP_GRACE_SECONDS="${WATCHDOG_STARTUP_GRACE_SECONDS:-120}"
STOP_GRACE_SECONDS="${STOP_GRACE_SECONDS:-10}"
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
SUPERVISOR_LOCK_PATH="${SUPERVISOR_LOCK_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.lock}"
CHILD_PID_PATH="${CHILD_PID_PATH:-$DAEMON_DIR/logic-port-daemon.pid}"
LATEST_LOG_PATH="${LATEST_LOG_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.latest.log}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"

if [[ ! -f "$REPO_ROOT/package.json" ]] || [[ ! -d "$REPO_ROOT/ipfs_datasets_py" ]]; then
  echo "REPO_ROOT must point at the outer project root containing package.json and ipfs_datasets_py/: $REPO_ROOT" >&2
  exit 2
fi

exec 9>"$REPO_ROOT/$SUPERVISOR_LOCK_PATH"
if ! flock -n 9; then
  existing_pid=""
  if [[ -f "$REPO_ROOT/$SUPERVISOR_PID_PATH" ]]; then
    existing_pid="$(tr -dc '0-9' < "$REPO_ROOT/$SUPERVISOR_PID_PATH" 2>/dev/null || true)"
  fi
  echo "logic-port daemon supervisor lock is held${existing_pid:+ by PID $existing_pid}"
  exit 0
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
cleaning_up=0
last_recycle_reason=""

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
  "watchdog_stale_after_seconds": $WATCHDOG_STALE_AFTER_SECONDS,
  "watchdog_startup_grace_seconds": $WATCHDOG_STARTUP_GRACE_SECONDS,
  "stop_grace_seconds": $STOP_GRACE_SECONDS,
  "run_id": "$run_id",
  "log_path": "$log_path",
  "status_path": "$STATUS_PATH",
  "progress_path": "$PROGRESS_PATH",
  "result_log_path": "$RESULT_LOG_PATH",
  "child_pid_path": "$CHILD_PID_PATH",
  "supervisor_lock_path": "$SUPERVISOR_LOCK_PATH",
  "model_name": "$MODEL_NAME",
  "provider": "$PROVIDER",
  "llm_timeout_seconds": $LLM_TIMEOUT_SECONDS,
  "command_timeout_seconds": $COMMAND_TIMEOUT_SECONDS,
  "last_exit_code": $last_exit_code,
  "last_recycle_reason": "$last_recycle_reason"
}
JSON
}

daemon_heartbeat_age_seconds() {
  python3 - "$REPO_ROOT/$STATUS_PATH" "$REPO_ROOT/$PROGRESS_PATH" <<'PY'
import json
import sys
from datetime import datetime, timezone


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


status = read_json(sys.argv[1])
progress = read_json(sys.argv[2])
heartbeat_at = parse_ts(
    status.get("heartbeat_at")
    or status.get("updated_at")
    or progress.get("updated_at")
)
if heartbeat_at is None:
    raise SystemExit(0)
print(max(0.0, (datetime.now(timezone.utc) - heartbeat_at).total_seconds()))
PY
}

heartbeat_is_stale() {
  local age=""
  age="$(daemon_heartbeat_age_seconds)"
  if [[ -z "$age" ]]; then
    return 1
  fi
  python3 - "$age" "$WATCHDOG_STALE_AFTER_SECONDS" <<'PY'
import sys
age = float(sys.argv[1])
threshold = float(sys.argv[2])
raise SystemExit(0 if age > threshold else 1)
PY
}

terminate_pid_tree() {
  local pid="$1"
  local child=""
  local deadline=0
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    terminate_pid_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
  deadline=$((SECONDS + STOP_GRACE_SECONDS))
  while kill -0 "$pid" 2>/dev/null && [[ "$SECONDS" -lt "$deadline" ]]; do
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

terminate_matching_logic_port_daemons() {
  local pid=""
  local args=""
  while read -r pid args; do
    if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]] || [[ "$pid" == "${child_pid:-}" ]]; then
      continue
    fi
    if [[ "$args" == *"ipfs_datasets_py.optimizers.logic_port_daemon"* ]] && [[ "$args" == *"--status-file $STATUS_PATH"* ]]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cleaning up orphaned logic-port daemon $pid before supervisor start/restart" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
      terminate_pid_tree "$pid"
    fi
  done < <(ps -eo pid=,args=)
}

stop_child() {
  local stopped_pid="${child_pid:-}"
  if [[ -n "${child_pid:-}" ]] && kill -0 "$child_pid" 2>/dev/null; then
    terminate_pid_tree "$child_pid"
    wait "$child_pid" 2>/dev/null || true
  fi
  if [[ -f "$REPO_ROOT/$CHILD_PID_PATH" ]] && [[ "$(cat "$REPO_ROOT/$CHILD_PID_PATH" 2>/dev/null)" == "$stopped_pid" ]]; then
    rm -f "$REPO_ROOT/$CHILD_PID_PATH"
  fi
  child_pid=""
}

cleanup() {
  if [[ "$cleaning_up" == "1" ]]; then
    return 0
  fi
  cleaning_up=1
  stop_child
  write_supervisor_status "stopped" "" "" null
  if [[ -f "$REPO_ROOT/$SUPERVISOR_PID_PATH" ]] && [[ "$(cat "$REPO_ROOT/$SUPERVISOR_PID_PATH" 2>/dev/null)" == "$$" ]]; then
    rm -f "$REPO_ROOT/$SUPERVISOR_PID_PATH"
  fi
  rm -f "$REPO_ROOT/$SUPERVISOR_LOCK_PATH"
}

trap 'cleanup; exit 143' TERM INT
trap 'cleanup' EXIT

terminate_matching_logic_port_daemons

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
  child_started_at=$SECONDS
  printf '%s\n' "$child_pid" > "$REPO_ROOT/$CHILD_PID_PATH"

  while kill -0 "$child_pid" 2>/dev/null; do
    write_supervisor_status "running" "$run_id" "$run_log" null
    if [[ $((SECONDS - child_started_at)) -ge "$WATCHDOG_STARTUP_GRACE_SECONDS" ]] && heartbeat_is_stale; then
      last_recycle_reason="stale_heartbeat"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog recycling child $child_pid after stale daemon heartbeat older than ${WATCHDOG_STALE_AFTER_SECONDS}s" >> "$REPO_ROOT/$run_log"
      stop_child
      break
    fi
    sleep "$SUPERVISOR_HEARTBEAT_SECONDS"
  done

  rc=0
  if [[ -n "${child_pid:-}" ]]; then
    wait "$child_pid"
    rc=$?
  fi
  if [[ -f "$REPO_ROOT/$CHILD_PID_PATH" ]] && [[ "$(cat "$REPO_ROOT/$CHILD_PID_PATH" 2>/dev/null)" == "${child_pid:-}" ]]; then
    rm -f "$REPO_ROOT/$CHILD_PID_PATH"
  fi
  child_pid=""
  restart_count=$((restart_count + 1))
  write_supervisor_status "restarting" "$run_id" "$run_log" "$rc"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) logic-port daemon exited with code $rc; restarting in ${RESTART_DELAY_SECONDS}s" >> "$REPO_ROOT/$run_log"
  if [[ "$RESTART_DELAY_SECONDS" != "0" ]]; then
    sleep "$RESTART_DELAY_SECONDS"
  fi
  terminate_matching_logic_port_daemons
done
