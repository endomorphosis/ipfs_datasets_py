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
ARGS_FILE="${LOG_DIR}/${RUN_ID}.args"
LIFECYCLE_FILE="${LOG_DIR}/${RUN_ID}.lifecycle.env"
LEANSTRAL_AUDIT_PID_FILE="${LOG_DIR}/${RUN_ID}.leanstral-audit.pid"
LEANSTRAL_AUDIT_LOG="${LOG_DIR}/${RUN_ID}.leanstral-audit.log"
RESTART_COUNT_FILE="${LOG_DIR}/${RUN_ID}.canonical-watchdog.restarts"

INTERVAL_SECONDS="${INTERVAL_SECONDS:-20}"
STALE_SECONDS="${STALE_SECONDS:-600}"
MAX_RESTARTS="${MAX_RESTARTS:-3}"

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
  local state_tmp="${STATE_JSON}.tmp.$$"
  cat > "${state_tmp}" <<EOF
{
  "run_id": "${RUN_ID}",
  "status": "${status}",
  "detail": "${detail}",
  "updated_at": "$(timestamp)"
}
EOF
  mv "${state_tmp}" "${STATE_JSON}"
}

read_lifecycle_field() {
  local field="$1"
  [[ -f "${LIFECYCLE_FILE}" ]] || return 0
  sed -n "s/^${field}=//p" "${LIFECYCLE_FILE}" | head -n 1
}

restart_count() {
  if [[ -f "${RESTART_COUNT_FILE}" ]]; then
    sed -n '1p' "${RESTART_COUNT_FILE}"
  else
    echo 0
  fi
}

start_leanstral_sidecar() {
  local parent_pid="$1"
  setsid bash scripts/ops/legal_ir/watch_leanstral_audit_worker.sh \
    "${RUN_ID}" "${parent_pid}" >> "${LEANSTRAL_AUDIT_LOG}" 2>&1 &
  echo "$!" > "${LEANSTRAL_AUDIT_PID_FILE}"
  log_line "leanstral_sidecar_started pid=$! parent_pid=${parent_pid}"
}

ensure_leanstral_sidecar() {
  local parent_pid="$1"
  local sidecar_pid=""
  [[ -f "${LEANSTRAL_AUDIT_PID_FILE}" ]] && sidecar_pid="$(sed -n '1p' "${LEANSTRAL_AUDIT_PID_FILE}")"
  if [[ -n "${sidecar_pid}" ]] && ps -p "${sidecar_pid}" >/dev/null 2>&1; then
    return 0
  fi
  log_line "leanstral_sidecar_missing action=restart"
  start_leanstral_sidecar "${parent_pid}"
}

restart_runner() {
  local count now deadline remaining index
  count="$(restart_count)"
  if ! [[ "${count}" =~ ^[0-9]+$ ]]; then count=0; fi
  if (( count >= MAX_RESTARTS )); then
    log_line "runner_restart_exhausted count=${count} max=${MAX_RESTARTS}"
    write_state "failed" "runner_restart_exhausted"
    exit 5
  fi
  [[ -s "${ARGS_FILE}" ]] || {
    log_line "runner_restart_failed reason=args_snapshot_missing"
    write_state "failed" "args_snapshot_missing"
    exit 6
  }
  now="$(date +%s)"
  deadline="$(read_lifecycle_field DEADLINE_EPOCH)"
  if [[ "${deadline}" =~ ^[0-9]+$ ]]; then
    remaining=$((deadline - now))
    if (( remaining <= 0 )); then
      write_state "completed" "deadline_reached"
      exit 0
    fi
  else
    remaining=28800
  fi
  mapfile -t runner_cmd < "${ARGS_FILE}"
  for ((index=0; index<${#runner_cmd[@]}; index++)); do
    if [[ "${runner_cmd[index]}" == "--duration-seconds" ]] && (( index + 1 < ${#runner_cmd[@]} )); then
      runner_cmd[index + 1]="${remaining}"
      break
    fi
  done
  count=$((count + 1))
  echo "${count}" > "${RESTART_COUNT_FILE}"
  log_line "runner_restarting attempt=${count} remaining_seconds=${remaining}"
  setsid "${runner_cmd[@]}" >> "${PIPELINE_LOG}" 2>&1 &
  echo "$!" > "${PID_FILE}"
  start_leanstral_sidecar "$!"
  write_state "running" "runner_restarted_${count}"
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
    log_line "runner_exited pid=${pid} action=restart"
    restart_runner
    pid="$(runner_pid)"
  fi

  ensure_leanstral_sidecar "${pid}"

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
