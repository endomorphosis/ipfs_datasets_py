#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

if [[ "${1:-}" == "" ]]; then
  echo "usage: $0 <run_id>"
  exit 2
fi

RUN_ID="$1"
LOG_DIR="${ROOT_DIR}/workspace/test-logs"
PID_FILE="${LOG_DIR}/${RUN_ID}.pid"
PIPELINE_LOG="${LOG_DIR}/${RUN_ID}.pipeline.log"
STATE_JSON="${LOG_DIR}/${RUN_ID}.canonical-watchdog.state.json"
WATCHDOG_LOG="${LOG_DIR}/${RUN_ID}.canonical-watchdog.log"

INTERVAL_SECONDS="${INTERVAL_SECONDS:-20}"
STALE_SECONDS="${STALE_SECONDS:-600}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  local msg="$1"
  echo "$(timestamp) ${msg}" | tee -a "${WATCHDOG_LOG}"
}

write_state() {
  local status="$1"
  local detail="$2"
  cat > "${STATE_JSON}" <<EOF
{
  "run_id": "${RUN_ID}",
  "status": "${status}",
  "detail": "${detail}",
  "updated_at": "$(timestamp)"
}
EOF
}

runner_pid() {
  if [[ -f "${PID_FILE}" ]]; then
    cat "${PID_FILE}" 2>/dev/null || true
  fi
}

latest_activity_epoch() {
  local latest=0
  local path
  shopt -s nullglob
  for path in \
    "${PIPELINE_LOG}" \
    "${LOG_DIR}/${RUN_ID}.summary" \
    "${LOG_DIR}/${RUN_ID}.jsonl" \
    "${LOG_DIR}/${RUN_ID}"-*.summary \
    "${LOG_DIR}/${RUN_ID}"-*.jsonl; do
    [[ -f "${path}" ]] || continue
    local mtime_epoch
    mtime_epoch="$(stat -c %Y "${path}" 2>/dev/null || echo 0)"
    if (( mtime_epoch > latest )); then
      latest="${mtime_epoch}"
    fi
  done
  shopt -u nullglob
  echo "${latest}"
}

log_line "watchdog_started run_id=${RUN_ID} interval=${INTERVAL_SECONDS}s stale=${STALE_SECONDS}s"
write_state "running" "watchdog_started"

while true; do
  pid="$(runner_pid)"
  if [[ -z "${pid}" ]]; then
    log_line "runner_missing reason=pid_file_missing_or_empty"
    write_state "failed" "pid_file_missing_or_empty"
    exit 3
  fi

  if ! ps -p "${pid}" >/dev/null 2>&1; then
    log_line "runner_exited pid=${pid}"
    write_state "failed" "runner_exited"
    exit 4
  fi

  mtime_epoch="$(latest_activity_epoch)"
  if (( mtime_epoch > 0 )); then
    now_epoch="$(date +%s)"
    age_seconds=$((now_epoch - mtime_epoch))
    if (( age_seconds > STALE_SECONDS )); then
      log_line "runner_alive_artifacts_stale pid=${pid} age_seconds=${age_seconds}"
      write_state "running" "runner_alive_artifacts_stale"
    else
      write_state "running" "runner_alive"
    fi
  else
    write_state "running" "waiting_for_pipeline_log"
  fi

  sleep "${INTERVAL_SECONDS}"
done
