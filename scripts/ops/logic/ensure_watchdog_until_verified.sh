#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

if [[ "${1:-}" == "" ]]; then
  echo "usage: $0 <base_run_id>"
  exit 2
fi

RUN_ID="$1"
LOG_DIR="${ROOT_DIR}/workspace/test-logs"
WATCHDOG_SCRIPT="${ROOT_DIR}/scripts/ops/logic/watch_hparam8h_pipeline.sh"
STATE_JSON="${LOG_DIR}/${RUN_ID}.watchdog.state.json"
SUPERVISOR_LOG="${LOG_DIR}/${RUN_ID}.watchdog-supervisor.log"

INTERVAL_SECONDS="${INTERVAL_SECONDS:-30}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  local msg="$1"
  echo "$(timestamp) ${msg}" | tee -a "${SUPERVISOR_LOG}"
}

watchdog_pid() {
  ps -eo pid,args | awk -v run_id="${RUN_ID}" '
    $0 ~ "watch_hparam8h_pipeline.sh "run_id"$" {print $1; exit}
  '
}

state_field() {
  local field="$1"
  if [[ ! -f "${STATE_JSON}" ]]; then
    echo ""
    return
  fi
  python3 - "${STATE_JSON}" "${field}" <<'PY' 2>/dev/null || true
import json, sys
path, field = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as h:
    data = json.load(h)
value = data.get(field, "")
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

log_line "supervisor_started run_id=${RUN_ID} interval=${INTERVAL_SECONDS}s"

while true; do
  pid="$(watchdog_pid || true)"
  if [[ -z "${pid}" ]]; then
    log_line "watchdog_missing action=restart"
    setsid -f "${WATCHDOG_SCRIPT}" "${RUN_ID}" >/dev/null 2>&1 || true
    sleep 1
    pid="$(watchdog_pid || true)"
    if [[ -n "${pid}" ]]; then
      log_line "watchdog_restarted pid=${pid}"
    else
      log_line "watchdog_restart_failed"
    fi
  fi

  status="$(state_field "status")"
  phase="$(state_field "phase")"
  final_verified="$(state_field "final_verified")"
  detail="$(state_field "detail")"

  if [[ "${final_verified}" == "true" ]]; then
    log_line "verification_complete phase=${phase} detail=${detail}"
    exit 0
  fi

  if [[ "${status}" == "failed" ]]; then
    log_line "watchdog_reported_failure phase=${phase} detail=${detail}"
    exit 3
  fi

  sleep "${INTERVAL_SECONDS}"
done
