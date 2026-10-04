#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

BASE_RUN_ID="${1:-legal-ir-daemon-$(date -u +%Y%m%dT%H%M%SZ)}"
LOG_DIR="${ROOT_DIR}/workspace/test-logs"
PIPELINE_LOG="${LOG_DIR}/${BASE_RUN_ID}.pipeline.log"
WATCHDOG_LOG="${LOG_DIR}/${BASE_RUN_ID}.watchdog.launch.log"
PID_FILE="${LOG_DIR}/${BASE_RUN_ID}.pid"
WATCHDOG_PID_FILE="${LOG_DIR}/${BASE_RUN_ID}.watchdog.pid"

STOP_EXISTING="${STOP_EXISTING:-1}"
CLEAN_STALE_WORKTREES="${CLEAN_STALE_WORKTREES:-1}"
START_WATCHDOG="${START_WATCHDOG:-1}"

mkdir -p "${LOG_DIR}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  echo "$(timestamp) $*"
}

matching_process_groups() {
  local self_pgid
  self_pgid="$(ps -o pgid= "$$" | tr -d '[:space:]')"
  ps -eo pid,pgid,args | awk -v self_pgid="${self_pgid}" '
    $2 == self_pgid {
      next
    }
    /run_hparam_then_8h\.sh legal-ir-daemon-/ ||
    (/uscode_modal_daemon_runner/ && /--run-id legal-ir-daemon-/) ||
    /\/workspace\/codex-work\/legal-ir-daemon-/ ||
    /watch_hparam8h_pipeline\.sh legal-ir-daemon-/ ||
    /ensure_watchdog_until_verified\.sh legal-ir-daemon-/ {
      print $2
    }
  ' | sort -u
}

stop_existing_legal_ir_runs() {
  local groups
  groups="$(matching_process_groups || true)"
  if [[ -z "${groups}" ]]; then
    log_line "no_existing_legal_ir_runs"
    return
  fi
  while read -r pgid; do
    [[ -n "${pgid}" ]] || continue
    log_line "stopping_existing_process_group pgid=${pgid}"
    kill -TERM "-${pgid}" 2>/dev/null || true
  done <<< "${groups}"
  sleep "${STOP_GRACE_SECONDS:-10}"
  groups="$(matching_process_groups || true)"
  while read -r pgid; do
    [[ -n "${pgid}" ]] || continue
    log_line "killing_stubborn_process_group pgid=${pgid}"
    kill -KILL "-${pgid}" 2>/dev/null || true
  done <<< "${groups}"
}

cleanup_stale_legal_ir_worktrees() {
  git worktree list --porcelain | awk '
    /^worktree / {
      path = substr($0, 10)
      if (path ~ /\/workspace\/codex-work\/legal-ir-daemon-/) {
        print path
      }
    }
  ' | while read -r path; do
    [[ -n "${path}" ]] || continue
    log_line "removing_stale_codex_worktree path=${path}"
    git worktree remove --force "${path}" >/dev/null 2>&1 || rm -rf "${path}"
  done
  git worktree prune >/dev/null 2>&1 || true
}

if [[ "${STOP_EXISTING}" == "1" ]]; then
  stop_existing_legal_ir_runs
fi

if [[ "${CLEAN_STALE_WORKTREES}" == "1" ]]; then
  cleanup_stale_legal_ir_worktrees
fi

export CODEX_MODEL="${CODEX_MODEL:-${IPFS_DATASETS_PY_CODEX_MODEL:-gpt-5.5}}"
if [[ -z "${AUTOENCODER_DEVICE:-}" ]]; then
  if [[ -x "${ROOT_DIR}/.venv-cuda/bin/python" ]] && \
    "${ROOT_DIR}/.venv-cuda/bin/python" -c \
      'import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)' \
      >/dev/null 2>&1; then
    export AUTOENCODER_DEVICE="cuda"
  else
    export AUTOENCODER_DEVICE="auto"
  fi
fi
export TRIAL_SECONDS="${TRIAL_SECONDS:-120}"
export TRIAL_COUNT="${TRIAL_COUNT:-2}"
export FINAL_SECONDS="${FINAL_SECONDS:-28800}"
export FINAL_PROJECTION_EPOCHS="${FINAL_PROJECTION_EPOCHS:-1}"
export BRIDGE_LOSS_ADAPTERS="${BRIDGE_LOSS_ADAPTERS:-none}"
export BRIDGE_EVALUATE_PROVERS="${BRIDGE_EVALUATE_PROVERS:-false}"
export TRAIN_COUNT="${TRAIN_COUNT:-1}"
export VALIDATION_COUNT="${VALIDATION_COUNT:-1}"
export VALIDATION_CANARY_COUNT="${VALIDATION_CANARY_COUNT:-4}"
export MAX_SAMPLE_TEXT_CHARS="${MAX_SAMPLE_TEXT_CHARS:-2500}"
export COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS="${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS:-10}"
export MAX_INNER_ITERATIONS="${MAX_INNER_ITERATIONS:-1}"
export MAX_ITEMS="${MAX_ITEMS:-1}"
export PROGRAM_SYNTHESIS_MIN_SUPPORT="${PROGRAM_SYNTHESIS_MIN_SUPPORT:-1}"
export MAX_PROGRAM_SYNTHESIS_PENDING="${MAX_PROGRAM_SYNTHESIS_PENDING:-128}"
export PROGRAM_SYNTHESIS_MIN_RESIDUAL_OCCURRENCES="${PROGRAM_SYNTHESIS_MIN_RESIDUAL_OCCURRENCES:-1}"
export PROGRAM_SYNTHESIS_MIN_RESIDUAL_SURVIVAL_SCORE="${PROGRAM_SYNTHESIS_MIN_RESIDUAL_SURVIVAL_SCORE:-0.0}"
export CODEX_PARALLEL_SCOPES="${CODEX_PARALLEL_SCOPES:-ir_decompiler}"
export CODEX_SCOPE_WORKERS="${CODEX_SCOPE_WORKERS:-1}"
export CODEX_VECTOR_MIN_BUNDLE_SIZE="${CODEX_VECTOR_MIN_BUNDLE_SIZE:-1}"
export CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS="${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS:-0}"
export CODEX_EXEC_MODE="${CODEX_EXEC_MODE:-codex_cli}"

log_line "starting_legal_ir_autoencoder_codex run_id=${BASE_RUN_ID} codex_model=${CODEX_MODEL} autoencoder_device=${AUTOENCODER_DEVICE}"
setsid bash scripts/ops/logic/run_hparam_then_8h.sh "${BASE_RUN_ID}" > "${PIPELINE_LOG}" 2>&1 &
echo "$!" > "${PID_FILE}"
log_line "pipeline_started pid=$(cat "${PID_FILE}") log=${PIPELINE_LOG}"

if [[ "${START_WATCHDOG}" == "1" ]]; then
  setsid bash scripts/ops/logic/watch_hparam8h_pipeline.sh "${BASE_RUN_ID}" > "${WATCHDOG_LOG}" 2>&1 &
  echo "$!" > "${WATCHDOG_PID_FILE}"
  log_line "watchdog_started pid=$(cat "${WATCHDOG_PID_FILE}") log=${ROOT_DIR}/workspace/test-logs/${BASE_RUN_ID}.watchdog.log"
fi

log_line "restart_complete run_id=${BASE_RUN_ID}"
