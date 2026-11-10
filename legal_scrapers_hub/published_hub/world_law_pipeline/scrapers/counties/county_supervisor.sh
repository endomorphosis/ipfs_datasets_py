#!/bin/bash
# 2026-11-05 ~00:10 PST durable county-lane supervisor (ONE fetcher slot).
# Owns county_supervisor_queue.jsonl (DONE-persistent). Never exits merely because the
# queue is empty: sleeps 300s and rechecks. Applies disk 10240 MiB / RAM 2048 MiB floors
# and staging/pdf 4 GB hold before each launch and during empty sleeps. No cron.
# kind=chain -> run a county_chain_*.sh unit; kind=target -> pdf_list_fetch.py on entries.
set -u
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh
export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048
source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
QUEUE=/workspace/world_law/pipeline/scrapers/counties/county_supervisor_queue.jsonl
LOCK=$L/county_supervisor.lock
STATUS=$L/county_supervisor.status
HEART=$L/county_supervisor.heartbeat
CUR=$L/county_supervisor.current
LOG=$L/county_supervisor.log
mkdir -p "$L"

if [ -f "$LOCK" ]; then
  old=$(cat "$LOCK" 2>/dev/null || true)
  if [ -n "${old:-}" ] && kill -0 "$old" 2>/dev/null; then
    echo "$(date) supervisor already running pid=$old" | tee -a "$LOG"
    exit 0
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"; echo idle > "$CUR"' EXIT
echo "$(date) supervisor start pid=$$" | tee -a "$LOG"
echo "running pid=$$ started=$(date -Iseconds)" > "$STATUS"

pdfhold() {
  while [ "$(du -sm /workspace/world_law/staging/pdf 2>/dev/null | cut -f1)" -gt 4096 ]; do
    echo "$(date) [sup] staging/pdf > 4 GB -> wait 15 min" | tee -a "$LOG"
    date -Iseconds > "$HEART"; echo "pdfhold" > "$CUR"; sleep 900
  done
}
floors_wait() {
  while ! floors_ok; do
    echo "$(date) [sup] floors low disk=$(free_mib)MiB ram=$(avail_mib)MiB -> sleep 300" | tee -a "$LOG"
    date -Iseconds > "$HEART"; echo "floors_wait" > "$CUR"; sleep 300
  done
}

claim_next() {
  $PY - <<'PY'
import json, os, time
from pathlib import Path
q = Path("/workspace/world_law/pipeline/scrapers/counties/county_supervisor_queue.jsonl")
if not q.exists():
    print("")
    raise SystemExit
lines = q.read_text().splitlines()
out = []
claimed = None
for ln in lines:
    if not ln.strip():
        continue
    try:
        d = json.loads(ln)
    except Exception:
        out.append(ln)
        continue
    if claimed is None and d.get("status") == "pending":
        d["status"] = "running"
        d["claimed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        claimed = d
        out.append(json.dumps(d, ensure_ascii=False))
    else:
        out.append(json.dumps(d, ensure_ascii=False))
tmp = str(q) + ".tmp"
open(tmp, "w").write("\n".join(out) + ("\n" if out else ""))
os.replace(tmp, q)
print(json.dumps(claimed) if claimed else "")
PY
}

mark_status() {
  local id=$1 st=$2 extra=${3:-}
  ID="$id" ST="$st" EXTRA="$extra" $PY - <<'PY'
import json, os, time
from pathlib import Path
qid = os.environ["ID"]; st = os.environ["ST"]; extra = os.environ.get("EXTRA", "")
q = Path("/workspace/world_law/pipeline/scrapers/counties/county_supervisor_queue.jsonl")
lines = []
for ln in q.read_text().splitlines() if q.exists() else []:
    if not ln.strip():
        continue
    d = json.loads(ln)
    if d.get("id") == qid:
        d["status"] = st
        d["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if extra:
            d["result"] = extra[:500]
    lines.append(json.dumps(d, ensure_ascii=False))
tmp = str(q) + ".tmp"
open(tmp, "w").write("\n".join(lines) + ("\n" if lines else ""))
os.replace(tmp, q)
PY
}

run_chain() {
  local script=$1 id=$2
  echo "$(date) [sup] run chain $id -> $script" | tee -a "$LOG"
  echo "$id chain $script" > "$CUR"
  if [ ! -f "$script" ]; then
    echo "$(date) [sup] missing $script" | tee -a "$LOG"
    mark_status "$id" failed "missing script"
    return 1
  fi
  chmod +x "$script" 2>/dev/null || true
  bash "$script" >> "$L/county_supervisor_chain_${id}.log" 2>&1
  local rc=$?
  echo "$(date) [sup] chain $id rc=$rc" | tee -a "$LOG"
  return $rc
}

run_target() {
  local n=$1 id=$2
  local f=entries/${n}_amtsblatt.json
  echo "$(date) [sup] run target $id ($n)" | tee -a "$LOG"
  echo "$id target $n" > "$CUR"
  if [ ! -s "$f" ] || [ ! -e "entries/_test_$n.ok" ]; then
    echo "$(date) [sup] skip $n (no entries/test-ok)" | tee -a "$LOG"
    mark_status "$id" failed "no entries/test-ok"
    return 1
  fi
  local tries=0 rc=0
  while [ $tries -lt 3 ]; do
    pdfhold; floors_wait
    guard_retry "$n" $PY -u pdf_list_fetch.py "$f" --delay 2 >> "$L/${n}.log" 2>&1
    rc=$?; tries=$((tries+1))
    echo "$(date) [sup] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log 2>/dev/null | tail -1 | cut -c1-160)" | tee -a "$LOG"
    [ $rc -eq 99 ] && { mark_status "$id" pending "guard floors - will retry"; return 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 "$L/${n}.log" | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY "$L/${n}.log" | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break
  done
  return $rc
}

while :; do
  date -Iseconds > "$HEART"
  floors_wait; pdfhold
  claim=$(claim_next)
  if [ -z "${claim}" ]; then
    next=$($PY - <<'PY'
import json
from pathlib import Path
q = Path("/workspace/world_law/pipeline/scrapers/counties/county_supervisor_queue.jsonl")
pending = []
if q.exists():
    for ln in q.read_text().splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("status") == "pending":
            pending.append(d.get("id"))
print(",".join(pending[:8]) if pending else "(none)")
print(len(pending))
PY
)
    echo "$(date) [sup] queue empty/no pending; peek=$(echo "$next" | tr '\n' ' ') ; sleep 300" | tee -a "$LOG"
    echo "idle waiting_for_queue" > "$CUR"
    echo "idle pid=$$ next_pending=$(echo "$next" | head -1) at=$(date -Iseconds)" > "$STATUS"
    sleep 300
    continue
  fi
  id=$($PY -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$claim")
  kind=$($PY -c "import json,sys; print(json.loads(sys.argv[1]).get('kind','target'))" "$claim")
  echo "$(date) [sup] claimed id=$id kind=$kind" | tee -a "$LOG"
  echo "running pid=$$ current=$id kind=$kind at=$(date -Iseconds)" > "$STATUS"
  rc=0
  if [ "$kind" = "chain" ]; then
    script=$($PY -c "import json,sys; print(json.loads(sys.argv[1])['script'])" "$claim")
    run_chain "$script" "$id"; rc=$?
  else
    n=$($PY -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('target') or d['id'])" "$claim")
    run_target "$n" "$id"; rc=$?
  fi
  if [ $rc -eq 0 ]; then
    mark_status "$id" done "rc=0"
  elif [ $rc -eq 99 ]; then
    echo "$(date) [sup] guard defer $id (re-queued pending)" | tee -a "$LOG"
  else
    mark_status "$id" failed "rc=$rc"
  fi
  date -Iseconds > "$HEART"
done
