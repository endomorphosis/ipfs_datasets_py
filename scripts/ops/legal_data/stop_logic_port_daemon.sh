#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
STATUS_PATH="${STATUS_PATH:-$DAEMON_DIR/logic-port-daemon.status.json}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.pid}"
CHILD_PID_PATH="${CHILD_PID_PATH:-$DAEMON_DIR/logic-port-daemon.pid}"
STOP_GRACE_SECONDS="${STOP_GRACE_SECONDS:-10}"
TMUX_SESSION_NAME="${TMUX_SESSION_NAME:-logic-port-daemon}"

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

pid_has_parser_daemon_ancestor() {
  local pid="$1"
  local parent=""
  local args=""
  while [[ -n "$pid" ]] && [[ "$pid" != "0" ]] && [[ "$pid" != "1" ]]; do
    args="$(ps -o args= -p "$pid" 2>/dev/null || true)"
    if [[ "$args" == *"parser_daemon"* ]] || [[ "$args" == *"run_legal_parser_optimizer_daemon.sh"* ]]; then
      return 0
    fi
    parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -dc '0-9' || true)"
    if [[ -z "$parent" ]] || [[ "$parent" == "$pid" ]]; then
      return 1
    fi
    pid="$parent"
  done
  return 1
}

pid_has_non_logic_port_daemon_ancestor() {
  local pid="$1"
  local parent=""
  local args=""
  while [[ -n "$pid" ]] && [[ "$pid" != "0" ]] && [[ "$pid" != "1" ]]; do
    args="$(ps -o args= -p "$pid" 2>/dev/null || true)"
    case "$args" in
      *"parser_daemon"*|*"run_legal_parser_optimizer_daemon.sh"*|*"ppd/daemon/ppd_supervisor.py"*|*"ppd/daemon/ppd_daemon.py"*)
        return 0
        ;;
    esac
    parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -dc '0-9' || true)"
    if [[ -z "$parent" ]] || [[ "$parent" == "$pid" ]]; then
      return 1
    fi
    pid="$parent"
  done
  return 1
}

terminate_repo_local_logic_codex_execs() {
  local pid=""
  local args=""
  local cwd=""
  while read -r pid args; do
    if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]]; then
      continue
    fi
    if [[ "$args" != *"codex exec --skip-git-repo-check"* ]] || [[ "$args" != *"--ephemeral --json -"* ]]; then
      continue
    fi
    if pid_has_non_logic_port_daemon_ancestor "$pid"; then
      continue
    fi
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ "$cwd" == "$REPO_ROOT" || "$cwd" == "$REPO_ROOT/ipfs_datasets_py" ]]; then
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
terminate_repo_local_logic_codex_execs
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$TMUX_SESSION_NAME" 2>/dev/null; then
  tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null || true
fi
sleep 1
rm -f "$SUPERVISOR_PID_PATH" "$CHILD_PID_PATH"
