#!/usr/bin/env bash
set -euo pipefail
trap 'echo "[pipeline] failed line=${LINENO} status=$?"' ERR

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

TRIAL_SECONDS="${TRIAL_SECONDS:-600}"
TRIAL_COUNT="${TRIAL_COUNT:-6}"
TOTAL_TRIAL_SECONDS=$((TRIAL_SECONDS * TRIAL_COUNT))
FINAL_SECONDS="${FINAL_SECONDS:-$((8 * 60 * 60))}"
SWEEP_LOOP_ROLE="${SWEEP_LOOP_ROLE:-autoencoder}"
SWEEP_TEST_EVERY_CYCLES="${SWEEP_TEST_EVERY_CYCLES:-48}"
FINAL_TEST_EVERY_CYCLES="${FINAL_TEST_EVERY_CYCLES:-96}"
SWEEP_PROJECTION_EPOCHS="${SWEEP_PROJECTION_EPOCHS:-1}"
FINAL_PROJECTION_EPOCHS="${FINAL_PROJECTION_EPOCHS:-2}"
FINAL_RECOVERY_MIN_CYCLES="${FINAL_RECOVERY_MIN_CYCLES:-1}"

CODEX_EXEC_MODE="${CODEX_EXEC_MODE:-codex_cli}"
if ! command -v codex >/dev/null 2>&1; then
  CODEX_EXEC_MODE="packet_only"
fi

COMMON_ARGS=(
  --train-count 4
  --validation-count 4
  --validation-canary-count 4
  --max-inner-iterations 3
  --max-items 8
  --autoencoder-device auto
  --autoencoder-bridge-workers 2
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
  --generalizable-projection-max-cosine-regression 0.005
  --generalizable-projection-max-reconstruction-regression 0.01
  --generalizable-projection-max-cross-entropy-regression 0.0
  --generalizable-projection-max-legal-ir-loss-regression 0.01
  --learning-rate-floor-ratio 0.25
  --learning-rate-cap-ratio 1.5
  --learning-rate-plateau-delta 1e-5
)

PAIRED_ARGS=(
  --paired-poll-seconds 1
  --paired-grace-seconds 20
  --codex-exec-mode "${CODEX_EXEC_MODE}"
  --codex-apply-mode apply_to_main
  --codex-commit-mode none
  --codex-model gpt-5.3-codex
  --codex-parallel-scopes compiler_parser,deontic,ir_decompiler
  --codex-scope-workers 1
  --codex-bundle-mode vector
  --codex-vector-min-similarity 0.65
  --codex-vector-fill-min-similarity 0.45
  --codex-vector-min-bundle-size 2
  --codex-vector-max-bundle-wait-seconds 120
)

CONFIGS=(
  "lr=0.28 ce=1.75 rec=0.60 cos=0.60 legal=1.35 hard=0.55 fam=1.05 emb=0.45 qemb=0.50 qfam=1.05 sigemb=0.50 sigfam=1.10 sigview=1.05 rtemb=0.50 rtfam=1.10 rtview=1.05 planemb=0.50 planfam=1.10 planview=1.05 argemb=0.50 argfam=1.10 argview=1.05 embnorm=0.50 famnorm=0.50 viewnorm=0.50 proto=0.55 famslot=0.55 triemb=0.45 joint=0.55 slotfam=1.10 viewfam=1.05 triview=1.00 slotviewfam=1.05 slotemb=0.55 slotviewemb=0.55 slotpair=0.30 slotview=1.05 view=1.00 viewemb=0.55 cossgd=0.25"
  "lr=0.30 ce=1.50 rec=0.70 cos=0.70 legal=1.25 hard=0.60 fam=0.95 emb=0.55 qemb=0.65 qfam=1.25 sigemb=0.70 sigfam=1.30 sigview=1.25 rtemb=0.70 rtfam=1.30 rtview=1.25 planemb=0.70 planfam=1.30 planview=1.25 argemb=0.70 argfam=1.30 argview=1.25 embnorm=0.65 famnorm=0.55 viewnorm=0.55 proto=0.50 famslot=0.70 triemb=0.65 joint=0.65 slotfam=1.25 viewfam=1.20 triview=1.25 slotviewfam=1.25 slotemb=0.65 slotviewemb=0.70 slotpair=0.40 slotview=1.20 view=1.10 viewemb=0.65 cossgd=0.35"
  "lr=0.33 ce=1.35 rec=0.80 cos=0.80 legal=1.15 hard=0.70 fam=1.15 emb=0.50 qemb=0.45 qfam=0.95 sigemb=0.45 sigfam=0.95 sigview=0.90 rtemb=0.45 rtfam=0.95 rtview=0.90 planemb=0.45 planfam=0.95 planview=0.90 argemb=0.45 argfam=0.95 argview=0.90 embnorm=0.35 famnorm=0.45 viewnorm=0.45 proto=0.65 famslot=0.45 triemb=0.40 joint=0.50 slotfam=0.95 viewfam=0.90 triview=0.85 slotviewfam=0.90 slotemb=0.50 slotviewemb=0.45 slotpair=0.25 slotview=0.95 view=0.95 viewemb=0.50 cossgd=0.20"
  "lr=0.26 ce=2.00 rec=0.50 cos=0.50 legal=1.50 hard=0.45 fam=0.85 emb=0.65 qemb=0.75 qfam=1.35 sigemb=0.80 sigfam=1.45 sigview=1.40 rtemb=0.80 rtfam=1.45 rtview=1.40 planemb=0.80 planfam=1.45 planview=1.40 argemb=0.80 argfam=1.45 argview=1.40 embnorm=0.75 famnorm=0.65 viewnorm=0.65 proto=0.45 famslot=0.80 triemb=0.80 joint=0.75 slotfam=1.35 viewfam=1.35 triview=1.45 slotviewfam=1.40 slotemb=0.75 slotviewemb=0.80 slotpair=0.50 slotview=1.35 view=1.20 viewemb=0.75 cossgd=0.40"
  "lr=0.31 ce=1.60 rec=0.65 cos=0.75 legal=1.40 hard=0.50 fam=1.10 emb=0.40 qemb=0.55 qfam=1.15 sigemb=0.60 sigfam=1.20 sigview=1.15 rtemb=0.60 rtfam=1.20 rtview=1.15 planemb=0.60 planfam=1.20 planview=1.15 argemb=0.60 argfam=1.20 argview=1.15 embnorm=0.50 famnorm=0.60 viewnorm=0.55 proto=0.70 famslot=0.60 triemb=0.55 joint=0.60 slotfam=1.20 viewfam=1.10 triview=1.10 slotviewfam=1.15 slotemb=0.60 slotviewemb=0.60 slotpair=0.35 slotview=1.15 view=1.05 viewemb=0.60 cossgd=0.30"
  "lr=0.29 ce=1.40 rec=0.75 cos=0.65 legal=1.30 hard=0.65 fam=1.00 emb=0.60 qemb=0.40 qfam=0.90 sigemb=0.40 sigfam=0.90 sigview=0.90 rtemb=0.40 rtfam=0.90 rtview=0.90 planemb=0.40 planfam=0.90 planview=0.90 argemb=0.40 argfam=0.90 argview=0.90 embnorm=0.25 famnorm=0.40 viewnorm=0.40 proto=0.55 famslot=0.40 triemb=0.35 joint=0.45 slotfam=1.00 viewfam=0.95 triview=0.90 slotviewfam=0.95 slotemb=0.45 slotviewemb=0.40 slotpair=0.20 slotview=0.90 view=0.90 viewemb=0.45 cossgd=0.25"
)

if (( TRIAL_COUNT < ${#CONFIGS[@]} )); then
  CONFIGS=("${CONFIGS[@]:0:${TRIAL_COUNT}}")
fi

echo "[pipeline] base_run_id=${BASE_RUN_ID}"
echo "[pipeline] codex_exec_mode=${CODEX_EXEC_MODE}"
echo "[pipeline] sweep_loop_role=${SWEEP_LOOP_ROLE}"
echo "[pipeline] hyperparam_budget_seconds=${TOTAL_TRIAL_SECONDS}"
echo "[pipeline] final_run_seconds=${FINAL_SECONDS}"

best_run_id=""
best_cfg=""
best_ce="1000000000000000000000000"
best_cos="-1000000000"

for idx in "${!CONFIGS[@]}"; do
  cfg="${CONFIGS[$idx]}"
  trial_id="${BASE_RUN_ID}-trial-$(printf "%02d" "$((idx + 1))")"

  lr=""
  ce=""
  rec=""
  cos=""
  legal=""
  hard=""
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
  trial_args=(
    --run-id "${trial_id}"
    --duration-seconds "${TRIAL_SECONDS}"
    --learning-rate "${lr}"
    --generalizable-projection-objective-cross-entropy-weight "${ce}"
    --generalizable-projection-objective-reconstruction-weight "${rec}"
    --generalizable-projection-objective-cosine-gap-weight "${cos}"
    --generalizable-projection-objective-legal-ir-weight "${legal}"
    --generalizable-projection-hard-example-fraction "${hard}"
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
  )
  if [[ "${SWEEP_LOOP_ROLE}" == "paired" ]]; then
    trial_args=(--loop-role paired "${trial_args[@]}" "${PAIRED_ARGS[@]}")
    summary_path="${LOG_DIR}/${trial_id}-autoencoder.summary"
  else
    trial_args=(--loop-role autoencoder "${trial_args[@]}")
    summary_path="${LOG_DIR}/${trial_id}.summary"
  fi

  set +e
  "${PYTHON_BIN}" -m "${MODULE}" "${trial_args[@]}"
  trial_exit_code=$?
  set -e
  echo "[trial] exit_code run_id=${trial_id} code=${trial_exit_code}"

  if [[ ! -f "${summary_path}" ]]; then
    echo "[trial] missing summary: ${summary_path}"
    continue
  fi

  read -r ce_score cos_score < <(
    "${PYTHON_BIN}" - "${summary_path}" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
ce = float(data.get("best_validation_ce", 1e9))
cos = float(data.get("best_validation_cosine", -1.0))
print(f"{ce} {cos}")
PY
  )
  valid_trial="$("${PYTHON_BIN}" - <<PY
ce = float("${ce_score}")
cos = float("${cos_score}")
print("1" if ce < 1e11 and cos > -0.99 else "0")
PY
)"
  if [[ "${valid_trial}" != "1" ]]; then
    echo "[trial] skipped_invalid_score run_id=${trial_id} ce=${ce_score} cos=${cos_score}"
    continue
  fi
  echo "[trial] score run_id=${trial_id} best_validation_ce=${ce_score} best_validation_cosine=${cos_score}"

  better="$("${PYTHON_BIN}" - <<PY
best_ce = float("${best_ce}")
best_cos = float("${best_cos}")
ce = float("${ce_score}")
cos = float("${cos_score}")
is_better = (ce < best_ce) or (abs(ce - best_ce) <= 1e-12 and cos > best_cos)
print("1" if is_better else "0")
PY
)"
  if [[ "${better}" == "1" ]]; then
    best_ce="${ce_score}"
    best_cos="${cos_score}"
    best_run_id="${trial_id}"
    best_cfg="${cfg}"
    echo "[trial] new_best run_id=${best_run_id} ce=${best_ce} cos=${best_cos}"
  fi
done

if [[ -z "${best_run_id}" ]]; then
  echo "[pipeline] no successful hyperparameter trial found"
  exit 1
fi

echo "[pipeline] best_trial=${best_run_id} cfg=${best_cfg} ce=${best_ce} cos=${best_cos}"

final_run_id="${BASE_RUN_ID}-best-8h"
lr=""
ce=""
rec=""
cos=""
legal=""
hard=""
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
  "${PAIRED_ARGS[@]}"
)

set +e
"${PYTHON_BIN}" -m "${MODULE}" "${final_args[@]}"
final_exit_code=$?
set -e

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
