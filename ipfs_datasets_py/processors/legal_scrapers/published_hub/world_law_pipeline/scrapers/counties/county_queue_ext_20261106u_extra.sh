#!/bin/bash
# Extra NEW targets after first tranche: Paderborn + Cuxhaven (rewritten media URLs)
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_queue_ext_20261106u_extra.log
echo "$(date) extra start pid=$$" | tee -a "$LOG"

# Wait for cux list3 and any pb list to finish
while pgrep -f 'de_amtsblatt_list.py entries/cfg/de_cux.json' >/dev/null \
   || pgrep -f 'de_amtsblatt_list.py entries/cfg/de_pb.json' >/dev/null; do
  echo "$(date) wait lists" >> "$LOG"; sleep 20
done

# Post-filter Cuxhaven: media/custom only, prefer Amtsblatt titles; keep media/custom even if title weak if path has Amtsblatt fn pattern
$PY - <<'PY' >> "$LOG"
import json,re
from pathlib import Path
p=Path('entries/de_cux_amtsblatt.json')
d=json.load(open(p))
items=d.get('items') or []
media=[it for it in items if '/media/custom/' in it['url']]
# Prefer titles mentioning Amtsblatt; else keep all media/custom from list (pdf_re already filtered)
ab=[it for it in media if re.search(r'amtsblatt', (it.get('title') or '') + ' ' + it['url'], re.I)]
keep=ab if len(ab)>=8 else media
d['items']=keep
p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
print('cux media', len(media), 'amtsblatt-titled', len(ab), 'kept', len(keep))
if keep: print('sample', keep[0]['url'], keep[0].get('title'))
PY

SPECS=()
for spec in "de_pb|Q6224|Kreis Paderborn" "de_cux|Q5897|Landkreis Cuxhaven"; do
  IFS='|' read -r n qid name <<< "$spec"
  if [ -s "/workspace/world_law/staging/counties/_state/done_wd_${qid}.jsonl" ]; then
    echo "$(date) REFUSE done $n $qid" | tee -a "$LOG"; continue
  fi
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json')).get('items') or []))" 2>/dev/null || echo 0)
  echo "$(date) candidate $n listed=$cnt" | tee -a "$LOG"
  if [ "$cnt" -ge 8 ]; then
    rm -f "entries/_test_${n}.ok"
    SPECS+=("$spec")
  fi
done

if [ ${#SPECS[@]} -eq 0 ]; then
  echo "$(date) no extra specs" | tee -a "$LOG"; exit 1
fi

# Wait until first enqueue_batch from u is not holding the slot forever — can run after it finishes OR interleave via same wait_idle in enqueue_batch
# If u's enqueue_batch is still waiting/running, append our specs by running another enqueue_batch (it waits idle between tests)
bash ./county_enqueue_batch.sh "${SPECS[@]}" >> "$LOG" 2>&1
echo "$(date) extra enqueue rc=$?" | tee -a "$LOG"
$PY - <<'PY' | tee -a "$LOG"
import json
from pathlib import Path
rows=[json.loads(l) for l in Path('county_supervisor_queue.jsonl').read_text().splitlines() if l.strip()]
print('pending', [(r['id'], r.get('listed'), r.get('qid')) for r in rows if r.get('status')=='pending'])
print('running', [(r['id'], r.get('listed')) for r in rows if r.get('status')=='running'])
PY
echo "$(date) extra done" | tee -a "$LOG"
