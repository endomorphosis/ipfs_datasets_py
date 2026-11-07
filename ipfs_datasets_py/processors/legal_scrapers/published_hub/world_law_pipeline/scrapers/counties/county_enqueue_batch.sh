#!/bin/bash
# 2026-11-06 queue-extension: wait for idle fetcher, 8-item test each, append pending.
# Usage: county_enqueue_batch.sh 'de_xx|Qid|Place Name' ...
# Does NOT start full fetches. Supervisor owns the only fetcher slot.
set -u
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
LOG=$L/county_enqueue_batch.log
mkdir -p "$L"
echo "$(date) enqueue_batch start pid=$$ args: $*" >> "$LOG"

wait_idle() {
  local reason=$1
  # Also wait while supervisor still owns a claimed target/chain (guard may sleep
  # with no pdf_list_fetch process — do not steal the single fetcher slot).
  while pgrep -f 'pdf_list_fetch.py entries/' >/dev/null \
     || grep -Eq 'target|chain' /workspace/world_law/staging/counties/_logs/county_supervisor.current 2>/dev/null; do
    echo "$(date) wait idle ($reason) cur=$(cat /workspace/world_law/staging/counties/_logs/county_supervisor.current 2>/dev/null)" >> "$LOG"; sleep 30
  done
}

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
  wait_idle "before test $n"
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
rows=[]
done=Path("/workspace/world_law/staging/counties/_state/done_wd_"+qid+".jsonl")
done_n=sum(1 for _ in open(done)) if done.exists() and done.stat().st_size else 0
# Ignore tiny ledgers left by the 8-item preflight test; refuse near-complete prior crawls.
if done_n >= max(20, int(int(count) * 0.5)):
  print("skip already collected", n, qid, f"done={done_n} listed={count}"); raise SystemExit
if q.exists():
  for ln in q.read_text().splitlines():
    if not ln.strip(): continue
    d=json.loads(ln); rows.append(d)
    if d.get("id")==n or d.get("target")==n:
      print("already in queue", n); raise SystemExit
rows.append({"id":n,"kind":"target","target":n,"qid":qid,"place_name":name,"listed":int(count),
             "status":"pending","queued_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())})
tmp=str(q)+".tmp"
open(tmp,"w").write("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n")
os.replace(tmp,q); print("appended", n, "listed", count)
PY
}

for spec in "$@"; do
  IFS='|' read -r n qid name <<< "$spec"
  [ -s entries/${n}_amtsblatt.json ] || { echo "$(date) skip missing list $n" >> "$LOG"; continue; }
  cnt=$($PY -c "import json; print(len(json.load(open('entries/${n}_amtsblatt.json'))['items']))")
  [ "$cnt" -ge 8 ] || { echo "$(date) skip $n count=$cnt" >> "$LOG"; continue; }
  if [ -e entries/_test_${n}.ok ]; then
    append_queue "$n" "$qid" "$name" "$cnt" >> "$LOG"
    continue
  fi
  wait_idle "before starting $n"
  run_test "$n" && append_queue "$n" "$qid" "$name" "$cnt" >> "$LOG"
done
echo "$(date) enqueue_batch done" >> "$LOG"
