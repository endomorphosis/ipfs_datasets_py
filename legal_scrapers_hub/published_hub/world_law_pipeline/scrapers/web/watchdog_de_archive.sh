#!/usr/bin/env bash
# Keeps the DE archive pass alive (relaunch on exit until _progress.json says finished; restart above RSS_LIMIT_MB).
W=/workspace/world_law/staging/web/DE/_archive_work
DIR="$(cd "$(dirname "$0")" && pwd)"
RSS_LIMIT_MB=${RSS_LIMIT_MB:-400}
while true; do
  sleep 60
  if grep -q '"finished": true' "$W/_progress.json" 2>/dev/null; then echo "$(date) finished; exiting"; exit 0; fi
  PID=$(cat "$W/archive.pid" 2>/dev/null)
  if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then echo "$(date) not running; relaunching"; "$DIR/run_de_archive.sh"; continue; fi
  RSS=$(ps -o rss= -p "$PID" | awk '{printf "%d", $1/1024}')
  KIDS=$(ps -eo ppid=,rss= | awk -v p="$PID" '$1==p {s+=$2} END {printf "%d", s/1024}')
  echo "$(date +%FT%T) pid=$PID rss_mb=$((RSS+KIDS))" >> "$W/_rss.log"
  if [ $((RSS+KIDS)) -gt "$RSS_LIMIT_MB" ]; then
    echo "$(date) RSS $((RSS+KIDS))MB > ${RSS_LIMIT_MB}MB; restarting"
    kill -TERM "$PID"; for i in $(seq 1 60); do sleep 3; kill -0 "$PID" 2>/dev/null || break; done; kill -9 "$PID" 2>/dev/null
    sleep 3; "$DIR/run_de_archive.sh"
  fi
done
