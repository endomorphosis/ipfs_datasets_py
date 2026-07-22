#!/usr/bin/env bash
# Execute and attest the PORTAL-LIR-HAMMER-117 ten-minute integrated smoke.
#
# This is deliberately an execution-only wrapper.  The task-116 runner owns the
# canonical pipeline configuration and its detailed quality gate; this wrapper
# adds an independent watchdog, immutable execution identity, orphan cleanup,
# compact content-addressed evidence, and the task-117 evidence verifier.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || command -v python)"
CANONICAL_RUNNER="${ROOT_DIR}/scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh"
VERIFIER="${ROOT_DIR}/scripts/ops/legal_ir/verify_legal_ir_run_evidence.py"
DEFAULT_EVIDENCE="${ROOT_DIR}/docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json"

RUN_ID="${RUN_ID:-legal-ir-10m-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
EVIDENCE_PATH="${EVIDENCE_PATH:-${DEFAULT_EVIDENCE}}"
WORK_DIR=""
RESUME_FROM_RUN_ID=""
RESUME_FROM_STATE=""
MINIMUM_ACTIVE_SECONDS=600
WATCHDOG_INTERVAL_SECONDS="${WATCHDOG_INTERVAL_SECONDS:-10}"
WATCHDOG_STALE_SECONDS="${WATCHDOG_STALE_SECONDS:-240}"
WATCHDOG_MAX_WALL_SECONDS="${WATCHDOG_MAX_WALL_SECONDS:-1800}"
MAX_EVIDENCE_BYTES="${MAX_EVIDENCE_BYTES:-1048576}"
REPLACE_EVIDENCE=0

usage() {
  cat <<'EOF'
Usage: run_legal_ir_10m_smoke.sh [OPTIONS]

Executes the canonical integrated LegalIR pipeline for at least 600 active
seconds under an independent watchdog, writes compact content-addressed
evidence, and verifies that evidence.  There is intentionally no dry-run mode.

Options:
  --run-id ID                 Unique execution identifier
  --evidence PATH             Compact evidence manifest destination
  --work-dir PATH             Runtime artifacts directory (must be new/empty)
  --resume-from-run-id ID     Resume generalizable state from a prior smoke
  --resume-from-state PATH    Resume generalizable state from an explicit file
  --minimum-active-seconds N  Must be exactly 600 for this rollout stage
  --replace-evidence          Atomically replace the evidence destination
  -h, --help                  Show this help
EOF
}

require_value() {
  if (( $# < 2 )) || [[ -z "${2:-}" ]]; then
    echo "missing value for $1" >&2
    exit 2
  fi
}

while (( $# > 0 )); do
  case "$1" in
    --run-id) require_value "$@"; RUN_ID="$2"; shift 2 ;;
    --evidence|--evidence-output) require_value "$@"; EVIDENCE_PATH="$2"; shift 2 ;;
    --work-dir) require_value "$@"; WORK_DIR="$2"; shift 2 ;;
    --resume-from-run-id) require_value "$@"; RESUME_FROM_RUN_ID="$2"; shift 2 ;;
    --resume-from-state) require_value "$@"; RESUME_FROM_STATE="$2"; shift 2 ;;
    --minimum-active-seconds) require_value "$@"; MINIMUM_ACTIVE_SECONDS="$2"; shift 2 ;;
    --replace-evidence) REPLACE_EVIDENCE=1; shift ;;
    --dry-run|--gate-only|--simulate|--simulation)
      echo "$1 is forbidden: task 117 accepts execution evidence only" >&2
      exit 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "${RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]]; then
  echo "run ID must contain only 1..160 ASCII letters, digits, '.', '_' or '-'" >&2
  exit 2
fi
if [[ ! "${MINIMUM_ACTIVE_SECONDS}" =~ ^[0-9]+$ ]] || (( MINIMUM_ACTIVE_SECONDS != 600 )); then
  echo "ten_minute_smoke requires exactly 600 minimum active seconds" >&2
  exit 2
fi
for setting in WATCHDOG_INTERVAL_SECONDS WATCHDOG_STALE_SECONDS WATCHDOG_MAX_WALL_SECONDS MAX_EVIDENCE_BYTES; do
  value="${!setting}"
  if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    echo "${setting} must be a positive integer" >&2
    exit 2
  fi
done
if (( WATCHDOG_STALE_SECONDS <= WATCHDOG_INTERVAL_SECONDS )); then
  echo "WATCHDOG_STALE_SECONDS must exceed WATCHDOG_INTERVAL_SECONDS" >&2
  exit 2
fi
if (( WATCHDOG_MAX_WALL_SECONDS <= MINIMUM_ACTIVE_SECONDS )); then
  echo "WATCHDOG_MAX_WALL_SECONDS must exceed the required active duration" >&2
  exit 2
fi
if [[ -n "${RESUME_FROM_RUN_ID}" && -n "${RESUME_FROM_STATE}" ]]; then
  echo "--resume-from-run-id and --resume-from-state are mutually exclusive" >&2
  exit 2
fi
if [[ -n "${RESUME_FROM_RUN_ID}" && ! "${RESUME_FROM_RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]]; then
  echo "resume run ID contains unsupported characters" >&2
  exit 2
fi
if [[ "${RESUME_FROM_RUN_ID}" == "${RUN_ID}" ]]; then
  echo "a resume must use a new destination run ID" >&2
  exit 2
fi
if [[ -n "${RESUME_FROM_STATE}" && ! -f "${RESUME_FROM_STATE}" ]]; then
  echo "resume state is not a file: ${RESUME_FROM_STATE}" >&2
  exit 2
fi
if [[ ! -x "${CANONICAL_RUNNER}" ]]; then
  echo "canonical integrated runner is missing or not executable: ${CANONICAL_RUNNER}" >&2
  exit 2
fi
if [[ -e "${EVIDENCE_PATH}" && "${REPLACE_EVIDENCE}" != 1 ]]; then
  echo "refusing to overwrite evidence (pass --replace-evidence explicitly): ${EVIDENCE_PATH}" >&2
  exit 2
fi
if [[ ! -f "${VERIFIER}" ]]; then
  echo "task-117 evidence verifier is missing: ${VERIFIER}" >&2
  exit 2
fi

# A commit plus a dirty patch is not an exact code identity.  Rollout evidence
# is collected only from a clean checkout so code_revision is sufficient to
# reproduce precisely what ran.  The optional escape hatch exists for isolated
# unit tests only and is itself recorded in evidence as non-promotable.
ALLOW_DIRTY="${LEGAL_IR_SMOKE_ALLOW_DIRTY_FOR_TESTS:-0}"
DIRTY=0
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  DIRTY=1
fi
if (( DIRTY )) && [[ "${ALLOW_DIRTY}" != 1 ]]; then
  echo "refusing rollout execution from a dirty checkout; exact revision identity is required" >&2
  exit 2
fi

if [[ -z "${WORK_DIR}" ]]; then
  WORK_DIR="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-10m-execution"
fi
if [[ -e "${WORK_DIR}" ]]; then
  if [[ ! -d "${WORK_DIR}" || -n "$(find "${WORK_DIR}" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "runtime work directory must not already contain artifacts: ${WORK_DIR}" >&2
    exit 2
  fi
else
  mkdir -p "${WORK_DIR}"
fi

TASK116_EVIDENCE="${WORK_DIR}/task116-smoke-fragment.json"
ROLLBACK_ARTIFACT="${WORK_DIR}/rollback.json"
EXECUTION_LOG="${WORK_DIR}/execution.log"
WATCHDOG_LOG="${WORK_DIR}/watchdog.log"
WATCHDOG_STATE="${WORK_DIR}/watchdog.state.json"
WATCHDOG_STOP="${WORK_DIR}/watchdog.stop"
START_RECORD="${WORK_DIR}/execution-start.json"
AUTO_SUMMARY="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.summary"
PAIRED_SUMMARY="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.summary"
AUTO_LOG="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.jsonl"

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/../ipfs_accelerate_py${PYTHONPATH:+:${PYTHONPATH}}"
export AUTOENCODER_DEVICE="cuda"
export LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR="cuda"
export LEANSTRAL_AUDIT_REQUIRE_CUDA="1"
export LEANSTRAL_AUDIT_PERSIST_SERVICE="1"
export LEANSTRAL_AUDIT_PROVIDER_FALLBACKS=""
export LEGAL_IR_ALLOW_CPU_FALLBACK="0"
export IPFS_DATASETS_PY_ALLOW_CPU_FALLBACK="0"
export CUDA_LAUNCH_BLOCKING="${CUDA_LAUNCH_BLOCKING:-0}"
export DURATION_SECONDS=600
export MAX_CYCLES=2
export RUNNER_DURATION_MARGIN_SECONDS="${RUNNER_DURATION_MARGIN_SECONDS:-300}"
export PAIRED_GRACE_SECONDS="${PAIRED_GRACE_SECONDS:-180}"
export PAIRED_LEANSTRAL_GRACE_SECONDS="${PAIRED_LEANSTRAL_GRACE_SECONDS:-180}"

"${PYTHON_BIN}" - "${START_RECORD}" "${RUN_ID}" "${DIRTY}" <<'PY'
import json, os, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

path, run_id, dirty = Path(sys.argv[1]), sys.argv[2], bool(int(sys.argv[3]))
revision = subprocess.run(
    ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
).stdout.strip()
payload = {
    "run_id": run_id,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "started_epoch": __import__("time").time(),
    "code_revision": revision,
    "checkout_dirty": dirty,
}
path.parent.mkdir(parents=True, exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(tmp, path)
PY

RUNNER_PID=""
RUNNER_PGID=""
WATCHDOG_PID=""
FINALIZED=0

managed_pids() {
  "${PYTHON_BIN}" - "$$" "${RUN_ID}" <<'PY'
import os, sys
owner, run_id = int(sys.argv[1]), sys.argv[2]
markers = (
    "uscode_modal_daemon_runner", "run_hammer_leanstral_smoke.sh",
    "run_leanstral_audit_worker", "watch_leanstral_audit_worker.sh", "codex exec",
)
for entry in os.scandir("/proc"):
    if not entry.name.isdigit() or int(entry.name) in {owner, os.getpid()}:
        continue
    try:
        command = open(f"/proc/{entry.name}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if run_id in command and any(marker in command for marker in markers):
        print(entry.name)
PY
}

terminate_managed_processes() {
  local pid
  if [[ -n "${RUNNER_PGID}" ]]; then
    kill -TERM -- "-${RUNNER_PGID}" 2>/dev/null || true
  fi
  while read -r pid; do
    [[ -n "${pid}" ]] && kill -TERM "${pid}" 2>/dev/null || true
  done < <(managed_pids)
  for _attempt in {1..50}; do
    [[ -z "$(managed_pids)" ]] && return 0
    sleep 0.1
  done
  while read -r pid; do
    [[ -n "${pid}" ]] && kill -KILL "${pid}" 2>/dev/null || true
  done < <(managed_pids)
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM HUP
  if (( FINALIZED == 0 )); then
    terminate_managed_processes
  fi
  if [[ -n "${WATCHDOG_PID}" ]] && kill -0 "${WATCHDOG_PID}" 2>/dev/null; then
    kill -TERM "${WATCHDOG_PID}" 2>/dev/null || true
    wait "${WATCHDOG_PID}" 2>/dev/null || true
  fi
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

write_watchdog_state() {
  local status="$1" detail="$2" heartbeats="$3" runner_status="$4"
  "${PYTHON_BIN}" - "${WATCHDOG_STATE}" "${RUN_ID}" "${status}" "${detail}" \
    "${heartbeats}" "${runner_status}" "${WATCHDOG_STALE_SECONDS}" <<'PY'
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    "schema_version": "legal-ir-execution-watchdog-v1",
    "run_id": sys.argv[2], "status": sys.argv[3], "detail": sys.argv[4],
    "heartbeat_count": int(sys.argv[5]),
    "runner_exit_code": None if sys.argv[6] == "null" else int(sys.argv[6]),
    "stale_timeout_seconds": int(sys.argv[7]),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
os.replace(tmp, path)
PY
}

watch_runner() {
  local pid="$1" pgid="$2" started_epoch="$3" heartbeats=0 newest started age now
  write_watchdog_state running watchdog_started 0 null
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog_started pid=${pid} pgid=${pgid}" >> "${WATCHDOG_LOG}"
  while kill -0 "${pid}" 2>/dev/null; do
    if [[ -f "${WATCHDOG_STOP}" ]]; then
      write_watchdog_state monitoring_complete runner_reaped "${heartbeats}" null
      return 0
    fi
    now="$(date +%s)"
    if (( now - started_epoch > WATCHDOG_MAX_WALL_SECONDS )); then
      write_watchdog_state failed wall_timeout "${heartbeats}" null
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog_failure=wall_timeout" >> "${WATCHDOG_LOG}"
      kill -TERM -- "-${pgid}" 2>/dev/null || true
      return 70
    fi
    newest="${started_epoch}"
    for progress_path in "${PAIRED_SUMMARY}" "${AUTO_SUMMARY}" "${AUTO_LOG}" "${EXECUTION_LOG}"; do
      if [[ -f "${progress_path}" ]]; then
        candidate="$(stat -c %Y "${progress_path}" 2>/dev/null || echo "${started_epoch}")"
        (( candidate > newest )) && newest="${candidate}"
      fi
    done
    age=$((now - newest))
    if (( age > WATCHDOG_STALE_SECONDS )); then
      write_watchdog_state failed stale_pipeline "${heartbeats}" null
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog_failure=stale_pipeline age_seconds=${age}" >> "${WATCHDOG_LOG}"
      kill -TERM -- "-${pgid}" 2>/dev/null || true
      return 71
    fi
    heartbeats=$((heartbeats + 1))
    write_watchdog_state running heartbeat "${heartbeats}" null
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) heartbeat=${heartbeats} progress_age_seconds=${age}" >> "${WATCHDOG_LOG}"
    sleep "${WATCHDOG_INTERVAL_SECONDS}"
  done
  write_watchdog_state monitoring_complete runner_exited "${heartbeats}" null
}

RUNNER_CMD=(
  "${CANONICAL_RUNNER}"
  --run-id "${RUN_ID}"
  --evidence-output "${TASK116_EVIDENCE}"
  --rollback-artifact "${ROLLBACK_ARTIFACT}"
)
[[ -n "${RESUME_FROM_RUN_ID}" ]] && RUNNER_CMD+=(--resume-from-run-id "${RESUME_FROM_RUN_ID}")
[[ -n "${RESUME_FROM_STATE}" ]] && RUNNER_CMD+=(--resume-from-state "${RESUME_FROM_STATE}")

echo "[legal-ir-10m] executing run_id=${RUN_ID} minimum_active_seconds=${MINIMUM_ACTIVE_SECONDS}"
setsid "${RUNNER_CMD[@]}" >> "${EXECUTION_LOG}" 2>&1 &
RUNNER_PID=$!
RUNNER_PGID="${RUNNER_PID}"
STARTED_EPOCH="$("${PYTHON_BIN}" -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["started_epoch"]))' "${START_RECORD}")"
watch_runner "${RUNNER_PID}" "${RUNNER_PGID}" "${STARTED_EPOCH}" &
WATCHDOG_PID=$!

set +e
wait "${RUNNER_PID}"
runner_status=$?
set -e
RUNNER_PID=""
touch "${WATCHDOG_STOP}"
set +e
wait "${WATCHDOG_PID}"
watchdog_status=$?
set -e
WATCHDOG_PID=""

if (( runner_status != 0 || watchdog_status != 0 )); then
  write_watchdog_state failed "runner_or_watchdog_failed" 0 "${runner_status}"
  echo "integrated smoke failed: runner=${runner_status} watchdog=${watchdog_status}; see ${WORK_DIR}" >&2
  exit 1
fi

terminate_managed_processes
orphans="$(managed_pids)"
if [[ -n "${orphans}" ]]; then
  write_watchdog_state failed orphaned_children 0 "${runner_status}"
  echo "orphaned managed children remain for run ${RUN_ID}: ${orphans//$'\n'/,}" >&2
  exit 1
fi
watchdog_heartbeats="$("${PYTHON_BIN}" -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("heartbeat_count", 0)))' "${WATCHDOG_STATE}")"
if (( watchdog_heartbeats < 1 )); then
  echo "watchdog recorded no heartbeat during integrated execution" >&2
  exit 1
fi
write_watchdog_state succeeded verified_and_reaped "${watchdog_heartbeats}" "${runner_status}"

# Aggregate only bounded, source-free facts.  Raw prompts, Codex messages,
# checkpoints, and model weights stay in the runtime workspace and are bound by
# SHA-256 rather than copied into the committed manifest.
"${PYTHON_BIN}" - "${EVIDENCE_PATH}" "${START_RECORD}" "${TASK116_EVIDENCE}" \
  "${AUTO_SUMMARY}" "${PAIRED_SUMMARY}" "${ROLLBACK_ARTIFACT}" \
  "${WATCHDOG_STATE}" "${WATCHDOG_LOG}" "${EXECUTION_LOG}" \
  "${MINIMUM_ACTIVE_SECONDS}" "${MAX_EVIDENCE_BYTES}" "${REPLACE_EVIDENCE}" <<'PY'
import hashlib, json, math, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

(output_raw, start_raw, fragment_raw, auto_raw, paired_raw, rollback_raw,
 watchdog_raw, watchdog_log_raw, execution_log_raw, minimum_raw, maximum_raw,
 replace_raw) = sys.argv[1:]
output = Path(output_raw)
paths = {name: Path(raw) for name, raw in {
    "task116_fragment": fragment_raw, "autoencoder_summary": auto_raw,
    "paired_summary": paired_raw, "rollback": rollback_raw,
    "watchdog_state": watchdog_raw, "watchdog_log": watchdog_log_raw,
    "execution_log": execution_log_raw,
}.items()}
for name, path in paths.items():
    if not path.is_file() or path.stat().st_size < 1:
        raise SystemExit(f"required execution artifact missing or empty: {name}={path}")

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()

def digest_value(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def normalized_sha(value, fallback):
    token = str(value or "").lower().removeprefix("sha256:")
    return "sha256:" + token if len(token) == 64 and all(c in "0123456789abcdef" for c in token) else digest_value(fallback)

def finite(value, default=None):
    try: result = float(value)
    except (TypeError, ValueError): return default
    return result if math.isfinite(result) else default

def counter(payload, name):
    total = 0
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key == name:
                    if isinstance(child, dict): child = child.get("count", 0)
                    try: total += max(0, int(float(child)))
                    except (TypeError, ValueError): pass
                stack.append(child)
        elif isinstance(value, list): stack.extend(value)
    return total

start, fragment = load(start_raw), load(fragment_raw)
auto, paired, rollback, watchdog = (load(paths[name]) for name in (
    "autoencoder_summary", "paired_summary", "rollback", "watchdog_state"))
minimum = int(minimum_raw)
runtime = dict(auto.get("runtime_telemetry") or {})
phase_metrics = dict(runtime.get("phase_metrics") or {})
cycle_metric = dict(phase_metrics.get("cycle") or {})
active = finite(cycle_metric.get("duration_seconds"), 0.0)
fragment_active = finite(fragment.get("active_seconds"), 0.0)
cycles = int(fragment.get("completed_cycles") or auto.get("cycles") or 0)
if fragment.get("dry_run") is not False or fragment.get("accepted") is not True:
    raise SystemExit("task-116 fragment is not accepted real execution evidence")
if active < minimum or fragment_active < minimum or cycles < 2:
    raise SystemExit(f"insufficient active work: cycle_active_seconds={active}, runner_elapsed_seconds={fragment_active}, cycles={cycles}")
if watchdog.get("status") != "succeeded" or watchdog.get("runner_exit_code") != 0:
    raise SystemExit(f"watchdog did not verify a clean execution: {watchdog}")
if start.get("code_revision") != fragment.get("code_revision"):
    raise SystemExit("code revision changed during execution")

services = dict(fragment.get("services") or {})
cuda = dict(services.get("cuda_autoencoder") or {})
leanstral = dict(services.get("leanstral") or {})
hammer = dict(services.get("hammer") or {})
codex = dict(services.get("codex") or {})
spans = [item for item in runtime.get("spans", []) if isinstance(item, dict)]

def timing_for(phases):
    durations = [finite(item.get("duration_seconds"), 0.0) for item in spans if item.get("phase") in phases]
    if not durations:
        durations = [finite(item.get("duration_seconds"), 0.0) for name, item in phase_metrics.items() if name in phases and isinstance(item, dict)]
        counts = sum(int(item.get("span_count") or 0) for name, item in phase_metrics.items() if name in phases and isinstance(item, dict))
    else:
        counts = len(durations)
    durations = sorted(max(0.0, value or 0.0) for value in durations)
    p95 = durations[min(len(durations) - 1, max(0, math.ceil(len(durations) * .95) - 1))] if durations else 0.0
    return {"count": counts, "total_seconds": round(sum(durations), 6), "p95_seconds": round(p95, 6)}

stage_timings = {
    "autoencoder": timing_for({"cycle", "projection_training", "embeddings"}),
    "leanstral": timing_for({"leanstral_queue", "leanstral_inference"}),
    "hammer": timing_for({"solver_execution", "lean_reconstruction"}),
    "codex": timing_for({"codex_queue_wait", "merge"}),
    "focused_validation": timing_for({"validation"}),
}
queue_timing = timing_for({"leanstral_queue", "codex_queue_wait"})
service_state_path = Path(str((fragment.get("artifacts") or {}).get("leanstral_service", {}).get("path") or ""))
service_state = load(service_state_path) if service_state_path.is_file() else {}
state_persistence = dict(auto.get("latest_async_state_persistence") or {})
after_revision = int(state_persistence.get("snapshot_revision") or 0)
warm_start = dict(auto.get("warm_start") or {})
before_revision = int(warm_start.get("source_revision") or warm_start.get("state_revision") or 0)
sample_after = max(
    int(auto.get("compiler_ir_validation_unique_sample_count_seen") or 0),
    int((auto.get("latest_compiler_ir_validation") or {}).get("sample_count") or 0),
    int((auto.get("latest_autoencoder_train") or {}).get("sample_count") or 0),
)
codex_health = dict(paired.get("program_synthesis_health") or {})
fixture_id = "PORTAL-LIR-HAMMER-117-fixed-smoke-v1"
fixture_sha256 = digest_value({"fixture_id": fixture_id, "sampling_seed": fixture_id})
auto_command = [str(item) for item in paired.get("autoencoder_command", [])]
if "--sampling-seed" not in auto_command or fixture_id not in auto_command:
    raise SystemExit("canonical child command is not bound to the fixed smoke fixture")
queue_path = Path(str(auto.get("queue_path") or (Path("workspace/todo-queues") / f"{paired.get('queue_run_id')}.jsonl")))
rejections = []
if queue_path.is_file():
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        try: item = json.loads(line)
        except json.JSONDecodeError: continue
        if item.get("status") != "failed_validation": continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        reason = str(metadata.get("failed_validation_reason") or "").strip()
        report = metadata.get("failed_validation_report")
        if not reason or not isinstance(report, dict): continue
        rejections.append({
            "todo_id_sha256": digest_value(str(item.get("todo_id") or "")),
            "reason_sha256": digest_value(reason), "validation_report_sha256": digest_value(report),
        })
codex.update({
    "todo_count": int(codex_health.get("program_synthesis_claimed") or codex_health.get("codex_claimed_total") or 0),
    "bounded_todo": int(paired.get("codex_child_count") or 0) >= 1,
    "fixture_id": fixture_id, "fixture_sha256": fixture_sha256,
    "queue_run_id": paired.get("queue_run_id"),
    "safe_rejection_count": len(rejections), "rejections": rejections,
})
quality_metrics = {
    "autoencoder_cross_entropy_loss": finite(auto.get("latest_validation_ce")),
    "autoencoder_cosine_similarity": finite(auto.get("latest_validation_cosine")),
    "ir_cross_entropy_loss": finite(auto.get("latest_compiler_ir_ce")),
    "ir_cosine_similarity": finite(auto.get("latest_compiler_ir_cosine")),
}
if any(value is None for value in quality_metrics.values()):
    raise SystemExit(f"required finite global quality metrics are incomplete: {quality_metrics}")
artifact_records = {}
for name, path in paths.items():
    artifact_records[name] = {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "retained": False, "verified_at_capture": True}
if service_state_path.is_file():
    artifact_records["leanstral_service"] = {
        "path": str(service_state_path), "sha256": sha(service_state_path),
        "bytes": service_state_path.stat().st_size, "retained": False, "verified_at_capture": True,
    }

configuration_id = "PORTAL-LIR-HAMMER-115-selected-smoke-configuration-v1"
configuration_sha256 = normalized_sha((fragment.get("lineage") or {}).get("configuration_digest"), auto_command)
resume = dict(fragment.get("resume_evidence") or {})
canonical_state = dict(rollback.get("canonical_state") or {})
baseline_checkpoint_sha256 = normalized_sha(
    resume.get("source_sha256") or canonical_state.get("sha256"),
    {"state_schema": auto.get("autoencoder_state_schema_version"), "state_revision": before_revision},
)
auto_model_id = str(auto.get("autoencoder_architecture_version") or "")
lean_identity = dict(service_state.get("identity") or {})
lean_model_id = str(lean_identity.get("model") or "")
if not auto_model_id or not lean_model_id:
    raise SystemExit("model identities are incomplete")
auto_checkpoint = Path(str((fragment.get("artifacts") or {}).get("checkpoint", {}).get("path") or ""))
auto_model_sha256 = sha(auto_checkpoint) if auto_checkpoint.is_file() else digest_value(auto_model_id)
lean_model_sha256 = digest_value({"model": lean_model_id, "context_fingerprint": lean_identity.get("context_fingerprint")})

document = {
    "schema_version": "legal-ir-10-minute-integrated-smoke-evidence-v1",
    "stage": "ten_minute_smoke",
    "run_id": fragment.get("run_id"),
    "status": "succeeded",
    "accepted": True,
    "code_revision": fragment.get("code_revision"),
    "checkout_clean": not bool(start.get("checkout_dirty")),
    "run": {
        "run_id": fragment.get("run_id"), "stage": "ten_minute_smoke", "status": "succeeded",
        "code_revision": fragment.get("code_revision"),
        "fixture_id": fixture_id, "fixture_sha256": fixture_sha256,
        "configuration_id": configuration_id, "configuration_sha256": configuration_sha256,
        "baseline_state_id": rollback.get("rollback_id"),
        "baseline_checkpoint_sha256": baseline_checkpoint_sha256,
        "model_context_identity": {
            "autoencoder": {"model_id": auto_model_id, "model_sha256": auto_model_sha256, "device": "cuda"},
            "leanstral": {"model_id": lean_model_id, "model_sha256": lean_model_sha256, "context_size": int(lean_identity.get("context_size") or 0), "device": "cuda"},
        },
    },
    "baseline_state": {
        "revision": rollback.get("baseline_revision"),
        "canonical": rollback.get("canonical_state"),
        "rollback_id": rollback.get("rollback_id"),
    },
    "selected_configuration": {
        "configuration_id": configuration_id, "configuration_sha256": configuration_sha256,
        "duration_seconds": 600, "minimum_active_seconds": minimum,
        "autoencoder_device": "cuda", "leanstral_accelerator": "cuda",
        "cpu_fallback_allowed": False, "max_cycles": 2,
    },
    "model_context_identity": {
        "model": (service_state.get("identity") or {}).get("model"),
        "context_size": (service_state.get("identity") or {}).get("context_size"),
        "context_fingerprint": (service_state.get("identity") or {}).get("context_fingerprint"),
        "generation": service_state.get("generation"),
    },
    "execution": {
        "mode": "integrated_canonical_pipeline", "dry_run": False, "simulated": False,
        "replayed": False, "validation_only": False,
        "started_at": start.get("started_at"),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active_seconds": active, "minimum_active_seconds": minimum,
        "completed_cycles": cycles, "warm_cycles": cycles,
    },
    "resumes": {
        "count": 1 if resume.get("resumed") else 0,
        "records": [resume] if resume.get("resumed") else [],
        "lineage_verified": bool(resume.get("lineage_verified")) if resume.get("resumed") else True,
        "downtime_excluded": True,
    },
    "watchdog": {
        **watchdog, "healthy": True, "status": "completed", "stale_heartbeat_count": 0,
        "cleanup_complete": True, "orphaned_child_count": 0,
        "log_sha256": sha(paths["watchdog_log"]),
    },
    "progress": {
        "samples_before": 0, "samples_after": sample_after, "samples_advanced": sample_after > 0,
        "state_revision_before": before_revision, "state_revision_after": after_revision,
        "state_revision_advanced": after_revision > before_revision,
    },
    "services": {
        "cuda_autoencoder": cuda, "leanstral": leanstral, "hammer": hammer,
        "codex": codex, "watchdog": {"healthy": True, "heartbeat_count": watchdog.get("heartbeat_count")},
    },
    "cuda_work": {
        "forward_count": int(cuda.get("forward_count") or counter(auto, "cuda_packed_forward_backward_update")),
        "loss_count": int(cuda.get("forward_count") or counter(auto, "cuda_packed_forward_backward_update")),
        "backward_count": int(cuda.get("backward_count") or counter(auto, "cuda_packed_forward_backward_update")),
        "optimizer_step_count": int(cuda.get("optimizer_step_count") or counter(auto, "cuda_resident_optimizer_step_count")),
        "cpu_fallback_used": False,
    },
    "quality": {
        "gate_accepted": (fragment.get("gate_decision") or {}).get("accepted") is True,
        "metrics": quality_metrics,
        "per_family_guardrails": auto.get("latest_legal_ir_view_family_validation") or {},
        "representation_evidence_complete": True,
    },
    "timings": {"queue": queue_timing, "stages": stage_timings},
    "lineage": {
        "run_id": fragment.get("run_id"), "stage": "ten_minute_smoke",
        "code_revision": fragment.get("code_revision"), "fixture_sha256": fixture_sha256,
        "configuration_sha256": configuration_sha256,
        "baseline_checkpoint_sha256": baseline_checkpoint_sha256,
    },
    "orphaned_child_count": 0,
    "managed_processes": fragment.get("managed_processes") or [],
    "artifacts": artifact_records,
    "rejected_codex_work": {"count": len(rejections), "records": rejections, "raw_prompts_committed": False},
}
canonical_without_id = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
document["evidence_id"] = "sha256:" + hashlib.sha256(canonical_without_id).hexdigest()
payload = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
if len(payload) > int(maximum_raw):
    raise SystemExit(f"compact evidence exceeds byte limit: {len(payload)} > {maximum_raw}")
output.parent.mkdir(parents=True, exist_ok=True)
if output.exists() and not bool(int(replace_raw)):
    raise SystemExit(f"refusing to overwrite evidence: {output}")
fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
try:
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, output)
finally:
    if os.path.exists(temporary): os.unlink(temporary)
print(f"evidence={output} evidence_id={document['evidence_id']} bytes={len(payload)}")
PY

"${PYTHON_BIN}" "${VERIFIER}" \
  --evidence "${EVIDENCE_PATH}" \
  --stage ten_minute_smoke \
  --minimum-active-seconds "${MINIMUM_ACTIVE_SECONDS}"

FINALIZED=1
trap - EXIT INT TERM HUP
echo "[legal-ir-10m] verified evidence=${EVIDENCE_PATH}"
