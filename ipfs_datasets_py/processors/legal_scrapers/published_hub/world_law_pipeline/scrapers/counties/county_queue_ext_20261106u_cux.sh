#!/bin/bash
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_queue_ext_20261106u_cux.log
echo "$(date) cux follow-on start pid=$$" | tee -a "$LOG"
# Wait for main u helper to finish listing phase (or whole script)
while pgrep -f 'county_queue_ext_20261106u.sh' >/dev/null; do
  echo "$(date) wait main u helper" >> "$LOG"; sleep 30
done
qid=Q5897; n=de_cux
if [ -s /workspace/world_law/staging/counties/_state/done_wd_${qid}.jsonl ]; then
  echo "$(date) REFUSE done $n" | tee -a "$LOG"; exit 0
fi
echo "$(date) LIST $n" | tee -a "$LOG"
$PY -u de_amtsblatt_list.py entries/cfg/${n}.json entries/${n}_amtsblatt.json > "$L/${n}_list.log" 2>&1
# Keep only Amtsblatt-titled items (drop navigation PDFs)
$PY - <<'PY'
import json
from pathlib import Path
p=Path('entries/de_cux_amtsblatt.json')
d=json.load(open(p))
items=[it for it in d.get('items') or [] if 'amtsblatt' in (it.get('title') or '').lower() or 'amtsblatt' in (it.get('url') or '').lower()]
# Prefer rewritten media/custom URLs
items=[it for it in items if '/media/custom/' in it['url'] or 'download.php' in it['url']]
d['items']=items
p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
print('filtered', len(items))
print('sample', items[0]['url'] if items else None)
PY
cnt=$($PY -c "import json; print(len(json.load(open('entries/de_cux_amtsblatt.json'))['items']))")
echo "$(date) LISTED de_cux count=$cnt" | tee -a "$LOG"
if [ "$cnt" -lt 8 ]; then echo "too few"; exit 1; fi
rm -f entries/_test_de_cux.ok
bash ./county_enqueue_batch.sh "de_cux|Q5897|Landkreis Cuxhaven" >> "$LOG" 2>&1
echo "$(date) cux enqueue rc=$?" | tee -a "$LOG"
