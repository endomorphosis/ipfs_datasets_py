#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".venv/bin/activate" ]]; then
  echo "[error] Missing virtualenv at .venv. Create it first." >&2
  exit 1
fi

source .venv/bin/activate

STATES="${STATES:-OR}"
MAX_ROUNDS="${MAX_ROUNDS:-1}"
ACTORS_PER_ROUND="${ACTORS_PER_ROUND:-1}"
ACTOR_CONCURRENCY="${ACTOR_CONCURRENCY:-1}"
MAX_STATUTES="${MAX_STATUTES:-0}"
TOP_N_DIAGNOSTICS="${TOP_N_DIAGNOSTICS:-10}"

OUTPUT_ROOT="${OUTPUT_ROOT:-/tmp/state_laws_agentic_full_runs}"
RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${OUTPUT_ROOT}/run_${RUN_STAMP}"
mkdir -p "$OUT_DIR"

echo "[agentic-state-laws] root=$ROOT_DIR"
echo "[agentic-state-laws] states=$STATES max_rounds=$MAX_ROUNDS actors_per_round=$ACTORS_PER_ROUND actor_concurrency=$ACTOR_CONCURRENCY max_statutes=$MAX_STATUTES"
echo "[agentic-state-laws] out_dir=$OUT_DIR"

python -m ipfs_datasets_py.optimizers.agentic.state_laws_actor_critic_loop \
  --states "$STATES" \
  --max-rounds "$MAX_ROUNDS" \
  --actors-per-round "$ACTORS_PER_ROUND" \
  --actor-concurrency "$ACTOR_CONCURRENCY" \
  --max-statutes "$MAX_STATUTES" \
  --top-n-diagnostics "$TOP_N_DIAGNOSTICS" \
  --output-dir "$OUT_DIR" \
  | tee "$OUT_DIR/run.log"

FINAL_SUMMARY_PATH="$OUT_DIR"/*/final_summary.json
if compgen -G "$FINAL_SUMMARY_PATH" > /dev/null; then
  python - <<'PY' "$OUT_DIR"
import glob
import json
import os
import sys

root = os.path.abspath(sys.argv[1])
matches = sorted(glob.glob(os.path.join(root, "*", "final_summary.json")))
if not matches:
    print("[agentic-state-laws] final_summary not found")
    raise SystemExit(0)

final_summary = matches[-1]
payload = json.loads(open(final_summary, "r", encoding="utf-8").read())
best = payload.get("best") or {}
metadata = best.get("metadata") or {}
coverage = metadata.get("coverage_summary") or {}
etl = metadata.get("etl_readiness") or {}

print(f"[agentic-state-laws] final_summary={final_summary}")
print(f"[agentic-state-laws] converged={payload.get('converged')} best_score={best.get('critic_score')}")
print(f"[agentic-state-laws] statutes_count={metadata.get('statutes_count')} states_count={metadata.get('states_count')}")
print(
    "[agentic-state-laws] coverage="
    f"{coverage.get('states_with_nonzero_statutes')}/{coverage.get('states_targeted')}"
)
print(
    "[agentic-state-laws] etl="
    f"ready={etl.get('ready_for_kg_etl')} full_text_ratio={etl.get('full_text_ratio')} "
    f"jsonld_ratio={etl.get('jsonld_ratio')}"
)
print(f"[agentic-state-laws] jsonld_dir={metadata.get('jsonld_dir')}")
PY
fi
