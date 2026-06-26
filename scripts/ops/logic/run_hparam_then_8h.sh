#!/usr/bin/env bash
set -euo pipefail

restore_err_trap() {
  trap 'echo "[pipeline] command_failed line=${LINENO} status=$?"' ERR
}

restore_err_trap

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

MODULE="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner"
BASE_RUN_ID="${1:-legal-ir-hparam-$(date -u +%Y%m%dT%H%M%SZ)}"
LOG_DIR="${ROOT_DIR}/workspace/test-logs"
mkdir -p "${LOG_DIR}"
SAMPLING_SEED="${SAMPLING_SEED:-${BASE_RUN_ID}}"

PREVENT_CONCURRENT_PIPELINES="${PREVENT_CONCURRENT_PIPELINES:-1}"
ALLOW_CONCURRENT_PIPELINES="${ALLOW_CONCURRENT_PIPELINES:-0}"
if [[ "${PREVENT_CONCURRENT_PIPELINES}" != "0" && "${ALLOW_CONCURRENT_PIPELINES}" != "1" ]]; then
  ACTIVE_PIPELINES="$("${PYTHON_BIN}" - <<'PY'
import json
import os


def _ancestor_pids(pid: int) -> set[int]:
    pids = {pid}
    while pid > 1:
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as handle:
                fields = handle.read().split()
        except OSError:
            break
        if len(fields) < 4:
            break
        try:
            pid = int(fields[3])
        except ValueError:
            break
        if pid in pids:
            break
        pids.add(pid)
    return pids


ignored = _ancestor_pids(os.getpid())
active = []
for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    if pid in ignored:
        continue
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            cmd = handle.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except OSError:
        continue
    if not cmd:
        continue
    is_pipeline = "scripts/ops/logic/run_hparam_then_8h.sh" in cmd
    is_paired = (
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner" in cmd
        and "--loop-role paired" in cmd
    )
    if not (is_pipeline or is_paired):
        continue
    active.append({"cmd": cmd[:320], "pid": pid})

print(json.dumps(active[:16], sort_keys=True))
PY
)"
  if [[ "${ACTIVE_PIPELINES}" != "[]" ]]; then
    echo "[pipeline] refusing_to_start_concurrent_pipeline base_run_id=${BASE_RUN_ID}" >&2
    echo "[pipeline] active_pipeline_processes=${ACTIVE_PIPELINES}" >&2
    echo "[pipeline] set ALLOW_CONCURRENT_PIPELINES=1 to bypass this guard intentionally" >&2
    exit 12
  fi
fi

TRIAL_COUNT="${TRIAL_COUNT:-6}"
# There are six built-in sweep configs. Run them in one wave so each candidate
# gets the full one-hour sweep budget instead of splitting into shorter waves.
TRIAL_PARALLELISM="${TRIAL_PARALLELISM:-6}"
TRIAL_PARALLEL_HEARTBEAT_SECONDS="${TRIAL_PARALLEL_HEARTBEAT_SECONDS:-20}"
HYPERPARAM_SWEEP_WALL_SECONDS="${HYPERPARAM_SWEEP_WALL_SECONDS:-3600}"
if (( TRIAL_PARALLELISM < 1 )); then
  TRIAL_PARALLELISM=1
fi
TRIAL_WAVES=$(((TRIAL_COUNT + TRIAL_PARALLELISM - 1) / TRIAL_PARALLELISM))
if (( TRIAL_WAVES < 1 )); then
  TRIAL_WAVES=1
fi
TRIAL_SECONDS="${TRIAL_SECONDS:-$(((HYPERPARAM_SWEEP_WALL_SECONDS + TRIAL_WAVES - 1) / TRIAL_WAVES))}"
TOTAL_TRIAL_SECONDS=$((TRIAL_SECONDS * TRIAL_COUNT))
TOTAL_TRIAL_WALL_SECONDS=$((TRIAL_SECONDS * TRIAL_WAVES))
FINAL_SECONDS="${FINAL_SECONDS:-$((8 * 60 * 60))}"
TRIAL_TIMEOUT_GRACE_SECONDS="${TRIAL_TIMEOUT_GRACE_SECONDS:-120}"
TRIAL_TIMEOUT_SECONDS="${TRIAL_TIMEOUT_SECONDS:-$((TRIAL_SECONDS + TRIAL_TIMEOUT_GRACE_SECONDS))}"
FINAL_TIMEOUT_GRACE_SECONDS="${FINAL_TIMEOUT_GRACE_SECONDS:-300}"
FINAL_TIMEOUT_SECONDS="${FINAL_TIMEOUT_SECONDS:-$((FINAL_SECONDS + FINAL_TIMEOUT_GRACE_SECONDS))}"
PAIRED_GRACE_SECONDS="${PAIRED_GRACE_SECONDS:-${FINAL_TIMEOUT_GRACE_SECONDS}}"
SWEEP_LOOP_ROLE="${SWEEP_LOOP_ROLE:-autoencoder}"
SWEEP_TEST_EVERY_CYCLES="${SWEEP_TEST_EVERY_CYCLES:-48}"
FINAL_TEST_EVERY_CYCLES="${FINAL_TEST_EVERY_CYCLES:-96}"
SWEEP_PROJECTION_EPOCHS="${SWEEP_PROJECTION_EPOCHS:-1}"
FINAL_PROJECTION_EPOCHS="${FINAL_PROJECTION_EPOCHS:-2}"
FINAL_RECOVERY_MIN_CYCLES="${FINAL_RECOVERY_MIN_CYCLES:-1}"
ALLOW_FINAL_FALLBACK_ON_SWEEP_FAILURE="${ALLOW_FINAL_FALLBACK_ON_SWEEP_FAILURE:-1}"
SKIP_HPARAM_SWEEP="${SKIP_HPARAM_SWEEP:-0}"
SWEEP_ONLY="${SWEEP_ONLY:-0}"
SKIP_FINAL_RUN="${SKIP_FINAL_RUN:-${SWEEP_ONLY}}"
BRIDGE_EVALUATE_PROVERS="${BRIDGE_EVALUATE_PROVERS:-false}"
BRIDGE_LOSS_ADAPTERS="${BRIDGE_LOSS_ADAPTERS:-modal_frame_logic,deontic_norms,fol_tdfol,cec_dcec,external_prover_router,zkp_attestation}"
GENERALIZABLE_PROJECTION_MAX_COSINE_REGRESSION="${GENERALIZABLE_PROJECTION_MAX_COSINE_REGRESSION:-0.005}"
GENERALIZABLE_PROJECTION_MAX_RECONSTRUCTION_REGRESSION="${GENERALIZABLE_PROJECTION_MAX_RECONSTRUCTION_REGRESSION:-0.01}"
GENERALIZABLE_PROJECTION_MAX_CROSS_ENTROPY_REGRESSION="${GENERALIZABLE_PROJECTION_MAX_CROSS_ENTROPY_REGRESSION:-0.0}"
GENERALIZABLE_PROJECTION_MAX_LEGAL_IR_LOSS_REGRESSION="${GENERALIZABLE_PROJECTION_MAX_LEGAL_IR_LOSS_REGRESSION:-0.01}"
GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS="${GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS:-0}"
AUTOENCODER_PROJECTION_DEADBAND_MODE="${AUTOENCODER_PROJECTION_DEADBAND_MODE:-shadow}"
AUTOENCODER_MAX_CE_DEADBAND="${AUTOENCODER_MAX_CE_DEADBAND:-0.0001}"
AUTOENCODER_HARD_GUARDRAIL_METRICS="${AUTOENCODER_HARD_GUARDRAIL_METRICS:-embedding_cosine_similarity,reconstruction_loss,legal_ir:*}"
AUTOENCODER_PROJECTION_PRESCREEN_MODE="${AUTOENCODER_PROJECTION_PRESCREEN_MODE:-off}"
AUTOENCODER_PROJECTION_PRESCREEN_TOP_K="${AUTOENCODER_PROJECTION_PRESCREEN_TOP_K:-3}"
AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES="${AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES:-8}"
COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS="${COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS:-3000}"
COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS="${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS:-30}"
COMPILER_IR_TRAIN_MODE="${COMPILER_IR_TRAIN_MODE:-off}"
COMPILER_IR_TRAIN_EVERY_N_CYCLES="${COMPILER_IR_TRAIN_EVERY_N_CYCLES:-4}"
COMPILER_IR_GUIDED_TRAIN_MODE="${COMPILER_IR_GUIDED_TRAIN_MODE:-off}"
COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES="${COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES:-4}"
MAX_SAMPLE_TEXT_CHARS="${MAX_SAMPLE_TEXT_CHARS:-4096}"
TRAIN_COUNT="${TRAIN_COUNT:-8}"
VALIDATION_COUNT="${VALIDATION_COUNT:-8}"
MAX_INNER_ITERATIONS="${MAX_INNER_ITERATIONS:-3}"
MAX_ITEMS="${MAX_ITEMS:-8}"
SWEEP_TRAIN_COUNT="${SWEEP_TRAIN_COUNT:-${TRAIN_COUNT}}"
SWEEP_VALIDATION_COUNT="${SWEEP_VALIDATION_COUNT:-${VALIDATION_COUNT}}"
SWEEP_MAX_INNER_ITERATIONS="${SWEEP_MAX_INNER_ITERATIONS:-${MAX_INNER_ITERATIONS}}"
SWEEP_MAX_ITEMS="${SWEEP_MAX_ITEMS:-${MAX_ITEMS}}"
SWEEP_MAX_SAMPLE_TEXT_CHARS="${SWEEP_MAX_SAMPLE_TEXT_CHARS:-${MAX_SAMPLE_TEXT_CHARS}}"
SWEEP_BRIDGE_LOSS_ADAPTERS="${SWEEP_BRIDGE_LOSS_ADAPTERS:-${BRIDGE_LOSS_ADAPTERS}}"
SWEEP_BRIDGE_EVALUATE_PROVERS="${SWEEP_BRIDGE_EVALUATE_PROVERS:-${BRIDGE_EVALUATE_PROVERS}}"
# Sweep trials run in parallel, so keep per-trial bridge fanout lower.
SWEEP_AUTOENCODER_BRIDGE_WORKERS="${SWEEP_AUTOENCODER_BRIDGE_WORKERS:-${AUTOENCODER_BRIDGE_WORKERS:-3}}"
FINAL_TRAIN_COUNT="${FINAL_TRAIN_COUNT:-${TRAIN_COUNT}}"
FINAL_VALIDATION_COUNT="${FINAL_VALIDATION_COUNT:-${VALIDATION_COUNT}}"
FINAL_MAX_INNER_ITERATIONS="${FINAL_MAX_INNER_ITERATIONS:-${MAX_INNER_ITERATIONS}}"
FINAL_MAX_ITEMS="${FINAL_MAX_ITEMS:-${MAX_ITEMS}}"
FINAL_MAX_SAMPLE_TEXT_CHARS="${FINAL_MAX_SAMPLE_TEXT_CHARS:-${MAX_SAMPLE_TEXT_CHARS}}"
FINAL_BRIDGE_LOSS_ADAPTERS="${FINAL_BRIDGE_LOSS_ADAPTERS:-${BRIDGE_LOSS_ADAPTERS}}"
FINAL_BRIDGE_EVALUATE_PROVERS="${FINAL_BRIDGE_EVALUATE_PROVERS:-${BRIDGE_EVALUATE_PROVERS}}"
FINAL_AUTOENCODER_BRIDGE_WORKERS="${FINAL_AUTOENCODER_BRIDGE_WORKERS:-${AUTOENCODER_BRIDGE_WORKERS:-8}}"
VALIDATION_CANARY_COUNT="${VALIDATION_CANARY_COUNT:-4}"
SWEEP_VALIDATION_CANARY_COUNT="${SWEEP_VALIDATION_CANARY_COUNT:-${VALIDATION_CANARY_COUNT}}"
FINAL_VALIDATION_CANARY_COUNT="${FINAL_VALIDATION_CANARY_COUNT:-${VALIDATION_CANARY_COUNT}}"
VALIDATION_CANARY_INDICES="${VALIDATION_CANARY_INDICES:-28380,25280,18192,38585}"
AUTOENCODER_DEVICE="${AUTOENCODER_DEVICE:-cpu}"
AUTOENCODER_BRIDGE_WORKERS="${AUTOENCODER_BRIDGE_WORKERS:-8}"
BRIDGE_ADAPTER_WORKERS="${BRIDGE_ADAPTER_WORKERS:-4}"
CODEX_PARALLEL_SCOPES="${CODEX_PARALLEL_SCOPES:-compiler_ambiguity,compiler_registry,autoencoder,ir_decompiler,bridge,compiler_parser,frame_logic,deontic,cec,tdfol,knowledge_graphs,external_provers,zkp}"
CODEX_SCOPE_WORKERS="${CODEX_SCOPE_WORKERS:-1}"
# The paired final run has one stateful autoencoder producer. Codex workers are
# demand-weighted from observed legal-IR TODO queues and cover every family scope
# the autoencoder can seed, while bridge workers keep the deterministic metrics fed.
CODEX_SCOPE_WORKER_MAP="${CODEX_SCOPE_WORKER_MAP:-compiler_ambiguity=3,compiler_registry=3,autoencoder=1,ir_decompiler=3,bridge=2,compiler_parser=2,frame_logic=2,deontic=2,cec=3,tdfol=2,knowledge_graphs=3,external_provers=2,zkp=2}"
CODEX_APPLY_MODE="${CODEX_APPLY_MODE:-apply_to_main}"
if [[ "${CODEX_APPLY_MODE}" == "packet_only" ]]; then
  CODEX_APPLY_MODE="patch_only"
fi
CODEX_COMMIT_MODE="${CODEX_COMMIT_MODE:-none}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"
CODEX_BUNDLE_MODE="${CODEX_BUNDLE_MODE:-vector}"
CODEX_VECTOR_MIN_SIMILARITY="${CODEX_VECTOR_MIN_SIMILARITY:-0.62}"
CODEX_VECTOR_FILL_MIN_SIMILARITY="${CODEX_VECTOR_FILL_MIN_SIMILARITY:-0.40}"
CODEX_VECTOR_MIN_BUNDLE_SIZE="${CODEX_VECTOR_MIN_BUNDLE_SIZE:-1}"
CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS="${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS:-30}"
CODEX_VECTOR_STALE_DRAIN_COOLDOWN_SECONDS="${CODEX_VECTOR_STALE_DRAIN_COOLDOWN_SECONDS:-120}"
CODEX_TARGET_FILE_LANE_LOCK_SECONDS="${CODEX_TARGET_FILE_LANE_LOCK_SECONDS:-900}"
CODEX_TARGET_FILE_LANE_LOCK_SCOPES="${CODEX_TARGET_FILE_LANE_LOCK_SCOPES:-all}"
CODEX_LANE_LOCK_MODE="${CODEX_LANE_LOCK_MODE:-hybrid}"
CODEX_TASK_EMBEDDINGS_PROVIDER="${CODEX_TASK_EMBEDDINGS_PROVIDER:-local_adapter}"
CODEX_TASK_EMBEDDINGS_BATCH_SIZE="${CODEX_TASK_EMBEDDINGS_BATCH_SIZE:-32}"
CODEX_VECTOR_FALLBACK_MODE="${CODEX_VECTOR_FALLBACK_MODE:-hash}"
CODEX_MERGE_REPAIR_MODE="${CODEX_MERGE_REPAIR_MODE:-apply_3way}"
CODEX_MERGE_REPAIR_ATTEMPTS="${CODEX_MERGE_REPAIR_ATTEMPTS:-1}"
CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS="${CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS:-600}"
CODEX_MAIN_APPLY_MAX_INFLIGHT_PACKETS="${CODEX_MAIN_APPLY_MAX_INFLIGHT_PACKETS:-3}"
CODEX_TARGET_METRIC_TIMEOUT_SECONDS="${CODEX_TARGET_METRIC_TIMEOUT_SECONDS:-30}"
CODEX_TARGET_METRIC_MAX_SAMPLES="${CODEX_TARGET_METRIC_MAX_SAMPLES:-2}"
PAIRED_RESOURCE_GUARD="${PAIRED_RESOURCE_GUARD:-auto}"
PAIRED_CODEX_MAX_WORKERS="${PAIRED_CODEX_MAX_WORKERS:-0}"
PAIRED_CODEX_WORKER_MEMORY_GB="${PAIRED_CODEX_WORKER_MEMORY_GB:-2.0}"
PAIRED_RESERVED_MEMORY_GB="${PAIRED_RESERVED_MEMORY_GB:-24.0}"
PAIRED_MIN_AVAILABLE_MEMORY_GB="${PAIRED_MIN_AVAILABLE_MEMORY_GB:-12.0}"
PAIRED_MIN_SWAP_FREE_GB="${PAIRED_MIN_SWAP_FREE_GB:-1.0}"
PAIRED_CODEX_LAUNCH_STAGGER_SECONDS="${PAIRED_CODEX_LAUNCH_STAGGER_SECONDS:-1.0}"
PAIRED_CODEX_DISABLE_CUDA="${PAIRED_CODEX_DISABLE_CUDA:-true}"
PAIRED_FAILED_VALIDATION_RESCUE_MODE="${PAIRED_FAILED_VALIDATION_RESCUE_MODE:-auto}"
PAIRED_FAILED_VALIDATION_RESCUE_MAX_CLUSTERS="${PAIRED_FAILED_VALIDATION_RESCUE_MAX_CLUSTERS:-8}"
PAIRED_FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS="${PAIRED_FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS:-3}"
PAIRED_FAILED_VALIDATION_RESCUE_INTERVAL_SECONDS="${PAIRED_FAILED_VALIDATION_RESCUE_INTERVAL_SECONDS:-300}"
PAIRED_FAILED_VALIDATION_RESCUE_BACKLOG_THRESHOLD="${PAIRED_FAILED_VALIDATION_RESCUE_BACKLOG_THRESHOLD:-16}"
WARM_START_RUN_IDS="${WARM_START_RUN_IDS:-}"
WARM_START_STATES="${WARM_START_STATES:-}"

CODEX_EXEC_MODE="${CODEX_EXEC_MODE:-codex_cli}"
if ! command -v codex >/dev/null 2>&1; then
  CODEX_EXEC_MODE="packet_only"
fi
CODEX_SANDBOX="${CODEX_SANDBOX:-danger-full-access}"

export IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS="${BRIDGE_ADAPTER_WORKERS}"
export IPFS_DATASETS_CODEX_TARGET_METRIC_TIMEOUT_SECONDS="${CODEX_TARGET_METRIC_TIMEOUT_SECONDS}"
export IPFS_DATASETS_CODEX_TARGET_METRIC_MAX_SAMPLES="${CODEX_TARGET_METRIC_MAX_SAMPLES}"

COMMON_ARGS=(
  --sampling-seed "${SAMPLING_SEED}"
  --train-count "${TRAIN_COUNT}"
  --validation-count "${VALIDATION_COUNT}"
  --validation-canary-count "${VALIDATION_CANARY_COUNT}"
  --validation-canary-indices "${VALIDATION_CANARY_INDICES}"
  --max-sample-text-chars "${MAX_SAMPLE_TEXT_CHARS}"
  --max-inner-iterations "${MAX_INNER_ITERATIONS}"
  --max-items "${MAX_ITEMS}"
  --bridge-loss-adapters "${BRIDGE_LOSS_ADAPTERS}"
  --bridge-evaluate-provers "${BRIDGE_EVALUATE_PROVERS}"
  --autoencoder-device "${AUTOENCODER_DEVICE}"
  --autoencoder-bridge-workers "${AUTOENCODER_BRIDGE_WORKERS}"
  --compiler-ir-metric-max-sample-text-chars "${COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS}"
  --compiler-ir-metric-sample-timeout-seconds "${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS}"
  --compiler-ir-train-mode "${COMPILER_IR_TRAIN_MODE}"
  --compiler-ir-train-every-n-cycles "${COMPILER_IR_TRAIN_EVERY_N_CYCLES}"
  --compiler-ir-guided-train-mode "${COMPILER_IR_GUIDED_TRAIN_MODE}"
  --compiler-ir-guided-train-every-n-cycles "${COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES}"
  --generalizable-projection-max-line-search-attempts "${GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS}"
  --autoencoder-projection-deadband-mode "${AUTOENCODER_PROJECTION_DEADBAND_MODE}"
  --autoencoder-max-ce-deadband "${AUTOENCODER_MAX_CE_DEADBAND}"
  --autoencoder-hard-guardrail-metrics "${AUTOENCODER_HARD_GUARDRAIL_METRICS}"
  --autoencoder-projection-prescreen-mode "${AUTOENCODER_PROJECTION_PRESCREEN_MODE}"
  --autoencoder-projection-prescreen-top-k "${AUTOENCODER_PROJECTION_PRESCREEN_TOP_K}"
  --autoencoder-projection-periodic-full-search-every-n-cycles "${AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES}"
  --autoencoder-max-token-features 48
  --autoencoder-max-token-bigram-features 24
  --autoencoder-max-token-trigram-features 12
  --autoencoder-max-legal-ir-token-features 24
  --autoencoder-max-legal-ir-token-bigram-features 12
  --autoencoder-max-legal-ir-token-trigram-features 8
  --autoencoder-max-compiler-latent-profile-features 48
  --autoencoder-max-round-trip-bridge-features 64
  --autoencoder-max-clause-topology-features 64
  --autoencoder-max-legal-semantic-frame-features 64
  --autoencoder-max-normative-polarity-features 48
  --autoencoder-max-compiler-contract-features 64
  --autoencoder-max-decompiler-surface-template-features 48
  --autoencoder-max-canonical-ir-graph-features 64
  --autoencoder-max-cycle-consistency-features 64
  --autoencoder-max-equivalence-prototype-features 48
  --autoencoder-max-contrastive-ir-boundary-features 64
  --autoencoder-max-repair-plan-features 64
  --autoencoder-max-logic-view-contract-features 64
  --autoencoder-max-objective-residual-features 64
  --autoencoder-max-provenance-alignment-features 64
  --autoencoder-max-discourse-flow-features 64
  --autoencoder-max-proof-obligation-features 64
  --autoencoder-max-entity-binding-features 64
  --autoencoder-max-defeasible-priority-features 64
  --autoencoder-max-constraint-grounding-features 64
  --autoencoder-max-quantitative-formula-features 64
  --autoencoder-max-definition-grounding-features 64
  --autoencoder-max-quantifier-scope-features 64
  --autoencoder-max-procedural-lifecycle-features 64
  --autoencoder-max-enforcement-remedy-features 64
  --autoencoder-max-mental-state-features 64
  --autoencoder-max-reference-dependency-features 64
  --autoencoder-max-amendment-operation-features 64
  --autoencoder-max-authority-jurisdiction-features 64
  --autoencoder-max-discretion-standard-features 64
  --autoencoder-max-temporal-validity-features 64
  --autoencoder-max-evidentiary-burden-features 64
  --autoencoder-max-legal-relation-features 64
  --autoencoder-max-status-transition-features 64
  --autoencoder-max-condition-consequence-features 64
  --autoencoder-max-applicability-scope-features 64
  --autoencoder-max-coreference-binding-features 64
  --autoencoder-max-logical-connective-features 64
  --autoencoder-max-enumeration-hierarchy-features 64
  --autoencoder-max-semantic-slot-interactions 24
  --autoencoder-feature-activity-reference 64
  --autoencoder-feature-logit-clip 24.0
  --learning-rate-floor-ratio 0.25
  --learning-rate-cap-ratio 1.5
  --learning-rate-plateau-delta 1e-5
)

SWEEP_COMMON_OVERRIDES=(
  --train-count "${SWEEP_TRAIN_COUNT}"
  --validation-count "${SWEEP_VALIDATION_COUNT}"
  --validation-canary-count "${SWEEP_VALIDATION_CANARY_COUNT}"
  --max-sample-text-chars "${SWEEP_MAX_SAMPLE_TEXT_CHARS}"
  --max-inner-iterations "${SWEEP_MAX_INNER_ITERATIONS}"
  --max-items "${SWEEP_MAX_ITEMS}"
  --bridge-loss-adapters "${SWEEP_BRIDGE_LOSS_ADAPTERS}"
  --bridge-evaluate-provers "${SWEEP_BRIDGE_EVALUATE_PROVERS}"
  --autoencoder-bridge-workers "${SWEEP_AUTOENCODER_BRIDGE_WORKERS}"
)

FINAL_COMMON_OVERRIDES=(
  --train-count "${FINAL_TRAIN_COUNT}"
  --validation-count "${FINAL_VALIDATION_COUNT}"
  --validation-canary-count "${FINAL_VALIDATION_CANARY_COUNT}"
  --max-sample-text-chars "${FINAL_MAX_SAMPLE_TEXT_CHARS}"
  --max-inner-iterations "${FINAL_MAX_INNER_ITERATIONS}"
  --max-items "${FINAL_MAX_ITEMS}"
  --bridge-loss-adapters "${FINAL_BRIDGE_LOSS_ADAPTERS}"
  --bridge-evaluate-provers "${FINAL_BRIDGE_EVALUATE_PROVERS}"
  --autoencoder-bridge-workers "${FINAL_AUTOENCODER_BRIDGE_WORKERS}"
)

PAIRED_ARGS=(
  --paired-poll-seconds 1
  --paired-grace-seconds "${PAIRED_GRACE_SECONDS}"
  --paired-resource-guard "${PAIRED_RESOURCE_GUARD}"
  --paired-codex-max-workers "${PAIRED_CODEX_MAX_WORKERS}"
  --paired-codex-worker-memory-gb "${PAIRED_CODEX_WORKER_MEMORY_GB}"
  --paired-reserved-memory-gb "${PAIRED_RESERVED_MEMORY_GB}"
  --paired-min-available-memory-gb "${PAIRED_MIN_AVAILABLE_MEMORY_GB}"
  --paired-min-swap-free-gb "${PAIRED_MIN_SWAP_FREE_GB}"
  --paired-codex-launch-stagger-seconds "${PAIRED_CODEX_LAUNCH_STAGGER_SECONDS}"
  --paired-codex-disable-cuda "${PAIRED_CODEX_DISABLE_CUDA}"
  --paired-failed-validation-rescue-mode "${PAIRED_FAILED_VALIDATION_RESCUE_MODE}"
  --paired-failed-validation-rescue-max-clusters "${PAIRED_FAILED_VALIDATION_RESCUE_MAX_CLUSTERS}"
  --paired-failed-validation-rescue-max-attempts "${PAIRED_FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS}"
  --paired-failed-validation-rescue-interval-seconds "${PAIRED_FAILED_VALIDATION_RESCUE_INTERVAL_SECONDS}"
  --paired-failed-validation-rescue-backlog-threshold "${PAIRED_FAILED_VALIDATION_RESCUE_BACKLOG_THRESHOLD}"
  --codex-exec-mode "${CODEX_EXEC_MODE}"
  --codex-apply-mode "${CODEX_APPLY_MODE}"
  --codex-commit-mode "${CODEX_COMMIT_MODE}"
  --codex-model "${CODEX_MODEL}"
  --codex-sandbox "${CODEX_SANDBOX}"
  --codex-parallel-scopes "${CODEX_PARALLEL_SCOPES}"
  --codex-scope-workers "${CODEX_SCOPE_WORKERS}"
  --codex-scope-worker-map "${CODEX_SCOPE_WORKER_MAP}"
  --codex-bundle-mode "${CODEX_BUNDLE_MODE}"
  --codex-vector-min-similarity "${CODEX_VECTOR_MIN_SIMILARITY}"
  --codex-vector-fill-min-similarity "${CODEX_VECTOR_FILL_MIN_SIMILARITY}"
  --codex-vector-min-bundle-size "${CODEX_VECTOR_MIN_BUNDLE_SIZE}"
  --codex-vector-max-bundle-wait-seconds "${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS}"
  --codex-vector-stale-drain-cooldown-seconds "${CODEX_VECTOR_STALE_DRAIN_COOLDOWN_SECONDS}"
  --codex-target-file-lane-lock-seconds "${CODEX_TARGET_FILE_LANE_LOCK_SECONDS}"
  --codex-target-file-lane-lock-scopes "${CODEX_TARGET_FILE_LANE_LOCK_SCOPES}"
  --codex-lane-lock-mode "${CODEX_LANE_LOCK_MODE}"
  --codex-task-embeddings-provider "${CODEX_TASK_EMBEDDINGS_PROVIDER}"
  --codex-task-embeddings-batch-size "${CODEX_TASK_EMBEDDINGS_BATCH_SIZE}"
  --codex-vector-fallback-mode "${CODEX_VECTOR_FALLBACK_MODE}"
  --codex-merge-repair-mode "${CODEX_MERGE_REPAIR_MODE}"
  --codex-merge-repair-attempts "${CODEX_MERGE_REPAIR_ATTEMPTS}"
  --codex-main-apply-lock-timeout-seconds "${CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS}"
  --codex-main-apply-max-inflight-packets "${CODEX_MAIN_APPLY_MAX_INFLIGHT_PACKETS}"
)

CONFIGS=(
  "lr=0.28 ce=1.75 rec=0.60 cos=1.20 legal=2.00 hard=0.55 maxcos=0.005 maxrec=0.010 maxce=0.000 maxlegal=0.010 fam=1.05 emb=0.45 qemb=0.50 qfam=1.05 sigemb=0.50 sigfam=1.10 sigview=1.05 rtemb=0.50 rtfam=1.10 rtview=1.05 planemb=0.50 planfam=1.10 planview=1.05 argemb=0.50 argfam=1.10 argview=1.05 embnorm=0.50 famnorm=0.50 viewnorm=0.50 proto=0.55 famslot=0.55 triemb=0.45 joint=0.55 slotfam=1.10 viewfam=1.05 triview=1.00 slotviewfam=1.05 slotemb=0.55 slotviewemb=0.55 slotpair=0.30 slotview=1.05 view=1.00 viewemb=0.55 cossgd=0.55"
  "lr=0.30 ce=1.50 rec=0.70 cos=1.50 legal=4.00 hard=0.60 maxcos=0.008 maxrec=0.012 maxce=0.003 maxlegal=0.012 fam=0.95 emb=0.55 qemb=0.65 qfam=1.25 sigemb=0.70 sigfam=1.30 sigview=1.25 rtemb=0.70 rtfam=1.30 rtview=1.25 planemb=0.70 planfam=1.30 planview=1.25 argemb=0.70 argfam=1.30 argview=1.25 embnorm=0.65 famnorm=0.55 viewnorm=0.55 proto=0.50 famslot=0.70 triemb=0.65 joint=0.65 slotfam=1.25 viewfam=1.20 triview=1.25 slotviewfam=1.25 slotemb=0.65 slotviewemb=0.70 slotpair=0.40 slotview=1.20 view=1.10 viewemb=0.65 cossgd=0.65"
  "lr=0.33 ce=1.35 rec=0.80 cos=1.80 legal=8.00 hard=0.70 maxcos=0.012 maxrec=0.018 maxce=0.006 maxlegal=0.018 fam=1.15 emb=0.50 qemb=0.45 qfam=0.95 sigemb=0.45 sigfam=0.95 sigview=0.90 rtemb=0.45 rtfam=0.95 rtview=0.90 planemb=0.45 planfam=0.95 planview=0.90 argemb=0.45 argfam=0.95 argview=0.90 embnorm=0.35 famnorm=0.45 viewnorm=0.45 proto=0.65 famslot=0.45 triemb=0.40 joint=0.50 slotfam=0.95 viewfam=0.90 triview=0.85 slotviewfam=0.90 slotemb=0.50 slotviewemb=0.45 slotpair=0.25 slotview=0.95 view=0.95 viewemb=0.50 cossgd=0.75"
  "lr=0.26 ce=2.00 rec=0.50 cos=1.10 legal=16.00 hard=0.45 maxcos=0.015 maxrec=0.025 maxce=0.010 maxlegal=0.020 fam=0.85 emb=0.65 qemb=0.75 qfam=1.35 sigemb=0.80 sigfam=1.45 sigview=1.40 rtemb=0.80 rtfam=1.45 rtview=1.40 planemb=0.80 planfam=1.45 planview=1.40 argemb=0.80 argfam=1.45 argview=1.40 embnorm=0.75 famnorm=0.65 viewnorm=0.65 proto=0.45 famslot=0.80 triemb=0.80 joint=0.75 slotfam=1.35 viewfam=1.35 triview=1.45 slotviewfam=1.40 slotemb=0.75 slotviewemb=0.80 slotpair=0.50 slotview=1.35 view=1.20 viewemb=0.75 cossgd=0.60"
  "lr=0.31 ce=1.60 rec=0.65 cos=1.60 legal=32.00 hard=0.50 maxcos=0.020 maxrec=0.030 maxce=0.015 maxlegal=0.030 fam=1.10 emb=0.40 qemb=0.55 qfam=1.15 sigemb=0.60 sigfam=1.20 sigview=1.15 rtemb=0.60 rtfam=1.20 rtview=1.15 planemb=0.60 planfam=1.20 planview=1.15 argemb=0.60 argfam=1.20 argview=1.15 embnorm=0.50 famnorm=0.60 viewnorm=0.55 proto=0.70 famslot=0.60 triemb=0.55 joint=0.60 slotfam=1.20 viewfam=1.10 triview=1.10 slotviewfam=1.15 slotemb=0.60 slotviewemb=0.60 slotpair=0.35 slotview=1.15 view=1.05 viewemb=0.60 cossgd=0.70"
  "lr=0.29 ce=1.40 rec=0.75 cos=1.35 legal=64.00 hard=0.65 maxcos=0.006 maxrec=0.015 maxce=0.002 maxlegal=0.015 fam=1.00 emb=0.60 qemb=0.40 qfam=0.90 sigemb=0.40 sigfam=0.90 sigview=0.90 rtemb=0.40 rtfam=0.90 rtview=0.90 planemb=0.40 planfam=0.90 planview=0.90 argemb=0.40 argfam=0.90 argview=0.90 embnorm=0.25 famnorm=0.40 viewnorm=0.40 proto=0.55 famslot=0.40 triemb=0.35 joint=0.45 slotfam=1.00 viewfam=0.95 triview=0.90 slotviewfam=0.95 slotemb=0.45 slotviewemb=0.40 slotpair=0.20 slotview=0.90 view=0.90 viewemb=0.45 cossgd=0.60"
)

if (( TRIAL_COUNT < ${#CONFIGS[@]} )); then
  CONFIGS=("${CONFIGS[@]:0:${TRIAL_COUNT}}")
fi
FALLBACK_HPARAM_CFG="${FALLBACK_HPARAM_CFG:-${CONFIGS[0]}}"
PRESELECTED_HPARAM_CFG="${PRESELECTED_HPARAM_CFG:-${FALLBACK_HPARAM_CFG}}"

echo "[pipeline] base_run_id=${BASE_RUN_ID}"
echo "[pipeline] sampling_seed=${SAMPLING_SEED}"
echo "[pipeline] codex_exec_mode=${CODEX_EXEC_MODE}"
echo "[pipeline] sweep_loop_role=${SWEEP_LOOP_ROLE}"
echo "[pipeline] skip_hparam_sweep=${SKIP_HPARAM_SWEEP}"
echo "[pipeline] skip_final_run=${SKIP_FINAL_RUN}"
echo "[pipeline] hyperparam_budget_seconds=${TOTAL_TRIAL_SECONDS}"
echo "[pipeline] hyperparam_wall_budget_seconds=${HYPERPARAM_SWEEP_WALL_SECONDS}"
echo "[pipeline] hyperparam_parallelism=${TRIAL_PARALLELISM}"
echo "[pipeline] hyperparam_estimated_wall_seconds=${TOTAL_TRIAL_WALL_SECONDS}"
echo "[pipeline] final_run_seconds=${FINAL_SECONDS}"
echo "[pipeline] trial_timeout_seconds=${TRIAL_TIMEOUT_SECONDS}"
echo "[pipeline] final_timeout_seconds=${FINAL_TIMEOUT_SECONDS}"
echo "[pipeline] paired_grace_seconds=${PAIRED_GRACE_SECONDS}"
echo "[pipeline] paired_resource_guard=${PAIRED_RESOURCE_GUARD}"
echo "[pipeline] paired_codex_max_workers=${PAIRED_CODEX_MAX_WORKERS}"
echo "[pipeline] paired_codex_worker_memory_gb=${PAIRED_CODEX_WORKER_MEMORY_GB}"
echo "[pipeline] paired_reserved_memory_gb=${PAIRED_RESERVED_MEMORY_GB}"
echo "[pipeline] paired_min_available_memory_gb=${PAIRED_MIN_AVAILABLE_MEMORY_GB}"
echo "[pipeline] paired_min_swap_free_gb=${PAIRED_MIN_SWAP_FREE_GB}"
echo "[pipeline] paired_codex_launch_stagger_seconds=${PAIRED_CODEX_LAUNCH_STAGGER_SECONDS}"
echo "[pipeline] paired_codex_disable_cuda=${PAIRED_CODEX_DISABLE_CUDA}"
echo "[pipeline] paired_failed_validation_rescue_mode=${PAIRED_FAILED_VALIDATION_RESCUE_MODE}"
echo "[pipeline] paired_failed_validation_rescue_max_clusters=${PAIRED_FAILED_VALIDATION_RESCUE_MAX_CLUSTERS}"
echo "[pipeline] paired_failed_validation_rescue_max_attempts=${PAIRED_FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS}"
echo "[pipeline] paired_failed_validation_rescue_interval_seconds=${PAIRED_FAILED_VALIDATION_RESCUE_INTERVAL_SECONDS}"
echo "[pipeline] paired_failed_validation_rescue_backlog_threshold=${PAIRED_FAILED_VALIDATION_RESCUE_BACKLOG_THRESHOLD}"
echo "[pipeline] warm_start_run_ids=${WARM_START_RUN_IDS}"
echo "[pipeline] warm_start_states=${WARM_START_STATES}"
echo "[pipeline] sweep_projection_epochs=${SWEEP_PROJECTION_EPOCHS}"
echo "[pipeline] final_projection_epochs=${FINAL_PROJECTION_EPOCHS}"
echo "[pipeline] allow_final_fallback_on_sweep_failure=${ALLOW_FINAL_FALLBACK_ON_SWEEP_FAILURE}"
echo "[pipeline] bridge_loss_adapters=${BRIDGE_LOSS_ADAPTERS}"
echo "[pipeline] bridge_evaluate_provers=${BRIDGE_EVALUATE_PROVERS}"
echo "[pipeline] projection_max_regressions=cosine:${GENERALIZABLE_PROJECTION_MAX_COSINE_REGRESSION},reconstruction:${GENERALIZABLE_PROJECTION_MAX_RECONSTRUCTION_REGRESSION},cross_entropy:${GENERALIZABLE_PROJECTION_MAX_CROSS_ENTROPY_REGRESSION},legal_ir:${GENERALIZABLE_PROJECTION_MAX_LEGAL_IR_LOSS_REGRESSION}"
echo "[pipeline] projection_max_line_search_attempts=${GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS}"
echo "[pipeline] projection_deadband_mode=${AUTOENCODER_PROJECTION_DEADBAND_MODE}"
echo "[pipeline] projection_max_ce_deadband=${AUTOENCODER_MAX_CE_DEADBAND}"
echo "[pipeline] projection_hard_guardrail_metrics=${AUTOENCODER_HARD_GUARDRAIL_METRICS}"
echo "[pipeline] projection_prescreen_mode=${AUTOENCODER_PROJECTION_PRESCREEN_MODE}"
echo "[pipeline] projection_prescreen_top_k=${AUTOENCODER_PROJECTION_PRESCREEN_TOP_K}"
echo "[pipeline] projection_prescreen_periodic_full_search_every_n_cycles=${AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES}"
echo "[pipeline] compiler_ir_metric_max_sample_text_chars=${COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS}"
echo "[pipeline] compiler_ir_metric_sample_timeout_seconds=${COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS}"
echo "[pipeline] compiler_ir_train_mode=${COMPILER_IR_TRAIN_MODE}"
echo "[pipeline] compiler_ir_train_every_n_cycles=${COMPILER_IR_TRAIN_EVERY_N_CYCLES}"
echo "[pipeline] compiler_ir_guided_train_mode=${COMPILER_IR_GUIDED_TRAIN_MODE}"
echo "[pipeline] compiler_ir_guided_train_every_n_cycles=${COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES}"
echo "[pipeline] max_sample_text_chars=${MAX_SAMPLE_TEXT_CHARS}"
echo "[pipeline] train_count=${TRAIN_COUNT}"
echo "[pipeline] validation_count=${VALIDATION_COUNT}"
echo "[pipeline] max_inner_iterations=${MAX_INNER_ITERATIONS}"
echo "[pipeline] max_items=${MAX_ITEMS}"
echo "[pipeline] sweep_train_count=${SWEEP_TRAIN_COUNT}"
echo "[pipeline] sweep_validation_count=${SWEEP_VALIDATION_COUNT}"
echo "[pipeline] sweep_validation_canary_count=${SWEEP_VALIDATION_CANARY_COUNT}"
echo "[pipeline] sweep_max_inner_iterations=${SWEEP_MAX_INNER_ITERATIONS}"
echo "[pipeline] sweep_max_items=${SWEEP_MAX_ITEMS}"
echo "[pipeline] sweep_max_sample_text_chars=${SWEEP_MAX_SAMPLE_TEXT_CHARS}"
echo "[pipeline] sweep_bridge_loss_adapters=${SWEEP_BRIDGE_LOSS_ADAPTERS}"
echo "[pipeline] sweep_bridge_evaluate_provers=${SWEEP_BRIDGE_EVALUATE_PROVERS}"
echo "[pipeline] sweep_autoencoder_bridge_workers=${SWEEP_AUTOENCODER_BRIDGE_WORKERS}"
echo "[pipeline] final_train_count=${FINAL_TRAIN_COUNT}"
echo "[pipeline] final_validation_count=${FINAL_VALIDATION_COUNT}"
echo "[pipeline] final_validation_canary_count=${FINAL_VALIDATION_CANARY_COUNT}"
echo "[pipeline] final_max_inner_iterations=${FINAL_MAX_INNER_ITERATIONS}"
echo "[pipeline] final_max_items=${FINAL_MAX_ITEMS}"
echo "[pipeline] final_max_sample_text_chars=${FINAL_MAX_SAMPLE_TEXT_CHARS}"
echo "[pipeline] final_bridge_loss_adapters=${FINAL_BRIDGE_LOSS_ADAPTERS}"
echo "[pipeline] final_bridge_evaluate_provers=${FINAL_BRIDGE_EVALUATE_PROVERS}"
echo "[pipeline] final_autoencoder_bridge_workers=${FINAL_AUTOENCODER_BRIDGE_WORKERS}"
echo "[pipeline] validation_canary_indices=${VALIDATION_CANARY_INDICES}"
echo "[pipeline] validation_canary_count=${VALIDATION_CANARY_COUNT}"
echo "[pipeline] autoencoder_device=${AUTOENCODER_DEVICE}"
echo "[pipeline] autoencoder_bridge_workers=${AUTOENCODER_BRIDGE_WORKERS}"
echo "[pipeline] bridge_adapter_workers=${BRIDGE_ADAPTER_WORKERS}"
echo "[pipeline] codex_parallel_scopes=${CODEX_PARALLEL_SCOPES}"
echo "[pipeline] codex_scope_workers=${CODEX_SCOPE_WORKERS}"
echo "[pipeline] codex_scope_worker_map=${CODEX_SCOPE_WORKER_MAP}"
echo "[pipeline] codex_sandbox=${CODEX_SANDBOX}"
echo "[pipeline] codex_bundle_mode=${CODEX_BUNDLE_MODE}"
echo "[pipeline] codex_vector_min_bundle_size=${CODEX_VECTOR_MIN_BUNDLE_SIZE}"
echo "[pipeline] codex_vector_max_bundle_wait_seconds=${CODEX_VECTOR_MAX_BUNDLE_WAIT_SECONDS}"
echo "[pipeline] codex_target_file_lane_lock_scopes=${CODEX_TARGET_FILE_LANE_LOCK_SCOPES}"
echo "[pipeline] codex_lane_lock_mode=${CODEX_LANE_LOCK_MODE}"
echo "[pipeline] codex_main_apply_lock_timeout_seconds=${CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS}"
echo "[pipeline] codex_main_apply_max_inflight_packets=${CODEX_MAIN_APPLY_MAX_INFLIGHT_PACKETS}"
echo "[pipeline] codex_target_metric_timeout_seconds=${CODEX_TARGET_METRIC_TIMEOUT_SECONDS}"
echo "[pipeline] codex_target_metric_max_samples=${CODEX_TARGET_METRIC_MAX_SAMPLES}"

best_run_id=""
best_cfg=""
best_ce="1000000000000000000000000"
best_cos="-1000000000"
best_score="1000000000000000000000000"

trial_id_for_index() {
  local idx="$1"
  printf "%s-trial-%02d" "${BASE_RUN_ID}" "$((idx + 1))"
}

trial_summary_path_for_id() {
  local trial_id="$1"
  if [[ "${SWEEP_LOOP_ROLE}" == "paired" ]]; then
    printf "%s/%s-autoencoder.summary" "${LOG_DIR}" "${trial_id}"
  else
    printf "%s/%s.summary" "${LOG_DIR}" "${trial_id}"
  fi
}

run_python_module_with_timeout() {
  local timeout_seconds="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout --kill-after=30s "${timeout_seconds}s" "${PYTHON_BIN}" -m "${MODULE}" "$@"
  else
    "${PYTHON_BIN}" -m "${MODULE}" "$@"
  fi
}

run_trial_index() {
  local idx="$1"
  local cfg="${CONFIGS[$idx]}"
  local trial_id
  trial_id="$(trial_id_for_index "${idx}")"

  local lr=""
  local ce=""
  local rec=""
  local cos=""
  local legal=""
  local hard=""
  local maxcos="${GENERALIZABLE_PROJECTION_MAX_COSINE_REGRESSION}"
  local maxrec="${GENERALIZABLE_PROJECTION_MAX_RECONSTRUCTION_REGRESSION}"
  local maxce="${GENERALIZABLE_PROJECTION_MAX_CROSS_ENTROPY_REGRESSION}"
  local maxlegal="${GENERALIZABLE_PROJECTION_MAX_LEGAL_IR_LOSS_REGRESSION}"
  local fam="1.0"
  local emb="0.5"
  local qemb="0.5"
  local qfam="1.0"
  local sigemb="0.5"
  local sigfam="1.0"
  local sigview="1.0"
  local rtemb="0.5"
  local rtfam="1.0"
  local rtview="1.0"
  local planemb="0.5"
  local planfam="1.0"
  local planview="1.0"
  local argemb="0.5"
  local argfam="1.0"
  local argview="1.0"
  local embnorm="0.5"
  local famnorm="0.5"
  local viewnorm="0.5"
  local proto="0.5"
  local famslot="0.5"
  local triemb="0.5"
  local joint="0.5"
  local slotfam="1.0"
  local viewfam="1.0"
  local triview="1.0"
  local slotviewfam="1.0"
  local slotemb="0.5"
  local slotviewemb="0.5"
  local slotpair="0.35"
  local slotview="1.0"
  local view="1.0"
  local viewemb="0.5"
  local cossgd="0.25"
  local kv key val

  for kv in ${cfg}; do
    key="${kv%%=*}"
    val="${kv#*=}"
    case "${key}" in
      lr) lr="${val}" ;;
      ce) ce="${val}" ;;
      rec) rec="${val}" ;;
      cos) cos="${val}" ;;
      legal) legal="${val}" ;;
      hard) hard="${val}" ;;
      maxcos) maxcos="${val}" ;;
      maxrec) maxrec="${val}" ;;
      maxce) maxce="${val}" ;;
      maxlegal) maxlegal="${val}" ;;
      fam) fam="${val}" ;;
      emb) emb="${val}" ;;
      qemb) qemb="${val}" ;;
      qfam) qfam="${val}" ;;
      sigemb) sigemb="${val}" ;;
      sigfam) sigfam="${val}" ;;
      sigview) sigview="${val}" ;;
      rtemb) rtemb="${val}" ;;
      rtfam) rtfam="${val}" ;;
      rtview) rtview="${val}" ;;
      planemb) planemb="${val}" ;;
      planfam) planfam="${val}" ;;
      planview) planview="${val}" ;;
      argemb) argemb="${val}" ;;
      argfam) argfam="${val}" ;;
      argview) argview="${val}" ;;
      embnorm) embnorm="${val}" ;;
      famnorm) famnorm="${val}" ;;
      viewnorm) viewnorm="${val}" ;;
      proto) proto="${val}" ;;
      famslot) famslot="${val}" ;;
      triemb) triemb="${val}" ;;
      joint) joint="${val}" ;;
      slotfam) slotfam="${val}" ;;
      viewfam) viewfam="${val}" ;;
      triview) triview="${val}" ;;
      slotviewfam) slotviewfam="${val}" ;;
      slotemb) slotemb="${val}" ;;
      slotviewemb) slotviewemb="${val}" ;;
      slotpair) slotpair="${val}" ;;
      slotview) slotview="${val}" ;;
      view) view="${val}" ;;
      viewemb) viewemb="${val}" ;;
      cossgd) cossgd="${val}" ;;
    esac
  done

  echo "[trial] run_id=${trial_id} cfg=${cfg}"
  local -a trial_args=(
    --run-id "${trial_id}"
    --duration-seconds "${TRIAL_SECONDS}"
    --learning-rate "${lr}"
    --generalizable-projection-objective-cross-entropy-weight "${ce}"
    --generalizable-projection-objective-reconstruction-weight "${rec}"
    --generalizable-projection-objective-cosine-gap-weight "${cos}"
    --generalizable-projection-objective-legal-ir-weight "${legal}"
    --generalizable-projection-hard-example-fraction "${hard}"
    --generalizable-projection-max-cosine-regression "${maxcos}"
    --generalizable-projection-max-reconstruction-regression "${maxrec}"
    --generalizable-projection-max-cross-entropy-regression "${maxce}"
    --generalizable-projection-max-legal-ir-loss-regression "${maxlegal}"
    --autoencoder-feature-family-logit-scale "${fam}"
    --autoencoder-feature-embedding-weight-scale "${emb}"
    --autoencoder-compiler-quality-embedding-weight-scale "${qemb}"
    --autoencoder-compiler-quality-family-logit-scale "${qfam}"
    --autoencoder-logic-signature-embedding-weight-scale "${sigemb}"
    --autoencoder-logic-signature-family-logit-scale "${sigfam}"
    --autoencoder-logic-signature-legal-ir-view-logit-scale "${sigview}"
    --autoencoder-round-trip-signal-embedding-weight-scale "${rtemb}"
    --autoencoder-round-trip-signal-family-logit-scale "${rtfam}"
    --autoencoder-round-trip-signal-legal-ir-view-logit-scale "${rtview}"
    --autoencoder-decompiler-plan-embedding-weight-scale "${planemb}"
    --autoencoder-decompiler-plan-family-logit-scale "${planfam}"
    --autoencoder-decompiler-plan-legal-ir-view-logit-scale "${planview}"
    --autoencoder-predicate-argument-embedding-weight-scale "${argemb}"
    --autoencoder-predicate-argument-family-logit-scale "${argfam}"
    --autoencoder-predicate-argument-legal-ir-view-logit-scale "${argview}"
    --autoencoder-embedding-head-update-normalization "${embnorm}"
    --autoencoder-family-logit-head-update-normalization "${famnorm}"
    --autoencoder-legal-ir-view-head-update-normalization "${viewnorm}"
    --autoencoder-family-embedding-weight-scale "${proto}"
    --autoencoder-family-semantic-slot-embedding-weight-scale "${famslot}"
    --autoencoder-family-semantic-slot-legal-ir-view-embedding-weight-scale "${triemb}"
    --autoencoder-family-legal-ir-view-embedding-weight-scale "${joint}"
    --autoencoder-semantic-slot-family-logit-scale "${slotfam}"
    --autoencoder-legal-ir-view-family-logit-scale "${viewfam}"
    --autoencoder-family-semantic-slot-legal-ir-view-logit-scale "${triview}"
    --autoencoder-semantic-slot-legal-ir-view-family-logit-scale "${slotviewfam}"
    --autoencoder-semantic-slot-embedding-weight-scale "${slotemb}"
    --autoencoder-semantic-slot-legal-ir-view-embedding-weight-scale "${slotviewemb}"
    --autoencoder-semantic-slot-interaction-weight "${slotpair}"
    --autoencoder-semantic-slot-legal-ir-view-logit-scale "${slotview}"
    --autoencoder-legal-ir-view-logit-scale "${view}"
    --autoencoder-legal-ir-view-embedding-weight-scale "${viewemb}"
    --autoencoder-cosine-reconstruction-weight "${cossgd}"
    --generalizable-projection-epochs "${SWEEP_PROJECTION_EPOCHS}"
    --test-every-cycles "${SWEEP_TEST_EVERY_CYCLES}"
    "${COMMON_ARGS[@]}"
    "${SWEEP_COMMON_OVERRIDES[@]}"
  )
  local summary_path
  if [[ "${SWEEP_LOOP_ROLE}" == "paired" ]]; then
    trial_args=(--loop-role paired "${trial_args[@]}" "${PAIRED_ARGS[@]}")
    summary_path="$(trial_summary_path_for_id "${trial_id}")"
  else
    trial_args=(--loop-role autoencoder "${trial_args[@]}")
    summary_path="$(trial_summary_path_for_id "${trial_id}")"
  fi

  local trial_exit_code
  trap - ERR
  set +e
  run_python_module_with_timeout "${TRIAL_TIMEOUT_SECONDS}" "${trial_args[@]}"
  trial_exit_code=$?
  echo "[trial] exit_code run_id=${trial_id} code=${trial_exit_code}"
  if [[ ! -f "${summary_path}" ]]; then
    echo "[trial] missing summary: ${summary_path}"
  fi
  return "${trial_exit_code}"
}

score_trial_index() {
  local idx="$1"
  local cfg="${CONFIGS[$idx]}"
  local trial_id
  trial_id="$(trial_id_for_index "${idx}")"
  local summary_path
  summary_path="$(trial_summary_path_for_id "${trial_id}")"
  if [[ ! -f "${summary_path}" ]]; then
    echo "[trial] missing summary: ${summary_path}"
    return 0
  fi

  local ce_score cos_score ir_ce_score ir_cos_score learned_ir_ce_score learned_ir_cos_score learned_ir_family_ce_excess_score learned_ir_worst_family_ce_excess_score learned_ir_worst_family_cosine_gap_score bridge_score source_copy_score source_decompiled_cosine_loss_score source_decompiled_token_loss_score structural_text_score projection_accepted_score trial_score
  read -r ce_score cos_score ir_ce_score ir_cos_score learned_ir_ce_score learned_ir_cos_score learned_ir_family_ce_excess_score learned_ir_worst_family_ce_excess_score learned_ir_worst_family_cosine_gap_score bridge_score source_copy_score source_decompiled_cosine_loss_score source_decompiled_token_loss_score structural_text_score projection_accepted_score trial_score < <(
    "${PYTHON_BIN}" - "${summary_path}" <<'PY'
import json
import math
import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

def finite(name, default):
    try:
        value = float(data.get(name, default))
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(value) or math.isinf(value):
        return float(default)
    return value

def finite_nested(mapping, name, default):
    if not isinstance(mapping, dict):
        return float(default)
    try:
        value = float(mapping.get(name, default))
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(value) or math.isinf(value):
        return float(default)
    return value

ce = finite("best_validation_ce", 1e12)
cos = finite("best_validation_cosine", -1.0)
ir_ce = finite("best_validation_ir_ce", 1e12)
ir_cos = finite("best_validation_ir_cosine", -1.0)
learned_ir_ce = finite("best_validation_learned_ir_view_ce", 1e12)
learned_ir_cos = finite("best_validation_learned_ir_view_cosine", -1.0)
latest_learned_ir = data.get("latest_learned_ir_validation")
if not isinstance(latest_learned_ir, dict):
    latest_learned_ir = {}
latest_learned_ir_losses = latest_learned_ir.get("losses")
if not isinstance(latest_learned_ir_losses, dict):
    latest_learned_ir_losses = {}
learned_ir_family_ce_excess = finite(
    "best_validation_learned_ir_family_ce_excess",
    finite_nested(
        latest_learned_ir,
        "family_cross_entropy_excess_loss",
        finite_nested(
            latest_learned_ir_losses,
            "legal_ir_view_family_cross_entropy_excess_loss",
            1e12,
        ),
    ),
)
learned_ir_worst_family_ce_excess = finite(
    "best_validation_learned_ir_worst_family_ce_excess",
    finite_nested(
        latest_learned_ir,
        "worst_family_cross_entropy_excess_loss",
        1e12,
    ),
)
learned_ir_worst_family_cosine_gap = finite(
    "best_validation_learned_ir_worst_family_cosine_gap",
    finite_nested(latest_learned_ir, "worst_family_cosine_gap_loss", 1e12),
)
if learned_ir_ce > 1e11:
    learned_ir_ce = 0.0
if learned_ir_cos < -0.99:
    learned_ir_cos = 0.0
if learned_ir_family_ce_excess > 1e11:
    learned_ir_family_ce_excess = 0.0
if learned_ir_worst_family_ce_excess > 1e11:
    learned_ir_worst_family_ce_excess = 0.0
if learned_ir_worst_family_cosine_gap > 1e11:
    learned_ir_worst_family_cosine_gap = 0.0
bridge = finite("best_validation_logic_bridge_total_loss", 0.0)
if bridge > 1e11:
    bridge = 0.0
source_copy = finite("best_validation_ir_source_copy_loss", 0.0)
if source_copy > 1e11:
    source_copy = 0.0
source_decompiled_cosine = finite(
    "best_validation_ir_source_decompiled_text_embedding_cosine_loss",
    0.0,
)
if source_decompiled_cosine > 1e11:
    source_decompiled_cosine = 0.0
source_decompiled_token = finite(
    "best_validation_ir_source_decompiled_text_token_loss",
    0.0,
)
if source_decompiled_token > 1e11:
    source_decompiled_token = 0.0
structural_text = finite("best_validation_ir_structural_text_reconstruction", 0.0)
if structural_text > 1e11:
    structural_text = 0.0
projection_report = data.get("latest_feature_projection_report")
if not isinstance(projection_report, dict):
    projection_report = {}
try:
    projection_accepted = float(projection_report.get("accepted_epochs", 0.0) or 0.0)
except (TypeError, ValueError):
    projection_accepted = 0.0
projection_score = -0.05 * min(max(projection_accepted, 0.0), 4.0)
if projection_accepted <= 0.0:
    projection_score += 0.30
score = (
    ce
    + (0.90 * ir_ce)
    + (0.75 * learned_ir_ce)
    + (0.65 * learned_ir_family_ce_excess)
    + (0.55 * min(learned_ir_worst_family_ce_excess, 4.0))
    + (0.45 * min(learned_ir_worst_family_cosine_gap, 1.0))
    + (0.40 * bridge)
    + (0.70 * source_copy)
    + (0.75 * source_decompiled_cosine)
    + (0.45 * source_decompiled_token)
    + (0.40 * structural_text)
    + projection_score
    - (0.50 * cos)
    - (0.80 * ir_cos)
    - (0.60 * learned_ir_cos)
)
print(f"{ce} {cos} {ir_ce} {ir_cos} {learned_ir_ce} {learned_ir_cos} {learned_ir_family_ce_excess} {learned_ir_worst_family_ce_excess} {learned_ir_worst_family_cosine_gap} {bridge} {source_copy} {source_decompiled_cosine} {source_decompiled_token} {structural_text} {projection_accepted} {score}")
PY
  )
  local valid_trial
  valid_trial="$("${PYTHON_BIN}" - <<PY
ce = float("${ce_score}")
cos = float("${cos_score}")
ir_ce = float("${ir_ce_score}")
learned_ir_ce = float("${learned_ir_ce_score}")
score = float("${trial_score}")
print("1" if ce < 1e11 and ir_ce < 1e11 and learned_ir_ce < 1e11 and cos > -0.99 and score < 1e11 else "0")
PY
)"
  if [[ "${valid_trial}" != "1" ]]; then
    echo "[trial] skipped_invalid_score run_id=${trial_id} ce=${ce_score} cos=${cos_score} ir_ce=${ir_ce_score} ir_cos=${ir_cos_score} learned_ir_ce=${learned_ir_ce_score} learned_ir_cos=${learned_ir_cos_score} score=${trial_score}"
    return 0
  fi
  echo "[trial] score run_id=${trial_id} score=${trial_score} best_validation_ce=${ce_score} best_validation_cosine=${cos_score} best_validation_ir_ce=${ir_ce_score} best_validation_ir_cosine=${ir_cos_score} best_validation_learned_ir_view_ce=${learned_ir_ce_score} best_validation_learned_ir_view_cosine=${learned_ir_cos_score} best_validation_learned_ir_family_ce_excess=${learned_ir_family_ce_excess_score} best_validation_learned_ir_worst_family_ce_excess=${learned_ir_worst_family_ce_excess_score} best_validation_learned_ir_worst_family_cosine_gap=${learned_ir_worst_family_cosine_gap_score} projection_accepted_epochs=${projection_accepted_score} best_validation_ir_source_copy_loss=${source_copy_score} best_validation_ir_source_decompiled_text_embedding_cosine_loss=${source_decompiled_cosine_loss_score} best_validation_ir_source_decompiled_text_token_loss=${source_decompiled_token_loss_score} best_validation_ir_structural_text_reconstruction=${structural_text_score} best_validation_logic_bridge_total_loss=${bridge_score}"

  local better
  better="$("${PYTHON_BIN}" - <<PY
best_score = float("${best_score}")
score = float("${trial_score}")
best_ce = float("${best_ce}")
ce = float("${ce_score}")
best_cos = float("${best_cos}")
cos = float("${cos_score}")
is_better = (
    score < best_score
    or (abs(score - best_score) <= 1e-12 and ce < best_ce)
    or (abs(score - best_score) <= 1e-12 and abs(ce - best_ce) <= 1e-12 and cos > best_cos)
)
print("1" if is_better else "0")
PY
)"
  if [[ "${better}" == "1" ]]; then
    best_ce="${ce_score}"
    best_cos="${cos_score}"
    best_score="${trial_score}"
    best_run_id="${trial_id}"
    best_cfg="${cfg}"
    echo "[trial] new_best run_id=${best_run_id} score=${best_score} ce=${best_ce} cos=${best_cos} ir_ce=${ir_ce_score} ir_cos=${ir_cos_score} learned_ir_ce=${learned_ir_ce_score} learned_ir_cos=${learned_ir_cos_score} learned_ir_family_ce_excess=${learned_ir_family_ce_excess_score} learned_ir_worst_family_ce_excess=${learned_ir_worst_family_ce_excess_score} learned_ir_worst_family_cosine_gap=${learned_ir_worst_family_cosine_gap_score} source_decompiled_text_embedding_cosine_loss=${source_decompiled_cosine_loss_score} source_decompiled_text_token_loss=${source_decompiled_token_loss_score}"
  fi
}

if [[ "${SKIP_HPARAM_SWEEP}" == "1" ]]; then
  best_run_id="${BASE_RUN_ID}-preselected"
  best_cfg="${PRESELECTED_HPARAM_CFG}"
  best_score="preselected"
  best_ce="nan"
  best_cos="nan"
  echo "[pipeline] hparam_sweep_skipped action=use_preselected cfg=${best_cfg}"
elif (( TRIAL_PARALLELISM <= 1 )); then
  for idx in "${!CONFIGS[@]}"; do
    trap - ERR
    set +e
    run_trial_index "${idx}"
    serial_trial_exit_code=$?
    set -e
    restore_err_trap
    echo "[trial] serial_complete run_id=$(trial_id_for_index "${idx}") code=${serial_trial_exit_code}"
    score_trial_index "${idx}"
  done
else
  if (( TRIAL_PARALLELISM > ${#CONFIGS[@]} )); then
    TRIAL_PARALLELISM="${#CONFIGS[@]}"
  fi
  echo "[pipeline] starting_parallel_sweep trial_parallelism=${TRIAL_PARALLELISM} trial_count=${#CONFIGS[@]}"
  declare -a trial_pids=()
  declare -a trial_logs=()
  for idx in "${!CONFIGS[@]}"; do
    while (( $(jobs -rp | wc -l) >= TRIAL_PARALLELISM )); do
      echo "[pipeline] parallel_sweep heartbeat active_trials=$(jobs -rp | wc -l)"
      sleep "${TRIAL_PARALLEL_HEARTBEAT_SECONDS}"
    done
    trial_id="$(trial_id_for_index "${idx}")"
    trial_log_path="${LOG_DIR}/${trial_id}.launcher.log"
    trial_exit_path="${LOG_DIR}/${trial_id}.exit"
    trial_logs[$idx]="${trial_log_path}"
    echo "[trial] launch_parallel run_id=${trial_id} cfg=${CONFIGS[$idx]} log=${trial_log_path}"
    (
      trap - ERR
      set +e
      run_trial_index "${idx}"
      code=$?
      echo "${code}" > "${trial_exit_path}"
      exit "${code}"
    ) > "${trial_log_path}" 2>&1 &
    trial_pids[$idx]=$!
  done

  while (( $(jobs -rp | wc -l) > 0 )); do
    echo "[pipeline] parallel_sweep heartbeat active_trials=$(jobs -rp | wc -l)"
    sleep "${TRIAL_PARALLEL_HEARTBEAT_SECONDS}"
  done
  wait || true

  for idx in "${!CONFIGS[@]}"; do
    trial_id="$(trial_id_for_index "${idx}")"
    trial_exit_path="${LOG_DIR}/${trial_id}.exit"
    trial_log_path="${trial_logs[$idx]}"
    trial_exit_code="missing"
    if [[ -f "${trial_exit_path}" ]]; then
      trial_exit_code="$(tr -d '\n\r' < "${trial_exit_path}")"
    fi
    echo "[trial] parallel_complete run_id=${trial_id} code=${trial_exit_code} log=${trial_log_path}"
    score_trial_index "${idx}"
  done
fi

if [[ -z "${best_run_id}" ]]; then
  if [[ "${ALLOW_FINAL_FALLBACK_ON_SWEEP_FAILURE}" == "1" ]]; then
    best_run_id="${BASE_RUN_ID}-fallback"
    best_cfg="${FALLBACK_HPARAM_CFG}"
    best_score="fallback"
    best_ce="nan"
    best_cos="nan"
    echo "[pipeline] hparam_sweep_no_successful_trial action=use_fallback cfg=${best_cfg}"
  else
    echo "[pipeline] hparam_sweep_no_successful_trial action=abort"
    exit 1
  fi
fi

echo "[pipeline] best_trial=${best_run_id} cfg=${best_cfg} score=${best_score} ce=${best_ce} cos=${best_cos}"

if [[ "${SKIP_FINAL_RUN}" == "1" ]]; then
  echo "[pipeline] final_run_skipped action=sweep_only best_trial=${best_run_id} score=${best_score}"
  exit 0
fi

final_run_id="${BASE_RUN_ID}-best-8h"
lr=""
ce=""
rec=""
cos=""
legal=""
hard=""
maxcos="${GENERALIZABLE_PROJECTION_MAX_COSINE_REGRESSION}"
maxrec="${GENERALIZABLE_PROJECTION_MAX_RECONSTRUCTION_REGRESSION}"
maxce="${GENERALIZABLE_PROJECTION_MAX_CROSS_ENTROPY_REGRESSION}"
maxlegal="${GENERALIZABLE_PROJECTION_MAX_LEGAL_IR_LOSS_REGRESSION}"
fam="1.0"
emb="0.5"
qemb="0.5"
qfam="1.0"
sigemb="0.5"
sigfam="1.0"
sigview="1.0"
rtemb="0.5"
rtfam="1.0"
rtview="1.0"
planemb="0.5"
planfam="1.0"
planview="1.0"
argemb="0.5"
argfam="1.0"
argview="1.0"
embnorm="0.5"
famnorm="0.5"
viewnorm="0.5"
proto="0.5"
famslot="0.5"
triemb="0.5"
joint="0.5"
slotfam="1.0"
viewfam="1.0"
triview="1.0"
slotviewfam="1.0"
slotemb="0.5"
slotviewemb="0.5"
slotpair="0.35"
slotview="1.0"
view="1.0"
viewemb="0.5"
cossgd="0.25"
for kv in ${best_cfg}; do
  key="${kv%%=*}"
  val="${kv#*=}"
  case "${key}" in
    lr) lr="${val}" ;;
    ce) ce="${val}" ;;
    rec) rec="${val}" ;;
    cos) cos="${val}" ;;
    legal) legal="${val}" ;;
    hard) hard="${val}" ;;
    maxcos) maxcos="${val}" ;;
    maxrec) maxrec="${val}" ;;
    maxce) maxce="${val}" ;;
    maxlegal) maxlegal="${val}" ;;
    fam) fam="${val}" ;;
    emb) emb="${val}" ;;
    qemb) qemb="${val}" ;;
    qfam) qfam="${val}" ;;
    sigemb) sigemb="${val}" ;;
    sigfam) sigfam="${val}" ;;
    sigview) sigview="${val}" ;;
    rtemb) rtemb="${val}" ;;
    rtfam) rtfam="${val}" ;;
    rtview) rtview="${val}" ;;
    planemb) planemb="${val}" ;;
    planfam) planfam="${val}" ;;
    planview) planview="${val}" ;;
    argemb) argemb="${val}" ;;
    argfam) argfam="${val}" ;;
    argview) argview="${val}" ;;
    embnorm) embnorm="${val}" ;;
    famnorm) famnorm="${val}" ;;
    viewnorm) viewnorm="${val}" ;;
    proto) proto="${val}" ;;
    famslot) famslot="${val}" ;;
    triemb) triemb="${val}" ;;
    joint) joint="${val}" ;;
    slotfam) slotfam="${val}" ;;
    viewfam) viewfam="${val}" ;;
    triview) triview="${val}" ;;
    slotviewfam) slotviewfam="${val}" ;;
    slotemb) slotemb="${val}" ;;
    slotviewemb) slotviewemb="${val}" ;;
    slotpair) slotpair="${val}" ;;
    slotview) slotview="${val}" ;;
    view) view="${val}" ;;
    viewemb) viewemb="${val}" ;;
    cossgd) cossgd="${val}" ;;
  esac
done

echo "[pipeline] starting final 8h run_id=${final_run_id}"
final_args=(
  --loop-role paired
  --run-id "${final_run_id}"
  --duration-seconds "${FINAL_SECONDS}"
  --learning-rate "${lr}"
  --generalizable-projection-objective-cross-entropy-weight "${ce}"
  --generalizable-projection-objective-reconstruction-weight "${rec}"
  --generalizable-projection-objective-cosine-gap-weight "${cos}"
  --generalizable-projection-objective-legal-ir-weight "${legal}"
  --generalizable-projection-hard-example-fraction "${hard}"
  --generalizable-projection-max-cosine-regression "${maxcos}"
  --generalizable-projection-max-reconstruction-regression "${maxrec}"
  --generalizable-projection-max-cross-entropy-regression "${maxce}"
  --generalizable-projection-max-legal-ir-loss-regression "${maxlegal}"
  --autoencoder-feature-family-logit-scale "${fam}"
  --autoencoder-feature-embedding-weight-scale "${emb}"
  --autoencoder-compiler-quality-embedding-weight-scale "${qemb}"
  --autoencoder-compiler-quality-family-logit-scale "${qfam}"
  --autoencoder-logic-signature-embedding-weight-scale "${sigemb}"
  --autoencoder-logic-signature-family-logit-scale "${sigfam}"
  --autoencoder-logic-signature-legal-ir-view-logit-scale "${sigview}"
  --autoencoder-round-trip-signal-embedding-weight-scale "${rtemb}"
  --autoencoder-round-trip-signal-family-logit-scale "${rtfam}"
  --autoencoder-round-trip-signal-legal-ir-view-logit-scale "${rtview}"
  --autoencoder-decompiler-plan-embedding-weight-scale "${planemb}"
  --autoencoder-decompiler-plan-family-logit-scale "${planfam}"
  --autoencoder-decompiler-plan-legal-ir-view-logit-scale "${planview}"
  --autoencoder-predicate-argument-embedding-weight-scale "${argemb}"
  --autoencoder-predicate-argument-family-logit-scale "${argfam}"
  --autoencoder-predicate-argument-legal-ir-view-logit-scale "${argview}"
  --autoencoder-embedding-head-update-normalization "${embnorm}"
  --autoencoder-family-logit-head-update-normalization "${famnorm}"
  --autoencoder-legal-ir-view-head-update-normalization "${viewnorm}"
  --autoencoder-family-embedding-weight-scale "${proto}"
  --autoencoder-family-semantic-slot-embedding-weight-scale "${famslot}"
  --autoencoder-family-semantic-slot-legal-ir-view-embedding-weight-scale "${triemb}"
  --autoencoder-family-legal-ir-view-embedding-weight-scale "${joint}"
  --autoencoder-semantic-slot-family-logit-scale "${slotfam}"
  --autoencoder-legal-ir-view-family-logit-scale "${viewfam}"
  --autoencoder-family-semantic-slot-legal-ir-view-logit-scale "${triview}"
  --autoencoder-semantic-slot-legal-ir-view-family-logit-scale "${slotviewfam}"
  --autoencoder-semantic-slot-embedding-weight-scale "${slotemb}"
  --autoencoder-semantic-slot-legal-ir-view-embedding-weight-scale "${slotviewemb}"
  --autoencoder-semantic-slot-interaction-weight "${slotpair}"
  --autoencoder-semantic-slot-legal-ir-view-logit-scale "${slotview}"
  --autoencoder-legal-ir-view-logit-scale "${view}"
  --autoencoder-legal-ir-view-embedding-weight-scale "${viewemb}"
  --autoencoder-cosine-reconstruction-weight "${cossgd}"
  --generalizable-projection-epochs "${FINAL_PROJECTION_EPOCHS}"
  --test-every-cycles "${FINAL_TEST_EVERY_CYCLES}"
  "${COMMON_ARGS[@]}"
  "${FINAL_COMMON_OVERRIDES[@]}"
  "${PAIRED_ARGS[@]}"
)
if [[ -n "${WARM_START_RUN_IDS}" ]]; then
  IFS=',' read -r -a warm_start_run_ids <<< "${WARM_START_RUN_IDS}"
  for warm_start_run_id in "${warm_start_run_ids[@]}"; do
    warm_start_run_id="${warm_start_run_id//[[:space:]]/}"
    if [[ -n "${warm_start_run_id}" ]]; then
      final_args+=(--warm-start-run-id "${warm_start_run_id}")
    fi
  done
fi
if [[ -n "${WARM_START_STATES}" ]]; then
  IFS=',' read -r -a warm_start_states <<< "${WARM_START_STATES}"
  for warm_start_state in "${warm_start_states[@]}"; do
    warm_start_state="${warm_start_state//[[:space:]]/}"
    if [[ -n "${warm_start_state}" ]]; then
      final_args+=(--warm-start-state "${warm_start_state}")
    fi
  done
fi

trap - ERR
set +e
run_python_module_with_timeout "${FINAL_TIMEOUT_SECONDS}" "${final_args[@]}"
final_exit_code=$?
set -e
restore_err_trap

if (( final_exit_code != 0 )); then
  final_summary_path="${LOG_DIR}/${final_run_id}-autoencoder.summary"
  if [[ -f "${final_summary_path}" ]]; then
    read -r final_cycles final_best_ce final_stop_reason < <(
      "${PYTHON_BIN}" - "${final_summary_path}" <<'PY'
import json
import math
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

cycles = int(data.get("cycles", 0) or 0)
best_ce = float(data.get("best_validation_ce", 1e12) or 1e12)
if math.isnan(best_ce) or math.isinf(best_ce):
    best_ce = 1e12
stop_reason = str(data.get("latest_stop_reason", "") or "")
print(f"{cycles} {best_ce} {stop_reason}")
PY
    )
    recovered="$("${PYTHON_BIN}" - <<PY
cycles = int("${final_cycles:-0}")
best_ce = float("${final_best_ce:-1000000000000.0}")
min_cycles = int("${FINAL_RECOVERY_MIN_CYCLES}")
print("1" if cycles >= min_cycles and best_ce < 1e11 else "0")
PY
)"
    if [[ "${recovered}" == "1" ]]; then
      echo "[pipeline] recovered_final_nonzero_exit run_id=${final_run_id} code=${final_exit_code} cycles=${final_cycles} best_validation_ce=${final_best_ce} stop_reason=${final_stop_reason:-unknown}"
      echo "[pipeline] completed final 8h run_id=${final_run_id}"
      exit 0
    fi
    echo "[pipeline] final_nonzero_exit_unrecovered run_id=${final_run_id} code=${final_exit_code} cycles=${final_cycles} best_validation_ce=${final_best_ce}"
  else
    echo "[pipeline] final_nonzero_exit_missing_summary run_id=${final_run_id} code=${final_exit_code}"
  fi
  exit "${final_exit_code}"
fi

echo "[pipeline] completed final 8h run_id=${final_run_id}"
