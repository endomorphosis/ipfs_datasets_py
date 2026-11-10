#!/bin/bash
# 2026-11-06 queue expansion: list -> 8-item test -> atomic append. Does NOT start full fetches.
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_queue_ext_20261106s.log
mkdir -p "$L" entries
echo "$(date) queue_ext_20261106s start pid=$$" | tee -a "$LOG"

# id|qid|name
SPECS=(
  "de_lg|Q5910|Landkreis Lüneburg"
  "de_hi|Q5978|Landkreis Hildesheim"
  "de_ce|Q5919|Landkreis Celle"
  "de_nom|Q6018|Landkreis Northeim"
  "de_dh|Q5956|Landkreis Diepholz"
  "de_hk|Q5922|Heidekreis"
  "de_wtm|Q5931|Landkreis Wittmund"
  "de_vec|Q5941|Landkreis Vechta"
)

list_one() {
  local n=$1
  local cfg=entries/cfg/${n}.json
  local out=entries/${n}_amtsblatt.json
  if [ -s "$out" ]; then
    local cnt
    cnt=$($PY -c "import json; print(len(json.load(open('$out')).get('items') or []))")
    if [ "$cnt" -ge 8 ]; then
      echo "$(date) list skip existing $n count=$cnt" | tee -a "$LOG"
      return 0
    fi
  fi
  echo "$(date) LIST start $n" | tee -a "$LOG"
  $PY -u de_amtsblatt_list.py "$cfg" "$out" > "$L/${n}_list.log" 2>&1
  local rc=$?
  local cnt=0
  [ -s "$out" ] && cnt=$($PY -c "import json; print(len(json.load(open('$out')).get('items') or []))")
  echo "$(date) LIST done $n rc=$rc count=$cnt" | tee -a "$LOG"
  return $rc
}

# List sequentially (polite; each lister already sleeps 2s/page)
for spec in "${SPECS[@]}"; do
  IFS='|' read -r n qid name <<< "$spec"
  list_one "$n" || echo "$(date) LIST fail $n" | tee -a "$LOG"
done

echo "$(date) listing phase done; enqueue_batch next" | tee -a "$LOG"
# Build args for targets with >=8 items
ARGS=()
for spec in "${SPECS[@]}"; do
  IFS='|' read -r n qid name <<< "$spec"
  [ -s entries/${n}_amtsblatt.json ] || continue
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json')).get('items') or []))")
  [ "$cnt" -ge 8 ] || { echo "$(date) skip enqueue $n count=$cnt" | tee -a "$LOG"; continue; }
  ARGS+=("${n}|${qid}|${name}")
done
echo "$(date) enqueue candidates: ${ARGS[*]}" | tee -a "$LOG"
if [ ${#ARGS[@]} -eq 0 ]; then
  echo "$(date) no candidates" | tee -a "$LOG"
  exit 1
fi
# county_enqueue_batch waits for fetcher idle, tests 8, appends pending
bash ./county_enqueue_batch.sh "${ARGS[@]}" >> "$LOG" 2>&1
echo "$(date) queue_ext_20261106s done" | tee -a "$LOG"
# Final queue snapshot
$PY - <<'PY' | tee -a "$LOG"
import json
from pathlib import Path
q=Path('county_supervisor_queue.jsonl')
rows=[json.loads(l) for l in q.read_text().splitlines() if l.strip()]
pending=[r for r in rows if r.get('status')=='pending']
running=[r for r in rows if r.get('status')=='running']
print('QUEUE pending', [(r['id'], r.get('listed')) for r in pending])
print('QUEUE running', [(r['id'], r.get('listed')) for r in running])
print('QUEUE pending_docs', sum(int(r.get('listed') or 0) for r in pending))
PY
