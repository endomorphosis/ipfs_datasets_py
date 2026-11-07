#!/bin/bash
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_queue_ext_20261106s_b.log
echo "$(date) queue_ext_b start pid=$$" | tee -a "$LOG"
for n in de_cux de_am; do
  echo "$(date) LIST $n" | tee -a "$LOG"
  $PY -u de_amtsblatt_list.py entries/cfg/${n}.json entries/${n}_amtsblatt.json > "$L/${n}_list.log" 2>&1
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json')).get('items') or []))")
  echo "$(date) LIST done $n count=$cnt" | tee -a "$LOG"
done
# Wait for first enqueue helper to finish so we don't double-test
while pgrep -f 'county_queue_ext_20261106s.sh' >/dev/null || pgrep -f 'county_enqueue_batch.sh' >/dev/null; do
  # only the primary ext script / its enqueue — not this one
  if pgrep -af 'county_queue_ext_20261106s.sh|county_enqueue_batch.sh' | rg -v 'queue_ext_20261106s_b|rg -' >/dev/null; then
    echo "$(date) wait primary enqueue" | tee -a "$LOG"; sleep 60
  else break; fi
done
ARGS=()
for spec in "de_cux|Q5897|Landkreis Cuxhaven" "de_am|Q5947|Landkreis Ammerland"; do
  IFS='|' read -r n qid name <<< "$spec"
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json')).get('items') or []))")
  [ "$cnt" -ge 8 ] && ARGS+=("$spec") && echo "$(date) candidate $n $cnt" | tee -a "$LOG"
done
[ ${#ARGS[@]} -gt 0 ] && bash ./county_enqueue_batch.sh "${ARGS[@]}" >> "$LOG" 2>&1
echo "$(date) queue_ext_b done" | tee -a "$LOG"
