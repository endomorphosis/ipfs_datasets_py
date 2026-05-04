#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
ENSURE_STATUS_PATH="${ENSURE_STATUS_PATH:-$DAEMON_DIR/logic-port-daemon-ensure.status.json}"
CHECK_LOG_PATH="${CHECK_LOG_PATH:-$DAEMON_DIR/logic-port-daemon-ensure-check.json}"
SUPERVISOR_OUT_PATH="${SUPERVISOR_OUT_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.out}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.pid}"
SUPERVISOR_STATUS_PATH="${SUPERVISOR_STATUS_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.status.json}"
ENSURE_STARTUP_WAIT_SECONDS="${ENSURE_STARTUP_WAIT_SECONDS:-20}"
ENSURE_LAUNCH_MODE="${ENSURE_LAUNCH_MODE:-nohup}"
ENSURE_TMUX_RESTART_DELAY_SECONDS="${ENSURE_TMUX_RESTART_DELAY_SECONDS:-5}"
TMUX_SESSION_NAME="${TMUX_SESSION_NAME:-logic-port-daemon}"
LOGIC_PORT_PROVIDER="${LOGIC_PORT_PROVIDER:-}"
PROPOSAL_TRANSPORT="${PROPOSAL_TRANSPORT:-worktree}"
WORKTREE_EDIT_TIMEOUT_SECONDS="${WORKTREE_EDIT_TIMEOUT_SECONDS:-300}"
WORKTREE_STALE_AFTER_SECONDS="${WORKTREE_STALE_AFTER_SECONDS:-7200}"
WORKTREE_CODEX_SANDBOX="${WORKTREE_CODEX_SANDBOX:-${IPFS_DATASETS_PY_CODEX_SANDBOX:-danger-full-access}}"
WORKTREE_ROOT="${WORKTREE_ROOT:-ipfs_datasets_py/.daemon/logic-port-worktrees}"
WORKTREE_REPAIR_ATTEMPTS="${WORKTREE_REPAIR_ATTEMPTS:-1}"
AUTO_COMMIT="${AUTO_COMMIT:-1}"
AUTO_COMMIT_STARTUP_DIRTY="${AUTO_COMMIT_STARTUP_DIRTY:-1}"
AUTO_COMMIT_BRANCH="${AUTO_COMMIT_BRANCH:-main}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"
cd "$REPO_ROOT" || exit 2

checked_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
launch_mode=""
launcher_pid=""

supervisor_pid() {
  if [[ -f "$SUPERVISOR_PID_PATH" ]]; then
    tr -dc '0-9' < "$SUPERVISOR_PID_PATH" 2>/dev/null || true
  fi
}

supervisor_alive() {
  local pid=""
  pid="$(supervisor_pid)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
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

write_already_running() {
  python3 - "$ENSURE_STATUS_PATH" "$checked_at" "$CHECK_LOG_PATH" <<'PY'
import json
import sys

status_path, checked_at, check_path = sys.argv[1:4]
try:
    with open(check_path, "r", encoding="utf-8") as handle:
        check = json.load(handle)
except Exception:
    check = {}
payload = {
    "schema": "ipfs_datasets_py.logic_port_daemon.ensure",
    "status": "already_running",
    "checked_at": checked_at,
    "started_supervisor": False,
    "check": check,
}
with open(status_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

launch_supervisor() {
  local out_abs="$REPO_ROOT/$SUPERVISOR_OUT_PATH"
  local command_text=""
  launch_mode="nohup_setsid"
  launcher_pid=""
  if [[ "$ENSURE_LAUNCH_MODE" == "tmux" ]] && command -v tmux >/dev/null 2>&1; then
    if tmux has-session -t "$TMUX_SESSION_NAME" 2>/dev/null; then
      tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null || true
    fi
    command_text="while true; do LOGIC_PORT_PROVIDER=$(printf '%q' "$LOGIC_PORT_PROVIDER") PROPOSAL_TRANSPORT=$(printf '%q' "$PROPOSAL_TRANSPORT") WORKTREE_EDIT_TIMEOUT_SECONDS=$(printf '%q' "$WORKTREE_EDIT_TIMEOUT_SECONDS") WORKTREE_STALE_AFTER_SECONDS=$(printf '%q' "$WORKTREE_STALE_AFTER_SECONDS") WORKTREE_CODEX_SANDBOX=$(printf '%q' "$WORKTREE_CODEX_SANDBOX") WORKTREE_ROOT=$(printf '%q' "$WORKTREE_ROOT") WORKTREE_REPAIR_ATTEMPTS=$(printf '%q' "$WORKTREE_REPAIR_ATTEMPTS") AUTO_COMMIT=$(printf '%q' "$AUTO_COMMIT") AUTO_COMMIT_STARTUP_DIRTY=$(printf '%q' "$AUTO_COMMIT_STARTUP_DIRTY") AUTO_COMMIT_BRANCH=$(printf '%q' "$AUTO_COMMIT_BRANCH") bash ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh </dev/null > $(printf '%q' "$out_abs") 2>&1; rc=\$?; printf '%s supervisor exited with code %s; tmux wrapper restarting in %ss\\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$rc\" \"$ENSURE_TMUX_RESTART_DELAY_SECONDS\" >> $(printf '%q' "$out_abs"); sleep $ENSURE_TMUX_RESTART_DELAY_SECONDS; done"
    if tmux new-session -d -s "$TMUX_SESSION_NAME" -c "$REPO_ROOT" "$command_text"; then
      launch_mode="tmux"
      launcher_pid="0"
      return 0
    fi
  fi
  LOGIC_PORT_PROVIDER="$LOGIC_PORT_PROVIDER" \
    PROPOSAL_TRANSPORT="$PROPOSAL_TRANSPORT" \
    WORKTREE_EDIT_TIMEOUT_SECONDS="$WORKTREE_EDIT_TIMEOUT_SECONDS" \
    WORKTREE_STALE_AFTER_SECONDS="$WORKTREE_STALE_AFTER_SECONDS" \
    WORKTREE_CODEX_SANDBOX="$WORKTREE_CODEX_SANDBOX" \
    WORKTREE_ROOT="$WORKTREE_ROOT" \
    WORKTREE_REPAIR_ATTEMPTS="$WORKTREE_REPAIR_ATTEMPTS" \
    AUTO_COMMIT="$AUTO_COMMIT" \
    AUTO_COMMIT_STARTUP_DIRTY="$AUTO_COMMIT_STARTUP_DIRTY" \
    AUTO_COMMIT_BRANCH="$AUTO_COMMIT_BRANCH" \
    nohup setsid -f bash ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh \
    </dev/null > "$SUPERVISOR_OUT_PATH" 2>&1 &
  launcher_pid=$!
}

write_start_status() {
  local ensure_status="$1"
  python3 - "$ENSURE_STATUS_PATH" "$checked_at" "$CHECK_LOG_PATH" "$ensure_status" "$launcher_pid" "$SUPERVISOR_PID_PATH" "$SUPERVISOR_STATUS_PATH" "$ENSURE_STARTUP_WAIT_SECONDS" "$launch_mode" "$TMUX_SESSION_NAME" "$ENSURE_TMUX_RESTART_DELAY_SECONDS" <<'PY'
import json
import os
import sys

(
    status_path,
    checked_at,
    check_path,
    ensure_status,
    launcher_pid,
    supervisor_pid_path,
    supervisor_status_path,
    startup_wait_seconds,
    launch_mode,
    tmux_session_name,
    tmux_restart_delay_seconds,
) = sys.argv[1:12]
try:
    with open(check_path, "r", encoding="utf-8") as handle:
        check = json.load(handle)
except Exception:
    check = {}
try:
    with open(supervisor_pid_path, "r", encoding="utf-8") as handle:
        supervisor_pid = int("".join(ch for ch in handle.read() if ch.isdigit()))
except Exception:
    supervisor_pid = None
try:
    with open(supervisor_status_path, "r", encoding="utf-8") as handle:
        supervisor_status = json.load(handle)
except Exception:
    supervisor_status = {}
try:
    supervisor_pid_alive = bool(supervisor_pid and os.kill(supervisor_pid, 0) is None)
except Exception:
    supervisor_pid_alive = False
payload = {
    "schema": "ipfs_datasets_py.logic_port_daemon.ensure",
    "status": ensure_status,
    "checked_at": checked_at,
    "started_supervisor": True,
    "launcher_pid": int(launcher_pid),
    "launch_mode": launch_mode,
    "tmux_session_name": tmux_session_name,
    "tmux_restart_delay_seconds": int(tmux_restart_delay_seconds),
    "proposal_transport": check.get("proposal_transport"),
    "worktree_root": check.get("worktree_root"),
    "worktree_repair_attempts": check.get("worktree_repair_attempts"),
    "auto_commit": check.get("auto_commit"),
    "auto_commit_startup_dirty": check.get("auto_commit_startup_dirty"),
    "auto_commit_branch": check.get("auto_commit_branch"),
    "supervisor_pid": supervisor_pid,
    "supervisor_pid_alive": supervisor_pid_alive,
    "supervisor_status": supervisor_status.get("status"),
    "startup_wait_seconds": int(startup_wait_seconds),
    "check": check,
}
with open(status_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

if bash ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh > "$CHECK_LOG_PATH" 2>&1; then
  write_already_running
  cat "$CHECK_LOG_PATH"
  exit 0
fi

launch_supervisor
wait_for_supervisor || true

if bash ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh > "$CHECK_LOG_PATH" 2>&1; then
  ensure_status="started"
  ensure_exit=0
elif supervisor_alive; then
  ensure_status="supervisor_started_waiting_for_daemon"
  ensure_exit=0
else
  ensure_status="start_attempted_but_unhealthy"
  ensure_exit=1
fi

write_start_status "$ensure_status"
cat "$CHECK_LOG_PATH"
exit "$ensure_exit"
