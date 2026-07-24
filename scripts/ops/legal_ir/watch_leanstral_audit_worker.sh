#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

RUN_ID="${1:?run id is required}"
PARENT_PID="${2:-0}"
DEFAULT_PYTHON_BIN="${ROOT_DIR}/.venv-cuda/bin/python"
if [[ ! -x "${DEFAULT_PYTHON_BIN}" ]]; then
  DEFAULT_PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi
if [[ ! -x "${DEFAULT_PYTHON_BIN}" ]]; then
  DEFAULT_PYTHON_BIN="$(command -v python3 || command -v python)"
fi
PYTHON_BIN="${PYTHON_BIN:-${DEFAULT_PYTHON_BIN}}"
INPUT_PATH_OVERRIDE="${LEANSTRAL_AUDIT_INPUT_PATH:-}"
DEFAULT_INPUT_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.canonical-disagreements.jsonl"
LEGACY_INPUT_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.canonical-disagreements.jsonl"
INPUT_PATH="${INPUT_PATH_OVERRIDE:-${DEFAULT_INPUT_PATH}}"
WORK_DIR="${ROOT_DIR}/workspace/leanstral-audit-worker"
CHECKPOINT_PATH="${WORK_DIR}/${RUN_ID}.checkpoint.json"
CACHE_DIR="${LEANSTRAL_AUDIT_CACHE_DIR:-${WORK_DIR}/cache}"
VERIFICATION_OUTPUT="${WORK_DIR}/${RUN_ID}.verification.jsonl"
RUN_REPORT_OUTPUT="${WORK_DIR}/${RUN_ID}.rule-gaps.json"
AUDIT_STDOUT_OUTPUT="${WORK_DIR}/${RUN_ID}.audit.stdout.jsonl"
PUBLISHED_REPORT_OUTPUT="${LEANSTRAL_RULE_GAP_REPORT_PATH:-${WORK_DIR}/canonical.rule-gaps.json}"
PROOF_CACHE_PATH="${LEANSTRAL_PROOF_CACHE_PATH:-${WORK_DIR}/lean-proof-cache.json}"
SERVICE_STATE_PATH="${LEANSTRAL_AUDIT_SERVICE_STATE_PATH:-${WORK_DIR}/persistent-service.state.json}"
SERVICE_START_LOCK_PATH="${LEANSTRAL_AUDIT_SERVICE_START_LOCK_PATH:-${WORK_DIR}/persistent-service.start.lock}"
SERVICE_STATE_LOCK_PATH="${LEANSTRAL_AUDIT_SERVICE_STATE_LOCK_PATH:-${WORK_DIR}/persistent-service.state.lock}"
SERVICE_HEALTH_FAILURE_LIMIT="${LEANSTRAL_AUDIT_SERVICE_HEALTH_FAILURE_LIMIT:-3}"
SERVICE_HEALTH_RETRY_SECONDS="${LEANSTRAL_AUDIT_SERVICE_HEALTH_RETRY_SECONDS:-2}"
SERVICE_MIN_REQUESTS_FOR_REUSE="${LEANSTRAL_AUDIT_SERVICE_MIN_REQUESTS_FOR_REUSE:-2}"
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
LLAMA_CPP_CONTEXT_DEFAULT="${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_PER_SLOT:-8096}"
if ! [[ "${LLAMA_CPP_CONTEXT_DEFAULT}" =~ ^[0-9]+$ ]]; then
  LLAMA_CPP_CONTEXT_DEFAULT="8096"
fi
LLAMA_CPP_GPU_LAYERS_DEFAULT="0"
LLAMA_CPP_AUTO_SIZE_DEFAULT="0"
LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT} --device none --no-op-offload --no-kv-offload"
LLAMA_CPP_RESOLVED_ACCELERATOR="cpu"
LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="0"
LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_CONTEXT_SIZE="0"
LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID=""
LEANSTRAL_AUDIT_SERVICE_GENERATION=""
LEANSTRAL_AUDIT_CONTEXT_FINGERPRINT=""
LEANSTRAL_AUDIT_SERVICE_PREFLIGHT_COMPLETED="0"
LEANSTRAL_AUDIT_SERVICE_RESTART_PENDING="0"
LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES="0"
if ! [[ "${SERVICE_HEALTH_FAILURE_LIMIT}" =~ ^[0-9]+$ ]] || (( SERVICE_HEALTH_FAILURE_LIMIT < 1 )); then
  echo "LEANSTRAL_AUDIT_SERVICE_HEALTH_FAILURE_LIMIT must be a positive integer" >&2
  exit 2
fi
if ! [[ "${SERVICE_HEALTH_RETRY_SECONDS}" =~ ^[0-9]+$ ]]; then
  echo "LEANSTRAL_AUDIT_SERVICE_HEALTH_RETRY_SECONDS must be a nonnegative integer" >&2
  exit 2
fi
if ! [[ "${SERVICE_MIN_REQUESTS_FOR_REUSE}" =~ ^[0-9]+$ ]] || (( SERVICE_MIN_REQUESTS_FOR_REUSE < 2 )); then
  echo "LEANSTRAL_AUDIT_SERVICE_MIN_REQUESTS_FOR_REUSE must be an integer of at least two" >&2
  exit 2
fi

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  echo "$(timestamp) $*"
}

llama_cpp_parallel_slots() {
  local raw="${1:-}" slots="1" previous=""
  # shellcheck disable=SC2206
  local args=( ${raw} )
  local arg
  for arg in "${args[@]}"; do
    if [[ "${previous}" == "--parallel" || "${previous}" == "-np" ]]; then
      if [[ "${arg}" =~ ^[0-9]+$ ]]; then
        slots="${arg}"
      fi
      previous=""
      continue
    fi
    case "${arg}" in
      --parallel=*)
        slots="${arg#--parallel=}"
        ;;
      -np=*)
        slots="${arg#-np=}"
        ;;
      --parallel|-np)
        previous="${arg}"
        ;;
      *)
        previous=""
        ;;
    esac
  done
  if ! [[ "${slots}" =~ ^[0-9]+$ ]] || (( slots < 1 )); then
    slots="1"
  fi
  printf '%s\n' "${slots}"
}

active_cuda_leanstral_server_info() {
  ps -eo pid=,args= 2>/dev/null | awk '
    /[l]lama-server/ && /[Ll]eanstral/ && (/--device[ =]CUDA[0-9]*/ || /--?(ngl|n-gpu-layers|gpu-layers)[ =][1-9][0-9]*/) {
      port = ""
      ctx = "0"
      pid = $1
      for (i = 2; i <= NF; i++) {
        if ($i == "--port" && (i + 1) <= NF) { port = $(i + 1) }
        if ($i ~ /^--port=/) { port = $i; sub(/^--port=/, "", port) }
        if (($i == "--ctx-size" || $i == "-c" || $i == "--context-size") && (i + 1) <= NF) { ctx = $(i + 1) }
        if ($i ~ /^--ctx-size=/) { ctx = $i; sub(/^--ctx-size=/, "", ctx) }
        if ($i ~ /^--context-size=/) { ctx = $i; sub(/^--context-size=/, "", ctx) }
      }
      if (port != "") { print port ":" ctx ":" pid; exit }
    }
  '
}

active_cuda_leanstral_server_count() {
  ps -eo args= 2>/dev/null | awk '
    /[l]lama-server/ && /[Ll]eanstral/ && (/--device[ =]CUDA[0-9]*/ || /--?(ngl|n-gpu-layers|gpu-layers)[ =][1-9][0-9]*/) { count++ }
    END { print count + 0 }
  '
}

active_cuda_leanstral_port() {
  local info
  info="$(active_cuda_leanstral_server_info)"
  [[ -n "${info}" ]] || return 0
  printf '%s\n' "${info%%:*}"
}

llama_cpp_cuda_available() {
  local candidate devices active_port
  active_port="$(active_cuda_leanstral_port)"
  [[ -n "${active_port}" ]] && return 0
  local candidates=()
  if [[ -n "${IPFS_ACCELERATE_LLAMA_CPP_CLI:-}" ]]; then
    candidates+=("${IPFS_ACCELERATE_LLAMA_CPP_CLI}")
  fi
  if [[ -n "${IPFS_ACCELERATE_LLAMA_CPP_BIN:-}" ]]; then
    candidates+=("${IPFS_ACCELERATE_LLAMA_CPP_BIN}")
  fi
  if command -v llama-cli >/dev/null 2>&1; then
    candidates+=("$(command -v llama-cli)")
  fi
  candidates+=("${HOME}/.cache/ipfs_accelerate_py/llama_cpp/build/bin/llama-cli")
  if command -v llama >/dev/null 2>&1; then
    candidates+=("$(command -v llama)")
  fi

  for candidate in "${candidates[@]}"; do
    [[ -n "${candidate}" && -x "${candidate}" ]] || continue
    case "$(basename "${candidate}")" in
      llama-cli)
        devices="$("${candidate}" --list-devices 2>/dev/null || true)"
        ;;
      *)
        devices="$("${candidate}" cli --list-devices 2>/dev/null || true)"
        ;;
    esac
    [[ "${devices}" == *"CUDA"* ]] && return 0
  done
  return 1
}

configure_llama_cpp_accelerator_defaults() {
  local request lower_request explicit_auto_size explicit_gpu_layers explicit_extra_args gpu_layers_value
  request="${LLAMA_CPP_ACCELERATOR_REQUEST}"
  lower_request="$(printf '%s' "${request}" | tr '[:upper:]' '[:lower:]')"
  explicit_auto_size="${IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING+x}"
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
    LLAMA_CPP_GPU_LAYERS_DEFAULT="auto"
  fi
  if [[ -z "${explicit_auto_size}" ]]; then
    LLAMA_CPP_AUTO_SIZE_DEFAULT="1"
  fi
  if [[ -z "${explicit_extra_args}" ]]; then
    LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT}"
  fi
}

configure_llama_cpp_accelerator_defaults

LLAMA_CPP_EFFECTIVE_EXTRA_ARGS="${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS:-${LLAMA_CPP_EXTRA_ARGS_DEFAULT}}"
LLAMA_CPP_PARALLEL_SLOTS="$(llama_cpp_parallel_slots "${LLAMA_CPP_EFFECTIVE_EXTRA_ARGS}")"
if [[ -z "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-}" ]]; then
  IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE="$(( LLAMA_CPP_CONTEXT_DEFAULT * LLAMA_CPP_PARALLEL_SLOTS ))"
fi
export IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE
mkdir -p "${WORK_DIR}"
ACTIVE_LEANSTRAL_CUDA_SERVER_INFO="$(active_cuda_leanstral_server_info)"
if [[ -n "${ACTIVE_LEANSTRAL_CUDA_SERVER_INFO}" && -z "${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL:-}" ]]; then
  ACTIVE_LEANSTRAL_CUDA_PORT="${ACTIVE_LEANSTRAL_CUDA_SERVER_INFO%%:*}"
  ACTIVE_LEANSTRAL_CUDA_REST="${ACTIVE_LEANSTRAL_CUDA_SERVER_INFO#*:}"
  ACTIVE_LEANSTRAL_CUDA_CONTEXT="${ACTIVE_LEANSTRAL_CUDA_REST%%:*}"
  ACTIVE_LEANSTRAL_CUDA_PID="${ACTIVE_LEANSTRAL_CUDA_REST#*:}"
  if [[ "${ACTIVE_LEANSTRAL_CUDA_CONTEXT}" =~ ^[0-9]+$ ]] && \
     [[ "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE}" =~ ^[0-9]+$ ]] && \
     (( ACTIVE_LEANSTRAL_CUDA_CONTEXT == IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE )); then
    export IPFS_ACCELERATE_LLAMA_CPP_BASE_URL="http://127.0.0.1:${ACTIVE_LEANSTRAL_CUDA_PORT}/v1"
    export IPFS_ACCELERATE_LLAMA_CPP_PORT="${ACTIVE_LEANSTRAL_CUDA_PORT}"
    LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="1"
    LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_CONTEXT_SIZE="${ACTIVE_LEANSTRAL_CUDA_CONTEXT}"
    LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID="${ACTIVE_LEANSTRAL_CUDA_PID}"
  else
    log_line "llama_cpp_reuse_rejected base_url=http://127.0.0.1:${ACTIVE_LEANSTRAL_CUDA_PORT}/v1 existing_context=${ACTIVE_LEANSTRAL_CUDA_CONTEXT:-unknown} required_context=${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE}"
  fi
fi

case "${LEANSTRAL_AUDIT_REQUIRE_CUDA:-0}" in
  1|true|True|TRUE|yes|Yes|YES|on|On|ON)
    if [[ "${LLAMA_CPP_RESOLVED_ACCELERATOR}" != "cuda" ]]; then
      echo "Leanstral CUDA is required but unavailable (resolved=${LLAMA_CPP_RESOLVED_ACCELERATOR})" >&2
      exit 2
    fi
    ;;
esac

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/../ipfs_accelerate_py${PYTHONPATH:+:${PYTHONPATH}}"
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1}"
export IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS="${IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS:-1}"
PROVER_PREFLIGHT_PORTFOLIO="${LEANSTRAL_AUDIT_PROVER_PORTFOLIO:-legal_ir_training}"
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_PROVIDER_FALLBACKS="${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS:-llama_cpp_native,mistral_vibe}"
export LEANSTRAL_AUDIT_REQUIRED_SEMANTIC_FAMILIES="${LEANSTRAL_AUDIT_REQUIRED_SEMANTIC_FAMILIES:-tdfol,dcec,flogic,deontic,knowledge_graph}"
if [[ "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER}" == "1" ]]; then
  export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="0"
else
  export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="${IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART:-1}"
fi
export IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL="${IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL:-1}"
export IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS="${IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS:-900}"
export IPFS_ACCELERATE_LLAMA_CPP_MAX_WARM_SERVERS="${IPFS_ACCELERATE_LLAMA_CPP_MAX_WARM_SERVERS:-1}"
export IPFS_ACCELERATE_LLAMA_CPP_RESTART_ON_CONFIG_MISMATCH="${IPFS_ACCELERATE_LLAMA_CPP_RESTART_ON_CONFIG_MISMATCH:-0}"
export IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS="${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-${LLAMA_CPP_GPU_LAYERS_DEFAULT}}"
export IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING="${IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING:-${LLAMA_CPP_AUTO_SIZE_DEFAULT}}"
export IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS="${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS:-${LLAMA_CPP_EXTRA_ARGS_DEFAULT}}"
export LEANSTRAL_AUDIT_LLAMA_CPP_RESOLVED_ACCELERATOR="${LLAMA_CPP_RESOLVED_ACCELERATOR}"
export LEANSTRAL_AUDIT_BATCH_SIZE="${LEANSTRAL_AUDIT_BATCH_SIZE:-${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT}}"
export LEANSTRAL_AUDIT_BATCH_MIN_SIZE="${LEANSTRAL_AUDIT_BATCH_MIN_SIZE:-1}"
export LEANSTRAL_AUDIT_BATCH_QUEUE_MAX_ITEMS="${LEANSTRAL_AUDIT_BATCH_QUEUE_MAX_ITEMS:-0}"
export LEANSTRAL_AUDIT_BATCH_MAX_WAIT_SECONDS="${LEANSTRAL_AUDIT_BATCH_MAX_WAIT_SECONDS:-0.05}"
export LEANSTRAL_AUDIT_BATCH_TOKEN_BUDGET_BUCKET_SIZE="${LEANSTRAL_AUDIT_BATCH_TOKEN_BUDGET_BUCKET_SIZE:-256}"
export LEANSTRAL_AUDIT_BATCH_DEADLINE_BUCKET_SECONDS="${LEANSTRAL_AUDIT_BATCH_DEADLINE_BUCKET_SECONDS:-1}"
export LEANSTRAL_AUDIT_BATCH_DEADLINE_GUARD_SECONDS="${LEANSTRAL_AUDIT_BATCH_DEADLINE_GUARD_SECONDS:-0.01}"
export LEANSTRAL_AUDIT_BATCH_MAX_WORKERS="${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS:-${LEANSTRAL_AUDIT_BATCH_SIZE}}"
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"
export IPFS_ACCELERATE_LLM_ROUTER_BATCH_WORKERS="${IPFS_ACCELERATE_LLM_ROUTER_BATCH_WORKERS:-${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS}}"
export IPFS_DATASETS_PY_LLM_ROUTER_BATCH_WORKERS="${IPFS_DATASETS_PY_LLM_ROUTER_BATCH_WORKERS:-${LEANSTRAL_AUDIT_BATCH_MAX_WORKERS}}"
AUDIT_PROVIDER_TIMEOUT_SECONDS="${LEANSTRAL_AUDIT_TIMEOUT_SECONDS:-600}"
AUDIT_MAX_WORK_ITEMS="${LEANSTRAL_AUDIT_MAX_WORK_ITEMS:-8}"
AUDIT_MAX_CONCURRENCY="${LEANSTRAL_AUDIT_MAX_CONCURRENCY:-1}"
AUDIT_RUN_TIMEOUT_SECONDS="${LEANSTRAL_AUDIT_RUN_TIMEOUT_SECONDS:-}"
if [[ -z "${AUDIT_RUN_TIMEOUT_SECONDS}" ]]; then
  if [[ "${AUDIT_PROVIDER_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] \
      && [[ "${AUDIT_MAX_WORK_ITEMS}" =~ ^[0-9]+$ ]] \
      && [[ "${AUDIT_MAX_CONCURRENCY}" =~ ^[0-9]+$ ]] \
      && (( AUDIT_MAX_WORK_ITEMS > 0 && AUDIT_MAX_CONCURRENCY > 0 )); then
    AUDIT_RUN_TIMEOUT_SECONDS="$((AUDIT_PROVIDER_TIMEOUT_SECONDS * ((AUDIT_MAX_WORK_ITEMS + AUDIT_MAX_CONCURRENCY - 1) / AUDIT_MAX_CONCURRENCY) + 60))"
  elif [[ "${AUDIT_PROVIDER_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]]; then
    AUDIT_RUN_TIMEOUT_SECONDS="$((AUDIT_PROVIDER_TIMEOUT_SECONDS + 60))"
  else
    AUDIT_RUN_TIMEOUT_SECONDS="${AUDIT_PROVIDER_TIMEOUT_SECONDS}"
  fi
fi
AUDIT_RUN_KILL_AFTER_SECONDS="${LEANSTRAL_AUDIT_RUN_KILL_AFTER_SECONDS:-30}"
CURRENT_AUDIT_PID=""

preflight_core_provers() {
  local preflight_log
  case "${LEANSTRAL_AUDIT_AUTO_INSTALL_CORE_PROVERS:-1}" in
    0|false|False|FALSE|no|No|NO|off|Off|OFF)
      log_line "prover_preflight_skipped reason=disabled"
      return 0
      ;;
  esac
  preflight_log="${WORK_DIR}/${RUN_ID}.prover-preflight.log"
  log_line "prover_preflight_started portfolio=${PROVER_PREFLIGHT_PORTFOLIO} log=${preflight_log}"
  if "${PYTHON_BIN}" -m scripts.setup.ipfs_prover_installer \
    --yes \
    --strict \
    --portfolio "${PROVER_PREFLIGHT_PORTFOLIO}" \
    > "${preflight_log}" 2>&1; then
    log_line "prover_preflight_completed portfolio=${PROVER_PREFLIGHT_PORTFOLIO}"
    return 0
  fi
  log_line "prover_preflight_failed portfolio=${PROVER_PREFLIGHT_PORTFOLIO} log=${preflight_log}"
  return 1
}

current_compiler_commit() {
  git rev-parse HEAD 2>/dev/null || true
}

process_group_for_pid() {
  local pid
  pid="${1:-}"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]'
}

terminate_process_group_or_pid() {
  local pid pgid self_pgid label
  pid="${1:-}"
  label="${2:-process}"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 0
  (( pid > 1 )) || return 0
  if ! kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi
  pgid="$(process_group_for_pid "${pid}" || true)"
  self_pgid="$(process_group_for_pid "$$" || true)"
  if [[ -n "${pgid}" && "${pgid}" != "${self_pgid}" ]]; then
    log_line "terminating_${label}_process_group pgid=${pgid} pid=${pid}"
    kill -TERM "-${pgid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
    sleep 2
    if ps -eo pgid= | awk -v target="${pgid}" '$1 == target {found=1} END {exit found ? 0 : 1}'; then
      log_line "killing_${label}_process_group pgid=${pgid} pid=${pid}"
      kill -KILL "-${pgid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
    fi
  else
    log_line "terminating_${label}_pid pid=${pid}"
    kill -TERM "${pid}" 2>/dev/null || true
    sleep 2
    kill -0 "${pid}" 2>/dev/null && kill -KILL "${pid}" 2>/dev/null || true
  fi
}

kill_leanstral_llama_servers() {
  local reason pid
  reason="${1:-cleanup}"
  case "${LEANSTRAL_AUDIT_PERSIST_SERVICE:-1}" in
    1|true|True|TRUE|yes|Yes|YES|on|On|ON)
      log_line "leanstral_llama_cleanup_skipped reason=${reason} persistent_service=1 generation=${LEANSTRAL_AUDIT_SERVICE_GENERATION:-unknown}"
      return 0
      ;;
  esac
  if [[ "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER}" == "1" ]]; then
    log_line "leanstral_llama_cleanup_skipped reason=${reason} shared_server=1"
    return 0
  fi
  case "${LEANSTRAL_AUDIT_KILL_LLAMA_ON_TIMEOUT:-1}" in
    0|false|False|FALSE|no|No|NO|off|Off|OFF)
      return 0
      ;;
  esac
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    log_line "leanstral_llama_cleanup reason=${reason} pid=${pid}"
    terminate_process_group_or_pid "${pid}" "leanstral_llama"
  done < <(ps -eo pid=,args= | awk '/[l]lama-server/ && /[Ll]eanstral/ {print $1}')
}

stop_current_audit() {
  if [[ -n "${CURRENT_AUDIT_PID}" ]]; then
    terminate_process_group_or_pid "${CURRENT_AUDIT_PID}" "audit"
    CURRENT_AUDIT_PID=""
  fi
}

handle_shutdown() {
  stop_current_audit
  kill_leanstral_llama_servers "watcher_shutdown"
  log_line "audit_companion_interrupted parent_pid=${PARENT_PID}"
  exit 143
}

trap handle_shutdown INT TERM HUP

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

set_persistent_service_identity() {
  local info rest port context pid fingerprint generation start_ticks
  info="${1:-}"
  [[ -n "${info}" ]] || return 1
  port="${info%%:*}"
  rest="${info#*:}"
  context="${rest%%:*}"
  pid="${rest#*:}"
  [[ "${port}" =~ ^[0-9]+$ && "${context}" =~ ^[0-9]+$ && "${pid}" =~ ^[0-9]+$ ]] || return 1
  [[ "${context}" == "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE}" ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  start_ticks="$(ps -o lstart= -p "${pid}" 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//')"
  fingerprint="$("${PYTHON_BIN}" - \
    "${LEANSTRAL_AUDIT_MODEL:-Leanstral}" \
    "${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}" \
    "${context}" \
    "${IPFS_ACCELERATE_LLAMA_CPP_MODEL_REF:-}" \
    "${IPFS_ACCELERATE_LLAMA_CPP_MODEL_PATH:-}" \
    "${IPFS_ACCELERATE_LLAMA_CPP_HF_FILE:-}" <<'PY'
import hashlib
import json
import sys

print(hashlib.sha256(json.dumps(sys.argv[1:], separators=(",", ":"), ensure_ascii=True).encode()).hexdigest())
PY
)"
  generation="$("${PYTHON_BIN}" - "${pid}" "${start_ticks}" "${fingerprint}" <<'PY'
import hashlib
import sys

print("leanstral-generation-" + hashlib.sha256("\0".join(sys.argv[1:]).encode()).hexdigest()[:24])
PY
)"
  export IPFS_ACCELERATE_LLAMA_CPP_BASE_URL="http://127.0.0.1:${port}/v1"
  export IPFS_ACCELERATE_LLAMA_CPP_PORT="${port}"
  export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="0"
  export LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="1"
  export LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_CONTEXT_SIZE="${context}"
  export LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID="${pid}"
  export LEANSTRAL_AUDIT_SERVICE_GENERATION="${generation}"
  export LEANSTRAL_AUDIT_CONTEXT_FINGERPRINT="${fingerprint}"
}

record_persistent_service_generation() {
  local elapsed_seconds state_json
  elapsed_seconds="${1:-0}"
  exec 8>"${SERVICE_STATE_LOCK_PATH}"
  if command -v flock >/dev/null 2>&1; then
    flock 8
  fi
  state_json="$("${PYTHON_BIN}" - \
    "${SERVICE_STATE_PATH}" \
    "${LEANSTRAL_AUDIT_SERVICE_GENERATION}" \
    "${LEANSTRAL_AUDIT_CONTEXT_FINGERPRINT}" \
    "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID}" \
    "${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL}" \
    "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE}" \
    "${LEANSTRAL_AUDIT_SERVICE_RESTART_PENDING}" \
    "${elapsed_seconds}" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys
import time

path = Path(sys.argv[1])
generation, fingerprint, pid, base_url, context, restarted, elapsed = sys.argv[2:]
try:
    previous = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    previous = {}
same_generation = previous.get("generation") == generation
lifetime_restarts = int(previous.get("lifetime_restart_count") or 0)
if restarted == "1":
    lifetime_restarts += 1
identity = {
    "model": os.environ.get("LEANSTRAL_AUDIT_MODEL", "Leanstral"),
    "provider": os.environ.get("LEANSTRAL_AUDIT_PROVIDER", "leanstral_local"),
    "context_size": int(context),
    "context_fingerprint": fingerprint,
}
service_id = "leanstral-service-" + hashlib.sha256(
    json.dumps({"generation": generation, "identity": identity}, sort_keys=True).encode()
).hexdigest()[:24]
payload = dict(previous) if same_generation else {}
payload.update({
    "schema_version": "legal-ir-leanstral-persistent-service-v1",
    "generation": generation,
    "service_generation": generation,
    "service_id": service_id,
    "identity": identity,
    "health": {
        "status": "healthy",
        "cuda_backed": True,
        "provider": identity["provider"],
        "model": identity["model"],
        "base_url": base_url,
        "service_id": service_id,
        "proof_authority": False,
        "context_size": identity["context_size"],
        "context_fingerprint": fingerprint,
        "generation": generation,
    },
    "pid": int(pid),
    "proof_authority": False,
    "model_load_count": 1,
    "model_reload_count": 1 if restarted == "1" else 0,
    "leanstral_service_startup_count": 1,
    "preflight_count": 1,
    "restart_count": 1 if restarted == "1" else int(payload.get("restart_count") or 0),
    "lifetime_restart_count": lifetime_restarts,
    "consecutive_health_failures": 0,
    "health_failure_count": int(previous.get("health_failure_count") or 0),
    "acquire_count": int(payload.get("acquire_count") or 0),
    "reuse_count": int(payload.get("reuse_count") or 0),
    "healthy_cuda_service_reused": bool(payload.get("healthy_cuda_service_reused", False)),
    "queue_seconds": float(payload.get("queue_seconds") or 0.0),
    "inference_seconds": float(payload.get("inference_seconds") or 0.0),
    "verification_seconds": float(payload.get("verification_seconds") or 0.0),
    "restart_seconds": float(payload.get("restart_seconds") or 0.0) + (float(elapsed) if restarted == "1" else 0.0),
    "updated_at": time.time(),
})
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, path)
print(json.dumps(payload, sort_keys=True))
PY
)"
  exec 8>&-
  log_line "leanstral_persistent_service ${state_json}"
}

record_persistent_service_audit() {
  local total_seconds state_json
  total_seconds="${1:-0}"
  exec 8>"${SERVICE_STATE_LOCK_PATH}"
  if command -v flock >/dev/null 2>&1; then
    flock 8
  fi
  state_json="$("${PYTHON_BIN}" - \
    "${SERVICE_STATE_PATH}" \
    "${AUDIT_STDOUT_OUTPUT}" \
    "${total_seconds}" \
    "${SERVICE_MIN_REQUESTS_FOR_REUSE}" <<'PY'
import json
import os
from pathlib import Path
import sys
import time

state_path, stdout_path = Path(sys.argv[1]), Path(sys.argv[2])
total_seconds = max(0.0, float(sys.argv[3]))
minimum_requests = max(2, int(sys.argv[4]))
state = json.loads(state_path.read_text(encoding="utf-8"))
summary = {}
try:
    for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            candidate = json.loads(line)
        except Exception:
            continue
        if isinstance(candidate, dict) and "work_item_count" in candidate:
            summary = candidate
except OSError:
    pass
batch = summary.get("batch_telemetry") if isinstance(summary.get("batch_telemetry"), dict) else {}
request_count = max(
    int(summary.get("llm_call_count") or 0),
    int(batch.get("dispatched_item_count") or 0),
)
queue_seconds = max(0.0, float(batch.get("queue_seconds") or 0.0))
inference_seconds = max(0.0, float(batch.get("inference_seconds") or 0.0))
if inference_seconds == 0.0:
    inference_seconds = max(0.0, float(summary.get("runtime_seconds") or 0.0) - queue_seconds)
verification_seconds = max(0.0, float(batch.get("verification_seconds") or 0.0))
if verification_seconds == 0.0:
    verification_seconds = max(0.0, total_seconds - queue_seconds - inference_seconds)
state["acquire_count"] = int(state.get("acquire_count") or 0) + request_count
state["reuse_count"] = max(0, int(state["acquire_count"]) - 1)
state["leanstral_request_count"] = state["acquire_count"]
state["leanstral_reuse_count"] = state["reuse_count"]
state["queue_seconds"] = float(state.get("queue_seconds") or 0.0) + queue_seconds
state["inference_seconds"] = float(state.get("inference_seconds") or 0.0) + inference_seconds
state["leanstral_inference_seconds"] = state["inference_seconds"]
state["verification_seconds"] = float(state.get("verification_seconds") or 0.0) + verification_seconds
state["healthy_cuda_service_reused"] = bool(
    state.get("health", {}).get("status") == "healthy"
    and state.get("health", {}).get("cuda_backed") is True
    and int(state.get("model_load_count") or 0) == 1
    and int(state.get("preflight_count") or 0) == 1
    and int(state.get("acquire_count") or 0) >= minimum_requests
)
state["updated_at"] = time.time()
temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, state_path)
print(json.dumps(state, sort_keys=True))
PY
)"
  exec 8>&-
  log_line "leanstral_persistent_service ${state_json}"
}

persistent_service_healthy() {
  local info rest context pid count
  count="$(active_cuda_leanstral_server_count)"
  [[ "${count}" == "1" ]] || return 1
  info="$(active_cuda_leanstral_server_info)"
  [[ -n "${info}" ]] || return 1
  rest="${info#*:}"
  context="${rest%%:*}"
  pid="${rest#*:}"
  [[ "${pid}" == "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID}" ]] || return 1
  [[ "${context}" == "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE}" ]] || return 1
  "${PYTHON_BIN}" - "${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL}" <<'PY'
import json
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1].rstrip("/") + "/models", timeout=3.0) as response:
    payload = json.load(response)
if "leanstral" not in json.dumps(payload, sort_keys=True).lower():
    raise SystemExit(1)
PY
}

record_persistent_service_health_failure() {
  local state_json
  exec 8>"${SERVICE_STATE_LOCK_PATH}"
  if command -v flock >/dev/null 2>&1; then
    flock 8
  fi
  state_json="$("${PYTHON_BIN}" - "${SERVICE_STATE_PATH}" <<'PY'
import json
import os
from pathlib import Path
import sys
import time

path = Path(sys.argv[1])
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {"schema_version": "legal-ir-leanstral-persistent-service-v1"}
state["health_failure_count"] = int(state.get("health_failure_count") or 0) + 1
state["consecutive_health_failures"] = int(state.get("consecutive_health_failures") or 0) + 1
if isinstance(state.get("health"), dict):
    state["health"]["status"] = "unhealthy"
state["healthy_cuda_service_reused"] = False
state["updated_at"] = time.time()
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, path)
print(json.dumps(state, sort_keys=True))
PY
)"
  exec 8>&-
  log_line "leanstral_persistent_service ${state_json}"
}

record_persistent_service_health_recovered() {
  "${PYTHON_BIN}" - "${SERVICE_STATE_PATH}" "${SERVICE_STATE_LOCK_PATH}" <<'PY'
import json
import os
from pathlib import Path
import sys
import time

state_path, lock_path = Path(sys.argv[1]), Path(sys.argv[2])
try:
    import fcntl
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a", encoding="utf-8")
    fcntl.flock(lock_handle, fcntl.LOCK_EX)
except Exception:
    lock_handle = None
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
changed = int(state.get("consecutive_health_failures") or 0) != 0
health = state.get("health")
if isinstance(health, dict) and health.get("status") != "healthy":
    health["status"] = "healthy"
    changed = True
if changed:
    state["consecutive_health_failures"] = 0
    state["updated_at"] = time.time()
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)
PY
}

ensure_persistent_service_for_request() {
  local failure_now
  if ! llama_cpp_preflight_if_enabled; then
    return 1
  fi
  if persistent_service_healthy; then
    LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES="0"
    record_persistent_service_health_recovered
    return 0
  fi
  LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES=$((LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES + 1))
  record_persistent_service_health_failure
  log_line "leanstral_service_health_failed generation=${LEANSTRAL_AUDIT_SERVICE_GENERATION:-unknown} consecutive_failures=${LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES} limit=${SERVICE_HEALTH_FAILURE_LIMIT}"
  if (( LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES < SERVICE_HEALTH_FAILURE_LIMIT )); then
    failure_now="$(date +%s)"
    next_retry_epoch=$((failure_now + SERVICE_HEALTH_RETRY_SECONDS))
    return 1
  fi

  log_line "leanstral_service_bounded_restart generation=${LEANSTRAL_AUDIT_SERVICE_GENERATION:-unknown} pid=${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID:-unknown} failures=${LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES}"
  terminate_process_group_or_pid "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID}" "unhealthy_leanstral_service"
  LEANSTRAL_AUDIT_SERVICE_RESTART_PENDING="1"
  LEANSTRAL_AUDIT_SERVICE_PREFLIGHT_COMPLETED="0"
  LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="0"
  LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER_PID=""
  unset IPFS_ACCELERATE_LLAMA_CPP_BASE_URL
  export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="1"
  llama_cpp_preflight_if_enabled
}

llama_cpp_preflight_if_enabled() {
  local provider_chain lower_chain preflight_log active_info active_count started_ns finished_ns elapsed_seconds
  local preflight_auto_size_args=()
  if [[ "${LEANSTRAL_AUDIT_SERVICE_PREFLIGHT_COMPLETED}" == "1" ]]; then
    return 0
  fi
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
  started_ns="$(date +%s%N)"
  exec 9>"${SERVICE_START_LOCK_PATH}"
  if command -v flock >/dev/null 2>&1; then
    if ! flock -w "${LEANSTRAL_AUDIT_SERVICE_LOCK_TIMEOUT_SECONDS:-900}" 9; then
      log_line "llama_cpp_preflight_lock_timeout lock=${SERVICE_START_LOCK_PATH}"
      exec 9>&-
      return 1
    fi
  fi
  active_count="$(active_cuda_leanstral_server_count)"
  if (( active_count > 1 )); then
    log_line "llama_cpp_preflight_rejected reason=multiple_cuda_leanstral_services count=${active_count}"
    exec 9>&-
    return 1
  fi
  active_info="$(active_cuda_leanstral_server_info)"
  if [[ -n "${active_info}" ]] && set_persistent_service_identity "${active_info}"; then
    log_line "llama_cpp_preflight_reused base_url=${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL} generation=${LEANSTRAL_AUDIT_SERVICE_GENERATION}"
    LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="1"
  else
    log_line "llama_cpp_preflight_started log=${preflight_log}"
    LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="0"
  case "$(printf '%s' "${IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)
      preflight_auto_size_args=(--auto-size)
      ;;
  esac
  if [[ "${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-}" == "auto" ]]; then
    preflight_auto_size_args=(--auto-size)
  fi
  if "${PYTHON_BIN}" -m ipfs_accelerate_py.utils.llama_cpp \
    --serve \
    --prefetch-model \
    "${preflight_auto_size_args[@]}" \
    --context-size "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-${LLAMA_CPP_CONTEXT_DEFAULT}}" \
    --gpu-layers "${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-${LLAMA_CPP_GPU_LAYERS_DEFAULT}}" \
    --extra-args "${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS:-${LLAMA_CPP_EXTRA_ARGS_DEFAULT}}" \
    --startup-timeout-seconds "${IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS:-900}" \
    >> "${preflight_log}" 2>&1; then
    log_line "llama_cpp_preflight_completed log=${preflight_log}"
  else
    log_line "llama_cpp_preflight_failed log=${preflight_log}"
      exec 9>&-
      return 1
    fi
    active_count="$(active_cuda_leanstral_server_count)"
    active_info="$(active_cuda_leanstral_server_info)"
    if [[ "${active_count}" != "1" ]] || ! set_persistent_service_identity "${active_info}"; then
      log_line "llama_cpp_preflight_failed reason=service_identity_or_cardinality_mismatch count=${active_count}"
      exec 9>&-
      return 1
    fi
  fi
  finished_ns="$(date +%s%N)"
  elapsed_seconds="$("${PYTHON_BIN}" - "${started_ns}" "${finished_ns}" <<'PY'
import sys
print(max(0.0, (int(sys.argv[2]) - int(sys.argv[1])) / 1_000_000_000.0))
PY
)"
  record_persistent_service_generation "${elapsed_seconds}"
  LEANSTRAL_AUDIT_SERVICE_PREFLIGHT_COMPLETED="1"
  LEANSTRAL_AUDIT_SERVICE_RESTART_PENDING="0"
  LEANSTRAL_AUDIT_SERVICE_CONSECUTIVE_HEALTH_FAILURES="0"
  exec 9>&-
}

last_signature=""
next_retry_epoch=0
current_input_signature=""

update_input_signature() {
  resolve_input_path
  if [[ ! -s "${INPUT_PATH}" ]]; then
    return 1
  fi
  current_input_signature="$(stat -c '%s:%Y' "${INPUT_PATH}" 2>/dev/null)"
}

run_audit_if_due() {
  local signature now failure_now batch_use_mesh_args audit_status audit_timeout_cmd audit_launch_cmd
  local expected_compiler_commit expected_compiler_commit_args
  local audit_started_ns audit_finished_ns audit_elapsed_seconds
  update_input_signature || return 0
  signature="${current_input_signature}"
  now="$(date +%s)"
  if (( now < next_retry_epoch )); then
    return 0
  fi
  if [[ "${signature}" == "${last_signature}" ]] && (( now < next_retry_epoch )); then
    return 0
  fi
  if [[ "${signature}" == "${last_signature}" ]] && (( next_retry_epoch == 0 )); then
    return 0
  fi

  last_signature="${signature}"
  if ! ensure_persistent_service_for_request; then
    return 0
  fi
  # The preflight may block while a local GGUF downloads. Refresh the audit
  # input and reference examples afterwards so startup races do not leave the
  # worker pointed at the parent-run path while the autoencoder writes the
  # child-run export path.
  update_input_signature || return 0
  signature="${current_input_signature}"
  last_signature="${signature}"
  configure_reference_example_args
  expected_compiler_commit="${LEANSTRAL_AUDIT_EXPECTED_COMPILER_COMMIT:-}"
  case "${LEANSTRAL_AUDIT_EXPECTED_COMPILER_COMMIT_AUTO:-1}" in
    0|false|False|FALSE|no|No|NO|off|Off|OFF)
      ;;
    *)
      if [[ -z "${expected_compiler_commit}" ]]; then
        expected_compiler_commit="$(current_compiler_commit)"
      fi
      ;;
  esac
  expected_compiler_commit_args=()
  if [[ -n "${expected_compiler_commit}" ]]; then
    expected_compiler_commit_args=(--expected-compiler-commit "${expected_compiler_commit}")
  fi
  batch_use_mesh_args=()
  case "${LEANSTRAL_AUDIT_BATCH_USE_MESH}" in
    1|true|True|TRUE|yes|Yes|YES|on|On|ON)
      batch_use_mesh_args=(--batch-use-mesh)
      ;;
  esac
  audit_timeout_cmd=()
  if [[ "${AUDIT_RUN_TIMEOUT_SECONDS}" != "0" ]] && command -v timeout >/dev/null 2>&1; then
    audit_timeout_cmd=(
      timeout
      --kill-after="${AUDIT_RUN_KILL_AFTER_SECONDS}s"
      "${AUDIT_RUN_TIMEOUT_SECONDS}s"
    )
  fi
  audit_launch_cmd=()
  if command -v setsid >/dev/null 2>&1; then
    audit_launch_cmd=(setsid)
  fi
  log_line "audit_started signature=${signature} expected_compiler_commit=${expected_compiler_commit:-none}"
  audit_status=0
  audit_started_ns="$(date +%s%N)"
  "${audit_launch_cmd[@]}" "${audit_timeout_cmd[@]}" "${PYTHON_BIN}" scripts/ops/legal_ir/run_leanstral_audit_worker.py \
    --input "${INPUT_PATH}" \
    --cache-dir "${CACHE_DIR}" \
    --checkpoint-path "${CHECKPOINT_PATH}" \
    --max-concurrency "${AUDIT_MAX_CONCURRENCY}" \
    --max-retries "${LEANSTRAL_AUDIT_MAX_RETRIES:-0}" \
    --validation-repair-retries "${LEANSTRAL_AUDIT_VALIDATION_REPAIR_RETRIES:-1}" \
    --timeout-seconds "${AUDIT_PROVIDER_TIMEOUT_SECONDS}" \
    --retry-backoff-seconds "${LEANSTRAL_AUDIT_RETRY_BACKOFF_SECONDS:-2}" \
    "${expected_compiler_commit_args[@]}" \
    --snapshot-selection "${LEANSTRAL_AUDIT_SNAPSHOT_SELECTION:-latest_canonical_snapshot}" \
    --min-snapshot-records "${LEANSTRAL_AUDIT_MIN_SNAPSHOT_RECORDS:-25}" \
    --max-records "${LEANSTRAL_AUDIT_MAX_RECORDS:-0}" \
    --max-work-items "${AUDIT_MAX_WORK_ITEMS}" \
    --required-semantic-families "${LEANSTRAL_AUDIT_REQUIRED_SEMANTIC_FAMILIES}" \
    --family-balanced-selection \
    --max-evidence-packets-per-item "${LEANSTRAL_AUDIT_MAX_EVIDENCE_PACKETS_PER_ITEM:-1}" \
    --evidence-refresh-policy latest_compiler_snapshot \
    --provider "${LEANSTRAL_AUDIT_PROVIDER}" \
    --provider-fallbacks "${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS}" \
    --model "${LEANSTRAL_AUDIT_MODEL:-Leanstral}" \
    --vibe-agent "${LEANSTRAL_AUDIT_VIBE_AGENT:-lean}" \
    --max-new-tokens "${LEANSTRAL_AUDIT_MAX_NEW_TOKENS:-1000}" \
    --prompt-payload-mode "${LEANSTRAL_AUDIT_PROMPT_PAYLOAD_MODE:-daemon}" \
    --context-size-per-slot "${LLAMA_CPP_CONTEXT_DEFAULT}" \
    --context-safety-margin-tokens "${LEANSTRAL_AUDIT_CONTEXT_SAFETY_MARGIN_TOKENS:-512}" \
    --tokenizer-base-url "${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL}" \
    --require-exact-token-count \
    --require-trusted-semantic-context \
    --max-semantic-context-source-chars "${LEANSTRAL_AUDIT_MAX_SEMANTIC_SOURCE_CHARS:-2500}" \
    --max-semantic-context-formulas "${LEANSTRAL_AUDIT_MAX_SEMANTIC_FORMULAS:-6}" \
    --max-semantic-context-obligations "${LEANSTRAL_AUDIT_MAX_SEMANTIC_OBLIGATIONS:-3}" \
    --batch-size "${LEANSTRAL_AUDIT_BATCH_SIZE:-2}" \
    --batch-min-size "${LEANSTRAL_AUDIT_BATCH_MIN_SIZE:-1}" \
    --batch-queue-max-items "${LEANSTRAL_AUDIT_BATCH_QUEUE_MAX_ITEMS:-0}" \
    --batch-max-wait-seconds "${LEANSTRAL_AUDIT_BATCH_MAX_WAIT_SECONDS:-0.05}" \
    --batch-token-budget-bucket-size "${LEANSTRAL_AUDIT_BATCH_TOKEN_BUDGET_BUCKET_SIZE:-256}" \
    --batch-deadline-bucket-seconds "${LEANSTRAL_AUDIT_BATCH_DEADLINE_BUCKET_SECONDS:-1}" \
    --batch-deadline-guard-seconds "${LEANSTRAL_AUDIT_BATCH_DEADLINE_GUARD_SECONDS:-0.01}" \
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
    --prover-timeout-seconds "${LEANSTRAL_PROVER_TIMEOUT_SECONDS:-5}" \
    --hammer-timeout-seconds "${LEANSTRAL_HAMMER_TIMEOUT_SECONDS:-5}" \
    --hammer-max-premises "${LEANSTRAL_HAMMER_MAX_PREMISES:-64}" \
    --hammer-parallel-workers "${LEANSTRAL_HAMMER_PARALLEL_WORKERS:-4}" \
    > "${AUDIT_STDOUT_OUTPUT}" \
    &
  CURRENT_AUDIT_PID=$!
  wait "${CURRENT_AUDIT_PID}" || audit_status=$?
  CURRENT_AUDIT_PID=""
  audit_finished_ns="$(date +%s%N)"
  audit_elapsed_seconds="$("${PYTHON_BIN}" - "${audit_started_ns}" "${audit_finished_ns}" <<'PY'
import sys
print(max(0.0, (int(sys.argv[2]) - int(sys.argv[1])) / 1_000_000_000.0))
PY
)"
  if [[ -s "${AUDIT_STDOUT_OUTPUT}" ]]; then
    cat "${AUDIT_STDOUT_OUTPUT}"
  fi
  if [[ -s "${SERVICE_STATE_PATH}" ]]; then
    record_persistent_service_audit "${audit_elapsed_seconds}"
  fi
  if (( audit_status == 0 )); then
    next_retry_epoch=0
    log_line "audit_completed signature=${signature} report=${PUBLISHED_REPORT_OUTPUT}"
  else
    failure_now="$(date +%s)"
    next_retry_epoch=$((failure_now + FAILURE_BACKOFF_SECONDS))
    if (( audit_status == 124 || audit_status == 137 )); then
      kill_leanstral_llama_servers "audit_timeout"
      log_line "audit_timed_out signature=${signature} timeout_seconds=${AUDIT_RUN_TIMEOUT_SECONDS} status=${audit_status} retry_after_epoch=${next_retry_epoch}"
    else
      log_line "audit_failed signature=${signature} status=${audit_status} retry_after_epoch=${next_retry_epoch}"
    fi
  fi
}

configure_reference_example_args
resolve_input_path
if ! preflight_core_provers; then
  exit 2
fi
log_line "audit_companion_started parent_pid=${PARENT_PID} input=${INPUT_PATH} reference_example_paths=${REFERENCE_EXAMPLE_COUNT}"
log_line "llama_cpp_accelerator_resolved requested=${LLAMA_CPP_ACCELERATOR_REQUEST} resolved=${LEANSTRAL_AUDIT_LLAMA_CPP_RESOLVED_ACCELERATOR} context=${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE} context_per_slot=${LLAMA_CPP_CONTEXT_DEFAULT} parallel_slots=${LLAMA_CPP_PARALLEL_SLOTS} gpu_layers=${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS} auto_sizing=${IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING} extra_args=${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS}"
log_line "leanstral_persistent_service_config state_path=${SERVICE_STATE_PATH} start_lock=${SERVICE_START_LOCK_PATH} state_lock=${SERVICE_STATE_LOCK_PATH} max_warm_servers=${IPFS_ACCELERATE_LLAMA_CPP_MAX_WARM_SERVERS} health_failure_limit=${SERVICE_HEALTH_FAILURE_LIMIT} min_requests_for_reuse=${SERVICE_MIN_REQUESTS_FOR_REUSE}"
log_line "audit_timeouts provider_seconds=${AUDIT_PROVIDER_TIMEOUT_SECONDS} run_seconds=${AUDIT_RUN_TIMEOUT_SECONDS} kill_after_seconds=${AUDIT_RUN_KILL_AFTER_SECONDS}"
while parent_alive; do
  run_audit_if_due
  sleep "${POLL_SECONDS}"
done
run_audit_if_due
log_line "audit_companion_stopped parent_pid=${PARENT_PID}"
