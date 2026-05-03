#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/legal_parser_optimizer_daemon}"
MODEL_NAME="${MODEL_NAME:-gpt-5.5}"
PROVIDER="${PROVIDER:-llm_router}"
# Call llm_router by default. The router backend defaults to codex_cli, but callers
# can override it with IPFS_DATASETS_PY_LLM_PROVIDER without changing daemon wiring.
IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-codex_cli}"
RESTART_BACKOFF_SECONDS="${RESTART_BACKOFF_SECONDS:-30}"
LLM_TIMEOUT_SECONDS="${LLM_TIMEOUT_SECONDS:-900}"
TEST_TIMEOUT_SECONDS="${TEST_TIMEOUT_SECONDS:-600}"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-10}"
LLM_PROPOSAL_ATTEMPTS="${LLM_PROPOSAL_ATTEMPTS:-3}"
DAEMON_DIR="${DAEMON_DIR:-.daemon}"
SUPERVISOR_HEARTBEAT_SECONDS="${SUPERVISOR_HEARTBEAT_SECONDS:-30}"
WATCHDOG_STALE_AFTER_SECONDS="${WATCHDOG_STALE_AFTER_SECONDS:-420}"
WATCHDOG_STARTUP_GRACE_SECONDS="${WATCHDOG_STARTUP_GRACE_SECONDS:-120}"
STOP_GRACE_SECONDS="${STOP_GRACE_SECONDS:-10}"
SUPERVISOR_STOP_COMPETING_DAEMONS="${SUPERVISOR_STOP_COMPETING_DAEMONS:-1}"
SUPERVISOR_DISABLE_COMPETING_SYSTEMD_SERVICE="${SUPERVISOR_DISABLE_COMPETING_SYSTEMD_SERVICE:-1}"
SUPERVISOR_STOP_LOGIC_PORT_DAEMON="${SUPERVISOR_STOP_LOGIC_PORT_DAEMON:-0}"
SUPERVISOR_DIRTY_TARGET_RECOVERY="${SUPERVISOR_DIRTY_TARGET_RECOVERY:-1}"
SUPERVISOR_DIRTY_TARGET_GRACE_SECONDS="${SUPERVISOR_DIRTY_TARGET_GRACE_SECONDS:-120}"
SUPERVISOR_AGENTIC_MAINTENANCE="${SUPERVISOR_AGENTIC_MAINTENANCE:-1}"
SUPERVISOR_AGENTIC_STALLED_METRIC_CYCLES="${SUPERVISOR_AGENTIC_STALLED_METRIC_CYCLES:-40}"
SUPERVISOR_AGENTIC_REJECTED_TAIL="${SUPERVISOR_AGENTIC_REJECTED_TAIL:-25}"
SUPERVISOR_AGENTIC_ROLLED_BACK_TAIL="${SUPERVISOR_AGENTIC_ROLLED_BACK_TAIL:-10}"
SUPERVISOR_AGENTIC_DIRTY_TARGET_FILES="${SUPERVISOR_AGENTIC_DIRTY_TARGET_FILES:-1}"
SUPERVISOR_AGENTIC_DIRTY_REJECTION_TAIL="${SUPERVISOR_AGENTIC_DIRTY_REJECTION_TAIL:-3}"
SUPERVISOR_AGENTIC_REPEATED_REJECTION_FAMILY_TAIL="${SUPERVISOR_AGENTIC_REPEATED_REJECTION_FAMILY_TAIL:-4}"
SUPERVISOR_REPEATED_REJECTION_RECOVERY="${SUPERVISOR_REPEATED_REJECTION_RECOVERY:-1}"
SUPERVISOR_RECOVERY_FAILURE_ESCALATION_TAIL="${SUPERVISOR_RECOVERY_FAILURE_ESCALATION_TAIL:-2}"
SUPERVISOR_AGENTIC_CYCLE_STALL_SECONDS="${SUPERVISOR_AGENTIC_CYCLE_STALL_SECONDS:-1800}"
SUPERVISOR_AGENTIC_COOLDOWN_SECONDS="${SUPERVISOR_AGENTIC_COOLDOWN_SECONDS:-3600}"
SUPERVISOR_AGENTIC_TIMEOUT_SECONDS="${SUPERVISOR_AGENTIC_TIMEOUT_SECONDS:-1200}"
SUPERVISOR_AGENTIC_SANDBOX="${SUPERVISOR_AGENTIC_SANDBOX:-danger-full-access}"
CODEX_BIN="${CODEX_BIN:-codex}"

SUPERVISOR_STATUS_PATH="${SUPERVISOR_STATUS_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.json}"
SUPERVISOR_AGENTIC_STATE_PATH="${SUPERVISOR_AGENTIC_STATE_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor_agentic_state.json}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.pid}"
SUPERVISOR_LOCK_PATH="${SUPERVISOR_LOCK_PATH:-$DAEMON_DIR/legal_parser_daemon_supervisor.lock}"
BASELINE_DIRTY_TARGET_MANIFEST_PATH="${BASELINE_DIRTY_TARGET_MANIFEST_PATH:-$DAEMON_DIR/legal_parser_dirty_target_baseline.json}"
BASELINE_DIRTY_TARGET_SNAPSHOT_DIR="${BASELINE_DIRTY_TARGET_SNAPSHOT_DIR:-$DAEMON_DIR/legal_parser_dirty_target_baseline_files}"
CHILD_PID_PATH="${CHILD_PID_PATH:-$DAEMON_DIR/legal_parser_daemon.pid}"
LATEST_LOG_PATH="${LATEST_LOG_PATH:-$DAEMON_DIR/legal_parser_daemon_overnight.log}"
CURRENT_STATUS_PATH="$OUTPUT_DIR/current_status.json"
PROGRESS_PATH="$OUTPUT_DIR/progress_summary.json"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"

exec 9>"$REPO_ROOT/$SUPERVISOR_LOCK_PATH"
if ! flock -n 9; then
  existing_pid=""
  if [[ -f "$REPO_ROOT/$SUPERVISOR_PID_PATH" ]]; then
    existing_pid="$(tr -dc '0-9' < "$REPO_ROOT/$SUPERVISOR_PID_PATH" 2>/dev/null || true)"
  fi
  echo "legal-parser daemon supervisor lock is held${existing_pid:+ by PID $existing_pid}"
  exit 0
fi

printf '%s\n' "$$" > "$REPO_ROOT/$SUPERVISOR_PID_PATH"

child_pid=""
restart_count=0
cleaning_up=0
last_recycle_reason=""
last_agentic_maintenance_status=""
last_agentic_maintenance_reason=""
last_agentic_maintenance_log_path=""

json_bool() {
  [[ "$1" == "1" ]] && printf true || printf false
}

snapshot_dirty_legal_parser_target_baseline() {
  python3 - "$REPO_ROOT" "$REPO_ROOT/$BASELINE_DIRTY_TARGET_MANIFEST_PATH" "$REPO_ROOT/$BASELINE_DIRTY_TARGET_SNAPSHOT_DIR" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
snapshot_dir = Path(sys.argv[3])
targets = [
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/exports.py",
    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    "tests/unit_tests/logic/deontic/test_deontic_converter.py",
    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
]
result = subprocess.run(
    ["git", "status", "--porcelain", "--", *targets],
    cwd=repo_root,
    text=True,
    capture_output=True,
    timeout=30,
)
if result.returncode != 0:
    raise SystemExit(result.returncode)
paths = []
entries = {}
for line in result.stdout.splitlines():
    path = line[3:].strip()
    if " -> " in path:
        path = path.rsplit(" -> ", 1)[1].strip()
    if not path or path in paths:
        continue
    paths.append(path)
    src = repo_root / path
    snapshot_path = snapshot_dir / path
    entry = {
        "path": path,
        "snapshot_path": str(snapshot_path.relative_to(repo_root)),
        "exists": src.exists(),
    }
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, snapshot_path)
    else:
        snapshot_path.unlink(missing_ok=True)
    entries[path] = entry
manifest = {
    "paths": paths,
    "entries": entries,
}
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

restore_legal_parser_targets_from_baseline_or_head() {
  local targets_file="$1"
  python3 - "$REPO_ROOT" "$REPO_ROOT/$BASELINE_DIRTY_TARGET_MANIFEST_PATH" "$targets_file" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
targets_path = Path(sys.argv[3])
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception:
    manifest = {}
entries = manifest.get("entries")
if not isinstance(entries, dict):
    entries = {}
targets = [line.strip() for line in targets_path.read_text(encoding="utf-8").splitlines() if line.strip()]
head_targets = []
for path_text in targets:
    entry = entries.get(path_text)
    if not isinstance(entry, dict):
        head_targets.append(path_text)
        continue
    snapshot_rel = str(entry.get("snapshot_path") or "").strip()
    dst = repo_root / path_text
    if bool(entry.get("exists")):
        if not snapshot_rel:
            head_targets.append(path_text)
            continue
        snapshot_path = repo_root / snapshot_rel
        if not snapshot_path.exists():
            head_targets.append(path_text)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_path, dst)
    else:
        dst.unlink(missing_ok=True)
if head_targets:
    subprocess.run(
        ["git", "restore", "--source=HEAD", "--", *head_targets],
        cwd=repo_root,
        check=True,
        timeout=60,
    )
PY
}

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
  "schema": "ipfs_datasets_py.legal_parser_daemon.supervisor",
  "status": "$status",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo_root": "$REPO_ROOT",
  "supervisor_pid": $$,
  "daemon_pid": $daemon_pid_json,
  "restart_count": $restart_count,
  "restart_backoff_seconds": $RESTART_BACKOFF_SECONDS,
  "supervisor_heartbeat_seconds": $SUPERVISOR_HEARTBEAT_SECONDS,
  "watchdog_stale_after_seconds": $WATCHDOG_STALE_AFTER_SECONDS,
  "watchdog_startup_grace_seconds": $WATCHDOG_STARTUP_GRACE_SECONDS,
  "stop_grace_seconds": $STOP_GRACE_SECONDS,
  "stop_competing_daemons": $(json_bool "$SUPERVISOR_STOP_COMPETING_DAEMONS"),
  "disable_competing_systemd_service": $(json_bool "$SUPERVISOR_DISABLE_COMPETING_SYSTEMD_SERVICE"),
  "stop_logic_port_daemon": $(json_bool "$SUPERVISOR_STOP_LOGIC_PORT_DAEMON"),
  "dirty_target_recovery_enabled": $(json_bool "$SUPERVISOR_DIRTY_TARGET_RECOVERY"),
  "run_id": "$run_id",
  "log_path": "$log_path",
  "current_status_path": "$CURRENT_STATUS_PATH",
  "progress_path": "$PROGRESS_PATH",
  "child_pid_path": "$CHILD_PID_PATH",
  "supervisor_lock_path": "$SUPERVISOR_LOCK_PATH",
  "agentic_maintenance_enabled": $(json_bool "$SUPERVISOR_AGENTIC_MAINTENANCE"),
  "agentic_stalled_metric_cycles": $SUPERVISOR_AGENTIC_STALLED_METRIC_CYCLES,
  "agentic_rejected_tail": $SUPERVISOR_AGENTIC_REJECTED_TAIL,
  "agentic_rolled_back_tail": $SUPERVISOR_AGENTIC_ROLLED_BACK_TAIL,
  "agentic_dirty_target_files_enabled": $(json_bool "$SUPERVISOR_AGENTIC_DIRTY_TARGET_FILES"),
  "agentic_dirty_rejection_tail": $SUPERVISOR_AGENTIC_DIRTY_REJECTION_TAIL,
  "agentic_repeated_rejection_family_tail": $SUPERVISOR_AGENTIC_REPEATED_REJECTION_FAMILY_TAIL,
  "repeated_rejection_recovery_enabled": $(json_bool "$SUPERVISOR_REPEATED_REJECTION_RECOVERY"),
  "recovery_failure_escalation_tail": $SUPERVISOR_RECOVERY_FAILURE_ESCALATION_TAIL,
  "agentic_cycle_stall_seconds": $SUPERVISOR_AGENTIC_CYCLE_STALL_SECONDS,
  "agentic_cooldown_seconds": $SUPERVISOR_AGENTIC_COOLDOWN_SECONDS,
  "agentic_timeout_seconds": $SUPERVISOR_AGENTIC_TIMEOUT_SECONDS,
  "agentic_state_path": "$SUPERVISOR_AGENTIC_STATE_PATH",
  "last_agentic_maintenance_status": "$last_agentic_maintenance_status",
  "last_agentic_maintenance_reason": "$last_agentic_maintenance_reason",
  "last_agentic_maintenance_log_path": "$last_agentic_maintenance_log_path",
  "model_name": "$MODEL_NAME",
  "provider": "$PROVIDER",
  "llm_timeout_seconds": $LLM_TIMEOUT_SECONDS,
  "test_timeout_seconds": $TEST_TIMEOUT_SECONDS,
  "llm_proposal_attempts": $LLM_PROPOSAL_ATTEMPTS,
  "last_exit_code": $last_exit_code,
  "last_recycle_reason": "$last_recycle_reason"
}
JSON
}

daemon_heartbeat_age_seconds() {
  python3 - "$REPO_ROOT/$CURRENT_STATUS_PATH" <<'PY'
import json
import sys
from datetime import datetime, timezone

try:
    status = json.load(open(sys.argv[1], "r", encoding="utf-8"))
except Exception:
    raise SystemExit(0)

raw = status.get("heartbeat_at") or status.get("updated_at")
if not raw:
    raise SystemExit(0)
try:
    heartbeat_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
except ValueError:
    raise SystemExit(0)
print(max(0.0, (datetime.now(timezone.utc) - heartbeat_at).total_seconds()))
PY
}

agentic_maintenance_reason() {
  if [[ "$SUPERVISOR_AGENTIC_MAINTENANCE" != "1" ]]; then
    return 1
  fi
  python3 - \
    "$REPO_ROOT/$PROGRESS_PATH" \
    "$REPO_ROOT/$CURRENT_STATUS_PATH" \
    "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" \
    "$REPO_ROOT" \
    "$SUPERVISOR_AGENTIC_STALLED_METRIC_CYCLES" \
    "$SUPERVISOR_AGENTIC_REJECTED_TAIL" \
    "$SUPERVISOR_AGENTIC_ROLLED_BACK_TAIL" \
    "$SUPERVISOR_AGENTIC_CYCLE_STALL_SECONDS" \
    "$SUPERVISOR_AGENTIC_COOLDOWN_SECONDS" \
    "$SUPERVISOR_AGENTIC_DIRTY_TARGET_FILES" \
    "$SUPERVISOR_AGENTIC_DIRTY_REJECTION_TAIL" \
    "$SUPERVISOR_AGENTIC_REPEATED_REJECTION_FAMILY_TAIL" \
    "$SUPERVISOR_DIRTY_TARGET_GRACE_SECONDS" <<'PY'
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

progress_path = Path(sys.argv[1])
status_path = Path(sys.argv[2])
state_path = Path(sys.argv[3])
repo_root = Path(sys.argv[4])
stalled_metric_threshold = int(sys.argv[5])
rejected_tail_threshold = int(sys.argv[6])
rolled_back_tail_threshold = int(sys.argv[7])
cycle_stall_seconds = int(sys.argv[8])
cooldown_seconds = int(sys.argv[9])
dirty_target_detection = str(sys.argv[10]).strip() == "1"
dirty_rejection_threshold = int(sys.argv[11])
repeated_rejection_family_threshold = int(sys.argv[12])
dirty_target_grace_seconds = int(sys.argv[13])
now = int(time.time())


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_epoch(value) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


LEGAL_PARSER_TARGETS = [
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/exports.py",
    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    "tests/unit_tests/logic/deontic/test_deontic_converter.py",
    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
]

dirty_status_errors: list[dict] = []
dirty_target_fingerprint = ""


def paths_from_git_status_porcelain(stdout: str) -> list[str]:
    paths: list[str] = []
    for line in stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def dirty_legal_parser_targets() -> list[str]:
    global dirty_target_fingerprint
    if not dirty_target_detection:
        return []
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *LEGAL_PARSER_TARGETS],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        return []
    if result.returncode != 0:
        dirty_status_errors.append(
            {
                "scope": "legal_parser_targets",
                "returncode": result.returncode,
                "stderr_tail": result.stderr[-1000:],
            }
        )
        return []
    paths = paths_from_git_status_porcelain(result.stdout)
    dirty_target_fingerprint = legal_parser_target_fingerprint(result.stdout, paths)
    return paths


def legal_parser_target_fingerprint(status_stdout: str, paths: list[str]) -> str:
    if not paths:
        return ""
    import hashlib

    digest = hashlib.sha256()
    digest.update(status_stdout.encode("utf-8", errors="replace"))
    try:
        diff = subprocess.run(
            ["git", "diff", "--binary", "--", *paths],
            cwd=repo_root,
            text=False,
            capture_output=True,
            timeout=60,
        )
        digest.update(diff.stdout or b"")
    except Exception as exc:
        digest.update(f"__diff_error__:{exc}".encode("utf-8", errors="replace"))
    for path_text in sorted(paths):
        digest.update(path_text.encode("utf-8", errors="replace"))
        path = repo_root / path_text
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"__missing__")
        except OSError as exc:
            digest.update(f"__read_error__:{exc}".encode("utf-8", errors="replace"))
    return digest.hexdigest()


def git_dirty_files(paths: list[str]) -> list[str]:
    if not paths:
        return []
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *paths],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        return []
    if result.returncode != 0:
        dirty_status_errors.append(
            {
                "scope": "dirty_rejection_files",
                "returncode": result.returncode,
                "stderr_tail": result.stderr[-1000:],
            }
        )
        return []
    return paths_from_git_status_porcelain(result.stdout)


def dirty_rejection_files(rejections: list[dict]) -> list[str]:
    files: list[str] = []
    for item in rejections:
        if "pre-existing uncommitted changes" not in json.dumps(item, sort_keys=True):
            continue
        candidate_files = item.get("dirty_touched_files") or item.get("changed_files") or []
        for path in candidate_files:
            text = str(path).strip()
            if text and text not in files:
                files.append(text)
    return files


def _rejection_family_key(item: dict) -> str:
    reason = str(item.get("reason") or "")
    if ":" in reason:
        reason = reason.split(":", 1)[0]
    changed_files = [str(path).strip() for path in (item.get("changed_files") or []) if str(path).strip()]
    return json.dumps(
        {
            "reason": reason,
            "changed_files": sorted(changed_files),
        },
        sort_keys=True,
    )


def repeated_rejection_family(rejections: list[dict]) -> dict:
    if not rejections:
        return {}
    counts: dict[str, int] = {}
    payloads: dict[str, dict] = {}
    for item in rejections:
        if not isinstance(item, dict):
            continue
        key = _rejection_family_key(item)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        payloads[key] = item
    if not counts:
        return {}
    winner = max(counts.items(), key=lambda pair: pair[1])[0]
    item = dict(payloads.get(winner) or {})
    item["count"] = counts[winner]
    return item


progress = read_json(progress_path)
status = read_json(status_path)
if not progress and not status:
    raise SystemExit(1)

state = read_json(state_path)
last_maintenance_at = int(state.get("last_maintenance_at") or 0)
run_baseline_head = str(status.get("baseline_head") or "")
goal_epoch_started_at = str(progress.get("goal_epoch_started_at") or "")
state_baseline_head = str(state.get("baseline_head") or "")
state_goal_epoch_started_at = str(state.get("goal_epoch_started_at") or "")
baseline_context_changed = (
    (run_baseline_head and run_baseline_head != state_baseline_head)
    or (
        goal_epoch_started_at
        and goal_epoch_started_at != state_goal_epoch_started_at
    )
)
if baseline_context_changed:
    last_maintenance_at = 0
cooling_down = last_maintenance_at > 0 and now - last_maintenance_at < cooldown_seconds

latest_cycle_index = int(progress.get("latest_cycle_index") or status.get("cycle_index") or 0)
accepted_count = int(progress.get("retained_accepted_patch_count") or progress.get("accepted_patch_count") or 0)
rolled_back_count = int(progress.get("rolled_back_count") or 0)
rejected_count = int(progress.get("rejected_patch_count") or progress.get("rejected_count") or 0)
stalled_metric_cycles = int(progress.get("stalled_metric_cycles") or 0)
cycles_since_meaningful_progress = int(
    progress.get("cycles_since_meaningful_progress") or stalled_metric_cycles
)
rolled_back_reasons_since_progress = progress.get("rolled_back_reasons_since_meaningful_progress")
if not isinstance(rolled_back_reasons_since_progress, dict):
    rolled_back_reasons_since_progress = {}
metric_stall_rollbacks_since_progress = int(
    rolled_back_reasons_since_progress.get("metric_stall_no_metric_progress") or 0
)
recent_rejections = progress.get("recent_rejections")
if not isinstance(recent_rejections, list):
    recent_rejections = []
repeated_rejection = repeated_rejection_family(recent_rejections)
repeated_rejection_count = int(repeated_rejection.get("count") or 0)
dirty_preexisting_rejections = [
    item
    for item in recent_rejections
    if "pre-existing uncommitted changes" in json.dumps(item, sort_keys=True)
]
dirty_targets = dirty_legal_parser_targets()
dirty_rejection_targets = git_dirty_files(dirty_rejection_files(dirty_preexisting_rejections))
previous_dirty_payload = state.get("dirty_legal_parser_targets")
previous_dirty_targets = [
    str(path)
    for path in previous_dirty_payload
] if isinstance(previous_dirty_payload, list) else []
previous_dirty_fingerprint = str(state.get("dirty_legal_parser_targets_fingerprint") or "")
dirty_targets_confirmed = bool(
    dirty_targets
    and sorted(previous_dirty_targets) == sorted(dirty_targets)
    and previous_dirty_fingerprint == dirty_target_fingerprint
)

baseline_cycle = int(state.get("baseline_cycle_index") or latest_cycle_index)
baseline_accepted = int(state.get("baseline_accepted_count") or accepted_count)
baseline_rolled_back = int(state.get("baseline_rolled_back_count") or rolled_back_count)
baseline_rejected = int(state.get("baseline_rejected_count") or rejected_count)
baseline_metric_stall_rollbacks = int(
    state.get("baseline_metric_stall_rollbacks_since_progress") or metric_stall_rollbacks_since_progress
)

if baseline_context_changed:
    baseline_cycle = latest_cycle_index
    baseline_accepted = accepted_count
    baseline_rolled_back = rolled_back_count
    baseline_rejected = rejected_count
    baseline_metric_stall_rollbacks = metric_stall_rollbacks_since_progress
elif accepted_count > baseline_accepted:
    baseline_cycle = latest_cycle_index
    baseline_accepted = accepted_count
    baseline_rolled_back = rolled_back_count
    baseline_rejected = rejected_count
    baseline_metric_stall_rollbacks = metric_stall_rollbacks_since_progress

cycle_delta = max(0, latest_cycle_index - baseline_cycle)
rolled_back_delta = max(0, rolled_back_count - baseline_rolled_back)
rejected_delta = max(0, rejected_count - baseline_rejected)
metric_stall_rollback_delta = max(0, metric_stall_rollbacks_since_progress - baseline_metric_stall_rollbacks)
phase_epoch = parse_epoch(status.get("phase_started_at") or "")
updated_epoch = parse_epoch(status.get("updated_at") or status.get("heartbeat_at"))
phase_stall_age = max(0, now - phase_epoch) if phase_epoch else 0
status_stall_age = max(0, now - updated_epoch) if updated_epoch else 0
try:
    phase_status_budget = int(status.get("phase_stale_after_seconds") or 0)
except (TypeError, ValueError):
    phase_status_budget = 0
effective_phase_stall_threshold = cycle_stall_seconds
if phase_status_budget > 0:
    effective_phase_stall_threshold = max(cycle_stall_seconds, phase_status_budget)
phase_stale = bool(
    effective_phase_stall_threshold > 0
    and phase_stall_age >= effective_phase_stall_threshold
)
dirty_defer_phases = {
    "applying_patch",
    "post_apply_validation",
    "running_tests",
    "evaluating_retained_change",
    "rolling_back_metric_stall_no_progress",
}
current_phase = str(status.get("phase") or "")
dirty_targets_deferred = bool(
    dirty_targets
    and (
        current_phase in dirty_defer_phases
        or (not phase_stale and status_stall_age < dirty_target_grace_seconds)
    )
    and not phase_stale
)
dirty_targets_pending_confirmation = bool(
    dirty_targets
    and not dirty_targets_deferred
    and not dirty_targets_confirmed
)

reason = ""
if dirty_targets and not dirty_targets_deferred and dirty_targets_confirmed:
    reason = "dirty_legal_parser_targets:" + ",".join(dirty_targets[:8])
elif dirty_targets_pending_confirmation:
    reason = ""
elif len(dirty_preexisting_rejections) >= dirty_rejection_threshold and dirty_rejection_targets:
    reason = (
        f"dirty_touched_file_rejections:{len(dirty_preexisting_rejections)}:"
        f"threshold:{dirty_rejection_threshold}:active_dirty_files:{','.join(dirty_rejection_targets[:8])}"
    )
elif not cooling_down and repeated_rejection_count >= repeated_rejection_family_threshold:
    repeated_reason = str(repeated_rejection.get("reason") or "unknown")
    repeated_files = [
        str(path).strip()
        for path in (repeated_rejection.get("changed_files") or [])
        if str(path).strip()
    ]
    reason = (
        f"repeated_rejection_family:{repeated_rejection_count}:"
        f"threshold:{repeated_rejection_family_threshold}:"
        f"reason:{repeated_reason}:files:{','.join(repeated_files[:8])}"
    )
elif (
    not cooling_down
    and stalled_metric_cycles >= stalled_metric_threshold
    and cycles_since_meaningful_progress >= stalled_metric_threshold
):
    reason = (
        f"stalled_metric_cycles:{stalled_metric_cycles}:"
        f"cycles_since_meaningful_progress:{cycles_since_meaningful_progress}:"
        f"threshold:{stalled_metric_threshold}"
    )
elif not cooling_down and metric_stall_rollback_delta >= rolled_back_tail_threshold:
    reason = (
        f"metric_stall_rollbacks_without_acceptance:{metric_stall_rollback_delta}:"
        f"threshold:{rolled_back_tail_threshold}"
    )
elif not cooling_down and rolled_back_delta >= rolled_back_tail_threshold:
    reason = f"rolled_back_without_acceptance:{rolled_back_delta}:threshold:{rolled_back_tail_threshold}"
elif not cooling_down and rejected_delta >= rejected_tail_threshold:
    reason = f"rejected_without_acceptance:{rejected_delta}:threshold:{rejected_tail_threshold}"
elif (
    not cooling_down
    and phase_stale
):
    reason = (
        f"phase_stale:{phase_stall_age}s:phase:{current_phase or 'unknown'}:"
        f"threshold:{effective_phase_stall_threshold}"
    )

state.update(
    {
        "updated_at_epoch": now,
        "baseline_cycle_index": baseline_cycle,
        "baseline_accepted_count": baseline_accepted,
        "baseline_rolled_back_count": baseline_rolled_back,
        "baseline_rejected_count": baseline_rejected,
        "baseline_metric_stall_rollbacks_since_progress": baseline_metric_stall_rollbacks,
        "baseline_head": run_baseline_head,
        "goal_epoch_started_at": goal_epoch_started_at,
        "baseline_context_changed": baseline_context_changed,
        "last_maintenance_at": last_maintenance_at,
        "latest_cycle_index": latest_cycle_index,
        "accepted_count": accepted_count,
        "rolled_back_count": rolled_back_count,
        "rejected_count": rejected_count,
        "metric_stall_rollbacks_since_progress": metric_stall_rollbacks_since_progress,
        "stalled_metric_cycles": stalled_metric_cycles,
        "cycles_since_meaningful_progress": cycles_since_meaningful_progress,
        "cycles_since_acceptance": cycle_delta,
        "rolled_back_since_acceptance": rolled_back_delta,
        "rejected_since_acceptance": rejected_delta,
        "metric_stall_rollbacks_since_acceptance": metric_stall_rollback_delta,
        "dirty_legal_parser_targets": dirty_targets,
        "dirty_legal_parser_targets_fingerprint": dirty_target_fingerprint,
        "previous_dirty_legal_parser_targets": previous_dirty_targets,
        "previous_dirty_legal_parser_targets_fingerprint": previous_dirty_fingerprint,
        "dirty_legal_parser_targets_confirmed": dirty_targets_confirmed,
        "dirty_target_detection_valid": not dirty_status_errors,
        "dirty_target_detection_errors": dirty_status_errors,
        "dirty_legal_parser_targets_deferred": dirty_targets_deferred,
        "dirty_legal_parser_targets_defer_phase": current_phase if dirty_targets_deferred else "",
        "dirty_legal_parser_targets_pending_confirmation": dirty_targets_pending_confirmation,
        "dirty_touched_file_rejections": len(dirty_preexisting_rejections),
        "dirty_rejection_active_targets": dirty_rejection_targets,
        "repeated_rejection_family": repeated_rejection,
        "repeated_rejection_family_count": repeated_rejection_count,
        "phase_stall_age_seconds": phase_stall_age,
        "status_stall_age_seconds": status_stall_age,
        "phase_status_budget_seconds": phase_status_budget,
        "effective_phase_stall_threshold_seconds": effective_phase_stall_threshold,
        "cooling_down": cooling_down,
        "candidate_reason": reason,
    }
)
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if reason:
    print(reason)
    raise SystemExit(0)
raise SystemExit(1)
PY
}

mark_agentic_maintenance_ran() {
  local reason="$1"
  python3 - "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" "$reason" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
reason = sys.argv[2]
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {}
state["last_maintenance_at"] = int(time.time())
state["last_maintenance_reason"] = reason
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

clear_recovery_failure_state() {
  python3 - "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {}
for key in (
    "recent_recovery_failures",
    "last_recovery_failure",
    "recovery_failure_escalation_reason",
):
    state.pop(key, None)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

record_recovery_failure() {
  local recovery_kind="$1"
  local reason="$2"
  local recovery_log="$3"
  local targets_file="$4"
  python3 - "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" "$recovery_kind" "$reason" "$REPO_ROOT/$recovery_log" "$targets_file" <<'PY'
import json
import re
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1])
recovery_kind = sys.argv[2]
reason = sys.argv[3]
log_path = Path(sys.argv[4])
targets_path = Path(sys.argv[5])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    state = {}
try:
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
except Exception:
    log_text = ""
try:
    targets = [line.strip() for line in targets_path.read_text(encoding="utf-8").splitlines() if line.strip()]
except Exception:
    targets = []

failed_lines = []
for line in log_text.splitlines():
    stripped = line.strip()
    if stripped.startswith("FAILED ") or stripped.startswith("E   "):
        failed_lines.append(stripped)
summary = " | ".join(failed_lines[:12]).strip()
if not summary:
    tail_lines = [line.strip() for line in log_text.splitlines()[-40:] if line.strip()]
    summary = " | ".join(tail_lines[-12:])[:4000]
summary = re.sub(r"\s+", " ", summary).strip()[:4000]

reason_family = reason.split(":", 1)[0] if ":" in reason else reason
record = {
    "recovery_kind": recovery_kind,
    "reason": reason,
    "reason_family": reason_family,
    "targets": targets,
    "failure_signature": summary,
    "recorded_at": int(time.time()),
}
recent = state.get("recent_recovery_failures")
if not isinstance(recent, list):
    recent = []
recent.append(record)
state["recent_recovery_failures"] = recent[-12:]
state["last_recovery_failure"] = record
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

confirmed_recovery_failure_escalation_reason() {
  if [[ "$SUPERVISOR_AGENTIC_MAINTENANCE" != "1" ]]; then
    return 1
  fi
  python3 - "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" "$SUPERVISOR_RECOVERY_FAILURE_ESCALATION_TAIL" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
threshold = int(sys.argv[2])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    state = {}
recent = state.get("recent_recovery_failures")
if not isinstance(recent, list) or len(recent) < threshold:
    raise SystemExit(1)
latest = recent[-1]
if not isinstance(latest, dict):
    raise SystemExit(1)
signature = str(latest.get("failure_signature") or "").strip()
reason_family = str(latest.get("reason_family") or "").strip()
recovery_kind = str(latest.get("recovery_kind") or "").strip()
targets = [str(path).strip() for path in (latest.get("targets") or []) if str(path).strip()]
if not signature or not reason_family or not recovery_kind:
    raise SystemExit(1)
match_count = 0
for item in reversed(recent):
    if not isinstance(item, dict):
        continue
    if str(item.get("failure_signature") or "").strip() != signature:
        continue
    if str(item.get("reason_family") or "").strip() != reason_family:
        continue
    if str(item.get("recovery_kind") or "").strip() != recovery_kind:
        continue
    if [str(path).strip() for path in (item.get("targets") or []) if str(path).strip()] != targets:
        continue
    match_count += 1
if match_count < threshold:
    raise SystemExit(1)
reason = (
    f"repeated_recovery_failure:{match_count}:threshold:{threshold}:"
    f"kind:{recovery_kind}:reason_family:{reason_family}:"
    f"targets:{','.join(targets[:8])}:signature:{signature[:500]}"
)
state["recovery_failure_escalation_reason"] = reason
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(reason)
raise SystemExit(0)
PY
}

confirmed_dirty_target_reason() {
  if [[ "$SUPERVISOR_DIRTY_TARGET_RECOVERY" != "1" ]]; then
    return 1
  fi
  python3 - \
    "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" \
    "$REPO_ROOT" \
    "$REPO_ROOT/$CURRENT_STATUS_PATH" \
    "$REPO_ROOT/$PROGRESS_PATH" \
    "$SUPERVISOR_AGENTIC_DIRTY_TARGET_FILES" \
    "$SUPERVISOR_DIRTY_TARGET_GRACE_SECONDS" <<'PY'
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
status_path = Path(sys.argv[3])
progress_path = Path(sys.argv[4])
dirty_target_detection = str(sys.argv[5]).strip() == "1"
dirty_target_grace_seconds = int(sys.argv[6])

LEGAL_PARSER_TARGETS = [
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/exports.py",
    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    "tests/unit_tests/logic/deontic/test_deontic_converter.py",
    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
]


def read_state() -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_status() -> dict:
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_progress() -> dict:
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_epoch(value) -> int:
    if not value:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return int(__import__("datetime").datetime.fromisoformat(candidate).timestamp())
        except ValueError:
            continue
    return 0


def paths_from_status(stdout: str) -> list[str]:
    paths: list[str] = []
    for line in stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def fingerprint(status_stdout: str, paths: list[str]) -> str:
    if not paths:
        return ""
    digest = hashlib.sha256()
    digest.update(status_stdout.encode("utf-8", errors="replace"))
    diff = subprocess.run(
        ["git", "diff", "--binary", "--", *paths],
        cwd=repo_root,
        text=False,
        capture_output=True,
        timeout=60,
    )
    digest.update(diff.stdout or b"")
    for text in sorted(paths):
        path = repo_root / text
        digest.update(text.encode("utf-8", errors="replace"))
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"__missing__")
    return digest.hexdigest()


def restore_failed_dirty_targets(progress: dict, paths: list[str]) -> bool:
    if not paths:
        return False
    recent_rejections = progress.get("recent_rejections")
    if not isinstance(recent_rejections, list):
        return False
    path_set = set(paths)
    for item in reversed(recent_rejections):
        if not isinstance(item, dict):
            continue
        text_parts = [
            str(item.get("reason") or ""),
            str(item.get("patch_stderr_tail") or ""),
            json.dumps(item.get("proposal_quality_reasons") or [], sort_keys=True),
        ]
        text = "\n".join(text_parts)
        if "automatic restore failed" not in text:
            continue
        if any(candidate in text for candidate in path_set):
            return True
    return False


if not dirty_target_detection:
    raise SystemExit(1)
result = subprocess.run(
    ["git", "status", "--porcelain", "--", *LEGAL_PARSER_TARGETS],
    cwd=repo_root,
    text=True,
    capture_output=True,
    timeout=30,
)
if result.returncode != 0:
    raise SystemExit(1)
paths = paths_from_status(result.stdout)
fp = fingerprint(result.stdout, paths)
state = read_state()
status = read_status()
progress = read_progress()
previous = [str(path) for path in state.get("dirty_legal_parser_targets") or []]
previous_fp = str(state.get("dirty_legal_parser_targets_fingerprint") or "")
current_phase = str(status.get("phase") or "")
phase_started_at = parse_epoch(status.get("phase_started_at"))
updated_at = parse_epoch(status.get("updated_at") or status.get("heartbeat_at"))
now = int(time.time())
try:
    phase_stale_after = int(status.get("phase_stale_after_seconds") or 0)
except (TypeError, ValueError):
    phase_stale_after = 0
phase_age = max(0, now - phase_started_at) if phase_started_at else 0
status_age = max(0, now - updated_at) if updated_at else 0
phase_stale = bool(phase_stale_after > 0 and phase_age >= phase_stale_after)
known_bad_restore_failure = restore_failed_dirty_targets(progress, paths)
transient_phases = {
    "requesting_llm_patch",
    "retrying_llm_patch",
    "repairing_failed_patch",
    "checking_patch",
    "applying_patch",
    "post_apply_validation",
    "running_tests",
    "evaluating_retained_change",
    "rolling_back_metric_stall_no_progress",
}
transient_dirty = bool(
    paths
    and not known_bad_restore_failure
    and not phase_stale
    and status_age < dirty_target_grace_seconds
    and (current_phase in transient_phases or bool(current_phase))
)
if paths and sorted(paths) == sorted(previous) and fp == previous_fp and not transient_dirty:
    print("dirty_legal_parser_targets:" + ",".join(paths[:8]))
    raise SystemExit(0)
state.update(
    {
        "dirty_legal_parser_targets": paths,
        "dirty_legal_parser_targets_fingerprint": fp,
        "dirty_legal_parser_targets_pending_confirmation": bool(paths),
        "dirty_legal_parser_targets_transient_phase": current_phase if transient_dirty else "",
        "dirty_legal_parser_targets_known_bad_restore_failure": known_bad_restore_failure,
    }
)
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
raise SystemExit(1)
PY
}

confirmed_repeated_rejection_dirty_target_reason() {
  if [[ "$SUPERVISOR_REPEATED_REJECTION_RECOVERY" != "1" ]]; then
    return 1
  fi
  python3 - \
    "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" \
    "$REPO_ROOT/$PROGRESS_PATH" \
    "$REPO_ROOT/$CURRENT_STATUS_PATH" \
    "$REPO_ROOT" \
    "$SUPERVISOR_AGENTIC_REPEATED_REJECTION_FAMILY_TAIL" \
    "$SUPERVISOR_DIRTY_TARGET_GRACE_SECONDS" <<'PY'
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1])
progress_path = Path(sys.argv[2])
status_path = Path(sys.argv[3])
repo_root = Path(sys.argv[4])
threshold = int(sys.argv[5])
grace_seconds = int(sys.argv[6])

LEGAL_PARSER_TARGETS = {
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/exports.py",
    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    "tests/unit_tests/logic/deontic/test_deontic_converter.py",
    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
}


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_epoch(value) -> int:
    if not value:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return int(__import__("datetime").datetime.fromisoformat(candidate).timestamp())
        except ValueError:
            continue
    return 0


def family_key(item: dict) -> str:
    reason = str(item.get("reason") or "")
    if ":" in reason:
        reason = reason.split(":", 1)[0]
    changed = sorted(
        str(path).strip()
        for path in (item.get("changed_files") or [])
        if str(path).strip() in LEGAL_PARSER_TARGETS
    )
    return json.dumps({"reason": reason, "changed_files": changed}, sort_keys=True)


def infer_legal_parser_targets(item: dict) -> list[str]:
    text_parts = [
        str(item.get("reason") or ""),
        str(item.get("patch_stderr_tail") or ""),
        json.dumps(item.get("proposal_quality_reasons") or [], sort_keys=True),
    ]
    text = "\n".join(text_parts)
    inferred: list[str] = []
    for candidate in sorted(LEGAL_PARSER_TARGETS):
        if candidate in text and candidate not in inferred:
            inferred.append(candidate)
    if inferred:
        return inferred
    changed = sorted(
        str(path).strip()
        for path in (item.get("changed_files") or [])
        if str(path).strip() in LEGAL_PARSER_TARGETS
    )
    return changed


def paths_from_porcelain(stdout: str) -> list[str]:
    paths: list[str] = []
    for line in stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def fingerprint(paths: list[str], status_stdout: str) -> str:
    if not paths:
        return ""
    digest = hashlib.sha256()
    digest.update(status_stdout.encode("utf-8", errors="replace"))
    diff = subprocess.run(
        ["git", "diff", "--binary", "--", *paths],
        cwd=repo_root,
        text=False,
        capture_output=True,
        timeout=60,
    )
    digest.update(diff.stdout or b"")
    for text in sorted(paths):
        digest.update(text.encode("utf-8", errors="replace"))
        path = repo_root / text
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"__missing__")
    return digest.hexdigest()


progress = read_json(progress_path)
status = read_json(status_path)
state = read_json(state_path)
rejections = progress.get("recent_rejections")
if not isinstance(rejections, list) or not rejections:
    raise SystemExit(1)
counts: dict[str, int] = {}
payloads: dict[str, dict] = {}
for item in rejections:
    if not isinstance(item, dict):
        continue
    key = family_key(item)
    if not key:
        continue
    counts[key] = counts.get(key, 0) + 1
    payloads[key] = item
if not counts:
    raise SystemExit(1)
winner = max(counts.items(), key=lambda pair: pair[1])[0]
count = counts[winner]
if count < threshold:
    raise SystemExit(1)
family = dict(payloads[winner])
changed_files = infer_legal_parser_targets(family)
if not changed_files:
    raise SystemExit(1)

updated_at = parse_epoch(status.get("updated_at") or status.get("heartbeat_at"))
now = int(time.time())
status_age = max(0, now - updated_at) if updated_at else 0
if status_age < grace_seconds:
    raise SystemExit(1)

git_status = subprocess.run(
    ["git", "status", "--porcelain", "--", *changed_files],
    cwd=repo_root,
    text=True,
    capture_output=True,
    timeout=30,
)
if git_status.returncode != 0:
    raise SystemExit(1)
dirty_paths = paths_from_porcelain(git_status.stdout)
if not dirty_paths:
    raise SystemExit(1)
fp = fingerprint(dirty_paths, git_status.stdout)
previous_paths = [str(path) for path in state.get("repeated_rejection_dirty_targets") or []]
previous_fp = str(state.get("repeated_rejection_dirty_targets_fingerprint") or "")
state.update(
    {
        "repeated_rejection_dirty_targets": dirty_paths,
        "repeated_rejection_dirty_targets_fingerprint": fp,
        "repeated_rejection_family_reason": str(family.get("reason") or ""),
        "repeated_rejection_family_count": count,
    }
)
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if dirty_paths == previous_paths and fp == previous_fp:
    print(
        "repeated_rejection_dirty_targets:"
        + str(family.get("reason") or "unknown")
        + ":"
        + ",".join(dirty_paths[:8])
    )
    raise SystemExit(0)
raise SystemExit(1)
PY
}

recover_repeated_rejection_dirty_targets() {
  local reason="$1"
  local recovery_id=""
  local recovery_log=""
  local targets_file=""
  local py_files_file=""
  local test_files_file=""
  local rc=0
  recovery_id="$(date -u +%Y%m%dT%H%M%SZ)"
  recovery_log="$DAEMON_DIR/legal_parser_daemon_repeated_rejection_recovery_${recovery_id}.log"
  last_agentic_maintenance_status="repeated_rejection_recovery_running"
  last_agentic_maintenance_reason="$reason"
  last_agentic_maintenance_log_path="$recovery_log"
  write_supervisor_status "repeated_rejection_recovery_started" "$recovery_id" "$recovery_log" null
  stop_child
  targets_file="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-repeated-targets.XXXXXX")"
  py_files_file="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-repeated-py.XXXXXX")"
  test_files_file="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-repeated-tests.XXXXXX")"
  python3 - "$REPO_ROOT" "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" "$targets_file" "$py_files_file" "$test_files_file" <<'PY'
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
state_path = Path(sys.argv[2])
targets_path = Path(sys.argv[3])
py_path = Path(sys.argv[4])
tests_path = Path(sys.argv[5])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    state = {}
paths = [
    str(path).strip()
    for path in (state.get("repeated_rejection_dirty_targets") or [])
    if str(path).strip()
]
targets_path.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
py_files = [path for path in paths if path.endswith(".py") and (repo_root / path).exists()]
test_files = [path for path in paths if path.startswith("tests/unit_tests/logic/deontic/") and path.endswith(".py")]
py_path.write_text("\n".join(py_files) + ("\n" if py_files else ""), encoding="utf-8")
tests_path.write_text("\n".join(test_files) + ("\n" if test_files else ""), encoding="utf-8")
PY
  if [[ ! -s "$targets_file" ]]; then
    last_agentic_maintenance_status="repeated_rejection_recovery_skipped_clean"
    write_supervisor_status "repeated_rejection_recovery_finished" "$recovery_id" "$recovery_log" 0
    rm -f "$targets_file" "$py_files_file" "$test_files_file"
    return 0
  fi
  {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting repeated rejection recovery: $reason"
    echo "Repeated rejection dirty targets:"
    sed 's/^/- /' "$targets_file"
    if [[ -s "$py_files_file" ]]; then
      echo "Running py_compile for repeated rejection Python targets"
      xargs -r python3 -m py_compile < "$py_files_file"
    fi
    if [[ -s "$test_files_file" ]]; then
      echo "Running focused pytest for repeated rejection deontic tests"
      xargs -r pytest -q < "$test_files_file"
    fi
  } >> "$REPO_ROOT/$recovery_log" 2>&1
  rc=$?
  if [[ "$rc" == "0" ]]; then
    {
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) repeated rejection validation passed; committing recovered daemon slice"
      xargs -r git -C "$REPO_ROOT" add -- < "$targets_file"
      git -C "$REPO_ROOT" commit -m "legal-parser-daemon: recover repeated rejection target slice"
    } >> "$REPO_ROOT/$recovery_log" 2>&1
    rc=$?
    last_agentic_maintenance_status="repeated_rejection_recovery_committed"
    clear_recovery_failure_state
  else
    {
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) repeated rejection validation failed with rc=$rc; restoring only repeated rejection targets"
      restore_legal_parser_targets_from_baseline_or_head "$targets_file"
    } >> "$REPO_ROOT/$recovery_log" 2>&1
    record_recovery_failure "repeated_rejection_recovery" "$reason" "$recovery_log" "$targets_file"
    last_agentic_maintenance_status="repeated_rejection_recovery_restored"
    rc=0
  fi
  mark_agentic_maintenance_ran "$reason"
  write_supervisor_status "repeated_rejection_recovery_finished" "$recovery_id" "$recovery_log" "$rc"
  rm -f "$targets_file" "$py_files_file" "$test_files_file"
  return "$rc"
}
recover_dirty_legal_parser_targets() {
  local reason="$1"
  local recovery_id=""
  local recovery_log=""
  local targets_file=""
  local py_files_file=""
  local test_files_file=""
  local rc=0
  recovery_id="$(date -u +%Y%m%dT%H%M%SZ)"
  recovery_log="$DAEMON_DIR/legal_parser_daemon_dirty_recovery_${recovery_id}.log"
  last_agentic_maintenance_status="dirty_recovery_running"
  last_agentic_maintenance_reason="$reason"
  last_agentic_maintenance_log_path="$recovery_log"
  write_supervisor_status "dirty_target_recovery_started" "$recovery_id" "$recovery_log" null
  stop_child
  targets_file="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-dirty-targets.XXXXXX")"
  py_files_file="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-dirty-py.XXXXXX")"
  test_files_file="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-dirty-tests.XXXXXX")"
  python3 - "$REPO_ROOT" "$targets_file" "$py_files_file" "$test_files_file" <<'PY'
import subprocess
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
targets_path = Path(sys.argv[2])
py_path = Path(sys.argv[3])
tests_path = Path(sys.argv[4])
targets = [
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/exports.py",
    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    "tests/unit_tests/logic/deontic/test_deontic_converter.py",
    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
]
result = subprocess.run(
    ["git", "status", "--porcelain", "--", *targets],
    cwd=repo_root,
    text=True,
    capture_output=True,
    timeout=30,
)
if result.returncode != 0:
    raise SystemExit(result.returncode)
paths = []
for line in result.stdout.splitlines():
    path = line[3:].strip()
    if " -> " in path:
        path = path.rsplit(" -> ", 1)[1].strip()
    if path and path not in paths:
        paths.append(path)
targets_path.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
py_files = [path for path in paths if path.endswith(".py") and (repo_root / path).exists()]
test_files = [path for path in paths if path.startswith("tests/unit_tests/logic/deontic/") and path.endswith(".py")]
py_path.write_text("\n".join(py_files) + ("\n" if py_files else ""), encoding="utf-8")
tests_path.write_text("\n".join(test_files) + ("\n" if test_files else ""), encoding="utf-8")
PY
  if [[ ! -s "$targets_file" ]]; then
    last_agentic_maintenance_status="dirty_recovery_skipped_clean"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) dirty target recovery skipped because targets are clean: $reason" >> "$REPO_ROOT/$recovery_log"
    write_supervisor_status "dirty_target_recovery_finished" "$recovery_id" "$recovery_log" 0
    rm -f "$targets_file" "$py_files_file" "$test_files_file"
    return 0
  fi
  {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting dirty legal-parser target recovery: $reason"
    echo "Dirty targets:"
    sed 's/^/- /' "$targets_file"
    if [[ -s "$py_files_file" ]]; then
      echo "Running py_compile for dirty Python targets"
      xargs -r python3 -m py_compile < "$py_files_file"
    fi
    if [[ -s "$test_files_file" ]]; then
      echo "Running focused pytest for dirty deontic tests"
      xargs -r pytest -q < "$test_files_file"
    fi
  } >> "$REPO_ROOT/$recovery_log" 2>&1
  rc=$?
  if [[ "$rc" == "0" ]]; then
    {
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) dirty target validation passed; committing recovered daemon slice"
      xargs -r git -C "$REPO_ROOT" add -- < "$targets_file"
      git -C "$REPO_ROOT" commit -m "legal-parser-daemon: recover stranded parser target slice"
    } >> "$REPO_ROOT/$recovery_log" 2>&1
    rc=$?
    last_agentic_maintenance_status="dirty_recovery_committed"
    clear_recovery_failure_state
  else
    {
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) dirty target validation failed with rc=$rc; restoring only dirty legal-parser targets"
      restore_legal_parser_targets_from_baseline_or_head "$targets_file"
    } >> "$REPO_ROOT/$recovery_log" 2>&1
    record_recovery_failure "dirty_target_recovery" "$reason" "$recovery_log" "$targets_file"
    last_agentic_maintenance_status="dirty_recovery_restored"
    rc=0
  fi
  mark_agentic_maintenance_ran "$reason"
  write_supervisor_status "dirty_target_recovery_finished" "$recovery_id" "$recovery_log" "$rc"
  rm -f "$targets_file" "$py_files_file" "$test_files_file"
  return "$rc"
}

run_agentic_maintenance() {
  local reason="$1"
  local refreshed_reason=""
  local maintenance_id=""
  local maintenance_log=""
  local rc=0
  local before_head=""
  local after_head=""
  local before_diff=""
  local after_diff=""
  maintenance_id="$(date -u +%Y%m%dT%H%M%SZ)"
  maintenance_log="$DAEMON_DIR/legal_parser_daemon_agentic_maintenance_${maintenance_id}.log"
  last_agentic_maintenance_status="running"
  last_agentic_maintenance_reason="$reason"
  last_agentic_maintenance_log_path="$maintenance_log"
  write_supervisor_status "agentic_maintenance_started" "$maintenance_id" "$maintenance_log" null
  stop_child
  refreshed_reason="$(agentic_maintenance_reason || true)"
  if [[ -z "$refreshed_reason" ]]; then
    last_agentic_maintenance_status="skipped_stale_trigger"
    last_agentic_maintenance_reason="$reason"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skipping agentic maintenance because trigger cleared after child stop: $reason" >> "$REPO_ROOT/$maintenance_log"
    write_supervisor_status "agentic_maintenance_finished" "$maintenance_id" "$maintenance_log" 0
    return 0
  fi
  if [[ "$refreshed_reason" != "$reason" ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) agentic maintenance reason refreshed after child stop: $reason -> $refreshed_reason" >> "$REPO_ROOT/$maintenance_log"
    reason="$refreshed_reason"
    last_agentic_maintenance_reason="$reason"
    write_supervisor_status "agentic_maintenance_started" "$maintenance_id" "$maintenance_log" null
  fi
  mark_agentic_maintenance_ran "$reason"
  before_head="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
  before_diff="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-agentic-before.XXXXXX")"
  after_diff="$(mktemp "$REPO_ROOT/$DAEMON_DIR/legal-parser-agentic-after.XXXXXX")"
  git -C "$REPO_ROOT" diff --name-only -- \
    ipfs_datasets_py/optimizers/logic/deontic/parser_daemon.py \
    tests/unit_tests/logic/deontic/test_legal_parser_optimizer_daemon.py \
    scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh \
    scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh \
    ipfs_datasets_py/logic/deontic/utils/deontic_parser.py \
    ipfs_datasets_py/logic/deontic/ir.py \
    ipfs_datasets_py/logic/deontic/formula_builder.py \
    ipfs_datasets_py/logic/deontic/converter.py \
    ipfs_datasets_py/logic/deontic/exports.py \
    tests/unit_tests/logic/deontic/test_deontic_formula_builder.py \
    tests/unit_tests/logic/deontic/test_deontic_converter.py \
    tests/unit_tests/logic/deontic/test_deontic_exports.py \
    docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md \
    docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md \
    > "$before_diff" 2>/dev/null || true
  {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting legal-parser daemon-maintenance pass: $reason"
    timeout "$SUPERVISOR_AGENTIC_TIMEOUT_SECONDS" "$CODEX_BIN" exec \
      --skip-git-repo-check \
      --sandbox "$SUPERVISOR_AGENTIC_SANDBOX" \
      -m "$MODEL_NAME" \
      -C "$REPO_ROOT" \
      - <<PROMPT
You are maintaining the deterministic legal-parser optimizer daemon and its supervisor.

The supervisor detected that the daemon may be stuck or not making meaningful progress.

Reason: $reason

Improve only daemon/supervisor programming, tests, or docs in this maintenance pass. Do not implement a new legal parser feature here unless it is strictly required to repair daemon progress logic.

If the reason mentions dirty_legal_parser_targets, dirty_touched_file_rejections, or repeated_rejection_family,
first inspect the stranded legal-parser diff. If it is a coherent parser slice,
run the focused tests and commit it with a legal-parser-daemon recovery message.
If it is incoherent, safely restore only those stranded legal-parser target files
to the current HEAD so future daemon proposals are not rejected as touching
pre-existing uncommitted changes. Do not touch unrelated dirty files.

If the reason mentions repeated_recovery_failure, inspect the cited recovery
log and failure signature first. Prefer fixing the daemon/supervisor recovery
logic, proposal gating, or validator targeting so this exact failure loop does
not recur on the next unattended cycle.

Allowed files:
- ipfs_datasets_py/optimizers/logic/deontic/parser_daemon.py
- tests/unit_tests/logic/deontic/test_legal_parser_optimizer_daemon.py
- scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh
- scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh
- ipfs_datasets_py/logic/deontic/utils/deontic_parser.py
- ipfs_datasets_py/logic/deontic/ir.py
- ipfs_datasets_py/logic/deontic/formula_builder.py
- ipfs_datasets_py/logic/deontic/converter.py
- ipfs_datasets_py/logic/deontic/exports.py
- tests/unit_tests/logic/deontic/test_deontic_formula_builder.py
- tests/unit_tests/logic/deontic/test_deontic_converter.py
- tests/unit_tests/logic/deontic/test_deontic_exports.py
- docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md
- docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md

Focus on unattended operation making real progress: better stuck/no-progress detection, better recovery prompts, safer restart behavior, clearer status/progress accounting, stronger validation before retaining patches, or documentation of those behaviors.

After editing, run:
- bash -n scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh
- python3 -m py_compile ipfs_datasets_py/optimizers/logic/deontic/parser_daemon.py
- pytest -q tests/unit_tests/logic/deontic/test_legal_parser_optimizer_daemon.py

Keep the daemon pointed at the deterministic legal parser plans and preserve the no-LLM parser contract for proof-ready clauses.
PROMPT
  } >> "$REPO_ROOT/$maintenance_log" 2>&1
  rc=$?
  after_head="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
  git -C "$REPO_ROOT" diff --name-only -- \
    ipfs_datasets_py/optimizers/logic/deontic/parser_daemon.py \
    tests/unit_tests/logic/deontic/test_legal_parser_optimizer_daemon.py \
    scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh \
    scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh \
    ipfs_datasets_py/logic/deontic/utils/deontic_parser.py \
    ipfs_datasets_py/logic/deontic/ir.py \
    ipfs_datasets_py/logic/deontic/formula_builder.py \
    ipfs_datasets_py/logic/deontic/converter.py \
    ipfs_datasets_py/logic/deontic/exports.py \
    tests/unit_tests/logic/deontic/test_deontic_formula_builder.py \
    tests/unit_tests/logic/deontic/test_deontic_converter.py \
    tests/unit_tests/logic/deontic/test_deontic_exports.py \
    docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md \
    docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md \
    > "$after_diff" 2>/dev/null || true
  if [[ "$rc" == "0" ]] \
    && bash -n "$REPO_ROOT/scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && bash -n "$REPO_ROOT/scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && python3 -m py_compile "$REPO_ROOT/ipfs_datasets_py/optimizers/logic/deontic/parser_daemon.py" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && pytest -q "$REPO_ROOT/tests/unit_tests/logic/deontic/test_legal_parser_optimizer_daemon.py" >> "$REPO_ROOT/$maintenance_log" 2>&1; then
    if [[ "$after_head" != "$before_head" ]] || ! cmp -s "$before_diff" "$after_diff"; then
      last_agentic_maintenance_status="accepted"
    else
      last_agentic_maintenance_status="no_change"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) agentic maintenance completed without file changes" >> "$REPO_ROOT/$maintenance_log"
    fi
  else
    last_agentic_maintenance_status="failed"
  fi
  rm -f "$before_diff" "$after_diff"
  write_supervisor_status "agentic_maintenance_finished" "$maintenance_id" "$maintenance_log" "$rc"
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

terminate_matching_legal_parser_daemons() {
  local pid=""
  local args=""
  while read -r pid args; do
    if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]] || [[ "$pid" == "${child_pid:-}" ]]; then
      continue
    fi
    if [[ "$args" == *"python"* && "$args" == *"-m ipfs_datasets_py.optimizers.logic.deontic.parser_daemon"* ]]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cleaning up orphaned legal-parser daemon $pid before supervisor start/restart" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
      terminate_pid_tree "$pid"
    fi
  done < <(ps -eo pid=,args=)
}

terminate_competing_daemons() {
  local pid=""
  local args=""
  if [[ "$SUPERVISOR_STOP_COMPETING_DAEMONS" != "1" ]]; then
    return 0
  fi
  if [[ "$SUPERVISOR_STOP_LOGIC_PORT_DAEMON" == "1" ]] && command -v tmux >/dev/null 2>&1; then
    while IFS=: read -r session _rest; do
      if [[ "$session" == "logic-port-daemon" ]]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) stopping competing tmux session $session" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
        tmux kill-session -t "$session" 2>/dev/null || true
      fi
    done < <(tmux ls 2>/dev/null || true)
  fi
  if [[ "$SUPERVISOR_STOP_LOGIC_PORT_DAEMON" == "1" ]] && command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-active --quiet logic-port-daemon.service 2>/dev/null; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) stopping competing user service logic-port-daemon.service" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
      if [[ "$SUPERVISOR_DISABLE_COMPETING_SYSTEMD_SERVICE" == "1" ]]; then
        systemctl --user disable --now logic-port-daemon.service 2>/dev/null || true
      else
        systemctl --user stop logic-port-daemon.service 2>/dev/null || true
      fi
      systemctl --user kill --signal=TERM logic-port-daemon.service 2>/dev/null || true
      systemctl --user reset-failed logic-port-daemon.service 2>/dev/null || true
    elif [[ "$SUPERVISOR_DISABLE_COMPETING_SYSTEMD_SERVICE" == "1" ]] && systemctl --user is-enabled --quiet logic-port-daemon.service 2>/dev/null; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) disabling competing user service logic-port-daemon.service" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
      systemctl --user disable logic-port-daemon.service 2>/dev/null || true
    fi
  fi
  while read -r pid args; do
    if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]] || [[ "$pid" == "${child_pid:-}" ]]; then
      continue
    fi
    case "$args" in
      *"ppd/daemon/ppd_daemon.py"*)
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) stopping competing automation $pid: $args" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
        terminate_pid_tree "$pid"
        ;;
      *"ipfs_datasets_py.optimizers.logic_port_daemon"*|*"run_logic_port_daemon.sh"*|*"ensure_logic_port_daemon.sh"*)
        if [[ "$SUPERVISOR_STOP_LOGIC_PORT_DAEMON" == "1" ]]; then
          echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) stopping competing automation $pid: $args" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
          terminate_pid_tree "$pid"
        fi
        ;;
    esac
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

terminate_matching_legal_parser_daemons
terminate_competing_daemons
snapshot_dirty_legal_parser_target_baseline

while true; do
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  log_path="$DAEMON_DIR/legal_parser_daemon_supervised_${run_id}.log"
  ln -sfn "$(basename "$log_path")" "$REPO_ROOT/$LATEST_LOG_PATH"
  write_supervisor_status "starting" "$run_id" "$log_path" null

  (
    cd "$REPO_ROOT" || exit 2
    python3_args=(
      python3 -u -m ipfs_datasets_py.optimizers.logic.deontic.parser_daemon
      --repo-root .
      --output-dir "$OUTPUT_DIR"
      --max-cycles 0
      --cycle-interval-seconds 0
      --error-backoff-seconds "$RESTART_BACKOFF_SECONDS"
      --llm-timeout-seconds "$LLM_TIMEOUT_SECONDS"
      --llm-proposal-attempts "$LLM_PROPOSAL_ATTEMPTS"
      --heartbeat-interval-seconds "$HEARTBEAT_INTERVAL_SECONDS"
      --test-timeout-seconds "$TEST_TIMEOUT_SECONDS"
      --apply-patches
      --commit-accepted-patches
    )
    [[ -n "$PROVIDER" ]] && python3_args+=(--provider "$PROVIDER")
    python3_args+=(--model-name "$MODEL_NAME")
    PYTHONUNBUFFERED=1 \
      IPFS_DATASETS_PY_LLM_PROVIDER="$IPFS_DATASETS_PY_LLM_PROVIDER" \
      IPFS_DATASETS_PY_CODEX_CLI_MODEL="$MODEL_NAME" \
      IPFS_DATASETS_PY_CODEX_SANDBOX="${IPFS_DATASETS_PY_CODEX_SANDBOX:-read-only}" \
      "${python3_args[@]}"
  ) >> "$REPO_ROOT/$log_path" 2>&1 &
  child_pid=$!
  child_started_at=$SECONDS
  printf '%s\n' "$child_pid" > "$REPO_ROOT/$CHILD_PID_PATH"

  while kill -0 "$child_pid" 2>/dev/null; do
    terminate_competing_daemons
    write_supervisor_status "running" "$run_id" "$log_path" null
    if [[ $((SECONDS - child_started_at)) -ge "$WATCHDOG_STARTUP_GRACE_SECONDS" ]] && heartbeat_is_stale; then
      last_recycle_reason="stale_heartbeat"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog recycling child $child_pid after stale daemon heartbeat older than ${WATCHDOG_STALE_AFTER_SECONDS}s" >> "$REPO_ROOT/$log_path"
      stop_child
      break
    fi
    repeated_rejection_recovery_reason="$(confirmed_repeated_rejection_dirty_target_reason || true)"
    if [[ -n "$repeated_rejection_recovery_reason" ]]; then
      last_recycle_reason="repeated_rejection_recovery"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor recovering repeated rejection dirty targets: $repeated_rejection_recovery_reason" >> "$REPO_ROOT/$log_path"
      recover_repeated_rejection_dirty_targets "$repeated_rejection_recovery_reason"
      break
    fi
    recovery_failure_escalation_reason="$(confirmed_recovery_failure_escalation_reason || true)"
    if [[ -n "$recovery_failure_escalation_reason" ]]; then
      last_recycle_reason="repeated_recovery_failure"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor escalating repeated recovery failure: $recovery_failure_escalation_reason" >> "$REPO_ROOT/$log_path"
      run_agentic_maintenance "$recovery_failure_escalation_reason"
      break
    fi
    dirty_recovery_reason="$(confirmed_dirty_target_reason || true)"
    if [[ -n "$dirty_recovery_reason" ]]; then
      last_recycle_reason="dirty_target_recovery"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor recovering dirty legal-parser targets: $dirty_recovery_reason" >> "$REPO_ROOT/$log_path"
      recover_dirty_legal_parser_targets "$dirty_recovery_reason"
      break
    fi
    maintenance_reason="$(agentic_maintenance_reason || true)"
    if [[ -n "$maintenance_reason" ]]; then
      last_recycle_reason="agentic_maintenance"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor invoking agentic maintenance: $maintenance_reason" >> "$REPO_ROOT/$log_path"
      run_agentic_maintenance "$maintenance_reason"
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
  write_supervisor_status "restarting" "$run_id" "$log_path" "$rc"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) daemon exited with code $rc; restarting in ${RESTART_BACKOFF_SECONDS}s" >> "$REPO_ROOT/$log_path"
  sleep "$RESTART_BACKOFF_SECONDS"
  terminate_matching_legal_parser_daemons
done
