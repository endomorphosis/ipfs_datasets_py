#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

RUN_ID="${1:?run id is required}"
PARENT_PID="${2:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INPUT_PATH_OVERRIDE="${LEANSTRAL_AUDIT_INPUT_PATH:-}"
DEFAULT_INPUT_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.canonical-disagreements.jsonl"
LEGACY_INPUT_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.canonical-disagreements.jsonl"
INPUT_PATH="${INPUT_PATH_OVERRIDE:-${DEFAULT_INPUT_PATH}}"
WORK_DIR="${ROOT_DIR}/workspace/leanstral-audit-worker"
CHECKPOINT_PATH="${WORK_DIR}/${RUN_ID}.checkpoint.json"
CACHE_DIR="${LEANSTRAL_AUDIT_CACHE_DIR:-${WORK_DIR}/cache}"
VERIFICATION_OUTPUT="${WORK_DIR}/${RUN_ID}.verification.jsonl"
RUN_REPORT_OUTPUT="${WORK_DIR}/${RUN_ID}.rule-gaps.json"
PUBLISHED_REPORT_OUTPUT="${LEANSTRAL_RULE_GAP_REPORT_PATH:-${WORK_DIR}/canonical.rule-gaps.json}"
PROOF_CACHE_PATH="${LEANSTRAL_PROOF_CACHE_PATH:-${WORK_DIR}/lean-proof-cache.json}"
POLL_SECONDS="${LEANSTRAL_AUDIT_POLL_SECONDS:-30}"
FAILURE_BACKOFF_SECONDS="${LEANSTRAL_AUDIT_FAILURE_BACKOFF_SECONDS:-900}"
DEFAULT_REFERENCE_EXAMPLE_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.reference-examples.json"
LEGACY_REFERENCE_EXAMPLE_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.reference-examples.json"
REFERENCE_EXAMPLE_PATHS_RAW="${LEANSTRAL_AUDIT_REFERENCE_EXAMPLE_PATHS:-${LEANSTRAL_AUDIT_REFERENCE_EXAMPLE_PATH:-}}"
REFERENCE_EXAMPLE_ARGS=()
REFERENCE_EXAMPLE_COUNT=0
LAST_RESOLVED_INPUT_PATH=""
LLAMA_CPP_ACCELERATOR_REQUEST="${LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR:-auto}"
LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT="${LEANSTRAL_AUDIT_BATCH_SIZE:-2}"
LLAMA_CPP_CONTEXT_DEFAULT="12288"
LLAMA_CPP_GPU_LAYERS_DEFAULT="0"
LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT} --device none --no-op-offload --no-kv-offload"
LLAMA_CPP_RESOLVED_ACCELERATOR="cpu"

llama_cpp_cuda_available() {
  local llama_bin devices
  llama_bin="${IPFS_ACCELERATE_LLAMA_CPP_BIN:-}"
  if [[ -z "${llama_bin}" ]]; then
    llama_bin="$(command -v llama || true)"
  fi
  [[ -n "${llama_bin}" ]] || return 1
  devices="$("${llama_bin}" cli --list-devices 2>/dev/null || true)"
  [[ "${devices}" == *"CUDA"* ]]
}

configure_llama_cpp_accelerator_defaults() {
  local request lower_request explicit_gpu_layers explicit_extra_args gpu_layers_value
  request="${LLAMA_CPP_ACCELERATOR_REQUEST}"
  lower_request="$(printf '%s' "${request}" | tr '[:upper:]' '[:lower:]')"
  explicit_gpu_layers="${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS+x}"
  explicit_extra_args="${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS+x}"
  gpu_layers_value="${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-}"

  case "${lower_request}" in
    cpu|none|off|false|0)
      return 0
      ;;
  esac

  if [[ -n "${explicit_gpu_layers}" && "${gpu_layers_value}" == "0" ]]; then
    return 0
  fi

  if ! llama_cpp_cuda_available; then
    if [[ "${lower_request}" == "cuda" || "${lower_request}" == "gpu" ]]; then
      LLAMA_CPP_RESOLVED_ACCELERATOR="cuda_unavailable_cpu_fallback"
    fi
    return 0
  fi

  LLAMA_CPP_RESOLVED_ACCELERATOR="cuda"
  if [[ -z "${explicit_gpu_layers}" ]]; then
    LLAMA_CPP_GPU_LAYERS_DEFAULT="1"
  fi
  if [[ -z "${explicit_extra_args}" ]]; then
    # Full Leanstral offload, and op/KV offload at 4k+ context, currently load
    # but can crash on first generation during cuBLAS handle creation on GB10.
    # One GPU layer keeps CUDA active while CPU op/KV execution preserves the
    # old 12k audit context without that allocation failure.
    LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT} -b 128 -ub 32 --no-op-offload --no-kv-offload"
  fi
}

configure_llama_cpp_accelerator_defaults

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/../ipfs_accelerate_py${PYTHONPATH:+:${PYTHONPATH}}"
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1}"
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_PROVIDER_FALLBACKS="${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS:-llama_cpp_native,mistral_vibe}"
export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="${IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART:-1}"
export IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL="${IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL:-1}"
export IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS="${IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS:-900}"
export IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE="${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-${LLAMA_CPP_CONTEXT_DEFAULT}}"
export IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS="${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-${LLAMA_CPP_GPU_LAYERS_DEFAULT}}"
export IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS="${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS:-${LLAMA_CPP_EXTRA_ARGS_DEFAULT}}"
export LEANSTRAL_AUDIT_LLAMA_CPP_RESOLVED_ACCELERATOR="${LLAMA_CPP_RESOLVED_ACCELERATOR}"
export LEANSTRAL_AUDIT_BATCH_SIZE="${LEANSTRAL_AUDIT_BATCH_SIZE:-${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT}}"
export LEANSTRAL_AUDIT_BATCH_MAX_WORKERS="${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS:-${LEANSTRAL_AUDIT_BATCH_SIZE}}"
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"
export IPFS_ACCELERATE_LLM_ROUTER_BATCH_WORKERS="${IPFS_ACCELERATE_LLM_ROUTER_BATCH_WORKERS:-${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS}}"
export IPFS_DATASETS_PY_LLM_ROUTER_BATCH_WORKERS="${IPFS_DATASETS_PY_LLM_ROUTER_BATCH_WORKERS:-${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS}}"
mkdir -p "${WORK_DIR}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  echo "$(timestamp) $*"
}

resolve_input_path() {
  local candidate
  if [[ -n "${INPUT_PATH_OVERRIDE}" ]]; then
    INPUT_PATH="${INPUT_PATH_OVERRIDE}"
  else
    INPUT_PATH="${DEFAULT_INPUT_PATH}"
    for candidate in "${DEFAULT_INPUT_PATH}" "${LEGACY_INPUT_PATH}"; do
      if [[ -s "${candidate}" ]]; then
        INPUT_PATH="${candidate}"
        break
      fi
    done
  fi
  if [[ "${INPUT_PATH}" != "${LAST_RESOLVED_INPUT_PATH}" ]]; then
    log_line "audit_input_resolved input=${INPUT_PATH} default=${DEFAULT_INPUT_PATH} legacy=${LEGACY_INPUT_PATH}"
    LAST_RESOLVED_INPUT_PATH="${INPUT_PATH}"
  fi
}

input_signature() {
  resolve_input_path
  if [[ ! -s "${INPUT_PATH}" ]]; then
    return 1
  fi
  stat -c '%s:%Y' "${INPUT_PATH}" 2>/dev/null
}

parent_alive() {
  [[ "${PARENT_PID}" =~ ^[0-9]+$ ]] || return 1
  (( PARENT_PID > 0 )) || return 1
  kill -0 "${PARENT_PID}" 2>/dev/null
}

configure_reference_example_args() {
  local raw normalized path
  REFERENCE_EXAMPLE_ARGS=()
  REFERENCE_EXAMPLE_COUNT=0
  raw="${REFERENCE_EXAMPLE_PATHS_RAW}"
  if [[ -z "${raw}" ]]; then
    for path in "${DEFAULT_REFERENCE_EXAMPLE_PATH}" "${LEGACY_REFERENCE_EXAMPLE_PATH}"; do
      if [[ -e "${path}" ]]; then
        REFERENCE_EXAMPLE_ARGS+=(--reference-example-path "${path}")
        REFERENCE_EXAMPLE_COUNT=$((REFERENCE_EXAMPLE_COUNT + 1))
      fi
    done
    return 0
  fi
  normalized="${raw//,/:}"
  IFS=':' read -r -a reference_paths <<< "${normalized}"
  for path in "${reference_paths[@]}"; do
    [[ -n "${path}" ]] || continue
    if [[ -e "${path}" ]]; then
      REFERENCE_EXAMPLE_ARGS+=(--reference-example-path "${path}")
      REFERENCE_EXAMPLE_COUNT=$((REFERENCE_EXAMPLE_COUNT + 1))
    else
      log_line "reference_example_path_missing path=${path}"
    fi
  done
}

llama_cpp_preflight_if_enabled() {
  local provider_chain lower_chain preflight_log
  case "${LEANSTRAL_AUDIT_LLAMA_CPP_PREFLIGHT:-1}" in
    0|false|False|FALSE|no|No|NO|off|Off|OFF)
      return 0
      ;;
  esac

  provider_chain="${LEANSTRAL_AUDIT_PROVIDER},${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS:-}"
  lower_chain="$(printf '%s' "${provider_chain}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${lower_chain}" != *"leanstral_local"* && "${lower_chain}" != *"llama_cpp"* && "${lower_chain}" != *"llamacpp"* ]]; then
    return 0
  fi

  preflight_log="${WORK_DIR}/${RUN_ID}.llama-cpp-preflight.log"
  log_line "llama_cpp_preflight_started log=${preflight_log}"
  if "${PYTHON_BIN}" -m ipfs_accelerate_py.utils.llama_cpp \
    --serve \
    --prefetch-model \
    --context-size "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-12288}" \
    --gpu-layers "${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-0}" \
    --extra-args "${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS:-${LLAMA_CPP_EXTRA_ARGS_DEFAULT}}" \
    --startup-timeout-seconds "${IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS:-900}" \
    >> "${preflight_log}" 2>&1; then
    log_line "llama_cpp_preflight_completed log=${preflight_log}"
  else
    log_line "llama_cpp_preflight_failed log=${preflight_log}"
  fi
}

last_signature=""
next_retry_epoch=0

run_audit_if_due() {
  local signature now batch_use_mesh_args
  signature="$(input_signature)" || return 0
  now="$(date +%s)"
  if [[ "${signature}" == "${last_signature}" ]] && (( now < next_retry_epoch )); then
    return 0
  fi
  if [[ "${signature}" == "${last_signature}" ]] && (( next_retry_epoch == 0 )); then
    return 0
  fi

  last_signature="${signature}"
  llama_cpp_preflight_if_enabled
  # The preflight may block while a local GGUF downloads. Refresh the audit
  # input and reference examples afterwards so startup races do not leave the
  # worker pointed at the parent-run path while the autoencoder writes the
  # child-run export path.
  signature="$(input_signature)" || return 0
  last_signature="${signature}"
  configure_reference_example_args
  batch_use_mesh_args=()
  case "${LEANSTRAL_AUDIT_BATCH_USE_MESH}" in
    1|true|True|TRUE|yes|Yes|YES|on|On|ON)
      batch_use_mesh_args=(--batch-use-mesh)
      ;;
  esac
  log_line "audit_started signature=${signature}"
  if "${PYTHON_BIN}" scripts/ops/legal_ir/run_leanstral_audit_worker.py \
    --input "${INPUT_PATH}" \
    --cache-dir "${CACHE_DIR}" \
    --checkpoint-path "${CHECKPOINT_PATH}" \
    --max-concurrency "${LEANSTRAL_AUDIT_MAX_CONCURRENCY:-1}" \
    --max-retries "${LEANSTRAL_AUDIT_MAX_RETRIES:-1}" \
    --validation-repair-retries "${LEANSTRAL_AUDIT_VALIDATION_REPAIR_RETRIES:-1}" \
    --timeout-seconds "${LEANSTRAL_AUDIT_TIMEOUT_SECONDS:-600}" \
    --retry-backoff-seconds "${LEANSTRAL_AUDIT_RETRY_BACKOFF_SECONDS:-2}" \
    --snapshot-selection "${LEANSTRAL_AUDIT_SNAPSHOT_SELECTION:-latest_canonical_snapshot}" \
    --min-snapshot-records "${LEANSTRAL_AUDIT_MIN_SNAPSHOT_RECORDS:-25}" \
    --max-work-items "${LEANSTRAL_AUDIT_MAX_WORK_ITEMS:-2}" \
    --max-evidence-packets-per-item "${LEANSTRAL_AUDIT_MAX_EVIDENCE_PACKETS_PER_ITEM:-1}" \
    --evidence-refresh-policy latest_compiler_snapshot \
    --provider "${LEANSTRAL_AUDIT_PROVIDER}" \
    --provider-fallbacks "${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS}" \
    --model "${LEANSTRAL_AUDIT_MODEL:-Leanstral}" \
    --vibe-agent "${LEANSTRAL_AUDIT_VIBE_AGENT:-lean}" \
    --max-new-tokens "${LEANSTRAL_AUDIT_MAX_NEW_TOKENS:-512}" \
    --batch-size "${LEANSTRAL_AUDIT_BATCH_SIZE:-2}" \
    --batch-max-workers "${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS:-${LEANSTRAL_AUDIT_BATCH_SIZE:-2}}" \
    "${batch_use_mesh_args[@]}" \
    "${REFERENCE_EXAMPLE_ARGS[@]}" \
    --verification-output "${VERIFICATION_OUTPUT}" \
    --rule-gap-report-output "${RUN_REPORT_OUTPUT}" \
    --publish-rule-gap-report-output "${PUBLISHED_REPORT_OUTPUT}" \
    --canonical-recompile-backend packet_canonical \
    --lean-timeout-seconds "${LEANSTRAL_LEAN_TIMEOUT_SECONDS:-30}" \
    --lean-parallel-workers "${LEANSTRAL_LEAN_PARALLEL_WORKERS:-4}" \
    --lean-slice-size "${LEANSTRAL_LEAN_SLICE_SIZE:-4}" \
    --lean-proof-cache-path "${PROOF_CACHE_PATH}" \
    --prover-timeout-seconds "${LEANSTRAL_PROVER_TIMEOUT_SECONDS:-5}"; then
    next_retry_epoch=0
    log_line "audit_completed signature=${signature} report=${PUBLISHED_REPORT_OUTPUT}"
  else
    next_retry_epoch=$((now + FAILURE_BACKOFF_SECONDS))
    log_line "audit_failed signature=${signature} retry_after_epoch=${next_retry_epoch}"
  fi
}

configure_reference_example_args
resolve_input_path
log_line "audit_companion_started parent_pid=${PARENT_PID} input=${INPUT_PATH} reference_example_paths=${REFERENCE_EXAMPLE_COUNT}"
log_line "llama_cpp_accelerator_resolved requested=${LLAMA_CPP_ACCELERATOR_REQUEST} resolved=${LEANSTRAL_AUDIT_LLAMA_CPP_RESOLVED_ACCELERATOR} context=${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE} gpu_layers=${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS} extra_args=${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS}"
while parent_alive; do
  run_audit_if_due
  sleep "${POLL_SECONDS}"
done
run_audit_if_due
log_line "audit_companion_stopped parent_pid=${PARENT_PID}"
