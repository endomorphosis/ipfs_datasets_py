#!/bin/bash
# 2026-11-06 urgent refill: NEW Saxony / Saxony-Anhalt / NI Amtsblatt targets only.
# List + 8-item test + enqueue. Does NOT start full fetches. No Brandenburg / done QIDs.
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_queue_ext_20261106u.log
mkdir -p "$L"
echo "$(date) queue_ext_20261106u start pid=$$" | tee -a "$LOG"

# Preflight: refuse any QID with nonempty done ledger
refuse_if_done() {
  local qid=$1 n=$2
  local f=/workspace/world_law/staging/counties/_state/done_wd_${qid}.jsonl
  if [ -s "$f" ]; then
    echo "$(date) REFUSE already collected $n $qid lines=$(wc -l < "$f")" | tee -a "$LOG"
    return 1
  fi
  return 0
}

SPECS=(
  "de_mei|Q6313|Landkreis Meißen"
  "de_jl|Q6068|Jerichower Land"
  "de_l|Q6308|Landkreis Leipzig"
  "de_soe|Q6323|Landkreis Sächsische Schweiz-Osterzgebirge"
  "de_gr|Q6317|Landkreis Görlitz"
  "de_wf|Q6041|Landkreis Wolfenbüttel"
)

READY=()
for spec in "${SPECS[@]}"; do
  IFS='|' read -r n qid name <<< "$spec"
  refuse_if_done "$qid" "$n" || continue
  cfg="entries/cfg/${n}.json"
  out="entries/${n}_amtsblatt.json"
  [ -f "$cfg" ] || { echo "$(date) missing cfg $n" | tee -a "$LOG"; continue; }
  # Always re-list for fresh URLs (do not trust stale markers alone)
  echo "$(date) LIST $n" | tee -a "$LOG"
  $PY -u de_amtsblatt_list.py "$cfg" "$out" > "$L/${n}_list.log" 2>&1
  rc=$?
  cnt=$($PY -c "import json; print(len(json.load(open('$out')).get('items') or []))" 2>/dev/null || echo 0)
  echo "$(date) LISTED $n rc=$rc count=$cnt" | tee -a "$LOG"
  if [ "$cnt" -lt 8 ]; then
    echo "$(date) skip low count $n=$cnt" | tee -a "$LOG"
    continue
  fi
  # Force fresh 8-item test (ignore old .ok)
  rm -f "entries/_test_${n}.ok"
  READY+=("$spec")
done

echo "$(date) ready_for_test ${#READY[@]}: ${READY[*]}" | tee -a "$LOG"
if [ ${#READY[@]} -eq 0 ]; then
  echo "$(date) nothing to enqueue" | tee -a "$LOG"
  exit 1
fi

# county_enqueue_batch waits for idle fetcher, runs 8-item tests, appends pending
bash ./county_enqueue_batch.sh "${READY[@]}" >> "$LOG" 2>&1
echo "$(date) enqueue_batch rc=$?" | tee -a "$LOG"

$PY - <<'PY' | tee -a "$LOG"
import json
from pathlib import Path
q=Path('county_supervisor_queue.jsonl')
rows=[json.loads(l) for l in q.read_text().splitlines() if l.strip()]
pending=[r for r in rows if r.get('status')=='pending']
running=[r for r in rows if r.get('status')=='running']
print('QUEUE pending', [(r['id'], r.get('listed'), r.get('qid')) for r in pending])
print('QUEUE running', [(r['id'], r.get('listed')) for r in running])
print('QUEUE pending_docs', sum(int(r.get('listed') or 0) for r in pending))
PY
echo "$(date) queue_ext_20261106u done" | tee -a "$LOG"
