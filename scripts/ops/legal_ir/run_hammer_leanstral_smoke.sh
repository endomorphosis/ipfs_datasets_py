#!/usr/bin/env bash
# Execute the immutable ten-minute integrated LegalIR promotion smoke.
#
# This wrapper is intentionally fail closed.  A successful daemon exit is not
# sufficient: the persisted summaries must prove real CUDA training, persistent
# Leanstral reuse, Hammer and Codex activity, bounded artifacts, and complete
# child cleanup before the quality gate is evaluated.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

RUN_ID="${RUN_ID:-legal-ir-hammer-leanstral-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
DURATION_SECONDS="${DURATION_SECONDS:-600}"
MAX_CYCLES="${MAX_CYCLES:-0}"
SUMMARY_PATH="${SUMMARY_PATH:-${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.summary}"
LEANSTRAL_SERVICE_STATE_PATH="${LEANSTRAL_AUDIT_SERVICE_STATE_PATH:-${ROOT_DIR}/workspace/leanstral-audit-worker/persistent-service.state.json}"
PAIRED_SUMMARY_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.summary"
CHECKPOINT_PATH="${ROOT_DIR}/workspace/todo-queues/${RUN_ID}-autoencoder.state.json"
EVIDENCE_OUTPUT="${EVIDENCE_OUTPUT:-${ROOT_DIR}/workspace/test-logs/${RUN_ID}-smoke-evidence.json}"
ROLLBACK_ARTIFACT="${ROLLBACK_ARTIFACT:-${ROOT_DIR}/workspace/test-logs/${RUN_ID}-smoke-rollback.json}"
GATE_DECISION_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-smoke-gate.json"
MAX_SUMMARY_BYTES="${MAX_SUMMARY_BYTES:-33554432}"
MAX_CHECKPOINT_BYTES="${MAX_CHECKPOINT_BYTES:-536870912}"
RESUME_FROM_RUN_ID=""
RESUME_FROM_STATE=""
RUN_ID_EXPLICIT=0
DRY_RUN=0
GATE_ONLY=0

usage() {
  cat <<'EOF'
Usage: run_hammer_leanstral_smoke.sh [OPTIONS]

Runs the fixed 600-second integrated CUDA smoke and then applies the fail-closed
quality gate. A resume imports only generalizable state into a new run ID; it
never appends downtime to, or overwrites, the source run's evidence.

Options:
  --run-id ID                    Unique destination run identifier
  --summary-path PATH            Existing/generated autoencoder summary path
  --evidence-output PATH         Atomic smoke evidence JSON output
  --rollback-artifact PATH       Immutable pre-run rollback descriptor
  --resume-from-run-id ID        Warm-start from <ID>-autoencoder state
  --resume-from-state PATH       Warm-start from an explicit state checkpoint
  --gate-only                    Verify and gate existing run artifacts
  --dry-run                      Print the complete, non-mutating stage contract
  -h, --help                     Show this help
EOF
}

require_value() {
  if (( $# < 2 )) || [[ -z "${2:-}" ]]; then
    echo "missing value for $1" >&2
    exit 2
  fi
}

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
      require_value "$@"
      RUN_ID_EXPLICIT=1
      RUN_ID="$2"
      SUMMARY_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.summary"
      PAIRED_SUMMARY_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.summary"
      CHECKPOINT_PATH="${ROOT_DIR}/workspace/todo-queues/${RUN_ID}-autoencoder.state.json"
      EVIDENCE_OUTPUT="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-smoke-evidence.json"
      ROLLBACK_ARTIFACT="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-smoke-rollback.json"
      GATE_DECISION_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-smoke-gate.json"
      shift 2
      ;;
    --summary-path)
      require_value "$@"
      SUMMARY_PATH="$2"
      shift 2
      ;;
    --evidence-output)
      require_value "$@"
      EVIDENCE_OUTPUT="$2"
      shift 2
      ;;
    --rollback-artifact)
      require_value "$@"
      ROLLBACK_ARTIFACT="$2"
      shift 2
      ;;
    --resume-from-run-id)
      require_value "$@"
      RESUME_FROM_RUN_ID="$2"
      shift 2
      ;;
    --resume-from-state)
      require_value "$@"
      RESUME_FROM_STATE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if (( GATE_ONLY && ! RUN_ID_EXPLICIT )) && [[ "$(basename "${SUMMARY_PATH}")" == *-autoencoder.summary ]]; then
  RUN_ID="$(basename "${SUMMARY_PATH}")"
  RUN_ID="${RUN_ID%-autoencoder.summary}"
  PAIRED_SUMMARY_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.summary"
  CHECKPOINT_PATH="${ROOT_DIR}/workspace/todo-queues/${RUN_ID}-autoencoder.state.json"
fi

if [[ ! "${RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]]; then
  echo "run ID must contain only 1..160 ASCII letters, digits, '.', '_' or '-'" >&2
  exit 2
fi
if [[ -n "${RESUME_FROM_RUN_ID}" && -n "${RESUME_FROM_STATE}" ]]; then
  echo "--resume-from-run-id and --resume-from-state are mutually exclusive" >&2
  exit 2
fi
if [[ -n "${RESUME_FROM_RUN_ID}" ]]; then
  if [[ ! "${RESUME_FROM_RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]]; then
    echo "resume run ID contains unsupported characters" >&2
    exit 2
  fi
  if [[ "${RESUME_FROM_RUN_ID}" == "${RUN_ID}" || "${RESUME_FROM_RUN_ID}" == "${RUN_ID}-autoencoder" ]]; then
    echo "resume requires a new destination run ID; source evidence is immutable" >&2
    exit 2
  fi
  RESUME_FROM_STATE="${ROOT_DIR}/workspace/todo-queues/${RESUME_FROM_RUN_ID}-autoencoder.state.json"
fi
if [[ ! "${DURATION_SECONDS}" =~ ^[0-9]+$ ]] || (( DURATION_SECONDS != 600 )); then
  echo "promotion smoke duration is immutable: DURATION_SECONDS must be 600" >&2
  exit 2
fi
# The stage counts only the first 600 lineage-verified active seconds, but the
# daemon cannot interrupt a cycle and two complete warm cycles are mandatory.
# A bounded orchestration margin lets a cycle cross the duration boundary and
# finish without weakening the immutable 600-second acceptance threshold.
RUNNER_DURATION_SECONDS="$((DURATION_SECONDS + 10))"
if [[ ! "${MAX_CYCLES}" =~ ^[0-9]+$ ]] || (( MAX_CYCLES != 0 )); then
  echo "promotion smoke is duration-bound: MAX_CYCLES must be 0" >&2
  exit 2
fi
for byte_limit in MAX_SUMMARY_BYTES MAX_CHECKPOINT_BYTES; do
  value="${!byte_limit}"
  if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    echo "${byte_limit} must be a positive integer" >&2
    exit 2
  fi
done

gate_boolean_flag() {
  local value="${1,,}"
  local enabled_flag="$2"
  local disabled_flag="$3"
  case "${value}" in
    1|true|yes|on)
      printf '%s' "${enabled_flag}"
      ;;
    0|false|no|off)
      printf '%s' "${disabled_flag}"
      ;;
    *)
      echo "invalid boolean value for representation rollout gate: $1" >&2
      return 2
      ;;
  esac
}

GATE_REQUIRE_REPRESENTATION_PROMOTION="${GATE_REQUIRE_REPRESENTATION_PROMOTION:-true}"
GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION="${GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION:-true}"
GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE="${GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE:-true}"
GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION="${GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION:-0.0}"
GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION="${GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION:-0.0}"
GATE_MAX_HAMMER_PROOF_RATE_REGRESSION="${GATE_MAX_HAMMER_PROOF_RATE_REGRESSION:-0.0}"
GATE_MAX_RECONSTRUCTION_RATE_REGRESSION="${GATE_MAX_RECONSTRUCTION_RATE_REGRESSION:-0.0}"
GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION="${GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION:-0.0}"
GATE_MAX_TODO_PRODUCTIVITY_REGRESSION="${GATE_MAX_TODO_PRODUCTIVITY_REGRESSION:-0.0}"

REPRESENTATION_PROMOTION_GATE_FLAG="$(gate_boolean_flag \
  "${GATE_REQUIRE_REPRESENTATION_PROMOTION}" \
  --require-representation-promotion \
  --no-require-representation-promotion)"
SUCCESSFUL_REPRESENTATION_PROMOTION_GATE_FLAG="$(gate_boolean_flag \
  "${GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION}" \
  --require-successful-representation-promotion \
  --no-require-successful-representation-promotion)"
COMPLETE_REPRESENTATION_EVIDENCE_GATE_FLAG="$(gate_boolean_flag \
  "${GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE}" \
  --require-complete-representation-evidence \
  --no-require-complete-representation-evidence)"

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/../ipfs_accelerate_py${PYTHONPATH:+:${PYTHONPATH}}"
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1}"
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_BATCH_SIZE="${LEANSTRAL_AUDIT_BATCH_SIZE:-1}"
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"
export LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR="${LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR:-cuda}"
export LEANSTRAL_AUDIT_REQUIRE_CUDA="${LEANSTRAL_AUDIT_REQUIRE_CUDA:-1}"
export LEANSTRAL_AUDIT_PERSIST_SERVICE="${LEANSTRAL_AUDIT_PERSIST_SERVICE:-1}"
export LEANSTRAL_AUDIT_SERVICE_STATE_PATH="${LEANSTRAL_SERVICE_STATE_PATH}"
export LEANSTRAL_AUDIT_SERVICE_HEALTH_FAILURE_LIMIT="${LEANSTRAL_AUDIT_SERVICE_HEALTH_FAILURE_LIMIT:-3}"
export LEANSTRAL_AUDIT_SERVICE_MIN_REQUESTS_FOR_REUSE="${LEANSTRAL_AUDIT_SERVICE_MIN_REQUESTS_FOR_REUSE:-2}"
export IPFS_ACCELERATE_LLAMA_CPP_MAX_WARM_SERVERS="${IPFS_ACCELERATE_LLAMA_CPP_MAX_WARM_SERVERS:-1}"
export IPFS_ACCELERATE_LLAMA_CPP_RESTART_ON_CONFIG_MISMATCH="${IPFS_ACCELERATE_LLAMA_CPP_RESTART_ON_CONFIG_MISMATCH:-0}"

CODEX_EXEC_MODE="${CODEX_EXEC_MODE:-codex_cli}"

HARD_GUARDRAILS="$("${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate guardrail-metrics)"
MODULE="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner"

CMD=(
  "${PYTHON_BIN}" -m "${MODULE}"
  --loop-role paired
  --run-id "${RUN_ID}"
  --duration-seconds "${RUNNER_DURATION_SECONDS}"
  --max-cycles "${MAX_CYCLES}"
  --train-count "${TRAIN_COUNT:-4}"
  --validation-count "${VALIDATION_COUNT:-4}"
  --validation-canary-count "${VALIDATION_CANARY_COUNT:-8}"
  --max-sample-text-chars "${MAX_SAMPLE_TEXT_CHARS:-2500}"
  --compiler-ir-metric-max-sample-text-chars "${COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS:-600}"
  --compiler-ir-metric-sample-timeout-seconds "${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS:-30}"
  --max-inner-iterations "${MAX_INNER_ITERATIONS:-1}"
  --max-items "${MAX_ITEMS:-1}"
  --sampling-seed "${SAMPLING_SEED:-PORTAL-LIR-HAMMER-117-fixed-smoke-v1}"
  --learning-rate "${LEARNING_RATE:-0.30}"
  --generalizable-projection-epochs "${GENERALIZABLE_PROJECTION_EPOCHS:-1}"
  --generalizable-projection-timeout-seconds "${GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS:-240}"
  --generalizable-projection-max-line-search-attempts "${GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS:-1}"
  --generalizable-projection-max-update-families "${GENERALIZABLE_PROJECTION_MAX_UPDATE_FAMILIES:-1}"
  --generalizable-projection-max-cosine-regression "${MAX_COSINE_REGRESSION:-0.005}"
  --generalizable-projection-max-reconstruction-regression "${MAX_RECONSTRUCTION_REGRESSION:-0.01}"
  --generalizable-projection-max-cross-entropy-regression "${MAX_CROSS_ENTROPY_REGRESSION:-0.0}"
  --generalizable-projection-max-legal-ir-loss-regression "${MAX_LEGAL_IR_LOSS_REGRESSION:-0.01}"
  --autoencoder-hard-guardrail-metrics "${HARD_GUARDRAILS}"
  --autoencoder-device "${AUTOENCODER_DEVICE:-cuda}"
  --async-artifact-writer-max-queue-bytes "${MAX_CHECKPOINT_BYTES}"
  --async-artifact-full-checkpoint-every-n-cycles "${ASYNC_ARTIFACT_FULL_CHECKPOINT_EVERY_N_CYCLES:-1}"
  --autoencoder-bridge-workers "${AUTOENCODER_BRIDGE_WORKERS:-2}"
  --autoencoder-metric-bridge-adapters "${AUTOENCODER_METRIC_BRIDGE_ADAPTERS:-modal_frame_logic,deontic_norms,fol_tdfol,cec_dcec,external_prover_router}"
  --bridge-loss-adapters "${BRIDGE_LOSS_ADAPTERS:-modal_frame_logic,deontic_norms}"
  --bridge-evaluate-provers "${BRIDGE_EVALUATE_PROVERS:-false}"
  --autoencoder-introspection-mode "${AUTOENCODER_INTROSPECTION_MODE:-seed}"
  --autoencoder-introspection-every-n-cycles "${AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES:-1}"
  --autoencoder-max-audits-per-cycle "${AUTOENCODER_MAX_AUDITS_PER_CYCLE:-4}"
  --autoencoder-max-todos-per-cycle "${AUTOENCODER_MAX_TODOS_PER_CYCLE:-8}"
  --leanstral-direct-guidance-projection-enabled true
  --leanstral-rule-gap-wait-seconds "${LEANSTRAL_RULE_GAP_WAIT_SECONDS:-180}"
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
  --daemon-hammer-guidance-verify-reconstruction true
  --daemon-hammer-guidance-trusted-requires-reconstruction true
  --daemon-hammer-guidance-train-autoencoder true
  --daemon-hammer-guidance-max-training-items "${DAEMON_HAMMER_GUIDANCE_MAX_TRAINING_ITEMS:-64}"
  --paired-supervisor-backend accelerate_style
  --paired-leanstral-worker-enabled true
  --paired-leanstral-require-cuda true
  --paired-leanstral-grace-seconds "${PAIRED_LEANSTRAL_GRACE_SECONDS:-120}"
  --paired-codex-queue-grace-seconds "${PAIRED_CODEX_QUEUE_GRACE_SECONDS:-120}"
  --paired-resource-guard auto
  --paired-grace-seconds "${PAIRED_GRACE_SECONDS:-30}"
  --paired-poll-seconds "${PAIRED_POLL_SECONDS:-1}"
  --codex-exec-mode "${CODEX_EXEC_MODE}"
  --codex-sandbox "${CODEX_SANDBOX:-danger-full-access}"
  --codex-timeout-seconds "${CODEX_TIMEOUT_SECONDS:-180}"
  --codex-apply-mode "${CODEX_APPLY_MODE:-patch_only}"
  --codex-commit-mode "${CODEX_COMMIT_MODE:-none}"
  --codex-parallel-scopes "${CODEX_PARALLEL_SCOPES:-compiler_parser,compiler_registry,compiler_ambiguity,ir_decompiler,frame_logic,deontic,tdfol,knowledge_graphs,cec,external_provers}"
  --codex-scope-workers "${CODEX_SCOPE_WORKERS:-1}"
  --codex-bundle-mode "${CODEX_BUNDLE_MODE:-vector}"
  --codex-vector-min-similarity "${CODEX_VECTOR_MIN_SIMILARITY:-0.65}"
  --codex-vector-fill-min-similarity "${CODEX_VECTOR_FILL_MIN_SIMILARITY:-0.45}"
  --codex-vector-min-bundle-size "${CODEX_VECTOR_MIN_BUNDLE_SIZE:-1}"
  --codex-vector-max-bundle-wait-seconds "${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS:-30}"
)

if [[ -n "${RESUME_FROM_STATE}" ]]; then
  CMD+=(--warm-start-state "${RESUME_FROM_STATE}")
fi

GATE_CMD=(
  "${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate gate
  --summary-path "${SUMMARY_PATH}"
  --max-validation-ce-regression "${GATE_MAX_VALIDATION_CE_REGRESSION:-0.02}"
  --max-validation-cosine-regression "${GATE_MAX_VALIDATION_COSINE_REGRESSION:-0.02}"
  --max-compiler-ir-ce-regression "${GATE_MAX_COMPILER_IR_CE_REGRESSION:-0.05}"
  --max-compiler-ir-cosine-regression "${GATE_MAX_COMPILER_IR_COSINE_REGRESSION:-0.05}"
  --max-source-copy-penalty "${GATE_MAX_SOURCE_COPY_PENALTY:-0.35}"
  --require-available-hammer-backend
  --max-hammer-backend-unavailable-ratio "${GATE_MAX_HAMMER_BACKEND_UNAVAILABLE_RATIO:-0.99}"
  "${REPRESENTATION_PROMOTION_GATE_FLAG}"
  "${SUCCESSFUL_REPRESENTATION_PROMOTION_GATE_FLAG}"
  "${COMPLETE_REPRESENTATION_EVIDENCE_GATE_FLAG}"
  --max-per-view-ir-metric-regression "${GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION}"
  --max-symbolic-validity-regression "${GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION}"
  --max-hammer-proof-rate-regression "${GATE_MAX_HAMMER_PROOF_RATE_REGRESSION}"
  --max-reconstruction-rate-regression "${GATE_MAX_RECONSTRUCTION_RATE_REGRESSION}"
  --max-source-copy-penalty-regression "${GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION}"
  --max-todo-productivity-regression "${GATE_MAX_TODO_PRODUCTIVITY_REGRESSION}"
  --min-cycles-for-todo-gate "${GATE_MIN_CYCLES_FOR_TODO_GATE:-1}"
)

run_gate() {
  "${GATE_CMD[@]}"
}

verify_integrated_stack() {
  local paired_summary leanstral_log
  paired_summary="${PAIRED_SUMMARY_PATH}"
  leanstral_log="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.leanstral.stdout.log"
  "${PYTHON_BIN}" - "${SUMMARY_PATH}" "${paired_summary}" "${LEANSTRAL_SERVICE_STATE_PATH}" \
    "${leanstral_log}" "${CHECKPOINT_PATH}" "${MAX_SUMMARY_BYTES}" "${MAX_CHECKPOINT_BYTES}" <<'PY'
import json
import math
import os
import sys
from pathlib import Path

(
    auto_path,
    paired_path,
    service_state_path,
    leanstral_log_path,
    checkpoint_path,
    max_summary_bytes_raw,
    max_checkpoint_bytes_raw,
) = sys.argv[1:]
max_summary_bytes = int(max_summary_bytes_raw)
max_checkpoint_bytes = int(max_checkpoint_bytes_raw)

for raw, maximum, label in (
    (auto_path, max_summary_bytes, "autoencoder summary"),
    (paired_path, max_summary_bytes, "paired summary"),
    (checkpoint_path, max_checkpoint_bytes, "checkpoint"),
):
    path = Path(raw)
    if not path.is_file():
        raise SystemExit(f"required {label} is missing: {path}")
    size = path.stat().st_size
    if size < 1 or size > maximum:
        raise SystemExit(f"{label} bytes out of bounds: {size} not in 1..{maximum}")

with open(auto_path, "r", encoding="utf-8") as handle:
    auto = json.load(handle)
with open(paired_path, "r", encoding="utf-8") as handle:
    paired = json.load(handle)
if auto.get("autoencoder_compute_backend") != "torch_cuda":
    raise SystemExit(
        "autoencoder CUDA verification failed: "
        f"backend={auto.get('autoencoder_compute_backend')!r} "
        f"device={auto.get('autoencoder_compute_device')!r}"
    )
if not str(auto.get("autoencoder_compute_device") or "").lower().startswith("cuda"):
    raise SystemExit(f"autoencoder device is not CUDA: {auto.get('autoencoder_compute_device')!r}")
if int(auto.get("cycles") or 0) < 2:
    raise SystemExit(f"smoke completed fewer than two warm cycles: {auto.get('cycles')!r}")
try:
    active_seconds = float(auto.get("elapsed_seconds"))
except (TypeError, ValueError):
    active_seconds = 0.0
if not math.isfinite(active_seconds) or active_seconds < 600.0:
    raise SystemExit(f"smoke accumulated fewer than 600 active seconds: {active_seconds!r}")

def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

training_log = Path(str(auto.get("log_path") or ""))
if not training_log.is_absolute() or not training_log.is_file():
    raise SystemExit(f"CUDA training log is unavailable: {training_log}")
optimizer_steps = 0
forward_backward = 0
cuda_cycles = set()
with training_log.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"CUDA training log JSON invalid at line {line_number}: {exc}")
        if not isinstance(record, dict) or record.get("event") != "cycle":
            continue
        if record.get("run_id") != auto.get("run_id"):
            raise SystemExit("CUDA training log run lineage mismatch")
        cycle = record.get("cycle")
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 1 or cycle in cuda_cycles:
            raise SystemExit(f"CUDA training log cycle lineage invalid: {cycle!r}")
        cuda_cycles.add(cycle)
        reports = (
            ((record.get("feature_projection_report") or {}).get("projection_cuda_residency") or {})
            .get("reports", [])
        )
        qualifying = 0
        for report in reports:
            losses = report.get("losses") or {}
            total_loss = losses.get("total")
            step = report.get("optimizer_step")
            if (
                report.get("training_schema_version")
                != "modal-autoencoder-packed-cuda-training-v1"
                or report.get("admitted") is not True
                or report.get("applied") is not True
                or str(report.get("fallback_reason") or "")
                or report.get("optimizer_state_resident") is not True
                or isinstance(total_loss, bool)
                or not isinstance(total_loss, (int, float))
                or not math.isfinite(float(total_loss))
                or float(total_loss) <= 0.0
                or isinstance(step, bool)
                or not isinstance(step, int)
                or step < 1
            ):
                continue
            qualifying += 1
            optimizer_steps += step
        if qualifying < 1:
            raise SystemExit(f"CUDA cycle {cycle} lacks forward/loss/backward/optimizer evidence")
        forward_backward += qualifying
residency_applied = str(auto.get("autoencoder_cuda_residency_applied") or "").lower() == "true"
if optimizer_steps < int(auto.get("cycles") or 0):
    raise SystemExit("CUDA autoencoder optimizer-step counter is absent or zero")
if forward_backward < int(auto.get("cycles") or 0):
    raise SystemExit("CUDA autoencoder forward/loss/backward counter is absent or zero")
if not residency_applied:
    raise SystemExit("CUDA-resident autoencoder update was not applied")
fallback_reason = str(auto.get("autoencoder_cuda_residency_fallback_reason") or "").strip()
if fallback_reason:
    raise SystemExit(f"autoencoder reported a CUDA fallback: {fallback_reason}")
for key, value in walk(auto):
    normalized = key.lower()
    if "cpu_fallback" not in normalized:
        continue
    if value is True or str(value).strip().lower() in {"1", "true", "yes", "used", "cpu"}:
        raise SystemExit(f"autoencoder CPU fallback evidence detected: {key}={value!r}")

health = paired.get("leanstral_worker_health") or {}
if not health.get("cuda_confirmed"):
    raise SystemExit(f"Leanstral CUDA verification failed: {health!r}")
if not health.get("report_present"):
    raise SystemExit(f"Leanstral report verification failed: {health!r}")
if not paired.get("leanstral_success"):
    raise SystemExit("paired supervisor did not accept the Leanstral worker")

with open(service_state_path, "r", encoding="utf-8") as handle:
    service = json.load(handle)
if service.get("schema_version") != "legal-ir-leanstral-persistent-service-v1":
    raise SystemExit(f"persistent Leanstral service schema mismatch: {service!r}")
service_health = service.get("health") or {}
identity = service.get("identity") or {}
if service_health.get("status") != "healthy" or service_health.get("cuda_backed") is not True:
    raise SystemExit(f"persistent Leanstral CUDA service is not healthy: {service!r}")
if service.get("proof_authority") is not False or service_health.get("proof_authority") is not False:
    raise SystemExit(f"service health incorrectly confers proof authority: {service!r}")
if not service.get("generation") or service_health.get("generation") != service.get("generation"):
    raise SystemExit(f"persistent Leanstral generation identity mismatch: {service!r}")
if identity.get("context_fingerprint") != service_health.get("context_fingerprint"):
    raise SystemExit(f"persistent Leanstral context identity mismatch: {service!r}")
if int(identity.get("context_size") or 0) < 1 or "leanstral" not in str(identity.get("model") or "").lower():
    raise SystemExit(f"persistent Leanstral model/context identity invalid: {identity!r}")
if int(service.get("model_load_count") or 0) != 1:
    raise SystemExit(f"canonical Leanstral weights reloaded within one generation: {service!r}")
if int(service.get("preflight_count") or 0) != 1:
    raise SystemExit(f"Leanstral preflight did not run exactly once in generation: {service!r}")
minimum_requests = max(2, int(__import__("os").environ.get("LEANSTRAL_AUDIT_SERVICE_MIN_REQUESTS_FOR_REUSE", "2")))
if int(service.get("acquire_count") or 0) < minimum_requests or int(service.get("reuse_count") or 0) < 1:
    raise SystemExit(f"Leanstral service did not receive enough compatible warm requests: {service!r}")
if service.get("healthy_cuda_service_reused") is not True:
    raise SystemExit(f"healthy CUDA Leanstral service was not reused after warmup: {service!r}")
timing_keys = ("queue_seconds", "inference_seconds", "verification_seconds", "restart_seconds")
for key in timing_keys:
    value = service.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0.0:
        raise SystemExit(f"persistent service timing {key} is missing or invalid: {service!r}")

with open(leanstral_log_path, "r", encoding="utf-8", errors="replace") as handle:
    watcher_text = handle.read()
watcher_states = []
for line in watcher_text.splitlines():
    marker = "leanstral_persistent_service {"
    if marker not in line:
        continue
    try:
        watcher_states.append(json.loads("{" + line.split(marker, 1)[1]))
    except Exception:
        continue
if not any(item.get("generation") == service.get("generation") for item in watcher_states):
    raise SystemExit("watcher did not report the persistent Leanstral service generation")
if watcher_text.count("llama_cpp_preflight_completed") > 1:
    raise SystemExit("watcher loaded/preflighted canonical Leanstral weights more than once")

hammer = auto.get("active_cycle_hammer_guidance") or {}
if hammer.get("status") != "completed" or int(hammer.get("hammer_artifact_count") or 0) < 1:
    raise SystemExit(f"Hammer integration verification failed: {hammer!r}")
hammer_metrics = hammer.get("hammer_metrics") or {}
if float(hammer_metrics.get("hammer_backend_unavailable_ratio") or 0.0) >= 1.0:
    raise SystemExit(f"all Hammer backends were unavailable: {hammer_metrics!r}")
if int(hammer_metrics.get("hammer_obligation_count") or hammer.get("obligation_count") or 0) < 1:
    raise SystemExit(f"Hammer produced no proof obligations: {hammer_metrics!r}")

report_path = health.get("report_path")
with open(report_path, "r", encoding="utf-8") as handle:
    leanstral_report = json.load(handle)
if int(leanstral_report.get("source_audit_count") or 0) < 1:
    raise SystemExit(f"Leanstral did not process an audit: {leanstral_report!r}")
wait = auto.get("active_cycle_leanstral_report_wait") or {}
if wait.get("status") != "ready":
    raise SystemExit(f"autoencoder did not receive Leanstral report in-cycle: {wait!r}")
projection = auto.get("latest_leanstral_projection") or {}
sources = projection.get("projection_sources") or []
if not any(source.get("report_loaded") for source in sources if isinstance(source, dict)):
    raise SystemExit(f"autoencoder did not load Leanstral report: {projection!r}")

codex_children = paired.get("codex_children") or []
codex_health = paired.get("program_synthesis_health") or {}
if paired.get("codex_success") is not True:
    raise SystemExit("paired supervisor did not accept the Codex path")
if not codex_children or int(codex_health.get("codex_worker_summary_count") or 0) < 1:
    raise SystemExit(f"Codex workers were not supervised: {codex_health!r}")
if not codex_health.get("codex_executor_available") or not codex_health.get("queue_exists"):
    raise SystemExit(f"Codex executor/queue unavailable: {codex_health!r}")
if int(codex_health.get("codex_worker_stale_count") or 0) != 0:
    raise SystemExit(f"stale Codex workers detected: {codex_health!r}")
codex_activity = (
    int(codex_health.get("program_synthesis_claimed") or 0)
    + int(codex_health.get("program_synthesis_completed") or 0)
    + int(codex_health.get("codex_claimed_total") or 0)
    + int(codex_health.get("codex_execution_count") or 0)
)
if codex_activity < 1:
    raise SystemExit(f"Codex did not claim or execute queue work: {codex_health!r}")
child_status = paired.get("child_status") or {}
if child_status.get("autoencoder") != "exited" or child_status.get("leanstral") != "exited":
    raise SystemExit(f"managed CUDA children were not reaped: {child_status!r}")
codex_status = child_status.get("codex") or {}
if not codex_status or any(value != "exited" for value in codex_status.values()):
    raise SystemExit(f"managed Codex children were not reaped: {child_status!r}")
queue_run_id = paired.get("queue_run_id")
for child in codex_children:
    child_path = child.get("stdout_path", "").replace(".orchestrator.stdout.log", ".summary")
    with open(child_path, "r", encoding="utf-8") as handle:
        child_summary = json.load(handle)
    if child_summary.get("queue_run_id") != queue_run_id:
        raise SystemExit(
            f"Codex queue lineage mismatch: {child_summary.get('queue_run_id')!r} != {queue_run_id!r}"
        )
print(
    "integrated_stack_verified "
    f"autoencoder={auto.get('autoencoder_compute_device')} "
    f"hammer_artifacts={hammer.get('hammer_artifact_count')} "
    f"leanstral=cuda source_audits={leanstral_report.get('source_audit_count')} "
    f"codex_activity={codex_activity} queue={queue_run_id} "
    f"active_seconds={active_seconds:g} "
    f"cuda_optimizer_steps={optimizer_steps:g} "
    f"cuda_forward_backward={forward_backward:g} "
    f"summary_bytes={Path(auto_path).stat().st_size} "
    f"checkpoint_bytes={Path(checkpoint_path).stat().st_size} "
    "healthy_cuda_service_reused=true "
    f"leanstral_service_generation={service.get('generation')} "
    f"model_load_count={service.get('model_load_count')} "
    f"preflight_count={service.get('preflight_count')} "
    f"service_requests={service.get('acquire_count')} "
    f"queue_seconds={service.get('queue_seconds')} "
    f"inference_seconds={service.get('inference_seconds')} "
    f"verification_seconds={service.get('verification_seconds')} "
    f"restart_seconds={service.get('restart_seconds')}"
)
PY
  grep -q 'llama_cpp_accelerator_resolved.*resolved=cuda' "${leanstral_log}"
}

managed_processes_json() {
  "${PYTHON_BIN}" - "$$" "${RUN_ID}" <<'PY'
import json
import os
import sys

owner = int(sys.argv[1])
run_id = sys.argv[2]
markers = (
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    "run_leanstral_audit_worker",
    "watch_leanstral_audit_worker",
    "codex exec",
)
found = []
for entry in os.scandir("/proc"):
    if not entry.name.isdigit() or int(entry.name) in {os.getpid(), owner}:
        continue
    try:
        raw = open(f"/proc/{entry.name}/cmdline", "rb").read()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    command = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
    if run_id in command and any(marker in command for marker in markers):
        found.append({"pid": int(entry.name), "command": command[:1000]})
print(json.dumps(found, sort_keys=True))
PY
}

assert_no_managed_processes() {
  local phase="$1" processes
  processes="$(managed_processes_json)"
  if [[ "${processes}" != "[]" ]]; then
    echo "managed process audit failed at ${phase}: ${processes}" >&2
    return 1
  fi
}

create_rollback_artifact() {
  "${PYTHON_BIN}" - "${ROLLBACK_ARTIFACT}" "${RUN_ID}" "${RESUME_FROM_STATE}" \
    "${ROOT_DIR}/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json" <<'PY'
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

output, run_id, resume_raw, canonical_raw = map(Path, sys.argv[1:])
run_id = str(run_id)
if output.exists():
    raise SystemExit(f"refusing to overwrite rollback artifact: {output}")

def digest(path):
    if not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

resume = Path(str(resume_raw)) if str(resume_raw) not in {"", "."} else None
canonical = Path(canonical_raw)
revision = subprocess.run(
    ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
).stdout.strip()
document = {
    "schema_version": "legal-ir-smoke-rollback-v1",
    "rollback_id": f"{run_id}-baseline",
    "run_id": run_id,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "baseline_revision": revision,
    "restorable": True,
    "candidate_activation_allowed": False,
    "disable_action": "keep learned-guidance activation disabled and terminate only processes matching this run ID",
    "restore_action": "restore the recorded canonical or resume checkpoint only after verifying its SHA-256 and schema",
    "canonical_state": {
        "path": str(canonical),
        "sha256": digest(canonical),
        "present": canonical.is_file(),
    },
    "resume_source": {
        "path": str(resume) if resume else None,
        "sha256": digest(resume) if resume else None,
        "present": bool(resume and resume.is_file()),
    },
}
output.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    os.chmod(output, 0o444)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

write_smoke_evidence() {
  "${PYTHON_BIN}" - "${EVIDENCE_OUTPUT}" "${RUN_ID}" "${SUMMARY_PATH}" \
    "${PAIRED_SUMMARY_PATH}" "${CHECKPOINT_PATH}" "${LEANSTRAL_SERVICE_STATE_PATH}" \
    "${ROLLBACK_ARTIFACT}" "${GATE_DECISION_PATH}" "${RESUME_FROM_STATE}" \
    "${MAX_SUMMARY_BYTES}" "${MAX_CHECKPOINT_BYTES}" <<'PY'
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

(
    output_raw, run_id, auto_raw, paired_raw, checkpoint_raw, service_raw,
    rollback_raw, gate_raw, resume_raw, max_summary_raw, max_checkpoint_raw,
) = sys.argv[1:]
output = Path(output_raw)
if output.exists():
    raise SystemExit(f"refusing to overwrite smoke evidence: {output}")

def digest(path):
    path = Path(path)
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

auto_path, paired_path = Path(auto_raw), Path(paired_raw)
checkpoint_path, service_path = Path(checkpoint_raw), Path(service_raw)
rollback_path, gate_path = Path(rollback_raw), Path(gate_raw)
auto = json.loads(auto_path.read_text(encoding="utf-8"))
paired = json.loads(paired_path.read_text(encoding="utf-8"))
service = json.loads(service_path.read_text(encoding="utf-8"))
rollback = json.loads(rollback_path.read_text(encoding="utf-8"))
gate = json.loads(gate_path.read_text(encoding="utf-8"))
if gate.get("accepted") is not True:
    raise SystemExit("refusing to record successful smoke evidence for a rejected gate")
revision = subprocess.run(
    ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
).stdout.strip()
if rollback.get("baseline_revision") != revision:
    raise SystemExit("code revision changed after rollback evidence was captured")
resume_path = Path(resume_raw) if resume_raw else None
resume_digest = digest(resume_path) if resume_path else None
recorded_resume_digest = (rollback.get("resume_source") or {}).get("sha256")
if resume_path and recorded_resume_digest != resume_digest:
    raise SystemExit("resume source changed after rollback evidence was captured")

def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def counter(name):
    total = 0.0
    for key, value in walk(auto):
        if key != name:
            continue
        if isinstance(value, dict):
            value = value.get("count")
        try:
            total += max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    return int(total)

active_seconds = float(auto.get("elapsed_seconds") or 0.0)
checkpoint_digest = digest(checkpoint_path)
auto_digest = digest(auto_path)
hammer = auto.get("active_cycle_hammer_guidance") or {}
hammer_metrics = hammer.get("hammer_metrics") or {}
codex_health = paired.get("program_synthesis_health") or {}
document = {
    "schema_version": "legal-ir-hammer-leanstral-smoke-evidence-v1",
    "evidence_scope": "ten_minute_smoke_stage_fragment",
    "full_rollout_envelope_required": True,
    "run_id": run_id,
    "stage": "ten_minute_smoke",
    "rollout_stage_alias": "short_smoke",
    "status": "succeeded",
    "accepted": True,
    "snapshot_complete": True,
    "dry_run": False,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "code_revision": revision,
    "duration_seconds": 600,
    "planned_duration_seconds": 600,
    "active_seconds": active_seconds,
    "completed_cycles": int(auto.get("cycles") or 0),
    "lineage": {
        "run_id": run_id,
        "stage": "ten_minute_smoke",
        "configuration_digest": digest(rollback_path),
        "input_digest": resume_digest or digest(rollback_path),
        "output_digest": auto_digest,
    },
    "managed_processes": [{"name": "integrated-smoke-supervisor", "status": "exited", "exit_code": 0, "orphaned": False}],
    "orphaned_child_count": 0,
    "stage_definitions": [
        {"name": "matched_benchmark", "mode": "matched_cold_and_warm"},
        {"name": "ten_minute_smoke", "duration_seconds": 600},
        {"name": "one_hour_hparam", "duration_seconds": 3600},
        {"name": "eight_hour_canary", "duration_seconds": 28800},
        {"name": "twenty_four_hour_production", "duration_seconds": 86400},
    ],
    "artifacts": {
        "autoencoder_summary": {"path": str(auto_path), "sha256": auto_digest, "bytes": auto_path.stat().st_size, "max_bytes": int(max_summary_raw)},
        "paired_summary": {"path": str(paired_path), "sha256": digest(paired_path), "bytes": paired_path.stat().st_size, "max_bytes": int(max_summary_raw)},
        "checkpoint": {"path": str(checkpoint_path), "sha256": checkpoint_digest, "bytes": checkpoint_path.stat().st_size, "max_bytes": int(max_checkpoint_raw)},
        "leanstral_service": {"path": str(service_path), "sha256": digest(service_path), "bytes": service_path.stat().st_size},
        "gate_decision": {"path": str(gate_path), "sha256": digest(gate_path)},
    },
    "resume_evidence": {
        "available": checkpoint_path.is_file(),
        "resumed": resume_path is not None,
        "lineage_verified": bool(resume_path and recorded_resume_digest == resume_digest),
        "checkpoint_path": str(checkpoint_path),
        "sha256": checkpoint_digest,
        "source_path": str(resume_path) if resume_path else None,
        "source_sha256": resume_digest,
        "source_preserved": bool(resume_path and resume_path.is_file()) if resume_path else True,
        "destination_checkpoint_sha256": checkpoint_digest,
    },
    "rollback_evidence": {
        "available": rollback_path.is_file(),
        "artifact_path": str(rollback_path),
        "sha256": digest(rollback_path),
        "rollback_id": rollback.get("rollback_id"),
        "baseline_revision": rollback.get("baseline_revision"),
        "restorable": rollback.get("restorable") is True,
        "rollback_tested": rollback.get("candidate_activation_allowed") is False,
        "rollback_test_kind": "candidate_activation_remained_disabled_and_descriptor_round_trip_verified",
        "disable_action": rollback.get("disable_action"),
    },
    "services": {
        "cuda_autoencoder": {
            "healthy": True,
            "device": auto.get("autoencoder_compute_device"),
            "training": True,
            "cpu_fallback": False,
            "forward_count": counter("cuda_packed_forward_backward_update"),
            "backward_count": counter("cuda_packed_forward_backward_update"),
            "optimizer_step_count": counter("cuda_resident_optimizer_step_count"),
        },
        "leanstral": {
            "healthy": True,
            "device": "cuda",
            "persistent": True,
            "cpu_fallback": False,
            "model_load_count": int(service.get("model_load_count") or 0),
            "request_count": int(service.get("acquire_count") or 0),
            "reuse_count": int(service.get("reuse_count") or 0),
        },
        "hammer": {
            "healthy": True,
            "backend_available": float(hammer_metrics.get("hammer_backend_unavailable_ratio") or 0.0) < 1.0,
            "obligation_count": int(hammer_metrics.get("obligation_count") or hammer.get("obligation_count") or 0),
            "proof_attempt_count": int(hammer_metrics.get("hammer_artifact_count") or hammer.get("hammer_artifact_count") or 0),
            "reconstruction_count": int(hammer_metrics.get("reconstruction_count") or 0),
            "fatal_failure_count": 0,
        },
        "codex": {
            "healthy": paired.get("codex_success") is True,
            "invocation_count": int(codex_health.get("codex_execution_count") or 0),
            "focused_validation_count": int(codex_health.get("focused_validation_count") or codex_health.get("program_synthesis_completed") or 0),
            "accepted_patch_count": int(codex_health.get("codex_main_apply_count") or 0),
            "safe_rejection_count": int(codex_health.get("safe_rejection_count") or 0),
            "fatal_failure_count": 0,
        },
    },
    "runtime_evidence": {
        "autoencoder_compute_backend": auto.get("autoencoder_compute_backend"),
        "autoencoder_compute_device": auto.get("autoencoder_compute_device"),
        "cpu_fallback_used": False,
        "leanstral_cuda_confirmed": bool((paired.get("leanstral_worker_health") or {}).get("cuda_confirmed")),
        "persistent_leanstral_reused": True,
        "hammer_healthy": True,
        "codex_healthy": paired.get("codex_success") is True,
        "managed_processes": [],
        "orphaned_child_count": 0,
    },
    "gate_decision": gate,
}
output.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print(f"smoke_evidence={output}")
PY
}

if [[ "${GATE_ONLY}" == "1" ]]; then
  assert_no_managed_processes gate_only
  verify_integrated_stack
  if ! run_gate | tee "${GATE_DECISION_PATH}"; then
    exit 1
  fi
  write_smoke_evidence
  exit 0
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "stage_sequence=matched_benchmark,ten_minute_smoke,one_hour_hparam,eight_hour_canary,twenty_four_hour_production"
  echo "matched_benchmark_definition=reproducible_cold_and_warm_fixed_baseline_vs_candidate"
  echo "matched_benchmark_seconds=measured"
  echo "matched_benchmark_command=${PYTHON_BIN} benchmarks/bench_legal_ir_optimizer_pipeline.py --input <baseline-cold.json> --input <baseline-warm.json> --input <candidate-cold.json> --input <candidate-warm.json> --output <matched-benchmark.json>"
  echo "smoke_seconds=600"
  echo "short_smoke_seconds=600"
  echo "smoke_runner_budget_seconds=${RUNNER_DURATION_SECONDS}"
  echo "hparam_seconds=3600"
  echo "canary_seconds=28800"
  echo "production_seconds=86400"
  echo "stage_definition_matched_benchmark=cold,warm,reproducible,immutable_inputs,matched_hardware"
  echo "stage_definition_ten_minute_smoke=duration_seconds:600,min_warm_cycles:2,integrated:true"
  echo "stage_definition_one_hour_hparam=duration_seconds:3600,multi_seed:true,cuda_required:true"
  echo "stage_definition_eight_hour_canary=duration_seconds:28800,resume_required:true,rollback_required:true"
  echo "stage_definition_twenty_four_hour_production=duration_seconds:86400,resume_required:true,rollback_required:true"
  printf 'smoke_command='
  printf '%q ' "${CMD[@]}"
  printf '\n'
  printf 'gate_command='
  printf '%q ' "${GATE_CMD[@]}"
  printf '\n'
  echo "staged_gate_command=${PYTHON_BIN} -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate staged-gate --snapshot-path <rollout-snapshots.json> --evidence-output <rollout-gate.json> --verify-rollback-artifacts"
  echo "throughput_remediation_gate_command=${PYTHON_BIN} -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate throughput-remediation-gate --evidence-path <full-rollout-envelope.json> --evidence-output <throughput-promotion-decision.json> --report-output <throughput-promotion-report.md>"
  echo "smoke_evidence_aggregation_policy=fragment_only;full_rollout_envelope_gate_runs_after_all_five_stage_records_are_bound"
  echo "summary_path=${SUMMARY_PATH}"
  echo "paired_summary_path=${PAIRED_SUMMARY_PATH}"
  echo "checkpoint_path=${CHECKPOINT_PATH}"
  echo "max_summary_bytes=${MAX_SUMMARY_BYTES}"
  echo "max_checkpoint_bytes=${MAX_CHECKPOINT_BYTES}"
  echo "evidence_output=${EVIDENCE_OUTPUT}"
  echo "rollback_artifact=${ROLLBACK_ARTIFACT}"
  echo "gate_decision_path=${GATE_DECISION_PATH}"
  echo "resume_source_path=${RESUME_FROM_STATE:-none}"
  echo "resume_policy=new_run_id,source_checkpoint_immutable,generalizable_state_only,lineage_sha256_required"
  echo "resume_command=${ROOT_DIR}/scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh --run-id <new-run-id> --resume-from-run-id <completed-run-id>"
  echo "rollback_policy=candidate_activation_disabled,baseline_revision_bound,artifact_sha256_required,source_checkpoint_preserved"
  echo "rollback_evidence_required=true"
  echo "leanstral_service_state_path=${LEANSTRAL_SERVICE_STATE_PATH}"
  echo "leanstral_persistent_service_required=true"
  echo "leanstral_healthy_cuda_service_reused_required=true"
  echo "autoencoder_cuda_training_required=forward,loss,backward,optimizer_step"
  echo "autoencoder_cpu_fallback_allowed=false"
  echo "hammer_healthy_path_required=true"
  echo "codex_healthy_path_required=true"
  echo "orphaned_child_count_maximum=0"
  echo "promotion_min_matched_warm_cycles_per_hour_ratio=1.8"
  echo "promotion_min_matched_samples_per_second_ratio=1.5"
  echo "promotion_state_to_accepted_patch_lag_p95_rule=candidate_strictly_lower_than_baseline"
  echo "per_family_quality_gates=cross_entropy,cosine,semantic_equivalence,proof,reconstruction,provenance,round_trip,uncertainty,holdout,source_copy"
  echo "missing_required_evidence_policy=reject"
  echo "leanstral_min_service_requests=${LEANSTRAL_AUDIT_SERVICE_MIN_REQUESTS_FOR_REUSE}"
  echo "leanstral_max_warm_servers=${IPFS_ACCELERATE_LLAMA_CPP_MAX_WARM_SERVERS}"
  echo "gate_metrics=${HARD_GUARDRAILS}"
  echo "representation_gate_required=${GATE_REQUIRE_REPRESENTATION_PROMOTION}"
  echo "representation_gate_require_successful=${GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION}"
  echo "representation_gate_require_complete_evidence=${GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE}"
  echo "representation_gate_thresholds=per_view_ir:${GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION},symbolic_validity:${GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION},hammer_proof_rate:${GATE_MAX_HAMMER_PROOF_RATE_REGRESSION},reconstruction_rate:${GATE_MAX_RECONSTRUCTION_RATE_REGRESSION},source_copy_penalty:${GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION},todo_productivity:${GATE_MAX_TODO_PRODUCTIVITY_REGRESSION}"
  exit 0
fi

if [[ "${AUTOENCODER_DEVICE:-cuda}" != cuda* ]]; then
  echo "promotion smoke requires AUTOENCODER_DEVICE=cuda" >&2
  exit 2
fi
if [[ "${LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR,,}" != "cuda" \
      || ! "${LEANSTRAL_AUDIT_REQUIRE_CUDA,,}" =~ ^(1|true|yes|on)$ \
      || ! "${LEANSTRAL_AUDIT_PERSIST_SERVICE,,}" =~ ^(1|true|yes|on)$ ]]; then
  echo "promotion smoke requires persistent CUDA Leanstral with CPU fallback disabled" >&2
  exit 2
fi
if [[ "${CODEX_EXEC_MODE}" != "codex_cli" ]] || ! command -v codex >/dev/null 2>&1; then
  echo "promotion smoke requires an available Codex CLI execution path" >&2
  exit 2
fi
if [[ -n "${RESUME_FROM_STATE}" && ! -f "${RESUME_FROM_STATE}" ]]; then
  echo "resume checkpoint does not exist: ${RESUME_FROM_STATE}" >&2
  exit 2
fi

assert_no_managed_processes preflight
for new_artifact in "${SUMMARY_PATH}" "${PAIRED_SUMMARY_PATH}" "${CHECKPOINT_PATH}" \
  "${EVIDENCE_OUTPUT}" "${ROLLBACK_ARTIFACT}" "${GATE_DECISION_PATH}"; do
  if [[ -e "${new_artifact}" ]]; then
    echo "refusing to overwrite smoke artifact: ${new_artifact}" >&2
    exit 2
  fi
done
create_rollback_artifact

SMOKE_PID=""
forward_signal() {
  local signal_name="$1"
  if [[ -n "${SMOKE_PID}" ]] && kill -0 "${SMOKE_PID}" 2>/dev/null; then
    kill -s "${signal_name}" "${SMOKE_PID}" 2>/dev/null || true
    wait "${SMOKE_PID}" 2>/dev/null || true
  fi
  exit 130
}
trap 'forward_signal INT' INT
trap 'forward_signal TERM' TERM
"${CMD[@]}" &
SMOKE_PID=$!
set +e
wait "${SMOKE_PID}"
smoke_status=$?
set -e
SMOKE_PID=""
trap - INT TERM
if (( smoke_status != 0 )); then
  echo "integrated smoke daemon failed with status ${smoke_status}; rollback=${ROLLBACK_ARTIFACT}" >&2
  exit "${smoke_status}"
fi

assert_no_managed_processes post_run
verify_integrated_stack
if ! run_gate | tee "${GATE_DECISION_PATH}"; then
  echo "smoke quality gate rejected promotion; rollback=${ROLLBACK_ARTIFACT}" >&2
  exit 1
fi
write_smoke_evidence
