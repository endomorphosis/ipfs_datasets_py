#!/bin/bash
# 2026-11-06 10:10 PST check-in: refill after Ammerland; Brandenburg Amtsblatt batch.
# Does NOT start full fetches. Supervisor owns the only fetcher slot.
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_queue_ext_20261106t.log
mkdir -p "$L"
echo "$(date) queue_ext_20261106t start pid=$$" | tee -a "$LOG"

# Already listed + test_ok (append only). Skip de_waf (done prior), de_cux (8/8 404).
SPECS=(
  "de_bar|Q6115|Landkreis Barnim"
  "de_hvl|Q6139|Landkreis Havelland"
  "de_los|Q6178|Landkreis Oder-Spree"
  "de_opr|Q6125|Landkreis Ostprignitz-Ruppin"
  "de_pm|Q6142|Landkreis Potsdam-Mittelmark"
  "de_pr|Q6132|Landkreis Prignitz"
  "de_spn|Q6165|Landkreis Spree-Neiße"
  "de_tf|Q6146|Landkreis Teltow-Fläming"
)

ARGS=()
for spec in "${SPECS[@]}"; do
  IFS='|' read -r n qid name <<< "$spec"
  [ -s "entries/${n}_amtsblatt.json" ] || { echo "$(date) skip missing list $n" | tee -a "$LOG"; continue; }
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json')).get('items') or []))")
  [ "$cnt" -ge 8 ] || { echo "$(date) skip $n count=$cnt" | tee -a "$LOG"; continue; }
  ARGS+=("$spec")
  echo "$(date) candidate $n listed=$cnt test_ok=$([ -e entries/_test_${n}.ok ] && echo yes || echo no)" | tee -a "$LOG"
done

if [ ${#ARGS[@]} -eq 0 ]; then
  echo "$(date) no candidates" | tee -a "$LOG"
  exit 1
fi
bash ./county_enqueue_batch.sh "${ARGS[@]}" >> "$LOG" 2>&1
echo "$(date) enqueue_batch rc=$?" | tee -a "$LOG"

# Follow-on: list+test Coesfeld / Märkisch-Oderland / Soest if lists need refresh
NEED_TEST=()
for spec in "de_coe|Q6210|Kreis Coesfeld" "de_mol|Q6181|Landkreis Märkisch-Oderland" "de_so|Q5965|Kreis Soest"; do
  IFS='|' read -r n qid name <<< "$spec"
  cfg="entries/cfg/${n}.json"
  out="entries/${n}_amtsblatt.json"
  [ -f "$cfg" ] || continue
  if [ ! -s "$out" ] || [ "$($PY -c "import json; print(len(json.load(open('$out')).get('items') or []))")" -lt 8 ]; then
    echo "$(date) LIST $n" | tee -a "$LOG"
    $PY -u de_amtsblatt_list.py "$cfg" "$out" > "$L/${n}_list.log" 2>&1 || echo "$(date) LIST fail $n" | tee -a "$LOG"
  fi
  cnt=$($PY -c "import json; print(len(json.load(open('$out')).get('items') or []))" 2>/dev/null || echo 0)
  if [ "$cnt" -ge 8 ] && [ ! -e "entries/_test_${n}.ok" ]; then
    NEED_TEST+=("$spec")
    echo "$(date) need test $n listed=$cnt" | tee -a "$LOG"
  elif [ "$cnt" -ge 8 ] && [ -e "entries/_test_${n}.ok" ]; then
    NEED_TEST+=("$spec")
    echo "$(date) re-enqueue ready $n listed=$cnt" | tee -a "$LOG"
  fi
done
if [ ${#NEED_TEST[@]} -gt 0 ]; then
  bash ./county_enqueue_batch.sh "${NEED_TEST[@]}" >> "$LOG" 2>&1
  echo "$(date) follow-on enqueue rc=$?" | tee -a "$LOG"
fi

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
echo "$(date) queue_ext_20261106t done" | tee -a "$LOG"
