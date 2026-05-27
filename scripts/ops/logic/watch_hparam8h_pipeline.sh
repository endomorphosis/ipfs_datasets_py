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
PIPELINE_LOG_PRIMARY="${LOG_DIR}/${RUN_ID}.pipeline.log"
PIPELINE_LOG="${PIPELINE_LOG_PRIMARY}"
PIPELINE_LOG_FALLBACK="${LOG_DIR}/${RUN_ID}.launcher.log"
WATCHDOG_LOG="${LOG_DIR}/${RUN_ID}.watchdog.log"
STATE_JSON="${LOG_DIR}/${RUN_ID}.watchdog.state.json"

INTERVAL_SECONDS="${INTERVAL_SECONDS:-20}"
STALE_SECONDS="${STALE_SECONDS:-600}"
FINAL_VERIFY_MIN_CYCLES="${FINAL_VERIFY_MIN_CYCLES:-1}"
STOP_AFTER_FINAL_VERIFY="${STOP_AFTER_FINAL_VERIFY:-1}"
TRIAL_OVERRUN_SECONDS="${TRIAL_OVERRUN_SECONDS:-900}"
TRIAL_OVERRUN_MAX_CYCLES="${TRIAL_OVERRUN_MAX_CYCLES:-0}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  local msg="$1"
  echo "$(timestamp) ${msg}" | tee -a "${WATCHDOG_LOG}"
}

resolve_pipeline_log() {
  if [[ -f "${PIPELINE_LOG_PRIMARY}" ]]; then
    echo "${PIPELINE_LOG_PRIMARY}"
  elif [[ -f "${PIPELINE_LOG_FALLBACK}" ]]; then
    echo "${PIPELINE_LOG_FALLBACK}"
  else
    echo "${PIPELINE_LOG_PRIMARY}"
  fi
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

extract_trial_ids() {
  if [[ ! -f "${PIPELINE_LOG}" ]]; then
    return
  fi
  grep -Eo 'run_id=[^ ]+-trial-[0-9]+' "${PIPELINE_LOG}" | sed 's/^run_id=//' | sort -u || true
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
    $0 ~ "uscode_modal_daemon_runner" && $0 ~ "--loop-role autoencoder" && $0 ~ "--run-id "run_id"-trial-" {pid=$1; etimes=$2}
    END {if (pid != "") print pid " " etimes}
  '
}

active_trial_pid_elapsed_rows() {
  ps -eo pid,etimes,args | awk -v run_id="${RUN_ID}" '
    $0 ~ "uscode_modal_daemon_runner" && $0 ~ "--loop-role autoencoder" && $0 ~ "--run-id "run_id"-trial-" {
      trial_run_id = ""
      for (idx = 3; idx <= NF; idx++) {
        if ($idx == "--run-id" && (idx + 1) <= NF) {
          trial_run_id = $(idx + 1)
          break
        }
      }
      if (trial_run_id != "") {
        print trial_run_id " " $1 " " $2
      }
    }
  '
}

trial_summary_path() {
  local trial_id="$1"
  if [[ -f "${LOG_DIR}/${trial_id}.summary" ]]; then
    echo "${LOG_DIR}/${trial_id}.summary"
  elif [[ -f "${LOG_DIR}/${trial_id}-autoencoder.summary" ]]; then
    echo "${LOG_DIR}/${trial_id}-autoencoder.summary"
  else
    echo "${LOG_DIR}/${trial_id}.summary"
  fi
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
  PIPELINE_LOG="$(resolve_pipeline_log)"
  if [[ ! -f "${PIPELINE_LOG}" ]]; then
    log_line "waiting_for_pipeline_log path=${PIPELINE_LOG} fallback=${PIPELINE_LOG_FALLBACK}"
    write_state "boot" "running" "waiting_for_pipeline_log" "" false
    sleep "${INTERVAL_SECONDS}"
    continue
  fi

  if has_success_signature; then
    log_line "pipeline_reported_success"
    write_state "completed" "succeeded" "pipeline_completed_final_8h" "" true
    exit 0
  fi

  if has_failure_signature; then
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

  mtime_epoch="$(stat -c %Y "${PIPELINE_LOG}")"
  now_epoch="$(date +%s)"
  pipeline_log_age_seconds=$((now_epoch - mtime_epoch))

  final_run_id="$(extract_final_run_id)"
  if [[ -n "${final_run_id}" ]]; then
    final_summary="${LOG_DIR}/${final_run_id}-autoencoder.summary"
    if [[ -f "${final_summary}" ]]; then
      cycles="$(read_cycles_from_summary "${final_summary}")"
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
      log_line "final_run_started_waiting_for_summary run_id=${final_run_id} pid=${pid}"
      write_state "final_run" "running" "final_run_started_waiting_for_summary" "${final_run_id}" false
    fi
  else
    active_rows="$(active_trial_pid_elapsed_rows || true)"
    if [[ -n "${active_rows}" ]]; then
      active_count=0
      status_parts=()
      while read -r trial_run_id trial_pid trial_elapsed; do
        [[ -n "${trial_run_id:-}" ]] || continue
        active_count=$((active_count + 1))
        trial_summary="$(trial_summary_path "${trial_run_id}")"
        trial_cycles=0
        if [[ -f "${trial_summary}" ]]; then
          trial_cycles="$(read_cycles_from_summary "${trial_summary}")"
        fi
        if (( trial_elapsed > TRIAL_OVERRUN_SECONDS && trial_cycles <= TRIAL_OVERRUN_MAX_CYCLES )); then
          log_line "problem_detected signature=trial_overrun_no_progress trial_id=${trial_run_id} trial_pid=${trial_pid} elapsed_seconds=${trial_elapsed} cycles=${trial_cycles}"
          write_state "sweep" "failed" "trial_overrun_no_progress" "" false
          exit 6
        fi
        status_parts+=("${trial_run_id}:cycles=${trial_cycles}:elapsed=${trial_elapsed}")
      done <<< "${active_rows}"
        log_line "sweep_running active_trials=${active_count} statuses=${status_parts[*]} pid=${pid} pipeline_log_age_seconds=${pipeline_log_age_seconds}"
      write_state "sweep" "running" "parallel_sweep_running" "" false
    else
      trial_id="$(extract_last_trial_id)"
      if [[ -n "${trial_id}" ]]; then
        trial_summary="$(trial_summary_path "${trial_id}")"
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
          log_line "sweep_running trial_id=${trial_id} cycles=${trial_cycles} pid=${pid} pipeline_log_age_seconds=${pipeline_log_age_seconds}"
          write_state "sweep" "running" "sweep_running" "" false
        else
          trial_count="$(extract_trial_ids | wc -l | tr -d ' ')"
          log_line "sweep_running trial_id=${trial_id} known_trials=${trial_count} waiting_for_summary pid=${pid} pipeline_log_age_seconds=${pipeline_log_age_seconds}"
          write_state "sweep" "running" "sweep_waiting_for_summary" "" false
        fi
      else
        if (( pipeline_log_age_seconds > STALE_SECONDS )); then
          log_line "problem_detected signature=stale_pipeline_log age_seconds=${pipeline_log_age_seconds} pid=${pid}"
          write_state "unknown" "failed" "stale_pipeline_log" "" false
          exit 5
        fi
        log_line "sweep_running waiting_for_first_trial pid=${pid}"
        write_state "sweep" "running" "sweep_waiting_for_first_trial" "" false
      fi
    fi
  fi

  sleep "${INTERVAL_SECONDS}"
done
