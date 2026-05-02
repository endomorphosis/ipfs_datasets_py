#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/legal_parser_optimizer_daemon}"
STALE_AFTER_SECONDS="${STALE_AFTER_SECONDS:-120}"

cd "$REPO_ROOT" || exit 2

python3 - "$OUTPUT_DIR/current_status.json" ".daemon/legal_parser_daemon_supervisor.json" "$OUTPUT_DIR/progress_summary.json" "$STALE_AFTER_SECONDS" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

status_path, supervisor_path, progress_path, stale_after_raw = sys.argv[1:5]
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


current = read_json(status_path)
supervisor = read_json(supervisor_path)
progress = read_json(progress_path)
now = datetime.now(timezone.utc)
heartbeat_at = parse_ts(current.get("heartbeat_at") or current.get("updated_at"))
heartbeat_age = None
if heartbeat_at is not None:
    heartbeat_age = max(0.0, (now - heartbeat_at).total_seconds())

daemon_pid = current.get("heartbeat_pid") or current.get("pid")
supervisor_pid = supervisor.get("supervisor_pid")
alive = bool(pid_alive(daemon_pid) and heartbeat_age is not None and heartbeat_age <= stale_after)

payload = {
    "alive": alive,
    "status": "running" if alive else "stale_or_stopped",
    "checked_at": now.isoformat(),
    "stale_after_seconds": stale_after,
    "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 3),
    "daemon_pid": daemon_pid,
    "daemon_pid_alive": pid_alive(daemon_pid) if daemon_pid else False,
    "supervisor_pid": supervisor_pid,
    "supervisor_pid_alive": pid_alive(supervisor_pid) if supervisor_pid else False,
    "cycle_index": current.get("cycle_index"),
    "phase": current.get("phase"),
    "model_name": current.get("model_name") or supervisor.get("model_name"),
    "provider": current.get("provider") or supervisor.get("provider"),
    "supervisor_status": supervisor.get("status"),
    "restart_count": supervisor.get("restart_count"),
    "watchdog_stale_after_seconds": supervisor.get("watchdog_stale_after_seconds"),
    "watchdog_startup_grace_seconds": supervisor.get("watchdog_startup_grace_seconds"),
    "last_recycle_reason": supervisor.get("last_recycle_reason"),
    "agentic_maintenance_enabled": supervisor.get("agentic_maintenance_enabled"),
    "agentic_stalled_metric_cycles": supervisor.get("agentic_stalled_metric_cycles"),
    "stalled_metric_cycles": progress.get("stalled_metric_cycles"),
    "cycles_since_meaningful_progress": progress.get("cycles_since_meaningful_progress"),
    "meaningful_progress_definition": progress.get("meaningful_progress_definition"),
    "rolled_back_since_meaningful_progress": progress.get("rolled_back_since_meaningful_progress"),
    "rolled_back_reasons_since_meaningful_progress": progress.get("rolled_back_reasons_since_meaningful_progress"),
    "active_dirty_touched_files": progress.get("active_dirty_touched_files"),
    "dirty_touched_file_rejection_count": progress.get("dirty_touched_file_rejection_count"),
    "agentic_rejected_tail": supervisor.get("agentic_rejected_tail"),
    "agentic_rolled_back_tail": supervisor.get("agentic_rolled_back_tail"),
    "agentic_cooldown_seconds": supervisor.get("agentic_cooldown_seconds"),
    "agentic_timeout_seconds": supervisor.get("agentic_timeout_seconds"),
    "agentic_state_path": supervisor.get("agentic_state_path"),
    "last_agentic_maintenance_status": supervisor.get("last_agentic_maintenance_status"),
    "last_agentic_maintenance_reason": supervisor.get("last_agentic_maintenance_reason"),
    "last_agentic_maintenance_log_path": supervisor.get("last_agentic_maintenance_log_path"),
    "current_status_path": status_path,
    "supervisor_status_path": supervisor_path,
}
print(json.dumps(payload, indent=2, sort_keys=True))
raise SystemExit(0 if alive else 1)
PY
