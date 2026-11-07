#!/usr/bin/env bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Keeps the robots requeue alive: relaunches on exit (recycle / lane done), restarts on RSS > RSS_LIMIT_MB
# (crawler + children) or stall (>40 min without a finished place), stops launching below MIN_FREE_GB, writes
# staging/web/_requeue/_progress.json every minute.
RQ=${WORLD_LAW_ROOT}/staging/web/_requeue
DIR="$(cd "$(dirname "$0")" && pwd)"
RSS_LIMIT_MB=${RSS_LIMIT_MB:-450}
export WORKERS=${WORKERS:-2} MIN_FREE_GB=${MIN_FREE_GB:-10}
RELAUNCH_FREE_GB=${RELAUNCH_FREE_GB:-12}   # relaunch threshold (hysteresis above the 10 GB stop floor)
LOG="$RQ/_logs/watchdog.log"
tree_rss_mb() { ps -eo pid=,ppid=,rss= | awk -v root="$1" '{ pp[$1]=$2; rss[$1]=$3 }
  END { for (p in pp) { q=p; while (q!="" && q!=0 && q!=1) { if (q==root) { s+=rss[p]; break } q=pp[q] } } printf "%d", s/1024 }'; }
stop_crawler() { kill -TERM "$1" 2>/dev/null; for i in $(seq 1 45); do sleep 2; kill -0 "$1" 2>/dev/null || return; done; kill -9 "$1" 2>/dev/null; }
progress() {
  ${WORLD_LAW_ROOT}/pipeline/venv/bin/python - "$1" "$2" <<'PY'
import json, sys, time, glob, os
RQ = "${WORLD_LAW_ROOT}/staging/web/_requeue"
lanes = {}
for l in ("IT", "DE", "FR", "CA", "_missing"):
    p = f"{RQ}/{l}/_progress.json"; d = {}
    try: d = json.load(open(p))
    except Exception: pass
    n = sum(1 for _ in open(f"{RQ}/lists/{l}.jsonl"))
    done = len(set(open(f"{RQ}/{l}/_state/done_place_ids.txt").read().split())) if os.path.exists(f"{RQ}/{l}/_state/done_place_ids.txt") else 0
    lanes[l] = {"queued": n, "done": done, "lane_done": os.path.exists(f"{RQ}/{l}/DONE"),
                "docs": d.get("documents_total"), "with_docs": d.get("with_docs"), "status_counts": d.get("status_counts")}
out = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pid": sys.argv[1], "rss_mb": int(sys.argv[2] or 0),
       "current_lane": open(f"{RQ}/current_lane").read().strip() if os.path.exists(f"{RQ}/current_lane") else None,
       "disk_stop": os.path.exists(f"{RQ}/DISK_STOP"), "lanes": lanes}
tmp = f"{RQ}/_progress.json.tmp"; open(tmp, "w").write(json.dumps(out, indent=1)); os.replace(tmp, f"{RQ}/_progress.json")
PY
}
echo $$ > "$RQ/watchdog.pid"
while true; do
  sleep 60
  [ -f "$RQ/ALL_DONE" ] && { echo "$(date) all lanes done; watchdog exiting" >> "$LOG"; progress "" 0; exit 0; }
  PID=$(cat "$RQ/crawler.pid" 2>/dev/null)
  FREE=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
  if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    if [ "$FREE" -lt "$RELAUNCH_FREE_GB" ]; then echo "$(date) disk ${FREE}G < ${RELAUNCH_FREE_GB}G: not relaunching" >> "$LOG"; touch "$RQ/DISK_STOP"; progress "" 0; continue; fi
    rm -f "$RQ/DISK_STOP"
    echo "$(date) crawler not running; relaunching" >> "$LOG"; "$DIR/run_robots_requeue.sh" >> "$LOG" 2>&1; continue
  fi
  RSS=$(tree_rss_mb "$PID")
  echo "$(date +%FT%T) pid=$PID rss_mb=$RSS free_gb=$FREE lane=$(cat $RQ/current_lane)" >> "$RQ/_logs/rss.log"
  progress "$PID" "$RSS"
  if [ "${RSS:-0}" -gt "$RSS_LIMIT_MB" ]; then
    echo "$(date) RSS ${RSS}MB > ${RSS_LIMIT_MB}MB; restarting from checkpoint" >> "$LOG"; stop_crawler "$PID"; continue; fi
  L=$(cat "$RQ/current_lane"); D="$RQ/$L/_state/done_place_ids.txt"
  REF="$RQ/crawler.pid"; [ -f "$D" ] && [ "$D" -nt "$REF" ] && REF=$D   # newer of last finished place / launch
  AGE=$(( $(date +%s) - $(stat -c %Y "$REF") ))
  if [ "$AGE" -gt 2400 ]; then echo "$(date) stalled ${AGE}s; restarting" >> "$LOG"; stop_crawler "$PID"; fi
done
