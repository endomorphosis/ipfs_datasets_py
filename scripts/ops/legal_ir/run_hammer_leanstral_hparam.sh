#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

BASE_RUN_ID="${BASE_RUN_ID:-legal-ir-hammer-leanstral-hparam24h-$(date -u +%Y%m%dT%H%M%SZ)}"
FINAL_RUN_LABEL="${FINAL_RUN_LABEL:-24h}"
SUMMARY_PATH="${SUMMARY_PATH:-${ROOT_DIR}/workspace/test-logs/${BASE_RUN_ID}-best-${FINAL_RUN_LABEL}-autoencoder.summary}"
DRY_RUN=0
GATE_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --gate-only)
      GATE_ONLY=1
      shift
      ;;
    --run-id|--base-run-id)
      BASE_RUN_ID="$2"
      SUMMARY_PATH="${ROOT_DIR}/workspace/test-logs/${BASE_RUN_ID}-best-${FINAL_RUN_LABEL}-autoencoder.summary"
      shift 2
      ;;
    --summary-path)
      SUMMARY_PATH="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/../ipfs_accelerate_py${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHON_BIN
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1}"
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"

export TRIAL_SECONDS="${TRIAL_SECONDS:-600}"
export TRIAL_COUNT="${TRIAL_COUNT:-6}"
export FINAL_SECONDS="${FINAL_SECONDS:-86400}"
export FINAL_RUN_LABEL
export SWEEP_LOOP_ROLE="${SWEEP_LOOP_ROLE:-autoencoder}"
export AUTOENCODER_DEVICE="${AUTOENCODER_DEVICE:-auto}"
export BRIDGE_LOSS_ADAPTERS="${BRIDGE_LOSS_ADAPTERS:-modal_frame_logic,deontic_norms}"
export BRIDGE_EVALUATE_PROVERS="${BRIDGE_EVALUATE_PROVERS:-false}"
export CODEX_PARALLEL_SCOPES="${CODEX_PARALLEL_SCOPES:-compiler_parser,compiler_registry,compiler_ambiguity,ir_decompiler,frame_logic,deontic,tdfol,knowledge_graphs,cec,external_provers}"
export CODEX_SCOPE_WORKERS="${CODEX_SCOPE_WORKERS:-1}"
export CODEX_BUNDLE_MODE="${CODEX_BUNDLE_MODE:-vector}"
export CODEX_VECTOR_MIN_BUNDLE_SIZE="${CODEX_VECTOR_MIN_BUNDLE_SIZE:-2}"
export CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS="${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS:-120}"

HARD_GUARDRAILS="$("${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate guardrail-metrics)"
EXTRA_ARGS=(
  --autoencoder-hard-guardrail-metrics "${HARD_GUARDRAILS}"
  --autoencoder-introspection-mode "${AUTOENCODER_INTROSPECTION_MODE:-seed}"
  --autoencoder-introspection-every-n-cycles "${AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES:-1}"
  --autoencoder-max-audits-per-cycle "${AUTOENCODER_MAX_AUDITS_PER_CYCLE:-4}"
  --autoencoder-max-todos-per-cycle "${AUTOENCODER_MAX_TODOS_PER_CYCLE:-8}"
  --leanstral-direct-guidance-projection-enabled true
  --leanstral-direct-guidance-require-executor-available "${LEANSTRAL_DIRECT_GUIDANCE_REQUIRE_EXECUTOR_AVAILABLE:-false}"
  --leanstral-direct-guidance-train-autoencoder true
  --leanstral-direct-guidance-max-training-items "${LEANSTRAL_DIRECT_GUIDANCE_MAX_TRAINING_ITEMS:-64}"
  --daemon-hammer-guidance-enabled true
  --daemon-hammer-guidance-cache-enabled true
  --daemon-hammer-guidance-max-samples-per-cycle "${DAEMON_HAMMER_GUIDANCE_MAX_SAMPLES_PER_CYCLE:-2}"
  --daemon-hammer-guidance-max-obligations-per-sample "${DAEMON_HAMMER_GUIDANCE_MAX_OBLIGATIONS_PER_SAMPLE:-8}"
  --daemon-hammer-guidance-max-premises "${DAEMON_HAMMER_GUIDANCE_MAX_PREMISES:-64}"
  --daemon-hammer-guidance-timeout-seconds "${DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS:-5}"
  --daemon-hammer-guidance-parallel-workers "${DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS:-2}"
  --daemon-hammer-guidance-train-autoencoder true
  --daemon-hammer-guidance-max-training-items "${DAEMON_HAMMER_GUIDANCE_MAX_TRAINING_ITEMS:-64}"
  --codex-bundle-mode "${CODEX_BUNDLE_MODE}"
)
export EXTRA_DAEMON_ARGS="${EXTRA_ARGS[*]}"

CMD=("${ROOT_DIR}/scripts/ops/logic/run_hparam_then_8h.sh" "${BASE_RUN_ID}")

run_gate() {
  "${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate gate \
    --summary-path "${SUMMARY_PATH}" \
    --max-validation-ce-regression "${GATE_MAX_VALIDATION_CE_REGRESSION:-0.02}" \
    --max-validation-cosine-regression "${GATE_MAX_VALIDATION_COSINE_REGRESSION:-0.02}" \
    --max-compiler-ir-ce-regression "${GATE_MAX_COMPILER_IR_CE_REGRESSION:-0.05}" \
    --max-compiler-ir-cosine-regression "${GATE_MAX_COMPILER_IR_COSINE_REGRESSION:-0.05}" \
    --max-source-copy-penalty "${GATE_MAX_SOURCE_COPY_PENALTY:-0.35}" \
    --min-cycles-for-todo-gate "${GATE_MIN_CYCLES_FOR_TODO_GATE:-1}"
}

if [[ "${GATE_ONLY}" == "1" ]]; then
  run_gate
  exit $?
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  printf '%q ' "${CMD[@]}"
  printf '\n'
  echo "summary_path=${SUMMARY_PATH}"
  echo "trial_seconds=${TRIAL_SECONDS}"
  echo "trial_count=${TRIAL_COUNT}"
  echo "final_seconds=${FINAL_SECONDS}"
  echo "final_run_label=${FINAL_RUN_LABEL}"
  echo "extra_daemon_args=${EXTRA_DAEMON_ARGS}"
  echo "gate_metrics=${HARD_GUARDRAILS}"
  exit 0
fi

"${CMD[@]}"
run_gate
