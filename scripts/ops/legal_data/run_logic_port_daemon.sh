#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
MODEL_NAME="${MODEL_NAME:-gpt-5.5}"
PROVIDER="${PROVIDER:-codex_cli}"
# The supervised overnight daemon still calls ipfs_datasets_py.llm_router, but
# pins the router provider to codex_cli by default so auto-routing does not fall
# into local/P2P providers that cannot reliably complete autonomous code edits.
# Set PROVIDER=auto-empty only for debugging the router's provider selection.
if [[ "$PROVIDER" == "auto-empty" ]]; then
  PROVIDER=""
fi
SLICE_MODE="${SLICE_MODE:-balanced}"
LOGIC_PORT_FORCE_ALLOW_DURING_LEGAL_PARSER="${LOGIC_PORT_FORCE_ALLOW_DURING_LEGAL_PARSER:-0}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
RESTART_DELAY_SECONDS="${RESTART_DELAY_SECONDS:-0}"
LLM_TIMEOUT_SECONDS="${LLM_TIMEOUT_SECONDS:-300}"
COMMAND_TIMEOUT_SECONDS="${COMMAND_TIMEOUT_SECONDS:-300}"
MAX_PROMPT_CHARS="${MAX_PROMPT_CHARS:-32000}"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-30}"
SUPERVISOR_HEARTBEAT_SECONDS="${SUPERVISOR_HEARTBEAT_SECONDS:-30}"
WATCHDOG_STALE_AFTER_SECONDS="${WATCHDOG_STALE_AFTER_SECONDS:-420}"
WATCHDOG_STARTUP_GRACE_SECONDS="${WATCHDOG_STARTUP_GRACE_SECONDS:-120}"
STOP_GRACE_SECONDS="${STOP_GRACE_SECONDS:-10}"
MAX_TASK_FAILURES="${MAX_TASK_FAILURES:-20}"
PROPOSAL_ATTEMPTS="${PROPOSAL_ATTEMPTS:-3}"
FILE_REPAIR_ATTEMPTS="${FILE_REPAIR_ATTEMPTS:-1}"
VALIDATION_REPAIR_ATTEMPTS="${VALIDATION_REPAIR_ATTEMPTS:-1}"
VALIDATION_REPAIR_FAILURE_BUDGET="${VALIDATION_REPAIR_FAILURE_BUDGET:-2}"
BLOCKED_BACKLOG_LIMIT="${BLOCKED_BACKLOG_LIMIT:-10}"
BLOCKED_TASK_STRATEGY="${BLOCKED_TASK_STRATEGY:-fewest-failures}"
PLAN_REPLENISHMENT_LIMIT="${PLAN_REPLENISHMENT_LIMIT:-12}"
SUPERVISOR_AGENTIC_MAINTENANCE="${SUPERVISOR_AGENTIC_MAINTENANCE:-1}"
SUPERVISOR_AGENTIC_STARTUP_MAINTENANCE="${SUPERVISOR_AGENTIC_STARTUP_MAINTENANCE:-0}"
SUPERVISOR_AGENTIC_STAGNANT_ROUNDS="${SUPERVISOR_AGENTIC_STAGNANT_ROUNDS:-12}"
SUPERVISOR_AGENTIC_TASK_FAILURES="${SUPERVISOR_AGENTIC_TASK_FAILURES:-6}"
SUPERVISOR_AGENTIC_PROPOSAL_FAILURES="${SUPERVISOR_AGENTIC_PROPOSAL_FAILURES:-3}"
SUPERVISOR_AGENTIC_ROLLBACK_FAILURES="${SUPERVISOR_AGENTIC_ROLLBACK_FAILURES:-5}"
SUPERVISOR_AGENTIC_TYPESCRIPT_QUALITY_FAILURES="${SUPERVISOR_AGENTIC_TYPESCRIPT_QUALITY_FAILURES:-3}"
SUPERVISOR_AGENTIC_COOLDOWN_SECONDS="${SUPERVISOR_AGENTIC_COOLDOWN_SECONDS:-3600}"
SUPERVISOR_AGENTIC_TIMEOUT_SECONDS="${SUPERVISOR_AGENTIC_TIMEOUT_SECONDS:-900}"
SUPERVISOR_AGENTIC_SANDBOX="${SUPERVISOR_AGENTIC_SANDBOX:-danger-full-access}"
SUPERVISOR_AGENTIC_FALLBACK_SANDBOX="${SUPERVISOR_AGENTIC_FALLBACK_SANDBOX:-auto}"
CODEX_BIN="${CODEX_BIN:-codex}"
export IPFS_DATASETS_PY_CODEX_SANDBOX="${IPFS_DATASETS_PY_CODEX_SANDBOX:-danger-full-access}"

STATUS_PATH="${STATUS_PATH:-$DAEMON_DIR/logic-port-daemon.status.json}"
PROGRESS_PATH="${PROGRESS_PATH:-$DAEMON_DIR/logic-port-daemon.progress.json}"
RESULT_LOG_PATH="${RESULT_LOG_PATH:-$DAEMON_DIR/logic-port-daemon.jsonl}"
SUPERVISOR_STATUS_PATH="${SUPERVISOR_STATUS_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.status.json}"
SUPERVISOR_AGENTIC_STATE_PATH="${SUPERVISOR_AGENTIC_STATE_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor-agentic.state.json}"
SUPERVISOR_PID_PATH="${SUPERVISOR_PID_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.pid}"
SUPERVISOR_LOCK_PATH="${SUPERVISOR_LOCK_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.lock}"
CHILD_PID_PATH="${CHILD_PID_PATH:-$DAEMON_DIR/logic-port-daemon.pid}"
LATEST_LOG_PATH="${LATEST_LOG_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.latest.log}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"

LEGAL_PARSER_SUPERVISOR_PID_PATH="${LEGAL_PARSER_SUPERVISOR_PID_PATH:-$REPO_ROOT/ipfs_datasets_py/.daemon/legal_parser_daemon_supervisor.pid}"
if [[ "$LOGIC_PORT_FORCE_ALLOW_DURING_LEGAL_PARSER" != "1" ]] && [[ -f "$LEGAL_PARSER_SUPERVISOR_PID_PATH" ]]; then
  legal_parser_pid="$(tr -dc '0-9' < "$LEGAL_PARSER_SUPERVISOR_PID_PATH" 2>/dev/null || true)"
  if [[ -n "$legal_parser_pid" ]] && kill -0 "$legal_parser_pid" 2>/dev/null; then
    echo "logic-port daemon suppressed because legal-parser daemon supervisor is running with PID $legal_parser_pid"
    exit 0
  fi
fi

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
last_agentic_maintenance_status=""
last_agentic_maintenance_reason=""
last_agentic_maintenance_log_path=""
last_orphaned_llm_cleanup_count=0

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
  "agentic_maintenance_enabled": $SUPERVISOR_AGENTIC_MAINTENANCE,
  "agentic_startup_maintenance_enabled": $SUPERVISOR_AGENTIC_STARTUP_MAINTENANCE,
  "agentic_stagnant_rounds": $SUPERVISOR_AGENTIC_STAGNANT_ROUNDS,
  "agentic_task_failures": $SUPERVISOR_AGENTIC_TASK_FAILURES,
  "agentic_proposal_failures": $SUPERVISOR_AGENTIC_PROPOSAL_FAILURES,
  "agentic_rollback_failures": $SUPERVISOR_AGENTIC_ROLLBACK_FAILURES,
  "agentic_typescript_quality_failures": $SUPERVISOR_AGENTIC_TYPESCRIPT_QUALITY_FAILURES,
  "agentic_cooldown_seconds": $SUPERVISOR_AGENTIC_COOLDOWN_SECONDS,
  "agentic_timeout_seconds": $SUPERVISOR_AGENTIC_TIMEOUT_SECONDS,
  "agentic_sandbox": "$SUPERVISOR_AGENTIC_SANDBOX",
  "agentic_fallback_sandbox": "$SUPERVISOR_AGENTIC_FALLBACK_SANDBOX",
  "agentic_state_path": "$SUPERVISOR_AGENTIC_STATE_PATH",
  "last_agentic_maintenance_status": "$last_agentic_maintenance_status",
  "last_agentic_maintenance_reason": "$last_agentic_maintenance_reason",
  "last_agentic_maintenance_log_path": "$last_agentic_maintenance_log_path",
  "last_orphaned_llm_cleanup_count": $last_orphaned_llm_cleanup_count,
  "model_name": "$MODEL_NAME",
  "provider": "$PROVIDER",
  "slice_mode": "$SLICE_MODE",
  "force_allow_during_legal_parser": "$LOGIC_PORT_FORCE_ALLOW_DURING_LEGAL_PARSER",
  "llm_timeout_seconds": $LLM_TIMEOUT_SECONDS,
  "command_timeout_seconds": $COMMAND_TIMEOUT_SECONDS,
  "max_prompt_chars": $MAX_PROMPT_CHARS,
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

agentic_maintenance_reason() {
  if [[ "$SUPERVISOR_AGENTIC_MAINTENANCE" != "1" ]]; then
    return 1
  fi
  python3 - \
    "$REPO_ROOT/$PROGRESS_PATH" \
    "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" \
    "$REPO_ROOT/$RESULT_LOG_PATH" \
    "$SUPERVISOR_AGENTIC_STAGNANT_ROUNDS" \
    "$SUPERVISOR_AGENTIC_TASK_FAILURES" \
    "$SUPERVISOR_AGENTIC_PROPOSAL_FAILURES" \
    "$SUPERVISOR_AGENTIC_ROLLBACK_FAILURES" \
    "$SUPERVISOR_AGENTIC_TYPESCRIPT_QUALITY_FAILURES" \
    "$SUPERVISOR_AGENTIC_COOLDOWN_SECONDS" <<'PY'
import json
import time
import sys
from pathlib import Path

progress_path = Path(sys.argv[1])
state_path = Path(sys.argv[2])
result_log_path = Path(sys.argv[3])
stagnant_rounds = int(sys.argv[4])
task_failures = int(sys.argv[5])
proposal_failures_threshold = int(sys.argv[6])
rollback_failures_threshold = int(sys.argv[7])
typescript_quality_failures_threshold = int(sys.argv[8])
cooldown_seconds = int(sys.argv[9])
now = int(time.time())


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_result_rows(path: Path) -> list[tuple[dict, dict]]:
    rows: list[tuple[dict, dict]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        for result in record.get("results", []) or []:
            if not isinstance(result, dict):
                continue
            artifact = result.get("artifact") or {}
            if isinstance(artifact, dict):
                rows.append((result, artifact))
    return rows


def validation_text(artifact: dict) -> str:
    parts: list[str] = []
    for item in artifact.get("validation_results") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("stdout") or ""))
            parts.append(str(item.get("stderr") or ""))
    parts.extend(str(error) for error in artifact.get("errors") or [])
    return "\n".join(parts)


TYPESCRIPT_QUALITY_CODES = (
    "TS1003",
    "TS1005",
    "TS1011",
    "TS1068",
    "TS1109",
    "TS1128",
    "TS1138",
    "TS1144",
    "TS1434",
    "TS2314",
    "TS2322",
    "TS2339",
    "TS2345",
    "TS2365",
    "TS7006",
)


def is_typescript_quality_failure(result: dict, artifact: dict) -> bool:
    if result.get("valid") or artifact.get("changed_files"):
        return False
    text = validation_text(artifact)
    if any(code in text for code in TYPESCRIPT_QUALITY_CODES):
        return True
    return "TypeScript replacement preflight" in text or "TypeScript parser preflight" in text


def is_proposal_quality_failure(result: dict, artifact: dict) -> bool:
    if result.get("valid") or artifact.get("changed_files"):
        return False
    failure_kind = str(artifact.get("failure_kind") or "")
    return failure_kind in {"parse", "codex_empty_event_stream", "empty_proposal", "invalid_no_change", "no_change"}


def is_rollback_quality_failure(result: dict, artifact: dict) -> bool:
    if result.get("valid"):
        return False
    if artifact.get("changed_files"):
        return False
    failure_kind = str(artifact.get("failure_kind") or "")
    if failure_kind in {"apply_check", "validation", "validation_repair", "file_repair_validation", "validation_repair_preflight", "preflight", "typescript_quality"}:
        return True
    return is_typescript_quality_failure(result, artifact)


def recent_matching_failures(rows: list[tuple[dict, dict]], predicate) -> int:
    count = 0
    for result, artifact in reversed(rows):
        if result.get("valid"):
            break
        if predicate(result, artifact):
            count += 1
            continue
        break
    return count


progress = read_json(progress_path)
if not progress:
    raise SystemExit(1)

state = read_json(state_path)
rounds_total = int(progress.get("rounds_total") or 0)
valid_rounds_total = int(progress.get("valid_rounds_total") or 0)
current_task = str(progress.get("current_task") or "")
task_failure_total = int((progress.get("current_task_failure_counts") or {}).get("total_since_success") or 0)
current_task_kind_counts = (progress.get("current_task_failure_counts") or {}).get("by_kind_since_success") or {}
current_task_typescript_quality_failures = int(current_task_kind_counts.get("typescript_quality") or 0)
result_rows = read_result_rows(result_log_path)
proposal_quality_failures = recent_matching_failures(result_rows, is_proposal_quality_failure)
rollback_quality_failures = recent_matching_failures(result_rows, is_rollback_quality_failure)
typescript_quality_failures = recent_matching_failures(result_rows, is_typescript_quality_failure)
typescript_quality_progress = progress.get("typescript_quality_failures") or {}
top_typescript_signature = str(typescript_quality_progress.get("top_signature") or "")
top_typescript_signature_count = int(typescript_quality_progress.get("top_signature_count") or 0)
last_maintenance_at = int(state.get("last_maintenance_at") or 0)
baseline_round = int(state.get("baseline_rounds_total") or rounds_total)
baseline_valid = int(state.get("baseline_valid_rounds_total") or valid_rounds_total)

if valid_rounds_total > baseline_valid:
    baseline_round = rounds_total
    baseline_valid = valid_rounds_total

stagnant_delta = max(0, rounds_total - baseline_round)
candidate_reason = ""
if task_failure_total >= task_failures:
    candidate_reason = f"task_failures:{task_failure_total}:threshold:{task_failures}"
elif proposal_quality_failures >= proposal_failures_threshold:
    candidate_reason = f"proposal_quality_failures:{proposal_quality_failures}:threshold:{proposal_failures_threshold}"
elif (
    top_typescript_signature
    and current_task
    and top_typescript_signature.startswith(current_task + " :: ")
    and top_typescript_signature_count >= typescript_quality_failures_threshold
):
    candidate_reason = f"repeated_typescript_diagnostic:{top_typescript_signature_count}:threshold:{typescript_quality_failures_threshold}:{top_typescript_signature[:160]}"
elif current_task_typescript_quality_failures >= typescript_quality_failures_threshold:
    candidate_reason = f"typescript_quality_failures:{current_task_typescript_quality_failures}:threshold:{typescript_quality_failures_threshold}"
elif rollback_quality_failures >= rollback_failures_threshold:
    candidate_reason = f"rollback_quality_failures:{rollback_quality_failures}:threshold:{rollback_failures_threshold}"
elif stagnant_delta >= stagnant_rounds:
    candidate_reason = f"stagnant_rounds:{stagnant_delta}:threshold:{stagnant_rounds}"


def reason_family(value: str) -> str:
    return value.split(":", 1)[0] if value else ""


last_reason = str(state.get("last_maintenance_reason") or "")
last_task = str(state.get("last_maintenance_task") or "")
cooling_down = (
    last_maintenance_at > 0
    and now - last_maintenance_at < cooldown_seconds
    and reason_family(candidate_reason) == reason_family(last_reason)
    and current_task == last_task
)
reason = "" if cooling_down else candidate_reason

state.update(
    {
        "updated_at_epoch": now,
        "baseline_rounds_total": baseline_round,
        "baseline_valid_rounds_total": baseline_valid,
        "rounds_total": rounds_total,
        "valid_rounds_total": valid_rounds_total,
        "current_task": current_task,
        "current_task_failure_total": task_failure_total,
        "proposal_quality_failure_total": proposal_quality_failures,
        "rollback_quality_failure_total": rollback_quality_failures,
        "typescript_quality_failure_total": typescript_quality_failures,
        "current_task_typescript_quality_failure_total": current_task_typescript_quality_failures,
        "top_typescript_diagnostic_signature": top_typescript_signature,
        "top_typescript_diagnostic_signature_count": top_typescript_signature_count,
        "stagnant_rounds_since_valid": stagnant_delta,
        "cooling_down": cooling_down,
        "suppressed_candidate_reason": candidate_reason if cooling_down else "",
        "candidate_reason": reason,
        "cooldown_scoped_to_task": current_task,
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
  python3 - "$REPO_ROOT/$SUPERVISOR_AGENTIC_STATE_PATH" "$REPO_ROOT/$PROGRESS_PATH" "$reason" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
progress_path = Path(sys.argv[2])
reason = sys.argv[3]
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {}
state["last_maintenance_at"] = int(time.time())
state["last_maintenance_reason"] = reason
try:
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
except Exception:
    progress = {}
state["last_maintenance_task"] = str(progress.get("current_task") or "")
state["baseline_rounds_total"] = int(progress.get("rounds_total") or state.get("rounds_total") or 0)
state["baseline_valid_rounds_total"] = int(progress.get("valid_rounds_total") or state.get("valid_rounds_total") or 0)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_agentic_codex_exec() {
  local sandbox="$1"
  local sandbox_args=()
  if [[ -n "$sandbox" ]] && [[ "$sandbox" != "auto" ]]; then
    sandbox_args=(--sandbox "$sandbox")
  fi
  timeout "$SUPERVISOR_AGENTIC_TIMEOUT_SECONDS" "$CODEX_BIN" exec \
    --skip-git-repo-check \
    "${sandbox_args[@]}" \
    -m "$MODEL_NAME" \
    -C "$REPO_ROOT" \
    -
}

run_agentic_maintenance() {
  local reason="$1"
  local maintenance_id=""
  local maintenance_log=""
  local maintenance_backup_dir=""
  local rc=0
  maintenance_id="$(date -u +%Y%m%dT%H%M%SZ)"
  maintenance_log="$DAEMON_DIR/logic-port-daemon-agentic-maintenance_${maintenance_id}.log"
  maintenance_backup_dir="$(mktemp -d "$REPO_ROOT/$DAEMON_DIR/logic-port-maintenance-backup.XXXXXX")"
  mkdir -p "$maintenance_backup_dir/scripts/ops/legal_data" "$maintenance_backup_dir/ipfs_datasets_py/optimizers" "$maintenance_backup_dir/tests/unit_tests/optimizers" "$maintenance_backup_dir/docs/logic"
  cp "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh" "$maintenance_backup_dir/scripts/ops/legal_data/run_logic_port_daemon.sh" 2>/dev/null || true
  cp "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh" "$maintenance_backup_dir/scripts/ops/legal_data/check_logic_port_daemon.sh" 2>/dev/null || true
  cp "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh" "$maintenance_backup_dir/scripts/ops/legal_data/ensure_logic_port_daemon.sh" 2>/dev/null || true
  cp "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh" "$maintenance_backup_dir/scripts/ops/legal_data/stop_logic_port_daemon.sh" 2>/dev/null || true
  cp "$REPO_ROOT/ipfs_datasets_py/ipfs_datasets_py/optimizers/logic_port_daemon.py" "$maintenance_backup_dir/ipfs_datasets_py/optimizers/logic_port_daemon.py" 2>/dev/null || true
  cp "$REPO_ROOT/ipfs_datasets_py/tests/unit_tests/optimizers/test_logic_port_daemon.py" "$maintenance_backup_dir/tests/unit_tests/optimizers/test_logic_port_daemon.py" 2>/dev/null || true
  cp "$REPO_ROOT/ipfs_datasets_py/docs/logic/LOGIC_PORT_DAEMON.md" "$maintenance_backup_dir/docs/logic/LOGIC_PORT_DAEMON.md" 2>/dev/null || true
  last_agentic_maintenance_status="running"
  last_agentic_maintenance_reason="$reason"
  last_agentic_maintenance_log_path="$maintenance_log"
  write_supervisor_status "agentic_maintenance_started" "$maintenance_id" "$maintenance_log" null
  stop_child
  mark_agentic_maintenance_ran "$reason"
  {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting agentic daemon-maintenance pass: $reason"
    run_agentic_codex_exec "$SUPERVISOR_AGENTIC_SANDBOX" <<PROMPT
You are maintaining the logic-port daemon infrastructure for the browser-native TypeScript/WASM port.

The supervisor detected that the daemon may be stuck or not making meaningful progress.

Reason: $reason

This maintenance pass is allowed to make the supervisor and daemon more robust automatically. Prefer infrastructure fixes that let future unattended rounds recover without user input. Keep default provider routing delegated to ipfs_datasets_py.llm_router unless an explicit PROVIDER/--provider override is supplied. Preserve existing supervisor robustness guards; do not remove tmux ensure launch support, parser-daemon cleanup exclusions, orphaned LLM call detection, or backup/restore validation around maintenance edits.

If the reason mentions proposal_quality_failures, rollback_quality_failures, typescript_quality_failures, repeated_typescript_diagnostic, orphaned_llm_calls, or supervisor_infrastructure, inspect the daemon result log and patch the daemon or supervisor so future cycles avoid that bad loop. Typical fixes include stricter JSON-only prompts, better raw-response capture, earlier TypeScript preflight checks, stronger proposal retry feedback, tighter validation-repair prompts, better task blocking, safer subprocess cleanup, or clearer status fields that let the supervisor diagnose the same failure mode sooner.

If repeated TypeScript-quality failures are caused by ambitious malformed file replacements, patch the daemon prompt, retry feedback, task blocking, or task-selection logic so it lands smaller compileable browser-native scaffolds first. If the supervisor itself stopped while the daemon was still stale or failing, patch the supervisor startup/restart path so it can invoke maintenance before launching another child. If repo-local Codex/router subprocesses outlive their daemon or maintenance parent, patch cleanup and stuck-detection so those orphaned LLM calls become an automatic infrastructure-maintenance trigger rather than a manual intervention. Do not kill or modify the separate legal parser daemon or subprocesses whose ancestor command contains parser_daemon or run_legal_parser_optimizer_daemon.sh.

Improve only the daemon/supervisor implementation, its tests, or its docs. Do not work on the TypeScript logic port itself in this maintenance pass.

Allowed files:
- ipfs_datasets_py/ipfs_datasets_py/optimizers/logic_port_daemon.py
- ipfs_datasets_py/tests/unit_tests/optimizers/test_logic_port_daemon.py
- ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh
- ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh
- ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh
- ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh
- ipfs_datasets_py/docs/logic/LOGIC_PORT_DAEMON.md

Focus on changes that help unattended operation make real progress: better stuck detection, better task selection, better validation repair prompts, safer restart behavior, clearer status/progress accounting, or better documentation for those behaviors.

Do not run `stop_logic_port_daemon.sh`, `ensure_logic_port_daemon.sh`, `run_logic_port_daemon.sh`, `run_legal_parser_optimizer_daemon.sh`, or any command that sends signals to daemon/supervisor processes. Validate shell syntax with `bash -n` only; the parent supervisor must remain alive and launch the next daemon cycle after this maintenance pass.

After editing, run:
- bash -n ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh
- PYTHONPATH=ipfs_datasets_py python3 -m py_compile ipfs_datasets_py/ipfs_datasets_py/optimizers/logic_port_daemon.py
- PYTHONPATH=ipfs_datasets_py pytest -q ipfs_datasets_py/tests/unit_tests/optimizers/test_logic_port_daemon.py

Keep the daemon pointed at docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md, not the deterministic parser plans.
PROMPT
  } >> "$REPO_ROOT/$maintenance_log" 2>&1
  rc=$?
  if [[ "$rc" == "0" ]] && grep -Eq "bwrap: loopback|Failed RTM_NEWADDR|couldn.t perform this maintenance pass|could not inspect files|could not .*run the requested validation" "$REPO_ROOT/$maintenance_log"; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) primary agentic maintenance reported sandbox failure despite exit code 0" >> "$REPO_ROOT/$maintenance_log"
    rc=70
  fi
  if [[ "$rc" != "0" ]] && [[ "$SUPERVISOR_AGENTIC_FALLBACK_SANDBOX" != "$SUPERVISOR_AGENTIC_SANDBOX" ]]; then
    {
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) primary agentic maintenance exited with code $rc; retrying with sandbox=$SUPERVISOR_AGENTIC_FALLBACK_SANDBOX"
      run_agentic_codex_exec "$SUPERVISOR_AGENTIC_FALLBACK_SANDBOX" <<PROMPT
You are maintaining the logic-port daemon infrastructure for the browser-native TypeScript/WASM port.

The previous maintenance attempt failed before it could make the daemon more robust. Retry the same maintenance task, but avoid exploratory shell work if the environment blocks sandboxed commands.

Reason: $reason

Improve only the daemon/supervisor implementation, tests, or docs from the allowed files. Keep default provider routing delegated to ipfs_datasets_py.llm_router unless an explicit PROVIDER/--provider override is supplied.

Focus on making future unattended rounds recover automatically from repeated TypeScript-quality proposal failures, repeated TypeScript diagnostic signatures, orphaned LLM subprocesses, reverted launcher cleanup, and stale supervisor exits. Preserve existing supervisor robustness guards; do not remove tmux ensure launch support, parser-daemon cleanup exclusions, orphaned LLM call detection, or backup/restore validation around maintenance edits.

Do not run `stop_logic_port_daemon.sh`, `ensure_logic_port_daemon.sh`, `run_logic_port_daemon.sh`, `run_legal_parser_optimizer_daemon.sh`, or any command that sends signals to daemon/supervisor processes. Validate shell syntax with `bash -n` only; the parent supervisor must remain alive and launch the next daemon cycle after this maintenance pass.

Run validation if possible:
- bash -n ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh
- PYTHONPATH=ipfs_datasets_py python3 -m py_compile ipfs_datasets_py/ipfs_datasets_py/optimizers/logic_port_daemon.py
- PYTHONPATH=ipfs_datasets_py pytest -q ipfs_datasets_py/tests/unit_tests/optimizers/test_logic_port_daemon.py
PROMPT
    } >> "$REPO_ROOT/$maintenance_log" 2>&1
    rc=$?
    if [[ "$rc" == "0" ]] && grep -Eq "bwrap: loopback|Failed RTM_NEWADDR|couldn.t perform this maintenance pass|could not inspect files|could not .*run the requested validation" "$REPO_ROOT/$maintenance_log"; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) fallback agentic maintenance reported sandbox failure despite exit code 0" >> "$REPO_ROOT/$maintenance_log"
      rc=70
    fi
  fi
  if [[ "$rc" == "0" ]] \
    && bash -n "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && bash -n "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && bash -n "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && bash -n "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && grep -q "launch_mode=\\\"tmux\\\"" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh" \
    && grep -q "terminate_orphaned_logic_port_llm_calls" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh" \
    && grep -q "pid_has_parser_daemon_ancestor" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh" \
    && grep -q "pid_has_parser_daemon_ancestor" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh" \
    && PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}" python3 -m py_compile "$REPO_ROOT/ipfs_datasets_py/ipfs_datasets_py/optimizers/logic_port_daemon.py" >> "$REPO_ROOT/$maintenance_log" 2>&1 \
    && PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}" pytest -q "$REPO_ROOT/ipfs_datasets_py/tests/unit_tests/optimizers/test_logic_port_daemon.py" >> "$REPO_ROOT/$maintenance_log" 2>&1; then
    last_agentic_maintenance_status="accepted"
  else
    last_agentic_maintenance_status="failed"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) maintenance validation failed; restoring daemon/supervisor files from $maintenance_backup_dir" >> "$REPO_ROOT/$maintenance_log"
    cp "$maintenance_backup_dir/scripts/ops/legal_data/run_logic_port_daemon.sh" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh" 2>/dev/null || true
    cp "$maintenance_backup_dir/scripts/ops/legal_data/check_logic_port_daemon.sh" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh" 2>/dev/null || true
    cp "$maintenance_backup_dir/scripts/ops/legal_data/ensure_logic_port_daemon.sh" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh" 2>/dev/null || true
    cp "$maintenance_backup_dir/scripts/ops/legal_data/stop_logic_port_daemon.sh" "$REPO_ROOT/ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh" 2>/dev/null || true
    cp "$maintenance_backup_dir/ipfs_datasets_py/optimizers/logic_port_daemon.py" "$REPO_ROOT/ipfs_datasets_py/ipfs_datasets_py/optimizers/logic_port_daemon.py" 2>/dev/null || true
    cp "$maintenance_backup_dir/tests/unit_tests/optimizers/test_logic_port_daemon.py" "$REPO_ROOT/ipfs_datasets_py/tests/unit_tests/optimizers/test_logic_port_daemon.py" 2>/dev/null || true
    cp "$maintenance_backup_dir/docs/logic/LOGIC_PORT_DAEMON.md" "$REPO_ROOT/ipfs_datasets_py/docs/logic/LOGIC_PORT_DAEMON.md" 2>/dev/null || true
  fi
  rm -rf "$maintenance_backup_dir"
  write_supervisor_status "agentic_maintenance_finished" "$maintenance_id" "$maintenance_log" "$rc"
  return 0
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

pid_has_ancestor() {
  local pid="$1"
  local ancestor="$2"
  local parent=""
  if [[ -z "$pid" ]] || [[ -z "$ancestor" ]]; then
    return 1
  fi
  while [[ -n "$pid" ]] && [[ "$pid" != "0" ]] && [[ "$pid" != "1" ]]; do
    if [[ "$pid" == "$ancestor" ]]; then
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

process_cwd_is_logic_repo_local() {
  local pid="$1"
  local cwd=""
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ "$cwd" == "$REPO_ROOT" || "$cwd" == "$REPO_ROOT/ipfs_datasets_py" ]]
}

terminate_orphaned_logic_port_llm_calls() {
  local pid=""
  local args=""
  local cleaned=0
  while read -r pid args; do
    if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]]; then
      continue
    fi
    if [[ "$args" != *"codex exec --skip-git-repo-check"* ]] || [[ "$args" != *"--ephemeral --json -"* ]]; then
      continue
    fi
    if [[ "$args" != *"-m $MODEL_NAME"* ]] && [[ "$args" != *"--model $MODEL_NAME"* ]]; then
      continue
    fi
    if pid_has_parser_daemon_ancestor "$pid"; then
      continue
    fi
    if [[ -n "${child_pid:-}" ]] && pid_has_ancestor "$pid" "$child_pid"; then
      continue
    fi
    if ! process_cwd_is_logic_repo_local "$pid"; then
      continue
    fi
    cleaned=$((cleaned + 1))
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cleaning up orphaned logic-port LLM call $pid before supervisor start/restart" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
    terminate_pid_tree "$pid"
  done < <(ps -eo pid=,args=)
  last_orphaned_llm_cleanup_count=$cleaned
  [[ "$cleaned" -gt 0 ]]
}

run_infrastructure_maintenance_if_needed() {
  local reason="$1"
  if [[ "$SUPERVISOR_AGENTIC_MAINTENANCE" != "1" ]] || [[ -z "$reason" ]]; then
    return 1
  fi
  last_recycle_reason="supervisor_infrastructure_maintenance"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor invoking infrastructure maintenance: $reason" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
  run_agentic_maintenance "$reason"
  return 0
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
  terminate_orphaned_logic_port_llm_calls || true
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
if terminate_orphaned_logic_port_llm_calls; then
  if [[ "$SUPERVISOR_AGENTIC_STARTUP_MAINTENANCE" == "1" ]]; then
    run_infrastructure_maintenance_if_needed "orphaned_llm_calls:$last_orphaned_llm_cleanup_count:startup_cleanup" || true
  else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cleaned up $last_orphaned_llm_cleanup_count startup orphaned logic-port LLM calls; startup maintenance disabled so continuing to daemon launch" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
  fi
fi

if [[ "$SUPERVISOR_AGENTIC_STARTUP_MAINTENANCE" == "1" ]]; then
  startup_maintenance_reason="$(agentic_maintenance_reason || true)"
  if [[ -n "$startup_maintenance_reason" ]]; then
    last_recycle_reason="startup_agentic_maintenance"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor invoking startup agentic maintenance: $startup_maintenance_reason" >> "$REPO_ROOT/$LATEST_LOG_PATH" 2>/dev/null || true
    run_agentic_maintenance "$startup_maintenance_reason"
  fi
fi

while true; do
  if terminate_orphaned_logic_port_llm_calls; then
    run_infrastructure_maintenance_if_needed "orphaned_llm_calls:$last_orphaned_llm_cleanup_count:pre_cycle_cleanup" || true
  fi
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  run_log="$DAEMON_DIR/logic-port-daemon-supervised_${run_id}.log"
  ln -sfn "$(basename "$run_log")" "$REPO_ROOT/$LATEST_LOG_PATH"
  write_supervisor_status "starting" "$run_id" "$run_log" null

  (
    cd "$REPO_ROOT" || exit 2
    export PYTHONUNBUFFERED=1
    export PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}"
    export IPFS_DATASETS_PY_CODEX_CLI_MODEL="$MODEL_NAME"
    python3_args=(
      python3 -u -m ipfs_datasets_py.optimizers.logic_port_daemon
      --repo-root .
      --model "$MODEL_NAME"
      --slice-mode "$SLICE_MODE"
    )
    [[ -n "$PROVIDER" ]] && python3_args+=(--provider "$PROVIDER")
    python3_args+=(
      --apply
      --watch
      --cycles 0
      --retry-interval 0
      --llm-timeout "$LLM_TIMEOUT_SECONDS"
      --command-timeout "$COMMAND_TIMEOUT_SECONDS"
      --max-prompt-chars "$MAX_PROMPT_CHARS"
      --heartbeat-interval "$HEARTBEAT_INTERVAL_SECONDS"
      --max-task-failures "$MAX_TASK_FAILURES"
      --proposal-attempts "$PROPOSAL_ATTEMPTS"
      --file-repair-attempts "$FILE_REPAIR_ATTEMPTS"
      --validation-repair-attempts "$VALIDATION_REPAIR_ATTEMPTS"
      --validation-repair-failure-budget "$VALIDATION_REPAIR_FAILURE_BUDGET"
      --revisit-blocked-tasks
      --blocked-backlog-limit "$BLOCKED_BACKLOG_LIMIT"
      --blocked-task-strategy "$BLOCKED_TASK_STRATEGY"
      --plan-replenishment-limit "$PLAN_REPLENISHMENT_LIMIT"
      --status-file "$STATUS_PATH"
      --progress-file "$PROGRESS_PATH"
      --log-file "$RESULT_LOG_PATH"
    )
    "${python3_args[@]}"
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
    maintenance_reason="$(agentic_maintenance_reason || true)"
    if [[ -n "$maintenance_reason" ]]; then
      last_recycle_reason="agentic_maintenance"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor invoking agentic maintenance: $maintenance_reason" >> "$REPO_ROOT/$run_log"
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
  write_supervisor_status "restarting" "$run_id" "$run_log" "$rc"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) logic-port daemon exited with code $rc; restarting in ${RESTART_DELAY_SECONDS}s" >> "$REPO_ROOT/$run_log"
  if [[ "$RESTART_DELAY_SECONDS" != "0" ]]; then
    sleep "$RESTART_DELAY_SECONDS"
  fi
  terminate_matching_logic_port_daemons
  if terminate_orphaned_logic_port_llm_calls; then
    run_infrastructure_maintenance_if_needed "orphaned_llm_calls:$last_orphaned_llm_cleanup_count:restart_cleanup" || true
  fi
done
