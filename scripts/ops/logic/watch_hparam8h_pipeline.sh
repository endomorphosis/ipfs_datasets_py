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
PIPELINE_LOG="${LOG_DIR}/${RUN_ID}.pipeline.log"
WATCHDOG_LOG="${LOG_DIR}/${RUN_ID}.watchdog.log"
STATE_JSON="${LOG_DIR}/${RUN_ID}.watchdog.state.json"

INTERVAL_SECONDS="${INTERVAL_SECONDS:-20}"
STALE_SECONDS="${STALE_SECONDS:-600}"
FINAL_VERIFY_MIN_CYCLES="${FINAL_VERIFY_MIN_CYCLES:-1}"
STOP_AFTER_FINAL_VERIFY="${STOP_AFTER_FINAL_VERIFY:-1}"
TRIAL_OVERRUN_SECONDS="${TRIAL_OVERRUN_SECONDS:-900}"
TRIAL_OVERRUN_MAX_CYCLES="${TRIAL_OVERRUN_MAX_CYCLES:-0}"
FINAL_OVERRUN_SECONDS="${FINAL_OVERRUN_SECONDS:-900}"
FINAL_OVERRUN_MAX_CYCLES="${FINAL_OVERRUN_MAX_CYCLES:-0}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  local msg="$1"
  echo "$(timestamp) ${msg}" | tee -a "${WATCHDOG_LOG}"
}

write_state() {
  local phase="$1"
  local status="$2"
  local detail="$3"
  local final_run_id="$4"
  local final_verified="$5"
  cat > "${STATE_JSON}" <<EOF
{
  "run_id": "${RUN_ID}",
  "phase": "${phase}",
  "status": "${status}",
  "detail": "${detail}",
  "final_run_id": "${final_run_id}",
  "final_verified": ${final_verified},
  "updated_at": "$(timestamp)"
}
EOF
}

extract_last_trial_id() {
  if [[ ! -f "${PIPELINE_LOG}" ]]; then
    echo ""
    return
  fi
  grep -Eo 'run_id=[^ ]+-trial-[0-9]+' "${PIPELINE_LOG}" | tail -n 1 | sed 's/^run_id=//' || true
}

extract_final_run_id() {
  if [[ ! -f "${PIPELINE_LOG}" ]]; then
    echo ""
    return
  fi
  grep -Eo 'starting final 8h run_id=[^ ]+' "${PIPELINE_LOG}" | tail -n 1 | sed 's/^starting final 8h run_id=//' || true
}

pipeline_pid() {
  ps -eo pid,args | awk -v run_id="${RUN_ID}" '
    $0 ~ "run_hparam_then_8h.sh "run_id"$" {print $1; exit}
  '
}

active_trial_pid_elapsed() {
  ps -eo pid,etimes,args | awk -v run_id="${RUN_ID}" '
    $0 ~ "uscode_modal_daemon_runner" && $0 ~ "--run-id "run_id"-trial-" {pid=$1; etimes=$2}
    END {if (pid != "") print pid " " etimes}
  '
}

active_final_autoencoder_pid_elapsed() {
  local final_run_id="$1"
  ps -eo pid,etimes,args | awk -v run_id="${final_run_id}-autoencoder" '
    $0 ~ "uscode_modal_daemon_runner" && $0 ~ "--run-id "run_id" " {pid=$1; etimes=$2}
    END {if (pid != "") print pid " " etimes}
  '
}

read_cycles_from_summary() {
  local summary_path="$1"
  python3 - "${summary_path}" <<'PY' 2>/dev/null || echo "0"
import json,sys
path=sys.argv[1]
with open(path, 'r', encoding='utf-8') as h:
    data=json.load(h)
print(int(data.get("cycles", 0) or 0))
PY
}

has_failure_signature() {
  [[ -f "${PIPELINE_LOG}" ]] || return 1
  if grep -Eq '\[pipeline\] failed|no successful hyperparameter trial found' "${PIPELINE_LOG}"; then
    return 0
  fi
  return 1
}

has_success_signature() {
  [[ -f "${PIPELINE_LOG}" ]] || return 1
  if grep -q '\[pipeline\] completed final 8h run_id=' "${PIPELINE_LOG}"; then
    return 0
  fi
  return 1
}

log_line "watchdog started run_id=${RUN_ID} interval=${INTERVAL_SECONDS}s stale=${STALE_SECONDS}s"
write_state "boot" "running" "watchdog_started" "" false

while true; do
  if [[ ! -f "${PIPELINE_LOG}" ]]; then
    log_line "waiting_for_pipeline_log path=${PIPELINE_LOG}"
    write_state "boot" "running" "waiting_for_pipeline_log" "" false
    sleep "${INTERVAL_SECONDS}"
    continue
  fi

  if has_success_signature; then
    log_line "pipeline_reported_success"
    write_state "completed" "succeeded" "pipeline_completed_final_8h" "" true
    exit 0
  fi

  final_run_id="$(extract_final_run_id)"
  if has_failure_signature && [[ -z "${final_run_id}" ]]; then
    log_line "problem_detected signature=failure_in_pipeline_log"
    write_state "unknown" "failed" "failure_signature_detected" "" false
    exit 3
  fi

  pid="$(pipeline_pid || true)"
  if [[ -z "${pid}" ]]; then
    log_line "problem_detected signature=pipeline_process_missing"
    write_state "unknown" "failed" "pipeline_process_missing_without_success" "" false
    exit 4
  fi

  if [[ -n "${final_run_id}" ]]; then
    final_summary="${LOG_DIR}/${final_run_id}-autoencoder.summary"
    if [[ -f "${final_summary}" ]]; then
      mtime_epoch="$(stat -c %Y "${final_summary}")"
      now_epoch="$(date +%s)"
      age_seconds=$((now_epoch - mtime_epoch))
      if (( age_seconds > STALE_SECONDS )); then
        log_line "problem_detected signature=stale_final_summary run_id=${final_run_id} age_seconds=${age_seconds} pid=${pid}"
        write_state "final_run" "failed" "stale_final_summary" "${final_run_id}" false
        exit 5
      fi
      cycles="$(read_cycles_from_summary "${final_summary}")"
      final_runtime="$(active_final_autoencoder_pid_elapsed "${final_run_id}" || true)"
      if [[ -n "${final_runtime}" ]]; then
        final_pid="${final_runtime%% *}"
        final_elapsed="${final_runtime##* }"
        if (( final_elapsed > FINAL_OVERRUN_SECONDS && cycles <= FINAL_OVERRUN_MAX_CYCLES )); then
          log_line "problem_detected signature=final_overrun_no_progress run_id=${final_run_id} final_pid=${final_pid} elapsed_seconds=${final_elapsed} cycles=${cycles}"
          write_state "final_run" "failed" "final_overrun_no_progress" "${final_run_id}" false
          exit 6
        fi
      fi
      if (( cycles >= FINAL_VERIFY_MIN_CYCLES )); then
        log_line "final_run_verified_working run_id=${final_run_id} cycles=${cycles} pid=${pid}"
        write_state "final_run" "running" "final_run_verified_working" "${final_run_id}" true
        if [[ "${STOP_AFTER_FINAL_VERIFY}" == "1" ]]; then
          log_line "verification_complete run_id=${final_run_id} cycles=${cycles}"
          write_state "completed" "succeeded" "final_run_verified_working" "${final_run_id}" true
          exit 0
        fi
      else
        log_line "final_run_started_waiting_for_cycles run_id=${final_run_id} cycles=${cycles} pid=${pid}"
        write_state "final_run" "running" "final_run_started_waiting_for_cycles" "${final_run_id}" false
      fi
    else
      mtime_epoch="$(stat -c %Y "${PIPELINE_LOG}")"
      now_epoch="$(date +%s)"
      age_seconds=$((now_epoch - mtime_epoch))
      if (( age_seconds > STALE_SECONDS )); then
        log_line "problem_detected signature=final_summary_missing_stale_pipeline run_id=${final_run_id} age_seconds=${age_seconds} pid=${pid}"
        write_state "final_run" "failed" "final_summary_missing_stale_pipeline" "${final_run_id}" false
        exit 5
      fi
      log_line "final_run_started_waiting_for_summary run_id=${final_run_id} pid=${pid}"
      write_state "final_run" "running" "final_run_started_waiting_for_summary" "${final_run_id}" false
    fi
  else
    mtime_epoch="$(stat -c %Y "${PIPELINE_LOG}")"
    now_epoch="$(date +%s)"
    age_seconds=$((now_epoch - mtime_epoch))
    if (( age_seconds > STALE_SECONDS )); then
      log_line "problem_detected signature=stale_pipeline_log age_seconds=${age_seconds} pid=${pid}"
      write_state "unknown" "failed" "stale_pipeline_log" "" false
      exit 5
    fi
    trial_id="$(extract_last_trial_id)"
    if [[ -n "${trial_id}" ]]; then
      trial_summary="${LOG_DIR}/${trial_id}.summary"
      if [[ -f "${trial_summary}" ]]; then
        trial_cycles="$(read_cycles_from_summary "${trial_summary}")"
        trial_runtime="$(active_trial_pid_elapsed || true)"
        if [[ -n "${trial_runtime}" ]]; then
          trial_pid="${trial_runtime%% *}"
          trial_elapsed="${trial_runtime##* }"
          if (( trial_elapsed > TRIAL_OVERRUN_SECONDS && trial_cycles <= TRIAL_OVERRUN_MAX_CYCLES )); then
            log_line "problem_detected signature=trial_overrun_no_progress trial_id=${trial_id} trial_pid=${trial_pid} elapsed_seconds=${trial_elapsed} cycles=${trial_cycles}"
            write_state "sweep" "failed" "trial_overrun_no_progress" "" false
            exit 6
          fi
        fi
        log_line "sweep_running trial_id=${trial_id} cycles=${trial_cycles} pid=${pid}"
        write_state "sweep" "running" "sweep_running" "" false
      else
        log_line "sweep_running trial_id=${trial_id} waiting_for_summary pid=${pid}"
        write_state "sweep" "running" "sweep_waiting_for_summary" "" false
      fi
    else
      log_line "sweep_running waiting_for_first_trial pid=${pid}"
      write_state "sweep" "running" "sweep_waiting_for_first_trial" "" false
    fi
  fi

  sleep "${INTERVAL_SECONDS}"
done
