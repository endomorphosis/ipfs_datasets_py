#!/bin/bash
# Wait for the single county fetcher slot to be free, run 8-item tests, append to supervisor queue.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_enqueue_pending.log
echo "$(date) enqueue helper start pid=$$" >> "$LOG"
# Wait until listing of sdl finishes first (if still running)
while pgrep -f 'de_amtsblatt_list.py entries/cfg/de_sdl' >/dev/null; do
  echo "$(date) wait sdl list" >> "$LOG"; sleep 30
done
# Wait until no pdf_list_fetch for counties
while pgrep -f 'pdf_list_fetch.py entries/' >/dev/null; do
  echo "$(date) wait fetcher idle" >> "$LOG"; sleep 60
done
run_test() {
  local n=$1 src=entries/${n}_amtsblatt.json tst=entries/_test_${n}.json
  [ -s "$src" ] || { echo "$(date) no src $n" >> "$LOG"; return 1; }
  $PY - <<PY
import json
from pathlib import Path
d=json.load(open("$src")); items=d.get("items") or []
assert len(items)>=8, f"only {len(items)}"
d2=dict(d); d2["items"]=items[:8]
Path("$tst").write_text(json.dumps(d2, ensure_ascii=False, indent=1))
PY
  # Ensure still idle
  pgrep -f 'pdf_list_fetch.py entries/' >/dev/null && { echo "$(date) fetcher busy again, abort $n" >> "$LOG"; return 1; }
  $PY -u pdf_list_fetch.py "$tst" --delay 2 > "$L/${n}_test.log" 2>&1
  sum=$(grep SUMMARY "$L/${n}_test.log" | tail -1)
  echo "$(date) TEST $n $sum" >> "$LOG"
  $PY - <<PY
import re,sys,ast
s='''$sum'''
m=re.search(r'\{[^}]+\}', s); d=ast.literal_eval(m.group(0)) if m else {}
sys.exit(0 if d.get('err',1)==0 and d.get('ok',0)+d.get('scanned',0)>=6 else 1)
PY
  [ $? -eq 0 ] || { echo "$(date) FAIL $n" >> "$LOG"; return 1; }
  touch "entries/_test_${n}.ok"
  echo "$(date) OK $n" >> "$LOG"
}
append_queue() {
  local n=$1 qid=$2 name=$3 count=$4
  ID="$n" QID="$qid" NAME="$name" COUNT="$count" $PY - <<'PY'
import json,os,time
from pathlib import Path
q=Path("county_supervisor_queue.jsonl")
n,qid,name,count=os.environ["ID"],os.environ["QID"],os.environ["NAME"],os.environ["COUNT"]
# skip if already present pending/running/done
rows=[]
if q.exists():
  for ln in q.read_text().splitlines():
    if not ln.strip(): continue
    d=json.loads(ln); rows.append(d)
    if d.get("id")==n or d.get("target")==n:
      print("already in queue", n); raise SystemExit
rows.append({"id":n,"kind":"target","target":n,"qid":qid,"place_name":name,"listed":int(count),
             "status":"pending","queued_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())})
tmp=str(q)+".tmp"; open(tmp,"w").write("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n")
import os as _os; _os.replace(tmp,q); print("appended", n)
PY
}
# Prefer sdl if listed >=8, then ky
for spec in "de_sdl|Q6057|Landkreis Stendal" "de_ky|Q7862|Kyffhäuserkreis"; do
  IFS='|' read -r n qid name <<< "$spec"
  [ -s entries/${n}_amtsblatt.json ] || continue
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json'))['items']))")
  [ "$cnt" -ge 8 ] || { echo "$(date) skip $n count=$cnt" >> "$LOG"; continue; }
  if [ -e entries/_test_${n}.ok ]; then
    append_queue "$n" "$qid" "$name" "$cnt" >> "$LOG"
    continue
  fi
  while pgrep -f 'pdf_list_fetch.py entries/' >/dev/null; do echo "$(date) wait idle for $n" >> "$LOG"; sleep 60; done
  run_test "$n" && append_queue "$n" "$qid" "$name" "$cnt" >> "$LOG"
done
echo "$(date) enqueue helper done" >> "$LOG"
