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
LLAMA_CPP_CONTEXT_PER_SLOT_DEFAULT="${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_PER_SLOT:-4096}"
if [[ "${LLAMA_CPP_CONTEXT_PER_SLOT_DEFAULT}" =~ ^[0-9]+$ ]] && \
   [[ "${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT}" =~ ^[0-9]+$ ]]; then
  LLAMA_CPP_CONTEXT_DEFAULT="$((LLAMA_CPP_CONTEXT_PER_SLOT_DEFAULT * LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT))"
else
  LLAMA_CPP_CONTEXT_DEFAULT="4096"
fi
LLAMA_CPP_GPU_LAYERS_DEFAULT="0"
LLAMA_CPP_AUTO_SIZE_DEFAULT="0"
LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT} --device none --no-op-offload --no-kv-offload"
LLAMA_CPP_RESOLVED_ACCELERATOR="cpu"
LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="0"

active_cuda_leanstral_port() {
  ps -eo args= 2>/dev/null | awk '
    /[l]lama-server/ && /[Ll]eanstral/ && /--device[ =]CUDA/ {
      for (i = 1; i <= NF; i++) {
        if ($i == "--port" && (i + 1) <= NF) { print $(i + 1); exit }
        if ($i ~ /^--port=/) { sub(/^--port=/, "", $i); print $i; exit }
      }
    }
  '
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

ACTIVE_LEANSTRAL_CUDA_PORT="$(active_cuda_leanstral_port)"
if [[ -n "${ACTIVE_LEANSTRAL_CUDA_PORT}" && -z "${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL:-}" ]]; then
  export IPFS_ACCELERATE_LLAMA_CPP_BASE_URL="http://127.0.0.1:${ACTIVE_LEANSTRAL_CUDA_PORT}/v1"
  export IPFS_ACCELERATE_LLAMA_CPP_PORT="${ACTIVE_LEANSTRAL_CUDA_PORT}"
  LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER="1"
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
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_PROVIDER_FALLBACKS="${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS:-llama_cpp_native,mistral_vibe}"
if [[ "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER}" == "1" ]]; then
  export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="0"
else
  export IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART="${IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART:-1}"
fi
export IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL="${IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL:-1}"
export IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS="${IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS:-900}"
export IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE="${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-${LLAMA_CPP_CONTEXT_DEFAULT}}"
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
AUDIT_RUN_TIMEOUT_SECONDS="${LEANSTRAL_AUDIT_RUN_TIMEOUT_SECONDS:-}"
if [[ -z "${AUDIT_RUN_TIMEOUT_SECONDS}" ]]; then
  if [[ "${AUDIT_PROVIDER_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]]; then
    AUDIT_RUN_TIMEOUT_SECONDS="$((AUDIT_PROVIDER_TIMEOUT_SECONDS + 60))"
  else
    AUDIT_RUN_TIMEOUT_SECONDS="${AUDIT_PROVIDER_TIMEOUT_SECONDS}"
  fi
fi
AUDIT_RUN_KILL_AFTER_SECONDS="${LEANSTRAL_AUDIT_RUN_KILL_AFTER_SECONDS:-30}"
CURRENT_AUDIT_PID=""
mkdir -p "${WORK_DIR}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  echo "$(timestamp) $*"
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

llama_cpp_preflight_if_enabled() {
  local provider_chain lower_chain preflight_log
  local preflight_auto_size_args=()
  if [[ "${LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER}" == "1" ]]; then
    log_line "llama_cpp_preflight_reused base_url=${IPFS_ACCELERATE_LLAMA_CPP_BASE_URL}"
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
  log_line "llama_cpp_preflight_started log=${preflight_log}"
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
  fi
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
  llama_cpp_preflight_if_enabled
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
  "${audit_launch_cmd[@]}" "${audit_timeout_cmd[@]}" "${PYTHON_BIN}" scripts/ops/legal_ir/run_leanstral_audit_worker.py \
    --input "${INPUT_PATH}" \
    --cache-dir "${CACHE_DIR}" \
    --checkpoint-path "${CHECKPOINT_PATH}" \
    --max-concurrency "${LEANSTRAL_AUDIT_MAX_CONCURRENCY:-1}" \
    --max-retries "${LEANSTRAL_AUDIT_MAX_RETRIES:-0}" \
    --validation-repair-retries "${LEANSTRAL_AUDIT_VALIDATION_REPAIR_RETRIES:-0}" \
    --timeout-seconds "${AUDIT_PROVIDER_TIMEOUT_SECONDS}" \
    --retry-backoff-seconds "${LEANSTRAL_AUDIT_RETRY_BACKOFF_SECONDS:-2}" \
    "${expected_compiler_commit_args[@]}" \
    --snapshot-selection "${LEANSTRAL_AUDIT_SNAPSHOT_SELECTION:-latest_canonical_snapshot}" \
    --min-snapshot-records "${LEANSTRAL_AUDIT_MIN_SNAPSHOT_RECORDS:-25}" \
    --max-records "${LEANSTRAL_AUDIT_MAX_RECORDS:-0}" \
    --max-work-items "${LEANSTRAL_AUDIT_MAX_WORK_ITEMS:-2}" \
    --max-evidence-packets-per-item "${LEANSTRAL_AUDIT_MAX_EVIDENCE_PACKETS_PER_ITEM:-1}" \
    --evidence-refresh-policy latest_compiler_snapshot \
    --provider "${LEANSTRAL_AUDIT_PROVIDER}" \
    --provider-fallbacks "${LEANSTRAL_AUDIT_PROVIDER_FALLBACKS}" \
    --model "${LEANSTRAL_AUDIT_MODEL:-Leanstral}" \
    --vibe-agent "${LEANSTRAL_AUDIT_VIBE_AGENT:-lean}" \
    --max-new-tokens "${LEANSTRAL_AUDIT_MAX_NEW_TOKENS:-512}" \
    --prompt-payload-mode "${LEANSTRAL_AUDIT_PROMPT_PAYLOAD_MODE:-compact}" \
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
    &
  CURRENT_AUDIT_PID=$!
  wait "${CURRENT_AUDIT_PID}" || audit_status=$?
  CURRENT_AUDIT_PID=""
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
log_line "audit_companion_started parent_pid=${PARENT_PID} input=${INPUT_PATH} reference_example_paths=${REFERENCE_EXAMPLE_COUNT}"
log_line "llama_cpp_accelerator_resolved requested=${LLAMA_CPP_ACCELERATOR_REQUEST} resolved=${LEANSTRAL_AUDIT_LLAMA_CPP_RESOLVED_ACCELERATOR} context=${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE} gpu_layers=${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS} auto_sizing=${IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING} extra_args=${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS}"
log_line "audit_timeouts provider_seconds=${AUDIT_PROVIDER_TIMEOUT_SECONDS} run_seconds=${AUDIT_RUN_TIMEOUT_SECONDS} kill_after_seconds=${AUDIT_RUN_KILL_AFTER_SECONDS}"
while parent_alive; do
  run_audit_if_due
  sleep "${POLL_SECONDS}"
done
run_audit_if_due
log_line "audit_companion_stopped parent_pid=${PARENT_PID}"
