#!/usr/bin/env bash
# Run the fail-closed LegalIR rollout: smoke -> hparam -> canary -> production.
set -euo pipefail
trap 'rc=$?; echo "[rollout] failed line=${LINENO} status=${rc}" >&2; exit "${rc}"' ERR

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv-cuda/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

BASE_RUN_ID="${BASE_RUN_ID:-legal-ir-hammer-leanstral-rollout-$(date -u +%Y%m%dT%H%M%SZ)}"
SMOKE_SECONDS="${SMOKE_SECONDS:-600}"
TRIAL_SECONDS="${TRIAL_SECONDS:-600}"
TRIAL_COUNT="${TRIAL_COUNT:-6}"
CANARY_SECONDS="${CANARY_SECONDS:-28800}"
PRODUCTION_SECONDS="${PRODUCTION_SECONDS:-${FINAL_SECONDS:-86400}}"
# Compatibility names retained for existing operators and monitoring/tests.
FINAL_SECONDS="${PRODUCTION_SECONDS}"
FINAL_RUN_LABEL="24h"

LOG_DIR="${ROOT_DIR}/workspace/test-logs"
SNAPSHOT_PATH="${SNAPSHOT_PATH:-${LOG_DIR}/${BASE_RUN_ID}-rollout-snapshots.json}"
EVIDENCE_OUTPUT="${EVIDENCE_OUTPUT:-${LOG_DIR}/${BASE_RUN_ID}-rollout-gate.json}"
EVIDENCE_DIR="${EVIDENCE_DIR:-${LOG_DIR}/${BASE_RUN_ID}-rollout-evidence}"
SUMMARY_PATH="${SUMMARY_PATH:-${LOG_DIR}/${BASE_RUN_ID}-best-24h-autoencoder.summary}"
DRY_RUN=0
GATE_ONLY=0
ALLOW_PREFIX=0

usage() {
  cat <<'EOF'
Usage: run_hammer_leanstral_hparam.sh [OPTIONS]

Runs short smoke, one-hour hyperparameter search, eight-hour canary, and
twenty-four-hour production in that exact order. Every completed prefix must
pass the staged rollout gate before the next stage starts.

Options:
  --run-id, --base-run-id ID  Stable rollout identifier
  --snapshot-path PATH        Staged snapshot manifest
  --evidence-output PATH      Final gate decision JSON
  --summary-path PATH         Production summary path (gate-only compatibility)
  --gate-only                 Gate an existing snapshot without starting work
  --allow-prefix              With --gate-only, accept a valid strict prefix
  --dry-run                   Print the rollout contract and commands
  -h, --help                  Show this help
EOF
}

require_value() {
  if (( $# < 2 )) || [[ -z "${2:-}" ]]; then
    echo "missing value for $1" >&2
    exit 2
  fi
}

while (( $# > 0 )); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --gate-only) GATE_ONLY=1; shift ;;
    --allow-prefix) ALLOW_PREFIX=1; shift ;;
    --run-id|--base-run-id)
      require_value "$@"
      BASE_RUN_ID="$2"
      SNAPSHOT_PATH="${LOG_DIR}/${BASE_RUN_ID}-rollout-snapshots.json"
      EVIDENCE_OUTPUT="${LOG_DIR}/${BASE_RUN_ID}-rollout-gate.json"
      EVIDENCE_DIR="${LOG_DIR}/${BASE_RUN_ID}-rollout-evidence"
      SUMMARY_PATH="${LOG_DIR}/${BASE_RUN_ID}-best-24h-autoencoder.summary"
      shift 2
      ;;
    --snapshot-path) require_value "$@"; SNAPSHOT_PATH="$2"; shift 2 ;;
    --evidence-output) require_value "$@"; EVIDENCE_OUTPUT="$2"; shift 2 ;;
    --summary-path) require_value "$@"; SUMMARY_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if (( SMOKE_SECONDS != 600 || TRIAL_SECONDS * TRIAL_COUNT != 3600 \
      || CANARY_SECONDS != 28800 || PRODUCTION_SECONDS != 86400 )); then
  echo "rollout durations are immutable: smoke=600, hparam=3600, canary=28800, production=86400" >&2
  exit 2
fi
if (( TRIAL_COUNT < 1 || TRIAL_COUNT > 6 || TRIAL_SECONDS < 1 )); then
  echo "TRIAL_COUNT must be 1..6 and TRIAL_SECONDS must be positive" >&2
  exit 2
fi

gate_boolean_flag() {
  local value="${1,,}"
  case "${value}" in
    1|true|yes|on) printf '%s' "$2" ;;
    0|false|no|off) printf '%s' "$3" ;;
    *) echo "invalid boolean value for rollout gate: $1" >&2; return 2 ;;
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

REPRESENTATION_PROMOTION_GATE_FLAG="$(gate_boolean_flag "${GATE_REQUIRE_REPRESENTATION_PROMOTION}" --require-representation-promotion --no-require-representation-promotion)"
SUCCESSFUL_REPRESENTATION_PROMOTION_GATE_FLAG="$(gate_boolean_flag "${GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION}" --require-successful-representation-promotion --no-require-successful-representation-promotion)"
COMPLETE_REPRESENTATION_EVIDENCE_GATE_FLAG="$(gate_boolean_flag "${GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE}" --require-complete-representation-evidence --no-require-complete-representation-evidence)"

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/../ipfs_accelerate_py${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHON_BIN
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1}"
export IPFS_DATASETS_PY_LLM_PROVIDER="${IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py}"
export LEANSTRAL_AUDIT_PROVIDER="${LEANSTRAL_AUDIT_PROVIDER:-leanstral_local}"
export LEANSTRAL_AUDIT_BATCH_USE_MESH="${LEANSTRAL_AUDIT_BATCH_USE_MESH:-1}"

export RUN_SUMMARY_GATE_MODULE="scripts.ops.legal_ir.hammer_leanstral_rollout_gate"
export RUN_SUMMARY_GATE_ARGS="${REPRESENTATION_PROMOTION_GATE_FLAG} ${SUCCESSFUL_REPRESENTATION_PROMOTION_GATE_FLAG} ${COMPLETE_REPRESENTATION_EVIDENCE_GATE_FLAG} --max-validation-ce-regression ${GATE_MAX_VALIDATION_CE_REGRESSION:-0.02} --max-validation-cosine-regression ${GATE_MAX_VALIDATION_COSINE_REGRESSION:-0.02} --max-compiler-ir-ce-regression ${GATE_MAX_COMPILER_IR_CE_REGRESSION:-0.05} --max-compiler-ir-cosine-regression ${GATE_MAX_COMPILER_IR_COSINE_REGRESSION:-0.05} --max-source-copy-penalty ${GATE_MAX_SOURCE_COPY_PENALTY:-0.35} --max-per-view-ir-metric-regression ${GATE_MAX_PER_VIEW_IR_METRIC_REGRESSION} --max-symbolic-validity-regression ${GATE_MAX_SYMBOLIC_VALIDITY_REGRESSION} --max-hammer-proof-rate-regression ${GATE_MAX_HAMMER_PROOF_RATE_REGRESSION} --max-reconstruction-rate-regression ${GATE_MAX_RECONSTRUCTION_RATE_REGRESSION} --max-source-copy-penalty-regression ${GATE_MAX_SOURCE_COPY_PENALTY_REGRESSION} --max-todo-productivity-regression ${GATE_MAX_TODO_PRODUCTIVITY_REGRESSION} --min-cycles-for-todo-gate ${GATE_MIN_CYCLES_FOR_TODO_GATE:-1}"

export SWEEP_LOOP_ROLE="${SWEEP_LOOP_ROLE:-paired}"
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

run_staged_gate() {
  local output_path="$1"
  local prefix_flag="${2:-}"
  local args=(
    "${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate
    staged-gate --snapshot-path "${SNAPSHOT_PATH}" --evidence-output "${output_path}"
    --verify-rollback-artifacts
  )
  [[ "${prefix_flag}" == "allow-prefix" ]] && args+=(--allow-prefix)
  "${args[@]}"
}

if (( GATE_ONLY )); then
  if [[ -f "${SNAPSHOT_PATH}" ]]; then
    prefix=""
    (( ALLOW_PREFIX )) && prefix="allow-prefix"
    run_staged_gate "${EVIDENCE_OUTPUT}" "${prefix}"
  elif [[ -f "${SUMMARY_PATH}" ]]; then
    # Preserve the pre-staged diagnostic path for an individual legacy run.
    read -r -a legacy_gate_args <<< "${RUN_SUMMARY_GATE_ARGS}"
    "${PYTHON_BIN}" -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate gate \
      --summary-path "${SUMMARY_PATH}" "${legacy_gate_args[@]}"
  else
    # Let staged-gate produce and persist the canonical fail-closed diagnostic.
    run_staged_gate "${EVIDENCE_OUTPUT}" ""
  fi
  exit $?
fi

if (( DRY_RUN )); then
  echo "rollout_id=${BASE_RUN_ID}"
  echo "stage_sequence=short_smoke,one_hour_hparam,eight_hour_canary,twenty_four_hour_production"
  echo "smoke_seconds=${SMOKE_SECONDS}"
  echo "trial_seconds=${TRIAL_SECONDS}"
  echo "trial_count=${TRIAL_COUNT}"
  echo "hparam_seconds=$((TRIAL_SECONDS * TRIAL_COUNT))"
  echo "canary_seconds=${CANARY_SECONDS}"
  echo "final_seconds=${PRODUCTION_SECONDS}"
  echo "final_run_label=${FINAL_RUN_LABEL}"
  echo "snapshot_path=${SNAPSHOT_PATH}"
  echo "evidence_output=${EVIDENCE_OUTPUT}"
  echo "summary_path=${SUMMARY_PATH}"
  echo "smoke_command=${ROOT_DIR}/scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh --run-id ${BASE_RUN_ID}-short-smoke"
  echo "hparam_canary_command=TRIAL_SECONDS=${TRIAL_SECONDS} TRIAL_COUNT=${TRIAL_COUNT} FINAL_SECONDS=${CANARY_SECONDS} FINAL_RUN_LABEL=8h source scripts/ops/logic/run_hparam_then_8h.sh ${BASE_RUN_ID}"
  echo "production_command=${PYTHON_BIN} -m ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner --run-id ${BASE_RUN_ID}-best-24h --duration-seconds ${PRODUCTION_SECONDS}"
  echo "extra_daemon_args=${EXTRA_DAEMON_ARGS}"
  echo "gate_metrics=${HARD_GUARDRAILS}"
  echo "representation_gate_required=${GATE_REQUIRE_REPRESENTATION_PROMOTION}"
  echo "representation_gate_require_successful=${GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION}"
  echo "representation_gate_require_complete_evidence=${GATE_REQUIRE_COMPLETE_REPRESENTATION_EVIDENCE}"
  echo "summary_gate_module=${RUN_SUMMARY_GATE_MODULE}"
  exit 0
fi

managed_processes_json() {
  "${PYTHON_BIN}" - "$$" "${BASE_RUN_ID}" <<'PY'
import json
import os
import sys

owner = int(sys.argv[1])
rollout_id = sys.argv[2]
markers = (
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    "scripts/ops/logic/run_hparam_then_8h.sh",
    "scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh",
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
    if rollout_id in command and any(marker in command for marker in markers):
        found.append({"pid": int(entry.name), "command": command[:1000]})
print(json.dumps(found, sort_keys=True))
PY
}

assert_no_orphans() {
  local phase="$1" processes
  processes="$(managed_processes_json)"
  if [[ "${processes}" != "[]" ]]; then
    echo "[rollout] orphaned managed processes at ${phase}: ${processes}" >&2
    return 1
  fi
}

append_snapshot() {
  local stage="$1" duration="$2" stage_pid="$3" primary_summary="$4"
  shift 4
  local artifact_path="${EVIDENCE_DIR}/${stage}.summary.json"
  "${PYTHON_BIN}" - "${BASE_RUN_ID}" "${SNAPSHOT_PATH}" "${stage}" "${duration}" \
    "${stage_pid}" "${primary_summary}" "${artifact_path}" "$@" <<'PY'
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

rollout_id, manifest_raw, stage, duration_raw, pid_raw, primary_raw, artifact_raw, *summary_args = sys.argv[1:]
manifest_path = Path(manifest_raw)
primary_path = Path(primary_raw)
artifact_path = Path(artifact_raw)
duration = int(duration_raw)

if not primary_path.is_file():
    raise SystemExit(f"missing stage summary: {primary_path}")
try:
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid stage summary {primary_path}: {exc}") from exc
if not isinstance(primary, dict):
    raise SystemExit(f"stage summary is not an object: {primary_path}")

artifact_path.parent.mkdir(parents=True, exist_ok=True)
if artifact_path.exists():
    raise SystemExit(f"refusing to overwrite rollback artifact: {artifact_path}")
shutil.copyfile(primary_path, artifact_path)
artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
revision = subprocess.run(
    ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
).stdout.strip()

summary_paths = []
seen = set()
for raw in [primary_raw, *summary_args]:
    path = Path(raw)
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path)
    if key not in seen and path.is_file():
        seen.add(key)
        summary_paths.append(path)

summaries = []
for path in summary_paths:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if isinstance(value, dict):
        summaries.append(value)

observed_wall_clock = 0.0
wall_clock_sources = summaries if stage == "one_hour_hparam" else [primary]
for source in wall_clock_sources:
    try:
        elapsed = float(source.get("elapsed_seconds"))
    except (TypeError, ValueError):
        continue
    if math.isfinite(elapsed) and elapsed > 0:
        observed_wall_clock += elapsed

def first_mapping(*values):
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}

promotion = first_mapping(
    primary.get("latest_legal_ir_learned_guidance_promotion"),
    primary.get("legal_ir_learned_guidance_promotion"),
    primary.get("latest_representation_promotion"),
)
canary_evidence = promotion.get("canary_evidence") if isinstance(promotion, dict) else {}
if not isinstance(canary_evidence, dict):
    canary_evidence = {}
validation = primary.get("latest_legal_ir_view_family_validation")
if not isinstance(validation, dict):
    validation = {}
family_metrics = first_mapping(
    canary_evidence.get("family_metrics"),
    primary.get("family_metrics"),
    validation.get("view_family_metrics"),
)
raw_family_metrics = family_metrics

hammer = primary.get("latest_daemon_hammer_guidance")
if not isinstance(hammer, dict):
    hammer = {}
training = hammer.get("autoencoder_training")
if not isinstance(training, dict):
    training = {}
guidance_ids = training.get("guidance_ids")
if not isinstance(guidance_ids, list):
    guidance_ids = []
trusted_count = int(primary.get("trusted_hammer_guidance_count", 0) or 0)
received_count = int(training.get("applied_count", 0) or 0)
feedback_digest = ""
if guidance_ids:
    feedback_digest = hashlib.sha256(
        json.dumps(guidance_ids, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()

accepted = 0
for summary in summaries:
    raw = summary.get("codex_main_apply_count", summary.get("codex_accepted_patch_count", 0))
    try:
        accepted += max(0, int(raw or 0))
    except (TypeError, ValueError):
        pass

queue_durations = []
for summary in summaries:
    telemetry = summary.get("runtime_telemetry")
    containers = [telemetry, summary.get("latest_runtime_telemetry")]
    for container in containers:
        if not isinstance(container, dict):
            continue
        spans = container.get("spans", container.get("recent_spans", []))
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict) or span.get("phase") not in {"leanstral_queue", "codex_queue_wait"}:
                continue
            try:
                value = float(span.get("duration_seconds"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value >= 0:
                queue_durations.append(value)
queue_durations.sort()
queue_p95 = None
if queue_durations:
    index = max(0, math.ceil(0.95 * len(queue_durations)) - 1)
    queue_p95 = queue_durations[index]
else:
    for key in ("queue_lag_p95_seconds", "codex_queue_lag_p95_seconds"):
        try:
            candidate = float(primary[key])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(candidate) and candidate >= 0:
            queue_p95 = candidate
            break

def finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None

def paired_regression(values, higher=(), lower=()):
    if not isinstance(values, dict):
        return None
    baseline = values.get("baseline")
    candidate = values.get("candidate")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return None
    compared = False
    for name in higher:
        before, after = finite(baseline.get(name)), finite(candidate.get(name))
        if before is not None and after is not None:
            compared = True
            if after < before - 1e-12:
                return True
    for name in lower:
        before, after = finite(baseline.get(name)), finite(candidate.get(name))
        if before is not None and after is not None:
            compared = True
            if after > before + 1e-12:
                return True
    return False if compared else None

previous_queue = None
previous_provenance_coverage = None
if manifest_path.exists():
    try:
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_snapshots = previous_manifest.get("snapshots", [])
        if isinstance(previous_snapshots, list) and previous_snapshots:
            previous_lag = previous_snapshots[-1].get("queue_lag", {})
            if isinstance(previous_lag, dict):
                previous_queue = finite(previous_lag.get("p95_seconds"))
            previous_provenance_coverage = finite(
                previous_snapshots[-1].get("legal_ir_contract_coverage")
            )
    except (OSError, json.JSONDecodeError, AttributeError):
        previous_queue = None

view_gaps = primary.get("legal_ir_contract_view_family_gaps")
failure_counts = primary.get("legal_ir_contract_failure_counts")
provenance_coverage = finite(primary.get("legal_ir_contract_coverage"))
provenance_evidence_present = (
    isinstance(view_gaps, dict)
    and isinstance(failure_counts, dict)
    and provenance_coverage is not None
)

def positive_family_value(mapping, family):
    if not isinstance(mapping, dict):
        return False
    aliases = {family, "knowledge_graphs" if family == "kg" else family}
    for key, value in mapping.items():
        key_text = str(key).lower()
        if not any(alias in key_text for alias in aliases):
            continue
        number = finite(value)
        if number is not None and number > 0:
            return True
        if isinstance(value, (list, dict)) and len(value) > 0:
            return True
    return False

families = ("deontic", "frame_logic", "tdfol", "kg", "cec", "external_provers", "decompiler")
normalized_family_metrics = {}
for family in families:
    raw = raw_family_metrics.get(family, {}) if isinstance(raw_family_metrics, dict) else {}
    raw = dict(raw) if isinstance(raw, dict) else {}
    semantic = paired_regression(
        raw,
        higher=("ir_cosine_similarity", "compiler_ir_cosine", "symbolic_validity_success_rate", "structural_validity"),
        lower=("ir_cross_entropy_loss", "compiler_ir_cross_entropy_loss"),
    )
    anti_copy = paired_regression(
        raw,
        higher=("anti_copy_success_rate",),
        lower=("source_copy_penalty", "source_copy_reward_hack_penalty", "source_copy_rate"),
    )
    hammer_proof = paired_regression(
        raw,
        higher=("hammer_proof_success_rate",),
        lower=("hammer_failure_rate",),
    )
    reconstruction = paired_regression(
        raw,
        higher=("reconstruction_success_rate", "hammer_reconstruction_success_rate"),
        lower=("reconstruction_failure_rate",),
    )
    # An absent paired metric is explicit incomplete evidence and must not be
    # serialized as a passing boolean.
    values = dict(raw)
    if semantic is not None:
        values["semantic_regression"] = semantic
    if anti_copy is not None:
        values["anti_copy_regression"] = anti_copy
    if hammer_proof is not None:
        values["hammer_proof_regression"] = hammer_proof
    if reconstruction is not None:
        values["lean_reconstruction_regression"] = reconstruction
    if provenance_evidence_present:
        values["provenance_regression"] = (
            positive_family_value(view_gaps, family)
            or positive_family_value(failure_counts, family)
            or (
                previous_provenance_coverage is not None
                and provenance_coverage < previous_provenance_coverage - 1e-12
            )
        )
    values["process_lifecycle_regression"] = False
    if queue_p95 is not None:
        values["queue_lag_regression"] = bool(
            previous_queue is not None and queue_p95 > previous_queue + 1e-12
        )
    normalized_family_metrics[family] = values

evaluator = primary.get("snapshot_evaluator")
promoted_snapshot = primary.get("latest_promoted_snapshot_evaluation")
published_snapshot = primary.get("latest_published_snapshot")
snapshot_shutdown = primary.get("snapshot_shutdown")
snapshot_diagnostics = {
    "evaluator_present": isinstance(evaluator, dict),
    "promoted_snapshot_present": isinstance(promoted_snapshot, dict),
    "published_snapshot_present": isinstance(published_snapshot, dict),
    "shutdown_present": isinstance(snapshot_shutdown, dict),
}
snapshot_complete = False
if isinstance(evaluator, dict):
    evaluation_enabled = primary.get("snapshot_evaluation_enabled", evaluator.get("enabled", True)) is True
    if not evaluation_enabled:
        snapshot_diagnostics["reason"] = "snapshot_evaluation_disabled"
    else:
        counters = (
            "failed_evaluations", "dropped_snapshot_count", "pending_count",
            "outstanding_count", "ready_result_count",
        )
        drained = all(int(evaluator.get(name, -1) or 0) == 0 for name in counters)
        drained = drained and not str(evaluator.get("inflight_snapshot_id") or "")
        closed = evaluator.get("closed") is True and evaluator.get("worker_alive") is False
        completed = int(evaluator.get("completed_evaluations", -1) or 0)
        published = int(evaluator.get("published_snapshots", -1) or 0)
        accounted = published > 0 and completed >= published
        matching_promotion = (
            isinstance(promoted_snapshot, dict)
            and isinstance(published_snapshot, dict)
            and bool(promoted_snapshot.get("snapshot_id"))
            and promoted_snapshot.get("snapshot_id") == published_snapshot.get("snapshot_id")
            and str(promoted_snapshot.get("status") or "").lower() == "succeeded"
            and not promoted_snapshot.get("error")
        )
        aggregate = promoted_snapshot.get("metrics") if isinstance(promoted_snapshot, dict) else None
        if isinstance(aggregate, dict) and isinstance(aggregate.get("family_evaluation"), dict):
            aggregate = aggregate["family_evaluation"]
        family_complete = (
            isinstance(aggregate, dict)
            and aggregate.get("complete") is True
            and aggregate.get("matching_snapshot") is True
            and int(aggregate.get("failure_count", -1) or 0) == 0
            and not aggregate.get("failed_families")
            and aggregate.get("snapshot_id", promoted_snapshot.get("snapshot_id"))
                == promoted_snapshot.get("snapshot_id")
        )
        shutdown_clean = (
            isinstance(snapshot_shutdown, dict)
            and snapshot_shutdown.get("drained") is True
            and not snapshot_shutdown.get("unmatched_result_ids")
        )
        snapshot_diagnostics.update({
            "worker_closed": closed,
            "queues_drained": drained,
            "published_evaluations_completed": accounted,
            "latest_snapshot_promoted": matching_promotion,
            "family_validation_complete": family_complete,
            "shutdown_clean": shutdown_clean,
        })
        snapshot_complete = all(
            (closed, drained, accounted, matching_promotion, family_complete, shutdown_clean)
        )

status = str(primary.get("status") or "").strip().lower()
fatal_stop_reason = str(primary.get("latest_stop_reason") or "").strip()
child_exit_failure = False
for key in ("autoencoder_exit_code", "codex_exit_code"):
    code = primary.get(key)
    if code is not None:
        try:
            child_exit_failure = child_exit_failure or int(code) != 0
        except (TypeError, ValueError):
            child_exit_failure = True
codex_exit_codes = primary.get("codex_exit_codes")
if isinstance(codex_exit_codes, dict):
    for code in codex_exit_codes.values():
        try:
            child_exit_failure = child_exit_failure or int(code) != 0
        except (TypeError, ValueError):
            child_exit_failure = True
summary_success = (
    primary.get("final") is True
    and status not in {"failed", "error", "cancelled"}
    and not fatal_stop_reason
    and not child_exit_failure
    and snapshot_complete
)
normalized_status = "succeeded" if summary_success else "incomplete"
snapshot = dict(primary)
snapshot.update(
    {
        "stage": stage,
        "duration_seconds": duration,
        "snapshot_complete": snapshot_complete,
        "snapshot_completeness": snapshot_diagnostics,
        "status": normalized_status,
        "managed_processes": [
            {
                "name": f"{stage}-controller",
                "pid": int(pid_raw),
                "status": "exited",
                "exit_code": 0,
                "orphaned": False,
            }
        ],
        "family_metrics": normalized_family_metrics,
        "raw_family_evidence": raw_family_metrics,
        "trusted_feedback": {
            "trusted_count": trusted_count,
            "autoencoder_received_count": received_count,
            "source_digest": feedback_digest,
            "autoencoder_source_digest": feedback_digest if received_count > 0 else "",
        },
        "accepted_patches": accepted,
        "elapsed_seconds": observed_wall_clock if observed_wall_clock > 0 else None,
        "wall_clock_seconds": observed_wall_clock if observed_wall_clock > 0 else None,
        "queue_lag": {"p95_seconds": queue_p95},
        "rollback_evidence": {
            "artifact_path": str(artifact_path),
            "sha256": artifact_digest,
            "baseline_revision": revision,
            "restorable": True,
        },
        "source_summaries": [str(path) for path in summary_paths],
    }
)

if manifest_path.exists():
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid existing rollout manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("rollout_id") != rollout_id:
        raise SystemExit("rollout manifest identity mismatch")
else:
    manifest = {
        "schema_version": "legal-ir-hammer-leanstral-rollout-v1",
        "rollout_id": rollout_id,
        "snapshots": [],
    }
snapshots = manifest.get("snapshots")
if not isinstance(snapshots, list):
    raise SystemExit("rollout manifest snapshots is not an array")
if any(isinstance(item, dict) and item.get("stage") == stage for item in snapshots):
    raise SystemExit(f"duplicate rollout stage: {stage}")
snapshots.append(snapshot)
manifest_path.parent.mkdir(parents=True, exist_ok=True)
temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, manifest_path)
print(f"[rollout] captured stage={stage} summary={primary_path} rollback={artifact_path}")
PY
}

assert_no_orphans preflight
if [[ -e "${SNAPSHOT_PATH}" || -e "${EVIDENCE_DIR}" ]]; then
  echo "rollout evidence already exists; choose a new --run-id or use --gate-only" >&2
  exit 2
fi
mkdir -p "${EVIDENCE_DIR}"

SMOKE_RUN_ID="${BASE_RUN_ID}-short-smoke"
SMOKE_SUMMARY="${LOG_DIR}/${SMOKE_RUN_ID}-autoencoder.summary"
echo "[rollout] starting stage=short_smoke run_id=${SMOKE_RUN_ID}"
DURATION_SECONDS="${SMOKE_SECONDS}" RUN_ID="${SMOKE_RUN_ID}" \
  "${ROOT_DIR}/scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh" --run-id "${SMOKE_RUN_ID}" &
smoke_pid=$!
wait "${smoke_pid}"
assert_no_orphans short_smoke
append_snapshot short_smoke "${SMOKE_SECONDS}" "${smoke_pid}" "${SMOKE_SUMMARY}"
run_staged_gate "${EVIDENCE_DIR}/short_smoke-gate.json" allow-prefix

echo "[rollout] starting stages=one_hour_hparam,eight_hour_canary run_id=${BASE_RUN_ID}"
export TRIAL_SECONDS TRIAL_COUNT
export FINAL_SECONDS="${CANARY_SECONDS}"
export FINAL_RUN_LABEL="8h"
gate_completed_hparam_sweep() {
  local selected_run_id="$1"
  local trial_summaries=()
  shopt -s nullglob
  if [[ "${SWEEP_LOOP_ROLE}" == "paired" ]]; then
    trial_summaries=("${LOG_DIR}/${BASE_RUN_ID}"-trial-*-autoencoder.summary)
    HPARAM_SUMMARY="${LOG_DIR}/${selected_run_id}-autoencoder.summary"
  else
    trial_summaries=("${LOG_DIR}/${BASE_RUN_ID}"-trial-*.summary)
    HPARAM_SUMMARY="${LOG_DIR}/${selected_run_id}.summary"
  fi
  shopt -u nullglob
  if (( ${#trial_summaries[@]} != TRIAL_COUNT )); then
    echo "hparam sweep evidence incomplete: ${#trial_summaries[@]}/${TRIAL_COUNT} summaries" >&2
    return 1
  fi
  append_snapshot one_hour_hparam "$((TRIAL_SECONDS * TRIAL_COUNT))" "$$" \
    "${HPARAM_SUMMARY}" "${trial_summaries[@]}"
  run_staged_gate "${EVIDENCE_DIR}/one_hour_hparam-gate.json" allow-prefix
}
export RUN_HPARAM_BEFORE_FINAL_FUNCTION=gate_completed_hparam_sweep
# Source intentionally: the helper leaves its selected, fully expanded final_args
# array available so production reuses the exact gated canary configuration.
# shellcheck source=../logic/run_hparam_then_8h.sh
source "${ROOT_DIR}/scripts/ops/logic/run_hparam_then_8h.sh" "${BASE_RUN_ID}"
unset RUN_HPARAM_BEFORE_FINAL_FUNCTION

assert_no_orphans eight_hour_canary
if [[ -z "${best_run_id:-}" ]]; then
  echo "hparam helper did not expose its selected run" >&2
  exit 1
fi
CANARY_RUN_ID="${BASE_RUN_ID}-best-8h"
CANARY_SUMMARY="${LOG_DIR}/${CANARY_RUN_ID}-autoencoder.summary"
append_snapshot eight_hour_canary "${CANARY_SECONDS}" "$$" "${CANARY_SUMMARY}"
run_staged_gate "${EVIDENCE_DIR}/eight_hour_canary-gate.json" allow-prefix

if ! declare -p final_args >/dev/null 2>&1; then
  echo "hparam helper did not expose the selected canary arguments" >&2
  exit 1
fi
PRODUCTION_RUN_ID="${BASE_RUN_ID}-best-24h"
production_args=("${final_args[@]}")
for ((idx = 0; idx < ${#production_args[@]}; idx++)); do
  case "${production_args[$idx]}" in
    --run-id) production_args[$((idx + 1))]="${PRODUCTION_RUN_ID}" ;;
    --duration-seconds) production_args[$((idx + 1))]="${PRODUCTION_SECONDS}" ;;
  esac
done

echo "[rollout] starting stage=twenty_four_hour_production run_id=${PRODUCTION_RUN_ID}"
"${PYTHON_BIN}" -m "${MODULE}" "${production_args[@]}" &
production_pid=$!
wait "${production_pid}"
assert_no_orphans twenty_four_hour_production
if [[ "${SUMMARY_PATH}" != "${LOG_DIR}/${PRODUCTION_RUN_ID}-autoencoder.summary" ]]; then
  echo "custom SUMMARY_PATH does not match the production runner output" >&2
  exit 2
fi
run_summary_gate "${SUMMARY_PATH}" twenty_four_hour_production
append_snapshot twenty_four_hour_production "${PRODUCTION_SECONDS}" "${production_pid}" "${SUMMARY_PATH}"
run_staged_gate "${EVIDENCE_OUTPUT}"
echo "[rollout] completed rollout_id=${BASE_RUN_ID} evidence=${EVIDENCE_OUTPUT}"
