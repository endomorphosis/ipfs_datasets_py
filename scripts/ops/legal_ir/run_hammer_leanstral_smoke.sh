#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

RUN_ID="${RUN_ID:-legal-ir-hammer-leanstral-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
DURATION_SECONDS="${DURATION_SECONDS:-600}"
MAX_CYCLES="${MAX_CYCLES:-1}"
SUMMARY_PATH="${SUMMARY_PATH:-${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.summary}"
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
    --run-id)
      RUN_ID="$2"
      SUMMARY_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.summary"
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
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1}"
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"

CODEX_EXEC_MODE="${CODEX_EXEC_MODE:-codex_cli}"
if ! command -v codex >/dev/null 2>&1; then
  CODEX_EXEC_MODE="packet_only"
fi

HARD_GUARDRAILS="$("${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate guardrail-metrics)"
MODULE="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner"

CMD=(
  "${PYTHON_BIN}" -m "${MODULE}"
  --loop-role paired
  --run-id "${RUN_ID}"
  --duration-seconds "${DURATION_SECONDS}"
  --max-cycles "${MAX_CYCLES}"
  --train-count "${TRAIN_COUNT:-4}"
  --validation-count "${VALIDATION_COUNT:-4}"
  --validation-canary-count "${VALIDATION_CANARY_COUNT:-8}"
  --max-sample-text-chars "${MAX_SAMPLE_TEXT_CHARS:-2500}"
  --compiler-ir-metric-max-sample-text-chars "${COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS:-600}"
  --compiler-ir-metric-sample-timeout-seconds "${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS:-10}"
  --max-inner-iterations "${MAX_INNER_ITERATIONS:-3}"
  --max-items "${MAX_ITEMS:-8}"
  --learning-rate "${LEARNING_RATE:-0.30}"
  --generalizable-projection-epochs "${GENERALIZABLE_PROJECTION_EPOCHS:-1}"
  --generalizable-projection-max-cosine-regression "${MAX_COSINE_REGRESSION:-0.005}"
  --generalizable-projection-max-reconstruction-regression "${MAX_RECONSTRUCTION_REGRESSION:-0.01}"
  --generalizable-projection-max-cross-entropy-regression "${MAX_CROSS_ENTROPY_REGRESSION:-0.0}"
  --generalizable-projection-max-legal-ir-loss-regression "${MAX_LEGAL_IR_LOSS_REGRESSION:-0.01}"
  --autoencoder-hard-guardrail-metrics "${HARD_GUARDRAILS}"
  --autoencoder-device "${AUTOENCODER_DEVICE:-auto}"
  --autoencoder-bridge-workers "${AUTOENCODER_BRIDGE_WORKERS:-2}"
  --bridge-loss-adapters "${BRIDGE_LOSS_ADAPTERS:-modal_frame_logic,deontic_norms}"
  --bridge-evaluate-provers "${BRIDGE_EVALUATE_PROVERS:-false}"
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
  --paired-supervisor-backend accelerate_style
  --paired-resource-guard auto
  --paired-grace-seconds "${PAIRED_GRACE_SECONDS:-120}"
  --paired-poll-seconds "${PAIRED_POLL_SECONDS:-1}"
  --codex-exec-mode "${CODEX_EXEC_MODE}"
  --codex-apply-mode "${CODEX_APPLY_MODE:-patch_only}"
  --codex-commit-mode "${CODEX_COMMIT_MODE:-none}"
  --codex-parallel-scopes "${CODEX_PARALLEL_SCOPES:-compiler_parser,compiler_registry,compiler_ambiguity,ir_decompiler,frame_logic,deontic,tdfol,knowledge_graphs,cec,external_provers}"
  --codex-scope-workers "${CODEX_SCOPE_WORKERS:-1}"
  --codex-bundle-mode "${CODEX_BUNDLE_MODE:-vector}"
  --codex-vector-min-similarity "${CODEX_VECTOR_MIN_SIMILARITY:-0.65}"
  --codex-vector-fill-min-similarity "${CODEX_VECTOR_FILL_MIN_SIMILARITY:-0.45}"
  --codex-vector-min-bundle-size "${CODEX_VECTOR_MIN_BUNDLE_SIZE:-2}"
  --codex-vector-max-bundle-wait-seconds "${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS:-120}"
)

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
  echo "gate_metrics=${HARD_GUARDRAILS}"
  exit 0
fi

"${CMD[@]}"
run_gate
