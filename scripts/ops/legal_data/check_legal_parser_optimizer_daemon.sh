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
ensure_path = ".daemon/legal_parser_daemon_ensure.status.json"
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

def pid_args(pid):
    if not pid_alive(pid):
        return ""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as handle:
            return handle.read().replace(b"\0", b" ").decode("utf-8", errors="replace")
    except Exception:
        return ""

def pid_is_legal_parser_wrapper(pid):
    args = pid_args(pid)
    return (
        "run_legal_parser_optimizer_daemon.sh" in args
        and "legal-parser supervisor exited with code" in args
    )


current = read_json(status_path)
supervisor = read_json(supervisor_path)
ensure = read_json(ensure_path)
progress = read_json(progress_path)
supervisor_state = read_json(supervisor.get("agentic_state_path", "")) if supervisor else {}
now = datetime.now(timezone.utc)
heartbeat_at = parse_ts(current.get("heartbeat_at") or current.get("updated_at"))
heartbeat_age = None
if heartbeat_at is not None:
    heartbeat_age = max(0.0, (now - heartbeat_at).total_seconds())

daemon_pid = current.get("heartbeat_pid") or current.get("pid")
supervisor_pid = supervisor.get("supervisor_pid")
supervisor_alive = pid_alive(supervisor_pid) if supervisor_pid else False
daemon_alive = pid_alive(daemon_pid) if daemon_pid else False
supervisor_status = str(supervisor.get("status") or "")
maintenance_timeout = supervisor.get("active_agentic_maintenance_timeout_seconds")
try:
    maintenance_timeout = float(maintenance_timeout)
except Exception:
    maintenance_timeout = float(supervisor.get("agentic_timeout_seconds") or 0.0)
maintenance_started_at = parse_ts(
    supervisor.get("active_agentic_maintenance_started_at") or supervisor.get("updated_at")
)
maintenance_age = None
maintenance_fresh = False
if (
    supervisor_alive
    and supervisor_status.endswith("_started")
    and str(supervisor.get("last_agentic_maintenance_status") or "").endswith("running")
    and maintenance_started_at is not None
    and maintenance_timeout > 0
):
    maintenance_age = max(0.0, (now - maintenance_started_at).total_seconds())
    maintenance_fresh = maintenance_age <= maintenance_timeout + 60.0
daemon_fresh = heartbeat_age is not None and heartbeat_age <= stale_after
alive = bool(supervisor_alive and ((daemon_alive and daemon_fresh) or maintenance_fresh))
status_label = "maintenance_running" if maintenance_fresh else "running" if alive else "stale_or_stopped"

payload = {
    "alive": alive,
    "status": status_label,
    "checked_at": now.isoformat(),
    "stale_after_seconds": stale_after,
    "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 3),
    "daemon_pid": daemon_pid,
    "daemon_pid_alive": daemon_alive,
    "supervisor_pid": supervisor_pid,
    "supervisor_pid_alive": supervisor_alive,
    "ensure_status": ensure.get("status"),
    "ensure_checked_at": ensure.get("checked_at"),
    "ensure_requested_launch_mode": ensure.get("requested_launch_mode"),
    "ensure_launch_mode": ensure.get("launch_mode"),
    "ensure_launcher_pid": ensure.get("launcher_pid"),
    "ensure_launcher_pid_alive": pid_is_legal_parser_wrapper(ensure.get("launcher_pid"))
    if ensure.get("launcher_pid")
    else False,
    "ensure_wrapper_pid": ensure.get("wrapper_pid"),
    "ensure_wrapper_pid_alive": pid_is_legal_parser_wrapper(ensure.get("wrapper_pid"))
    if ensure.get("wrapper_pid")
    else False,
    "ensure_supervisor_pid_alive": ensure.get("supervisor_pid_alive"),
    "cycle_index": current.get("cycle_index"),
    "phase": current.get("phase"),
    "model_name": current.get("model_name") or supervisor.get("model_name"),
    "provider": current.get("provider") or supervisor.get("provider"),
    "supervisor_status": supervisor.get("status"),
    "active_agentic_maintenance_started_at": supervisor.get("active_agentic_maintenance_started_at"),
    "active_agentic_maintenance_timeout_seconds": supervisor.get("active_agentic_maintenance_timeout_seconds"),
    "active_agentic_maintenance_age_seconds": None if maintenance_age is None else round(maintenance_age, 3),
    "active_agentic_maintenance_fresh": maintenance_fresh,
    "formal_logic_goal": supervisor.get("formal_logic_goal"),
    "restart_count": supervisor.get("restart_count"),
    "watchdog_stale_after_seconds": supervisor.get("watchdog_stale_after_seconds"),
    "watchdog_startup_grace_seconds": supervisor.get("watchdog_startup_grace_seconds"),
    "last_recycle_reason": supervisor.get("last_recycle_reason"),
    "phase_started_at": current.get("phase_started_at"),
    "phase_stale_after_seconds": current.get("phase_stale_after_seconds"),
    "phase_stale_after_reason": current.get("phase_stale_after_reason"),
    "agentic_maintenance_enabled": supervisor.get("agentic_maintenance_enabled"),
    "agentic_stalled_metric_cycles": supervisor.get("agentic_stalled_metric_cycles"),
    "agentic_acceptance_stall_cycles": supervisor.get("agentic_acceptance_stall_cycles"),
    "stalled_metric_cycles": progress.get("stalled_metric_cycles"),
    "cycles_since_meaningful_progress": progress.get("cycles_since_meaningful_progress"),
    "meaningful_progress_definition": progress.get("meaningful_progress_definition"),
    "rolled_back_since_meaningful_progress": progress.get("rolled_back_since_meaningful_progress"),
    "rolled_back_reasons_since_meaningful_progress": progress.get("rolled_back_reasons_since_meaningful_progress"),
    "current_dirty_legal_parser_targets": current.get("dirty_legal_parser_targets"),
    "current_dirty_legal_parser_targets_valid": current.get("dirty_legal_parser_targets_valid"),
    "current_dirty_legal_parser_targets_error": current.get("dirty_legal_parser_targets_error"),
    "current_dirty_legal_parser_targets_fingerprint": current.get("dirty_legal_parser_targets_fingerprint"),
    "current_dirty_legal_parser_targets_diff_summary": current.get(
        "dirty_legal_parser_targets_diff_summary"
    ),
    "progress_dirty_legal_parser_targets": progress.get("dirty_legal_parser_targets"),
    "progress_dirty_legal_parser_targets_valid": progress.get("dirty_legal_parser_targets_valid"),
    "progress_dirty_legal_parser_targets_error": progress.get("dirty_legal_parser_targets_error"),
    "progress_dirty_legal_parser_targets_fingerprint": progress.get("dirty_legal_parser_targets_fingerprint"),
    "progress_dirty_legal_parser_targets_diff_summary": progress.get(
        "dirty_legal_parser_targets_diff_summary"
    ),
    "active_dirty_touched_files": progress.get("active_dirty_touched_files"),
    "dirty_touched_file_rejection_count": progress.get("dirty_touched_file_rejection_count"),
    "supervisor_dirty_legal_parser_targets": supervisor_state.get("dirty_legal_parser_targets"),
    "supervisor_dirty_legal_parser_targets_fingerprint": supervisor_state.get("dirty_legal_parser_targets_fingerprint"),
    "supervisor_previous_dirty_legal_parser_targets": supervisor_state.get(
        "previous_dirty_legal_parser_targets"
    ),
    "supervisor_previous_dirty_legal_parser_targets_fingerprint": supervisor_state.get(
        "previous_dirty_legal_parser_targets_fingerprint"
    ),
    "supervisor_dirty_legal_parser_targets_confirmed": supervisor_state.get(
        "dirty_legal_parser_targets_confirmed"
    ),
    "supervisor_dirty_target_detection_valid": supervisor_state.get("dirty_target_detection_valid"),
    "supervisor_dirty_target_detection_errors": supervisor_state.get("dirty_target_detection_errors"),
    "supervisor_dirty_legal_parser_targets_deferred": supervisor_state.get("dirty_legal_parser_targets_deferred"),
    "supervisor_dirty_legal_parser_targets_defer_phase": supervisor_state.get("dirty_legal_parser_targets_defer_phase"),
    "supervisor_dirty_legal_parser_targets_pending_confirmation": supervisor_state.get(
        "dirty_legal_parser_targets_pending_confirmation"
    ),
    "supervisor_dirty_rejection_active_targets": supervisor_state.get("dirty_rejection_active_targets"),
    "supervisor_effective_phase_stall_threshold_seconds": supervisor_state.get(
        "effective_phase_stall_threshold_seconds"
    ),
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
