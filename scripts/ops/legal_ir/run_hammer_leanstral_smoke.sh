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
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"
export LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR="${LEANSTRAL_AUDIT_LLAMA_CPP_ACCELERATOR:-cuda}"
export LEANSTRAL_AUDIT_REQUIRE_CUDA="${LEANSTRAL_AUDIT_REQUIRE_CUDA:-1}"

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
  --autoencoder-device "${AUTOENCODER_DEVICE:-cuda}"
  --autoencoder-bridge-workers "${AUTOENCODER_BRIDGE_WORKERS:-2}"
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
  --daemon-hammer-guidance-train-autoencoder true
  --daemon-hammer-guidance-max-training-items "${DAEMON_HAMMER_GUIDANCE_MAX_TRAINING_ITEMS:-64}"
  --paired-supervisor-backend accelerate_style
  --paired-leanstral-worker-enabled true
  --paired-leanstral-require-cuda true
  --paired-leanstral-grace-seconds "${PAIRED_LEANSTRAL_GRACE_SECONDS:-900}"
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
    "${REPRESENTATION_PROMOTION_GATE_FLAG}" \
    "${SUCCESSFUL_REPRESENTATION_PROMOTION_GATE_FLAG}" \
    "${COMPLETE_REPRESENTATION_EVIDENCE_GATE_FLAG}" \
    --max-per-view-ir-metric-regression "${GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION}" \
    --max-symbolic-validity-regression "${GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION}" \
    --max-hammer-proof-rate-regression "${GATE_MAX_HAMMER_PROOF_RATE_REGRESSION}" \
    --max-reconstruction-rate-regression "${GATE_MAX_RECONSTRUCTION_RATE_REGRESSION}" \
    --max-source-copy-penalty-regression "${GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION}" \
    --max-todo-productivity-regression "${GATE_MAX_TODO_PRODUCTIVITY_REGRESSION}" \
    --min-cycles-for-todo-gate "${GATE_MIN_CYCLES_FOR_TODO_GATE:-1}"
}

verify_integrated_stack() {
  local paired_summary leanstral_log
  paired_summary="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.summary"
  leanstral_log="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.leanstral.stdout.log"
  "${PYTHON_BIN}" - "${SUMMARY_PATH}" "${paired_summary}" <<'PY'
import json
import sys

auto_path, paired_path = sys.argv[1:]
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
health = paired.get("leanstral_worker_health") or {}
if not health.get("cuda_confirmed"):
    raise SystemExit(f"Leanstral CUDA verification failed: {health!r}")
if not health.get("report_present"):
    raise SystemExit(f"Leanstral report verification failed: {health!r}")
if not paired.get("leanstral_success"):
    raise SystemExit("paired supervisor did not accept the Leanstral worker")

hammer = auto.get("active_cycle_hammer_guidance") or {}
if hammer.get("status") != "completed" or int(hammer.get("hammer_artifact_count") or 0) < 1:
    raise SystemExit(f"Hammer integration verification failed: {hammer!r}")
hammer_metrics = hammer.get("hammer_metrics") or {}
if float(hammer_metrics.get("hammer_backend_unavailable_ratio") or 0.0) >= 1.0:
    raise SystemExit(f"all Hammer backends were unavailable: {hammer_metrics!r}")

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
    f"codex_activity={codex_activity} queue={queue_run_id}"
)
PY
  grep -q 'llama_cpp_accelerator_resolved.*resolved=cuda' "${leanstral_log}"
}

if [[ "${GATE_ONLY}" == "1" ]]; then
  verify_integrated_stack
  run_gate
  exit $?
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  printf '%q ' "${CMD[@]}"
  printf '\n'
  echo "summary_path=${SUMMARY_PATH}"
  echo "gate_metrics=${HARD_GUARDRAILS}"
  echo "representation_gate_required=${GATE_REQUIRE_REPRESENTATION_PROMOTION}"
  echo "representation_gate_require_successful=${GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION}"
  echo "representation_gate_require_complete_evidence=${GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE}"
  echo "representation_gate_thresholds=per_view_ir:${GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION},symbolic_validity:${GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION},hammer_proof_rate:${GATE_MAX_HAMMER_PROOF_RATE_REGRESSION},reconstruction_rate:${GATE_MAX_RECONSTRUCTION_RATE_REGRESSION},source_copy_penalty:${GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION},todo_productivity:${GATE_MAX_TODO_PRODUCTIVITY_REGRESSION}"
  exit 0
fi

"${CMD[@]}"
verify_integrated_stack
run_gate
