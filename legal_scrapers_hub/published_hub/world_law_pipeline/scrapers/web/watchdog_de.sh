#!/usr/bin/env bash
# Keeps the DE crawl alive: relaunches when it exits (process recycling / crash), restarts when it
# stalls (>30 min without a finished place) or when RSS (crawler + children) exceeds RSS_LIMIT_MB.
OUT=/workspace/world_law/staging/web/DE
DIR="$(cd "$(dirname "$0")" && pwd)"
RSS_LIMIT_MB=${RSS_LIMIT_MB:-600}
export WORKERS=${WORKERS:-12}
tree_rss_mb() {  # RSS of pid + all descendants (e.g. pdftotext), MB
  ps -eo pid=,ppid=,rss= | awk -v root="$1" '
    { pp[$1]=$2; rss[$1]=$3 }
    END { for (p in pp) { q=p; while (q!="" && q!=0 && q!=1) { if (q==root) { s+=rss[p]; break } q=pp[q] } }
          printf "%d", s/1024 }'
}
stop_crawler() {
  local pid=$1
  kill -TERM "$pid" 2>/dev/null
  for i in $(seq 1 30); do sleep 2; kill -0 "$pid" 2>/dev/null || return; done
  kill -9 "$pid" 2>/dev/null
}
while true; do
  sleep 60
  if grep -q '"finished": true' "$OUT/_progress.json" 2>/dev/null; then echo "$(date) finished; watchdog exiting"; exit 0; fi
  PID=$(cat "$OUT/_state/crawler.pid" 2>/dev/null)
  if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "$(date) crawler not running (recycle/exit); relaunching"; "$DIR/run_de.sh"; continue
  fi
  RSS=$(tree_rss_mb "$PID")
  echo "$(date +%FT%T) pid=$PID rss_mb=$RSS" >> "$OUT/_logs/rss.log"
  if [ "${RSS:-0}" -gt "$RSS_LIMIT_MB" ]; then
    echo "$(date) RSS ${RSS}MB > ${RSS_LIMIT_MB}MB; restarting from checkpoint"
    stop_crawler "$PID"; sleep 3; "$DIR/run_de.sh"; continue
  fi
  AGE=$(( $(date +%s) - $(stat -c %Y "$OUT/_state/done_place_ids.txt" 2>/dev/null || date +%s) ))
  if [ "$AGE" -gt 1800 ]; then
    echo "$(date) stalled ${AGE}s; dumping stacks and restarting"
    ~/.local/bin/py-spy dump --pid "$PID" > "$OUT/_logs/hang_$(date +%Y%m%d_%H%M%S).txt" 2>&1 || true
    stop_crawler "$PID"; sleep 3; "$DIR/run_de.sh"
  fi
done
