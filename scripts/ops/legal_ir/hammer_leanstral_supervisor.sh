#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

ACTION="${1:-status}"
STATE_DIR="${HAMMER_LEANSTRAL_SUPERVISOR_STATE_DIR:-${ROOT_DIR}/workspace/hammer-leanstral-supervisor}"
TODO_PATH="${HAMMER_LEANSTRAL_TODO_PATH:-${ROOT_DIR}/docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md}"
PID_FILE="${STATE_DIR}/supervisor.pid"
LOG_FILE="${STATE_DIR}/supervisor.log"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
ACCELERATE_ROOT="${IPFS_ACCELERATE_ROOT:-${ROOT_DIR}/../ipfs_accelerate_py}"
STATE_PREFIX="${HAMMER_LEANSTRAL_STATE_PREFIX:-hammer_leanstral}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

mkdir -p "${STATE_DIR}"
export PYTHONPATH="${ACCELERATE_ROOT}:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

supervisor_pid() {
  [[ -f "${PID_FILE}" ]] && sed -n '1p' "${PID_FILE}" || true
}

managed_daemon_pid() {
  local daemon_pid_file="${STATE_DIR}/${STATE_PREFIX}_managed_daemon.pid"
  [[ -f "${daemon_pid_file}" ]] && sed -n '1p' "${daemon_pid_file}" || true
}

supervisor_alive() {
  local pid
  pid="$(supervisor_pid)"
  [[ -n "${pid}" ]] && ps -p "${pid}" -o args= 2>/dev/null | grep -Fq "implementation_supervisor"
}

common_args=(
  --todo-path "${TODO_PATH}"
  --state-dir "${STATE_DIR}"
  --task-prefix "## PORTAL-"
  --state-prefix "${STATE_PREFIX}"
  --stale-seconds "${HAMMER_LEANSTRAL_STALE_SECONDS:-1800}"
  --check-interval "${HAMMER_LEANSTRAL_CHECK_INTERVAL:-60}"
  --daemon-interval "${HAMMER_LEANSTRAL_DAEMON_INTERVAL:-15}"
  --max-restarts "${HAMMER_LEANSTRAL_MAX_RESTARTS:-100}"
  # Covers an eight-hour canary plus setup, durable evidence, and validation.
  --implementation-timeout "${HAMMER_LEANSTRAL_IMPLEMENTATION_TIMEOUT:-43200}"
  --implementation-log-stall-seconds "${HAMMER_LEANSTRAL_LOG_STALL_SECONDS:-900}"
  --worktree-root "${HAMMER_LEANSTRAL_WORKTREE_ROOT:-${ROOT_DIR}/workspace/hammer-leanstral-worktrees}"
  --worktree-reconciliation-max-merges "${HAMMER_LEANSTRAL_RECONCILIATION_MAX_MERGES:-2}"
  --merge-reconciliation-max-merges "${HAMMER_LEANSTRAL_MERGE_RECONCILIATION_MAX_MERGES:-2}"
  --validation-retry-budget "${HAMMER_LEANSTRAL_VALIDATION_RETRY_BUDGET:-3}"
  --merge-retry-budget "${HAMMER_LEANSTRAL_MERGE_RETRY_BUDGET:-3}"
  --implementation-retry-budget "${HAMMER_LEANSTRAL_IMPLEMENTATION_RETRY_BUDGET:-3}"
)

case "${ACTION}" in
  once)
    exec "${PYTHON_BIN}" -m \
      ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor \
      --once --no-implement --reconciliation-only "${common_args[@]}"
    ;;
  start)
    if supervisor_alive; then
      echo "hammer_leanstral_supervisor=already_running pid=$(supervisor_pid)"
      exit 0
    fi
    if [[ -n "$(git status --porcelain)" ]]; then
      echo "refusing to start implementation supervisor from a dirty checkout" >&2
      echo "commit or otherwise resolve the current Hammer/Leanstral integration first" >&2
      exit 10
    fi
    setsid "${PYTHON_BIN}" -m \
      ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor \
      --implement "${common_args[@]}" >> "${LOG_FILE}" 2>&1 &
    echo "$!" > "${PID_FILE}"
    echo "hammer_leanstral_supervisor=started pid=$! log=${LOG_FILE}"
    ;;
  stop)
    if ! supervisor_alive; then
      echo "hammer_leanstral_supervisor=stopped"
      exit 0
    fi
    pid="$(supervisor_pid)"
    daemon_pid="$(managed_daemon_pid)"
    if [[ -n "${daemon_pid}" ]] && ps -p "${daemon_pid}" >/dev/null 2>&1; then
      kill -TERM -- "-${daemon_pid}" 2>/dev/null || kill -TERM "${daemon_pid}" 2>/dev/null || true
    fi
    kill -TERM "${pid}"
    echo "hammer_leanstral_supervisor=stopping pid=${pid} daemon_pid=${daemon_pid:-none}"
    ;;
  status)
    if supervisor_alive; then
      echo "hammer_leanstral_supervisor=running pid=$(supervisor_pid)"
    else
      echo "hammer_leanstral_supervisor=stopped"
    fi
    echo "todo_path=${TODO_PATH}"
    echo "state_dir=${STATE_DIR}"
    "${PYTHON_BIN}" -c \
      'from collections import Counter; from pathlib import Path; import sys; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path(sys.argv[1])); counts=Counter(task.status for task in tasks); print("tasks={} completed={} todo={} in_progress={} blocked={}".format(len(tasks), counts.get("completed", 0), counts.get("todo", 0), counts.get("in_progress", 0), counts.get("blocked", 0)))' \
      "${TODO_PATH}"
    ;;
  *)
    echo "usage: $0 {start|stop|status|once}" >&2
    exit 2
    ;;
esac
