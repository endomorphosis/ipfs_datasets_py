#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/legal_parser_optimizer_daemon}"
DAEMON_DIR="${DAEMON_DIR:-.daemon}"
ENSURE_STATUS_PATH="${ENSURE_STATUS_PATH:-$DAEMON_DIR/legal_parser_daemon_ensure.status.json}"
CHECK_LOG_PATH="${CHECK_LOG_PATH:-$DAEMON_DIR/legal_parser_daemon_ensure_check.json}"
SUPERVISOR_OUT_PATH="${SUPERVISOR_OUT_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.out}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.pid}"
WRAPPER_PID_PATH="${WRAPPER_PID_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor_wrapper.pid}"
SUPERVISOR_STATUS_PATH="${SUPERVISOR_STATUS_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.json}"
SUPERVISOR_LOCK_PATH="${SUPERVISOR_LOCK_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.lock}"
RUN_SCRIPT="${RUN_SCRIPT:-scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh}"
CHECK_SCRIPT="${CHECK_SCRIPT:-scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh}"
ENSURE_STARTUP_WAIT_SECONDS="${ENSURE_STARTUP_WAIT_SECONDS:-30}"
ENSURE_RESTART_DELAY_SECONDS="${ENSURE_RESTART_DELAY_SECONDS:-5}"
ENSURE_LAUNCH_MODE="${ENSURE_LAUNCH_MODE:-nohup_loop}"
TMUX_SESSION_NAME="${TMUX_SESSION_NAME:-legal-parser-daemon}"
MODEL_NAME="${MODEL_NAME:-gpt-5.5}"
PROVIDER="${PROVIDER:-llm_router}"
IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-codex_cli}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR" "$REPO_ROOT/$OUTPUT_DIR"
cd "$REPO_ROOT" || exit 2

checked_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
launch_mode=""
launcher_pid=""

pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

supervisor_pid() {
  if [[ -f "$SUPERVISOR_PID_PATH" ]]; then
    tr -dc '0-9' < "$SUPERVISOR_PID_PATH" 2>/dev/null || true
  fi
}

wrapper_pid() {
  if [[ -f "$WRAPPER_PID_PATH" ]]; then
    tr -dc '0-9' < "$WRAPPER_PID_PATH" 2>/dev/null || true
  fi
}

supervisor_alive() {
  local pid=""
  pid="$(supervisor_pid)"
  pid_is_legal_parser_supervisor "$pid"
}

pid_is_legal_parser_supervisor() {
  local pid="$1"
  local args=""
  if ! pid_alive "$pid"; then
    return 1
  fi
  args="$(ps -o args= -p "$pid" 2>/dev/null || true)"
  [[ "$args" == *"run_legal_parser_optimizer_daemon.sh"* ]]
}

wrapper_alive() {
  local pid=""
  if [[ "$ENSURE_LAUNCH_MODE" == "tmux" ]] && command -v tmux >/dev/null 2>&1; then
    tmux has-session -t "$TMUX_SESSION_NAME" 2>/dev/null && return 0
  fi
  pid="$(wrapper_pid)"
  pid_alive "$pid"
}

run_check() {
  if [[ -x "$CHECK_SCRIPT" || -f "$CHECK_SCRIPT" ]]; then
    bash "$CHECK_SCRIPT" > "$CHECK_LOG_PATH" 2>&1 || true
  else
    printf '{"status":"missing_check_script","checked_at":"%s"}\n' "$checked_at" > "$CHECK_LOG_PATH"
  fi
}

cleanup_stale_supervisor_artifacts() {
  local pid=""
  pid="$(supervisor_pid)"
  if [[ -n "$pid" ]] && ! pid_is_legal_parser_supervisor "$pid"; then
    rm -f "$SUPERVISOR_PID_PATH"
  fi
  if [[ -f "$SUPERVISOR_LOCK_PATH" ]] && ! supervisor_alive; then
    rm -f "$SUPERVISOR_LOCK_PATH"
  fi
  if [[ -f "$WRAPPER_PID_PATH" ]] && ! wrapper_alive; then
    rm -f "$WRAPPER_PID_PATH"
  fi
}

wait_for_supervisor() {
  local deadline=$((SECONDS + ENSURE_STARTUP_WAIT_SECONDS))
  while [[ "$SECONDS" -lt "$deadline" ]]; do
    if supervisor_alive; then
      return 0
    fi
    sleep 1
  done
  supervisor_alive
}

write_status() {
  local ensure_status="$1"
  local started_supervisor="$2"
  python3 - \
    "$ENSURE_STATUS_PATH" \
    "$checked_at" \
    "$CHECK_LOG_PATH" \
    "$ensure_status" \
    "$started_supervisor" \
    "$launcher_pid" \
    "$WRAPPER_PID_PATH" \
    "$SUPERVISOR_PID_PATH" \
    "$SUPERVISOR_STATUS_PATH" \
    "$SUPERVISOR_OUT_PATH" \
    "$ENSURE_LAUNCH_MODE" \
    "$launch_mode" \
    "$ENSURE_RESTART_DELAY_SECONDS" <<'PY'
import json
import os
import sys

(
    status_path,
    checked_at,
    check_path,
    ensure_status,
    started_supervisor,
    launcher_pid,
    wrapper_pid_path,
    supervisor_pid_path,
    supervisor_status_path,
    supervisor_out_path,
    requested_launch_mode,
    launch_mode,
    restart_delay_seconds,
) = sys.argv[1:14]

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}

def read_pid(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = "".join(ch for ch in handle.read() if ch.isdigit())
        return int(text) if text else None
    except Exception:
        return None

def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

supervisor_pid = read_pid(supervisor_pid_path)
wrapper_pid = read_pid(wrapper_pid_path)
payload = {
    "schema": "ipfs_datasets_py.legal_parser_daemon.ensure",
    "status": ensure_status,
    "checked_at": checked_at,
    "started_supervisor": started_supervisor == "1",
    "launcher_pid": int(launcher_pid) if str(launcher_pid).isdigit() else None,
    "wrapper_pid": wrapper_pid,
    "wrapper_pid_alive": pid_alive(wrapper_pid),
    "requested_launch_mode": requested_launch_mode,
    "launch_mode": launch_mode,
    "restart_delay_seconds": int(restart_delay_seconds),
    "supervisor_pid": supervisor_pid,
    "supervisor_pid_alive": pid_alive(supervisor_pid),
    "supervisor_status_path": supervisor_status_path,
    "supervisor_out_path": supervisor_out_path,
    "check": read_json(check_path),
}
with open(status_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

launch_supervisor() {
  local out_abs="$REPO_ROOT/$SUPERVISOR_OUT_PATH"
  local command_text=""
  launch_mode="$ENSURE_LAUNCH_MODE"
  launcher_pid=""
  command_text="while true; do MODEL_NAME=$(printf '%q' "$MODEL_NAME") PROVIDER=$(printf '%q' "$PROVIDER") IPFS_DATASETS_PY_LLM_PROVIDER=$(printf '%q' "$IPFS_DATASETS_PY_LLM_PROVIDER") bash $(printf '%q' "$RUN_SCRIPT"); rc=\$?; printf '%s legal-parser supervisor exited with code %s; wrapper restarting in %ss\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$rc\" $(printf '%q' "$ENSURE_RESTART_DELAY_SECONDS"); sleep $(printf '%q' "$ENSURE_RESTART_DELAY_SECONDS"); done"
  if [[ "$ENSURE_LAUNCH_MODE" == "tmux" ]] && command -v tmux >/dev/null 2>&1; then
    if tmux has-session -t "$TMUX_SESSION_NAME" 2>/dev/null; then
      tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null || true
    fi
    if tmux new-session -d -s "$TMUX_SESSION_NAME" -c "$REPO_ROOT" "$command_text"; then
      launch_mode="tmux"
      launcher_pid="0"
      printf '%s\n' "$launcher_pid" > "$WRAPPER_PID_PATH"
      return 0
    fi
  fi
  launch_mode="nohup_loop"
  nohup setsid bash -lc "$command_text" > "$out_abs" 2>&1 < /dev/null &
  launcher_pid=$!
  printf '%s\n' "$launcher_pid" > "$WRAPPER_PID_PATH"
}

run_check
if supervisor_alive && wrapper_alive; then
  write_status "already_running" "0"
  exit 0
fi

if supervisor_alive && ! wrapper_alive; then
  cleanup_stale_supervisor_artifacts
  launch_supervisor
  write_status "wrapped_existing_supervisor" "1"
  exit 0
fi

if ! supervisor_alive && wrapper_alive; then
  if wait_for_supervisor; then
    run_check
    write_status "wrapper_recovered_supervisor" "0"
    exit 0
  fi
fi

cleanup_stale_supervisor_artifacts
launch_supervisor
if wait_for_supervisor; then
  run_check
  write_status "started" "1"
  exit 0
fi

run_check
write_status "failed_to_start" "1"
exit 1
