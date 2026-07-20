#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

BASE_RUN_ID="${1:-legal-ir-canonical-8h-metric-rich-$(date -u +%Y%m%dT%H%M%SZ)}"
LOG_DIR="${ROOT_DIR}/workspace/test-logs"
PIPELINE_LOG="${LOG_DIR}/${BASE_RUN_ID}.pipeline.log"
PID_FILE="${LOG_DIR}/${BASE_RUN_ID}.pid"
ARGS_SNAPSHOT="${LOG_DIR}/${BASE_RUN_ID}.args"
LIFECYCLE_FILE="${LOG_DIR}/${BASE_RUN_ID}.lifecycle.env"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="${PYTHON_BIN}"
elif [[ -x "${ROOT_DIR}/.venv-cuda/bin/python" ]] && \
  "${ROOT_DIR}/.venv-cuda/bin/python" -c \
    'import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)' \
    >/dev/null 2>&1; then
  PYTHON_BIN="${ROOT_DIR}/.venv-cuda/bin/python"
else
  PYTHON_BIN="python3"
fi

STOP_EXISTING="${STOP_EXISTING:-1}"
START_SUPERVISOR="${START_SUPERVISOR:-1}"
SUPERVISOR_LOG="${LOG_DIR}/${BASE_RUN_ID}.canonical-watchdog.launch.log"
SUPERVISOR_PID_FILE="${LOG_DIR}/${BASE_RUN_ID}.watchdog-supervisor.pid"
START_LEANSTRAL_AUDIT_WORKER="${START_LEANSTRAL_AUDIT_WORKER:-1}"
LEANSTRAL_AUDIT_LOG="${LOG_DIR}/${BASE_RUN_ID}.leanstral-audit.log"
LEANSTRAL_AUDIT_PID_FILE="${LOG_DIR}/${BASE_RUN_ID}.leanstral-audit.pid"

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
    $2 == self_pgid { next }
    /uscode_modal_daemon_runner/ && /--run-id legal-ir-canonical-/ { print $2 }
  ' | sort -u
}

stop_existing_canonical_runs() {
  local groups
  groups="$(matching_process_groups || true)"
  if [[ -z "${groups}" ]]; then
    log_line "no_existing_canonical_runs"
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

if [[ "${STOP_EXISTING}" == "1" ]]; then
  stop_existing_canonical_runs
fi

CMD=(
  "${PYTHON_BIN}"
  -m
  ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner
  --run-id "${BASE_RUN_ID}"
  --loop-role paired
  --duration-seconds "${DURATION_SECONDS:-28800}"
  --train-count "${TRAIN_COUNT:-4}"
  --validation-count "${VALIDATION_COUNT:-25}"
  --validation-canary-count "${VALIDATION_CANARY_COUNT:-25}"
  --max-sample-text-chars "${MAX_SAMPLE_TEXT_CHARS:-3072}"
  # One bounded TODO update per outer cycle keeps Codex/Leanstral consumers fed.
  --max-inner-iterations "${MAX_INNER_ITERATIONS:-1}"
  --max-items "${MAX_ITEMS:-8}"
  --learning-rate "${LEARNING_RATE:-0.24}"
  --generalizable-projection-epochs "${GENERALIZABLE_PROJECTION_EPOCHS:-1}"
  --generalizable-projection-timeout-seconds "${GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS:-120}"
  --generalizable-projection-max-line-search-attempts "${GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS:-1}"
  --autoencoder-canonical-warm-start "${AUTOENCODER_CANONICAL_WARM_START:-require}"
  --autoencoder-device "${AUTOENCODER_DEVICE:-cuda}"
  --autoencoder-introspection-mode "${AUTOENCODER_INTROSPECTION_MODE:-export}"
  --autoencoder-introspection-every-n-cycles "${AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES:-4}"
  --autoencoder-introspection-min-export-samples "${AUTOENCODER_INTROSPECTION_MIN_EXPORT_SAMPLES:-25}"
  --autoencoder-max-audits-per-cycle "${AUTOENCODER_MAX_AUDITS_PER_CYCLE:-4}"
  --autoencoder-max-todos-per-cycle "${AUTOENCODER_MAX_TODOS_PER_CYCLE:-8}"
  --leanstral-rule-gap-projection-enabled "${LEANSTRAL_RULE_GAP_PROJECTION_ENABLED:-true}"
  --leanstral-rule-gap-report-path "${LEANSTRAL_RULE_GAP_REPORT_PATH:-${ROOT_DIR}/workspace/leanstral-audit-worker/canonical.rule-gaps.json}"
  --leanstral-rule-gap-max-todos-per-scope "${LEANSTRAL_RULE_GAP_MAX_TODOS_PER_SCOPE:-2}"
  --leanstral-rule-gap-require-executor-available "${LEANSTRAL_RULE_GAP_REQUIRE_EXECUTOR_AVAILABLE:-true}"
  --leanstral-rule-gap-max-report-age-seconds "${LEANSTRAL_RULE_GAP_MAX_REPORT_AGE_SECONDS:-604800}"
  --leanstral-direct-guidance-projection-enabled "${LEANSTRAL_DIRECT_GUIDANCE_PROJECTION_ENABLED:-true}"
  --leanstral-direct-guidance-require-executor-available "${LEANSTRAL_DIRECT_GUIDANCE_REQUIRE_EXECUTOR_AVAILABLE:-false}"
  --leanstral-direct-guidance-train-autoencoder "${LEANSTRAL_DIRECT_GUIDANCE_TRAIN_AUTOENCODER:-true}"
  --leanstral-direct-guidance-max-training-items "${LEANSTRAL_DIRECT_GUIDANCE_MAX_TRAINING_ITEMS:-64}"
  --daemon-hammer-guidance-enabled "${DAEMON_HAMMER_GUIDANCE_ENABLED:-true}"
  --daemon-hammer-guidance-cache-enabled "${DAEMON_HAMMER_GUIDANCE_CACHE_ENABLED:-true}"
  --daemon-hammer-guidance-max-samples-per-cycle "${DAEMON_HAMMER_GUIDANCE_MAX_SAMPLES_PER_CYCLE:-2}"
  --daemon-hammer-guidance-max-obligations-per-sample "${DAEMON_HAMMER_GUIDANCE_MAX_OBLIGATIONS_PER_SAMPLE:-8}"
  --daemon-hammer-guidance-max-premises "${DAEMON_HAMMER_GUIDANCE_MAX_PREMISES:-64}"
  --daemon-hammer-guidance-timeout-seconds "${DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS:-5}"
  --daemon-hammer-guidance-parallel-workers "${DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS:-2}"
  --daemon-hammer-guidance-train-autoencoder "${DAEMON_HAMMER_GUIDANCE_TRAIN_AUTOENCODER:-true}"
  --daemon-hammer-guidance-max-training-items "${DAEMON_HAMMER_GUIDANCE_MAX_TRAINING_ITEMS:-64}"
  --autoencoder-target-scope-filters "${AUTOENCODER_TARGET_SCOPE_FILTERS:-}"
  --autoencoder-require-prover-confirmation "${AUTOENCODER_REQUIRE_PROVER_CONFIRMATION:-true}"
  --bridge-loss-adapters "${BRIDGE_LOSS_ADAPTERS:-modal_frame_logic,deontic_norms,fol_tdfol,cec_dcec,external_prover_router,zkp_attestation}"
  --autoencoder-metric-bridge-adapters "${AUTOENCODER_METRIC_BRIDGE_ADAPTERS:-same}"
  --autoencoder-diagnostic-bridge-adapters "${AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS:-same}"
  --bridge-evaluate-provers "${BRIDGE_EVALUATE_PROVERS:-false}"
  --autoencoder-bridge-workers "${AUTOENCODER_BRIDGE_WORKERS:-8}"
  --autoencoder-max-codec-feature-keys "${AUTOENCODER_MAX_CODEC_FEATURE_KEYS:-64}"
  --compiler-ir-metric-sample-timeout-seconds "${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS:-10}"
  --compiler-ir-metric-max-sample-text-chars "${COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS:-400}"
  --compiler-ir-train-mode "${COMPILER_IR_TRAIN_MODE:-every_cycle}"
  --compiler-ir-guided-train-mode "${COMPILER_IR_GUIDED_TRAIN_MODE:-every_cycle}"
  --autoencoder-before-train-eval-mode "${AUTOENCODER_BEFORE_TRAIN_EVAL_MODE:-every_cycle}"
  --autoencoder-sample-memory-probe-mode "${AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE:-periodic}"
  --autoencoder-todo-supervisor-mode "${AUTOENCODER_TODO_SUPERVISOR_MODE:-starved}"
  --autoencoder-todo-supervisor-min-open "${AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN:-12}"
  --autoencoder-projection-deadband-mode "${AUTOENCODER_PROJECTION_DEADBAND_MODE:-enforce}"
  --autoencoder-max-ce-deadband "${AUTOENCODER_MAX_CE_DEADBAND:-0.0001}"
  --autoencoder-hard-guardrail-metrics "${AUTOENCODER_HARD_GUARDRAIL_METRICS:-compiler_ir_cosine,structural_validity,source_copy_penalty}"
  --autoencoder-projection-prescreen-mode "${AUTOENCODER_PROJECTION_PRESCREEN_MODE:-enforce}"
  --autoencoder-projection-prescreen-top-k "${AUTOENCODER_PROJECTION_PRESCREEN_TOP_K:-2}"
  --autoencoder-projection-periodic-full-search-every-n-cycles "${AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES:-8}"
  --codex-exec-mode "${CODEX_EXEC_MODE:-codex_cli}"
  --codex-apply-mode "${CODEX_APPLY_MODE:-apply_to_main}"
  --codex-commit-mode "${CODEX_COMMIT_MODE:-commit_applied}"
  --codex-sandbox "${CODEX_SANDBOX:-workspace-write}"
  --codex-parallel-scopes "${CODEX_PARALLEL_SCOPES:-compiler_parser,compiler_registry,compiler_ambiguity,ir_decompiler,frame_logic,bridge,fol,deontic,flogic,tdfol,cec,knowledge_graphs,external_provers,zkp,loss}"
  --codex-scope-workers "${CODEX_SCOPE_WORKERS:-1}"
  --codex-bundle-mode "${CODEX_BUNDLE_MODE:-semantic}"
  --codex-timeout-seconds "${CODEX_TIMEOUT_SECONDS:-900}"
  --codex-main-apply-lock-timeout-seconds "${CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS:-1200}"
  --codex-main-apply-max-inflight-packets "${CODEX_MAIN_APPLY_MAX_INFLIGHT_PACKETS:-1}"
  --codex-lane-lock-mode "${CODEX_LANE_LOCK_MODE:-hybrid}"
  --codex-target-file-lane-lock-scopes "${CODEX_TARGET_FILE_LANE_LOCK_SCOPES:-all}"
  --paired-poll-seconds "${PAIRED_POLL_SECONDS:-5}"
  --paired-grace-seconds "${PAIRED_GRACE_SECONDS:-300}"
  --paired-supervisor-backend "${PAIRED_SUPERVISOR_BACKEND:-accelerate_style}"
)

MAX_CYCLES_VALUE="${MAX_CYCLES:-0}"
if [[ "${MAX_CYCLES_VALUE}" =~ ^[0-9]+$ ]] && (( MAX_CYCLES_VALUE > 0 )); then
  CMD+=(--max-cycles "${MAX_CYCLES_VALUE}")
fi

printf '%s\n' "${CMD[@]}" > "${ARGS_SNAPSHOT}"
log_line "saved_args_snapshot path=${ARGS_SNAPSHOT}"

STARTED_EPOCH="$(date +%s)"
DURATION_VALUE="${DURATION_SECONDS:-28800}"
DEADLINE_EPOCH=$((STARTED_EPOCH + DURATION_VALUE))
cat > "${LIFECYCLE_FILE}.tmp" <<EOF
RUN_ID=${BASE_RUN_ID}
STARTED_EPOCH=${STARTED_EPOCH}
DEADLINE_EPOCH=${DEADLINE_EPOCH}
DURATION_SECONDS=${DURATION_VALUE}
EOF
mv "${LIFECYCLE_FILE}.tmp" "${LIFECYCLE_FILE}"
log_line "saved_lifecycle path=${LIFECYCLE_FILE} deadline_epoch=${DEADLINE_EPOCH}"

log_line "starting_canonical_weights_loop run_id=${BASE_RUN_ID}"
setsid "${CMD[@]}" > "${PIPELINE_LOG}" 2>&1 &
echo "$!" > "${PID_FILE}"
log_line "pipeline_started pid=$(cat "${PID_FILE}") log=${PIPELINE_LOG}"

if [[ "${START_LEANSTRAL_AUDIT_WORKER}" == "1" ]]; then
  setsid bash scripts/ops/legal_ir/watch_leanstral_audit_worker.sh \
    "${BASE_RUN_ID}" "$(cat "${PID_FILE}")" > "${LEANSTRAL_AUDIT_LOG}" 2>&1 &
  echo "$!" > "${LEANSTRAL_AUDIT_PID_FILE}"
  log_line "leanstral_audit_worker_started pid=$(cat "${LEANSTRAL_AUDIT_PID_FILE}") log=${LEANSTRAL_AUDIT_LOG}"
fi

if [[ "${START_SUPERVISOR}" == "1" ]]; then
  setsid bash scripts/ops/logic/watch_canonical_weights_loop.sh "${BASE_RUN_ID}" > "${SUPERVISOR_LOG}" 2>&1 &
  echo "$!" > "${SUPERVISOR_PID_FILE}"
  log_line "supervisor_started pid=$(cat "${SUPERVISOR_PID_FILE}") log=${SUPERVISOR_LOG}"
fi

log_line "restart_complete run_id=${BASE_RUN_ID}"
