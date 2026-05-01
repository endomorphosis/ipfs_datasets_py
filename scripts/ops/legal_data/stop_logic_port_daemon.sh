#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
STATUS_PATH="${STATUS_PATH:-$DAEMON_DIR/logic-port-daemon.status.json}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.pid}"
CHILD_PID_PATH="${CHILD_PID_PATH:-$DAEMON_DIR/logic-port-daemon.pid}"
STOP_GRACE_SECONDS="${STOP_GRACE_SECONDS:-10}"

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
    if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]]; then
      continue
    fi
    if [[ "$args" == *"ipfs_datasets_py.optimizers.logic_port_daemon"* ]] && [[ "$args" == *"--status-file $STATUS_PATH"* ]]; then
      terminate_pid_tree "$pid"
    fi
  done < <(ps -eo pid=,args=)
}

cd "$REPO_ROOT" || exit 2

supervisor_pid=""
child_pid=""
if [[ -f "$SUPERVISOR_PID_PATH" ]]; then
  supervisor_pid="$(tr -dc '0-9' < "$SUPERVISOR_PID_PATH" 2>/dev/null || true)"
fi
if [[ -f "$CHILD_PID_PATH" ]]; then
  child_pid="$(tr -dc '0-9' < "$CHILD_PID_PATH" 2>/dev/null || true)"
fi

if [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
  terminate_pid_tree "$supervisor_pid"
elif [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
  terminate_pid_tree "$child_pid"
else
  echo "logic-port daemon supervisor is not running"
fi

terminate_matching_logic_port_daemons
sleep 1
rm -f "$SUPERVISOR_PID_PATH" "$CHILD_PID_PATH"
