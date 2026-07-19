#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LOG_DIR="${ROOT_DIR}/workspace/test-logs"

RUN_ID="${1:-}"
if [[ -z "${RUN_ID}" ]]; then
  latest_args="$(ls -1t "${LOG_DIR}"/legal-ir-canonical-*.args 2>/dev/null | head -n 1 || true)"
  if [[ -z "${latest_args}" ]]; then
    echo "no canonical run artifacts found under ${LOG_DIR}"
    exit 1
  fi
  RUN_ID="$(basename "${latest_args}" .args)"
fi

PID_FILE="${LOG_DIR}/${RUN_ID}.pid"
WATCHDOG_PID_FILE="${LOG_DIR}/${RUN_ID}.watchdog-supervisor.pid"
LEANSTRAL_AUDIT_PID_FILE="${LOG_DIR}/${RUN_ID}.leanstral-audit.pid"
ARGS_FILE="${LOG_DIR}/${RUN_ID}.args"
STATE_FILE="${LOG_DIR}/${RUN_ID}.canonical-watchdog.state.json"
PIPELINE_LOG="${LOG_DIR}/${RUN_ID}.pipeline.log"
WATCHDOG_LOG="${LOG_DIR}/${RUN_ID}.canonical-watchdog.launch.log"
LEANSTRAL_AUDIT_LOG="${LOG_DIR}/${RUN_ID}.leanstral-audit.log"
LEANSTRAL_INPUT_CURRENT="${LOG_DIR}/${RUN_ID}.canonical-disagreements.jsonl"
LEANSTRAL_INPUT_LEGACY="${LOG_DIR}/${RUN_ID}-autoencoder.canonical-disagreements.jsonl"
LEANSTRAL_REFERENCE_CURRENT="${LOG_DIR}/${RUN_ID}.reference-examples.json"
LEANSTRAL_REFERENCE_LEGACY="${LOG_DIR}/${RUN_ID}-autoencoder.reference-examples.json"
LEANSTRAL_WORK_DIR="${ROOT_DIR}/workspace/leanstral-audit-worker"
LEANSTRAL_RULE_GAP_REPORT="${LEANSTRAL_RULE_GAP_REPORT_PATH:-${LEANSTRAL_WORK_DIR}/canonical.rule-gaps.json}"

echo "run_id=${RUN_ID}"
echo "log_dir=${LOG_DIR}"

if [[ -f "${ARGS_FILE}" ]]; then
  echo "args_file=${ARGS_FILE}"
else
  echo "args_file=missing"
fi

if [[ -f "${PID_FILE}" ]]; then
  main_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  echo "main_pid=${main_pid}"
  if [[ -n "${main_pid}" ]] && ps -p "${main_pid}" >/dev/null 2>&1; then
    echo "main_status=alive"
    ps -fp "${main_pid}" | sed -n '2p'
  else
    echo "main_status=dead"
  fi
else
  echo "main_pid=missing"
fi

if [[ -f "${WATCHDOG_PID_FILE}" ]]; then
  watchdog_pid="$(cat "${WATCHDOG_PID_FILE}" 2>/dev/null || true)"
  echo "watchdog_pid=${watchdog_pid}"
  if [[ -n "${watchdog_pid}" ]] && ps -p "${watchdog_pid}" >/dev/null 2>&1; then
    echo "watchdog_status=alive"
    ps -fp "${watchdog_pid}" | sed -n '2p'
  else
    echo "watchdog_status=dead"
  fi
else
  echo "watchdog_pid=missing"
fi

if [[ -f "${LEANSTRAL_AUDIT_PID_FILE}" ]]; then
  leanstral_audit_pid="$(cat "${LEANSTRAL_AUDIT_PID_FILE}" 2>/dev/null || true)"
  echo "leanstral_audit_pid=${leanstral_audit_pid}"
  if [[ -n "${leanstral_audit_pid}" ]] && ps -p "${leanstral_audit_pid}" >/dev/null 2>&1; then
    echo "leanstral_audit_status=alive"
    ps -fp "${leanstral_audit_pid}" | sed -n '2p'
  else
    echo "leanstral_audit_status=dead"
  fi
else
  echo "leanstral_audit_pid=missing"
fi

for path in \
  "${LEANSTRAL_INPUT_CURRENT}" \
  "${LEANSTRAL_INPUT_LEGACY}" \
  "${LEANSTRAL_REFERENCE_CURRENT}" \
  "${LEANSTRAL_REFERENCE_LEGACY}" \
  "${LEANSTRAL_RULE_GAP_REPORT}"; do
  if [[ -f "${path}" ]]; then
    echo "artifact=$(basename "${path}") bytes=$(stat -c %s "${path}") mtime=$(date -u -d "@$(stat -c %Y "${path}")" +"%Y-%m-%dT%H:%M:%SZ") path=${path}"
  else
    echo "artifact=$(basename "${path}") missing path=${path}"
  fi
done

if [[ -f "${STATE_FILE}" ]]; then
  echo "watchdog_state_file=${STATE_FILE}"
  cat "${STATE_FILE}"
else
  echo "watchdog_state_file=missing"
fi

if [[ -f "${PIPELINE_LOG}" ]]; then
  echo "pipeline_log_tail=${PIPELINE_LOG}"
  tail -n 5 "${PIPELINE_LOG}" || true
else
  echo "pipeline_log_tail=missing"
fi

if [[ -f "${WATCHDOG_LOG}" ]]; then
  echo "watchdog_log_tail=${WATCHDOG_LOG}"
  tail -n 5 "${WATCHDOG_LOG}" || true
else
  echo "watchdog_log_tail=missing"
fi

if [[ -f "${LEANSTRAL_AUDIT_LOG}" ]]; then
  echo "leanstral_audit_log_tail=${LEANSTRAL_AUDIT_LOG}"
  tail -n 8 "${LEANSTRAL_AUDIT_LOG}" || true
else
  echo "leanstral_audit_log_tail=missing"
fi
