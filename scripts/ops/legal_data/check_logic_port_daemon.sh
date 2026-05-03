#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
STATUS_PATH="${STATUS_PATH:-$DAEMON_DIR/logic-port-daemon.status.json}"
PROGRESS_PATH="${PROGRESS_PATH:-$DAEMON_DIR/logic-port-daemon.progress.json}"
SUPERVISOR_STATUS_PATH="${SUPERVISOR_STATUS_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.status.json}"
STALE_AFTER_SECONDS="${STALE_AFTER_SECONDS:-180}"

cd "$REPO_ROOT" || exit 2

python3 - "$STATUS_PATH" "$PROGRESS_PATH" "$SUPERVISOR_STATUS_PATH" "$STALE_AFTER_SECONDS" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

status_path, progress_path, supervisor_path, stale_after_raw = sys.argv[1:5]
stale_after = float(stale_after_raw)


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def parse_ts(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


status = read_json(status_path)
progress = read_json(progress_path)
supervisor = read_json(supervisor_path)
now = datetime.now(timezone.utc)
heartbeat_at = parse_ts(
    status.get("heartbeat_at")
    or status.get("updated_at")
    or progress.get("updated_at")
    or supervisor.get("updated_at")
)
heartbeat_age = None
if heartbeat_at is not None:
    heartbeat_age = max(0.0, (now - heartbeat_at).total_seconds())

supervisor_pid = supervisor.get("supervisor_pid")
supervisor_alive = bool(supervisor_pid and pid_alive(supervisor_pid))
supervisor_daemon_pid = supervisor.get("daemon_pid")
status_daemon_pid = status.get("heartbeat_pid") or status.get("pid")
daemon_pid = supervisor_daemon_pid if supervisor_alive and supervisor_daemon_pid else status_daemon_pid
daemon_alive = bool(daemon_pid and pid_alive(daemon_pid))
fresh = heartbeat_age is not None and heartbeat_age <= stale_after
alive = bool(supervisor_alive and daemon_alive and fresh)

payload = {
    "alive": alive,
    "status": "running" if alive else "stale_or_stopped",
    "checked_at": now.isoformat(),
    "stale_after_seconds": stale_after,
    "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 3),
    "daemon_pid": daemon_pid,
    "daemon_pid_alive": daemon_alive,
    "status_daemon_pid": status_daemon_pid,
    "supervisor_daemon_pid": supervisor_daemon_pid,
    "supervisor_pid": supervisor_pid,
    "supervisor_pid_alive": supervisor_alive,
    "supervisor_status": supervisor.get("status"),
    "restart_count": supervisor.get("restart_count"),
    "watchdog_stale_after_seconds": supervisor.get("watchdog_stale_after_seconds"),
    "watchdog_startup_grace_seconds": supervisor.get("watchdog_startup_grace_seconds"),
    "stop_grace_seconds": supervisor.get("stop_grace_seconds"),
    "last_recycle_reason": supervisor.get("last_recycle_reason"),
    "active_state": progress.get("active_state") or status.get("active_state") or status.get("state"),
    "current_task": progress.get("current_task") or status.get("selected_task"),
    "plan_status_counts": progress.get("plan_status_counts"),
    "failure_kind_counts": progress.get("failure_kind_counts"),
    "typescript_quality_failures": progress.get("typescript_quality_failures"),
    "stagnant_rounds_since_valid": progress.get("stagnant_rounds_since_valid"),
    "latest_round": progress.get("latest_round"),
    "model_name": status.get("model_name") or supervisor.get("model_name"),
    "provider": status.get("provider") or supervisor.get("provider"),
    "router_default_mode": supervisor.get("router_default_mode"),
    "enable_ipfs_accelerate": supervisor.get("enable_ipfs_accelerate"),
    "status_path": status_path,
    "progress_path": progress_path,
    "supervisor_status_path": supervisor_path,
    "supervisor_lock_path": supervisor.get("supervisor_lock_path"),
    "agentic_maintenance_enabled": supervisor.get("agentic_maintenance_enabled"),
    "agentic_stagnant_rounds": supervisor.get("agentic_stagnant_rounds"),
    "agentic_task_failures": supervisor.get("agentic_task_failures"),
    "agentic_proposal_failures": supervisor.get("agentic_proposal_failures"),
    "agentic_rollback_failures": supervisor.get("agentic_rollback_failures"),
    "agentic_typescript_quality_failures": supervisor.get("agentic_typescript_quality_failures"),
    "agentic_cooldown_seconds": supervisor.get("agentic_cooldown_seconds"),
    "agentic_timeout_seconds": supervisor.get("agentic_timeout_seconds"),
    "agentic_state_path": supervisor.get("agentic_state_path"),
    "last_agentic_maintenance_status": supervisor.get("last_agentic_maintenance_status"),
    "last_agentic_maintenance_reason": supervisor.get("last_agentic_maintenance_reason"),
    "last_agentic_maintenance_log_path": supervisor.get("last_agentic_maintenance_log_path"),
}
print(json.dumps(payload, indent=2, sort_keys=True))
raise SystemExit(0 if alive else 1)
PY
