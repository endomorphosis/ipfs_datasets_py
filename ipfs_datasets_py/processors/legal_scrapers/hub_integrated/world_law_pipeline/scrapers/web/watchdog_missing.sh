#!/usr/bin/env bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Keeps the missing-URL job alive (same pattern as watchdog_it.sh): relaunches discovery/crawler/archive when they exit
# (crawler recycles every MAX_PLACES places; new discovery results are picked up on relaunch), restarts on RSS > 500 MB
# (process tree), restarts a crawler stalled > 30 min, pauses below 10 GB free, resumes at >= 12 GB.
OUT=${WORLD_LAW_ROOT}/staging/web/_missing
DIR="$(cd "$(dirname "$0")" && pwd)"
RSS_LIMIT_MB=${RSS_LIMIT_MB:-500}
MIN_FREE_GB=${MIN_FREE_GB:-10} RELAUNCH_FREE_GB=${RELAUNCH_FREE_GB:-12}; PAUSED=0
export WORKERS=${WORKERS:-4}
tree_rss_mb() { ps -eo pid=,ppid=,rss= | awk -v root="$1" '{ pp[$1]=$2; rss[$1]=$3 } END { for (p in pp) { q=p; while (q!="" && q!=0 && q!=1) { if (q==root) { s+=rss[p]; break } q=pp[q] } } printf "%d", s/1024 }'; }
stop() { kill -TERM "$1" 2>/dev/null; for i in $(seq 1 30); do sleep 2; kill -0 "$1" 2>/dev/null || return; done; kill -9 "$1" 2>/dev/null; }
echo $$ > "$OUT/_state/watchdog.pid"
while true; do
  sleep 60
  FREE_GB=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
  if [ "${FREE_GB:-0}" -lt "$MIN_FREE_GB" ] || { [ "$PAUSED" = 1 ] && [ "${FREE_GB:-0}" -lt "$RELAUNCH_FREE_GB" ]; }; then
    PAUSED=1; echo "$(date) free disk ${FREE_GB}G (stop <${MIN_FREE_GB}G, resume >=${RELAUNCH_FREE_GB}G): stopping job until space returns"
    for f in crawler archive; do P=$(cat "$OUT/_state/$f.pid" 2>/dev/null); [ -n "$P" ] && stop "$P"; done; continue
  fi
  PAUSED=0
  if grep -q '"finished": true' "$OUT/_progress.json" 2>/dev/null && grep -qs ARCHIVE_PASS_DONE "$OUT"/_logs/archive_*.log \
     && ! [ -n "$(cat $OUT/_state/archive.pid 2>/dev/null)" -a -d /proc/$(cat $OUT/_state/archive.pid 2>/dev/null) ]; then
    LASTQ=$(stat -c %Y "$OUT/_state/archive_queue.jsonl" 2>/dev/null || echo 0); LASTA=$(stat -c %Y $(ls -t "$OUT"/_logs/archive_*.log | head -1))
    if [ "$LASTA" -gt "$LASTQ" ]; then echo "$(date) all finished; watchdog exiting"; exit 0; fi
  fi
  TOTAL=0
  for f in crawler archive discover; do
    P=$(cat "$OUT/_state/$f.pid" 2>/dev/null); [ -n "$P" ] && kill -0 "$P" 2>/dev/null || continue
    R=$(tree_rss_mb "$P"); TOTAL=$((TOTAL+R))
    echo "$(date +%FT%T) $f pid=$P rss_mb=$R" >> "$OUT/_logs/rss.log"
    if [ "$R" -gt "$RSS_LIMIT_MB" ]; then echo "$(date) $f RSS ${R}MB > ${RSS_LIMIT_MB}MB; restarting"; stop "$P"; fi
  done
  if [ "$TOTAL" -gt "$RSS_LIMIT_MB" ]; then
    P=$(cat "$OUT/_state/crawler.pid" 2>/dev/null); echo "$(date) job total RSS ${TOTAL}MB > ${RSS_LIMIT_MB}MB; recycling crawler"; [ -n "$P" ] && stop "$P"
  fi
  P=$(cat "$OUT/_state/crawler.pid" 2>/dev/null)
  if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$OUT/_state/done_place_ids.txt" 2>/dev/null || stat -c %Y "$OUT/_state/crawler.pid") ))
    if [ "$AGE" -gt 1800 ]; then echo "$(date) crawler stalled ${AGE}s; restarting"; touch "$OUT/_state/crawler.pid"; stop "$P"; fi
  fi
  "$DIR/run_missing.sh" >> "$OUT/_logs/watchdog_launch.log" 2>&1
done
