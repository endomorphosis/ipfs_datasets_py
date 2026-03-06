#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

MIN_RECORDS="${MIN_RECORDS:-20}"
COVERAGE_SCOPE="${COVERAGE_SCOPE:-target}"
MATRIX_OUT_DIR="${MATRIX_OUT_DIR:-/tmp/procedural_rules_guarded_matrix_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$MATRIX_OUT_DIR"

# Semi-colon separated state groups.
MATRIX_SETS="${MATRIX_SETS:-MI;KY MI;IN MO NH}"

log() {
  printf '[matrix] %s\n' "$*"
}

run_one() {
  local set_name="$1"
  local states="$2"
  local out_log="$MATRIX_OUT_DIR/${set_name}.log"
  log "running ${set_name} states=\"${states}\""
  set +e
  STATES="$states" MIN_RECORDS="$MIN_RECORDS" COVERAGE_SCOPE="$COVERAGE_SCOPE" \
    bash scripts/ops/legal_data/run_procedural_rules_guarded_smoke.sh >"$out_log" 2>&1
  local rc=$?
  set -e
  echo "$rc" >"$MATRIX_OUT_DIR/${set_name}.rc"
  log "finished ${set_name} rc=${rc}"
}

idx=0
pids=()
set_names=()
IFS=';' read -r -a sets <<< "$MATRIX_SETS"
for states_raw in "${sets[@]}"; do
  states="$(echo "$states_raw" | xargs)"
  [[ -n "$states" ]] || continue
  idx=$((idx + 1))
  set_name="set_${idx}"
  set_names+=("$set_name")
  run_one "$set_name" "$states" &
  pids+=("$!")
done

for pid in "${pids[@]}"; do
  wait "$pid"
done

python3 - <<'PY' "$MATRIX_OUT_DIR" "$MATRIX_SETS"
import json, os, sys
out_dir = sys.argv[1]
matrix_sets = [s.strip() for s in sys.argv[2].split(';') if s.strip()]
result = {
    'out_dir': out_dir,
    'matrix_sets': matrix_sets,
    'runs': [],
}
all_ok = True
for i, states in enumerate(matrix_sets, start=1):
    name = f"set_{i}"
    rc_path = os.path.join(out_dir, f"{name}.rc")
    log_path = os.path.join(out_dir, f"{name}.log")
    rc = int(open(rc_path, 'r', encoding='utf-8').read().strip()) if os.path.exists(rc_path) else 99
    ok = rc == 0
    all_ok = all_ok and ok
    tail = []
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        tail = lines[-40:]
    result['runs'].append({
        'name': name,
        'states': states,
        'rc': rc,
        'ok': ok,
        'log_path': log_path,
        'tail': tail,
    })
result['all_ok'] = all_ok
summary_path = os.path.join(out_dir, 'summary.json')
with open(summary_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2)
print(json.dumps({'all_ok': all_ok, 'summary_path': summary_path}, indent=2))
PY

if [[ ! -f "$MATRIX_OUT_DIR/summary.json" ]]; then
  echo "matrix summary missing" >&2
  exit 1
fi

if [[ "$(python3 - <<'PY' "$MATRIX_OUT_DIR/summary.json"
import json,sys
p=sys.argv[1]
obj=json.load(open(p,'r',encoding='utf-8'))
print('1' if obj.get('all_ok') else '0')
PY
)" == "1" ]]; then
  log "guarded matrix: PASS"
else
  log "guarded matrix: FAIL"
  exit 1
fi
