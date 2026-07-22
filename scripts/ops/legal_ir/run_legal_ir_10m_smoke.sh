#!/usr/bin/env bash
# Execute PORTAL-LIR-HAMMER-117 and seal its compact evidence receipt.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

DEFAULT_PYTHON="${ROOT_DIR}/.venv-cuda/bin/python"
if [[ ! -x "${DEFAULT_PYTHON}" ]]; then
  COMMON_GIT_DIR="$(git -C "${ROOT_DIR}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "${COMMON_GIT_DIR}" ]]; then
    DEFAULT_PYTHON="$(dirname "${COMMON_GIT_DIR}")/.venv-cuda/bin/python"
  fi
fi
PYTHON_BIN="${PYTHON_BIN:-${DEFAULT_PYTHON}}"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || command -v python)"
CANONICAL_RUNNER="${ROOT_DIR}/scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh"
VERIFIER="${ROOT_DIR}/scripts/ops/legal_ir/verify_legal_ir_run_evidence.py"
DEFAULT_EVIDENCE="${ROOT_DIR}/docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json"
RUN_ID="legal-ir-10m-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_PATH="${DEFAULT_EVIDENCE}"
RUN_ROOT=""
RESUME_ARGS=()
DRY_RUN=0
VERIFY_ONLY=0
ACTIVE_SECONDS=600
MAX_WALL_SECONDS=2400
HEARTBEAT_SECONDS=5
STALL_SECONDS=360

usage() {
  cat <<'EOF'
Usage: run_legal_ir_10m_smoke.sh [OPTIONS]

Executes the canonical integrated pipeline for at least 600 active seconds,
under an external heartbeat watchdog, then seals and independently verifies a
compact content-addressed receipt. The default command is always a real run.

Options:
  --run-id ID                 Fresh run lineage ID
  --evidence PATH             Compact receipt destination
  --run-root PATH             Directory for bulky transient run artifacts
  --resume-from-run-id ID     Import a prior run's generalizable state
  --resume-from-state PATH    Import an explicit state checkpoint
  --max-wall-seconds N        Watchdog wall limit (minimum 900; default 2400)
  --verify-only               Verify an already-sealed --evidence receipt
  --dry-run                   Print the immutable contract; never emit evidence
  -h, --help                  Show this help
EOF
}

require_value() {
  if (( $# < 2 )) || [[ -z "${2:-}" ]]; then
    echo "missing value for $1" >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) require_value "$@"; RUN_ID="$2"; shift 2 ;;
    --evidence) require_value "$@"; EVIDENCE_PATH="$2"; shift 2 ;;
    --run-root) require_value "$@"; RUN_ROOT="$2"; shift 2 ;;
    --resume-from-run-id) require_value "$@"; RESUME_ARGS=(--resume-from-run-id "$2"); shift 2 ;;
    --resume-from-state) require_value "$@"; RESUME_ARGS=(--resume-from-state "$2"); shift 2 ;;
    --max-wall-seconds) require_value "$@"; MAX_WALL_SECONDS="$2"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "${RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]]; then
  echo "invalid run ID" >&2
  exit 2
fi
if [[ ! "${MAX_WALL_SECONDS}" =~ ^[0-9]+$ ]] || (( MAX_WALL_SECONDS < 900 )); then
  echo "--max-wall-seconds must be an integer of at least 900" >&2
  exit 2
fi
if [[ "${DURATION_SECONDS:-600}" != "600" || "${ACTIVE_DURATION_SECONDS:-600}" != "600" ]]; then
  echo "the executed smoke minimum is immutable at 600 active seconds" >&2
  exit 2
fi

if (( VERIFY_ONLY )); then
  exec "${PYTHON_BIN}" "${VERIFIER}" --evidence "${EVIDENCE_PATH}" \
    --stage ten_minute_smoke --minimum-active-seconds "${ACTIVE_SECONDS}"
fi

if (( DRY_RUN )); then
  echo "task_id=PORTAL-LIR-HAMMER-117"
  echo "execution=false"
  echo "promotable_evidence=false"
  echo "stage=ten_minute_smoke"
  echo "minimum_active_seconds=${ACTIVE_SECONDS}"
  echo "minimum_warm_cycles=2"
  echo "max_wall_seconds=${MAX_WALL_SECONDS}"
  echo "watchdog_heartbeat_seconds=${HEARTBEAT_SECONDS}"
  echo "watchdog_stall_seconds=${STALL_SECONDS}"
  echo "cpu_fallback_allowed=false"
  echo "canonical_runner=${CANONICAL_RUNNER}"
  echo "evidence=${EVIDENCE_PATH}"
  PYTHON_BIN="${PYTHON_BIN}" DURATION_SECONDS=600 MAX_CYCLES=0 \
    PAIRED_GRACE_SECONDS=240 PAIRED_CODEX_QUEUE_GRACE_SECONDS=0 \
    "${CANONICAL_RUNNER}" --run-id "${RUN_ID}" --dry-run
  exit 0
fi

if [[ -e "${EVIDENCE_PATH}" ]]; then
  echo "refusing to overwrite evidence: ${EVIDENCE_PATH}" >&2
  exit 2
fi
if [[ "${AUTOENCODER_DEVICE:-cuda}" != cuda* ]]; then
  echo "AUTOENCODER_DEVICE must be CUDA" >&2
  exit 2
fi
for required in "${CANONICAL_RUNNER}" "${VERIFIER}"; do
  [[ -f "${required}" ]] || { echo "required executable missing: ${required}" >&2; exit 2; }
done

RUN_ROOT="${RUN_ROOT:-${ROOT_DIR}/workspace/legal-ir-10m-smoke/${RUN_ID}}"
if [[ -e "${RUN_ROOT}" ]]; then
  echo "refusing to reuse run artifact directory: ${RUN_ROOT}" >&2
  exit 2
fi
mkdir -p "${RUN_ROOT}"
RAW_EVIDENCE="${RUN_ROOT}/canonical-smoke-evidence.json"
WATCHDOG_RECEIPT="${RUN_ROOT}/watchdog.json"
RUN_LOG="${RUN_ROOT}/runner.log"
START_EPOCH="$(date +%s)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HEARTBEATS=0
MAX_HEARTBEAT_GAP=0
LAST_HEARTBEAT_EPOCH="${START_EPOCH}"
LAST_PROGRESS_EPOCH="${START_EPOCH}"
PROGRESS_HEARTBEATS=0
MAX_PROGRESS_GAP=0
RUNNER_PID=""

terminate_group() {
  local signal_name="$1"
  if [[ -n "${RUNNER_PID}" ]] && kill -0 "${RUNNER_PID}" 2>/dev/null; then
    kill -s "${signal_name}" -- "-${RUNNER_PID}" 2>/dev/null || kill -s "${signal_name}" "${RUNNER_PID}" 2>/dev/null || true
  fi
}
on_signal() {
  terminate_group TERM
  local waited=0
  while [[ -n "${RUNNER_PID}" ]] && kill -0 "${RUNNER_PID}" 2>/dev/null && (( waited < 10 )); do
    sleep 1
    waited=$((waited + 1))
  done
  terminate_group KILL
  if [[ -n "${RUNNER_PID}" ]]; then
    wait "${RUNNER_PID}" 2>/dev/null || true
  fi
  exit 130
}
trap on_signal INT TERM HUP

# The canonical launcher owns service semantics and its internal child cleanup.
# setsid gives the outer watchdog a bounded process group for abnormal shutdown.
setsid --wait env \
  PYTHON_BIN="${PYTHON_BIN}" \
  DURATION_SECONDS=600 \
  MAX_CYCLES=0 \
  PAIRED_GRACE_SECONDS=240 \
  PAIRED_CODEX_QUEUE_GRACE_SECONDS=0 \
  AUTOENCODER_DEVICE=cuda \
  LEANSTRAL_AUDIT_REQUIRE_CUDA=1 \
  LEANSTRAL_AUDIT_PERSIST_SERVICE=1 \
  LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR=cuda \
  EVIDENCE_OUTPUT="${RAW_EVIDENCE}" \
  "${CANONICAL_RUNNER}" --run-id "${RUN_ID}" --evidence-output "${RAW_EVIDENCE}" \
  "${RESUME_ARGS[@]}" >"${RUN_LOG}" 2>&1 &
RUNNER_PID=$!

watchdog_status="healthy"
while kill -0 "${RUNNER_PID}" 2>/dev/null; do
  sleep "${HEARTBEAT_SECONDS}"
  now_epoch="$(date +%s)"
  HEARTBEATS=$((HEARTBEATS + 1))
  gap=$((now_epoch - LAST_HEARTBEAT_EPOCH))
  (( gap > MAX_HEARTBEAT_GAP )) && MAX_HEARTBEAT_GAP="${gap}"
  LAST_HEARTBEAT_EPOCH="${now_epoch}"
  newest_progress="$(
    find "${RUN_LOG}" "${ROOT_DIR}/workspace" \
      -type f \( -path "*${RUN_ID}*" -o -path "${RUN_LOG}" \) \
      -printf '%T@\n' 2>/dev/null | sort -nr | head -1 || true
  )"
  newest_progress="${newest_progress%%.*}"
  if [[ "${newest_progress:-}" =~ ^[0-9]+$ ]] && (( newest_progress > LAST_PROGRESS_EPOCH )); then
    progress_gap=$((newest_progress - LAST_PROGRESS_EPOCH))
    (( progress_gap > MAX_PROGRESS_GAP )) && MAX_PROGRESS_GAP="${progress_gap}"
    LAST_PROGRESS_EPOCH="${newest_progress}"
    PROGRESS_HEARTBEATS=$((PROGRESS_HEARTBEATS + 1))
  fi
  current_progress_gap=$((now_epoch - LAST_PROGRESS_EPOCH))
  (( current_progress_gap > MAX_PROGRESS_GAP )) && MAX_PROGRESS_GAP="${current_progress_gap}"
  if (( current_progress_gap > STALL_SECONDS )); then
    watchdog_status="progress_stalled"
    terminate_group TERM
    sleep 5
    terminate_group KILL
    break
  fi
  if (( now_epoch - START_EPOCH > MAX_WALL_SECONDS )); then
    watchdog_status="max_wall_exceeded"
    terminate_group TERM
    sleep 5
    terminate_group KILL
    break
  fi
done

set +e
wait "${RUNNER_PID}"
runner_status=$?
set -e
RUNNER_PID=""
trap - INT TERM HUP
ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
END_EPOCH="$(date +%s)"

"${PYTHON_BIN}" - "${WATCHDOG_RECEIPT}" "${RUN_ID}" "${STARTED_AT}" "${ENDED_AT}" \
  "$((END_EPOCH - START_EPOCH))" "${HEARTBEATS}" "${MAX_HEARTBEAT_GAP}" \
  "${PROGRESS_HEARTBEATS}" "${MAX_PROGRESS_GAP}" "${runner_status}" "${watchdog_status}" <<'PY'
import json, os, sys, tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": "legal-ir-execution-watchdog-v1",
    "run_id": sys.argv[2],
    "started_at": sys.argv[3],
    "ended_at": sys.argv[4],
    "wall_seconds": int(sys.argv[5]),
    "heartbeat_count": int(sys.argv[6]),
    "max_heartbeat_gap_seconds": int(sys.argv[7]),
    "progress_heartbeat_count": int(sys.argv[8]),
    "max_progress_gap_seconds": int(sys.argv[9]),
    "runner_exit_code": int(sys.argv[10]),
    "status": (
        "exited_cleanly"
        if int(sys.argv[10]) == 0 and sys.argv[11] == "healthy"
        else (sys.argv[11] if sys.argv[11] != "healthy" else "runner_failed")
    ),
}
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

if (( runner_status != 0 )); then
  echo "canonical smoke rejected (exit ${runner_status}); artifacts preserved at ${RUN_ROOT}" >&2
  tail -80 "${RUN_LOG}" >&2 || true
  exit "${runner_status}"
fi

"${PYTHON_BIN}" "${VERIFIER}" --seal-canonical-fragment "${RAW_EVIDENCE}" \
  --watchdog-receipt "${WATCHDOG_RECEIPT}" --evidence "${EVIDENCE_PATH}" \
  --stage ten_minute_smoke --minimum-active-seconds "${ACTIVE_SECONDS}"
"${PYTHON_BIN}" "${VERIFIER}" --evidence "${EVIDENCE_PATH}" \
  --stage ten_minute_smoke --minimum-active-seconds "${ACTIVE_SECONDS}" --verify-available-artifacts
echo "legal_ir_10m_smoke_completed run_id=${RUN_ID} evidence=${EVIDENCE_PATH} artifacts=${RUN_ROOT}"
