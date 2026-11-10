#!/usr/bin/env bash
# Resumable country queue for the web lane: FR -> CA -> IT -> CH. One country crawls at a time (same
# memory envelope: RSS cap 500 MB incl. children, 18 workers). State: staging/web/_queue/state.json-ish
# (a country is "done" when its _progress.json says "finished": true). Safe to re-run / restart at any time.
# IT: it_bylaw_crawler.py (run_it.sh/watchdog_it.sh). CH comes next and stays a stub (queue pauses there)
# until ch_bylaw_crawler.py + run_ch.sh + watchdog_ch.sh exist.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
STAGE=/workspace/world_law/staging/web
QLOG=$STAGE/_queue/queue.log
mkdir -p "$STAGE/_queue"
echo $$ > "$STAGE/_queue/queue.pid"
ORDER=(FR CA IT CH)
lc() { echo "$1" | tr 'A-Z' 'a-z'; }
finished() { grep -q '"finished": true' "$STAGE/$1/_progress.json" 2>/dev/null; }
wd_running() { local p; p=$(cat "$STAGE/$1/_state/watchdog.pid" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
for CC in "${ORDER[@]}"; do
  c=$(lc "$CC")
  if finished "$CC"; then echo "$(date +%FT%T) $CC finished; next" >> "$QLOG"; continue; fi
  if [ ! -x "$DIR/watchdog_$c.sh" ] || [ ! -x "$DIR/run_$c.sh" ]; then
    echo "$(date +%FT%T) $CC is a stub (no run_$c.sh/watchdog_$c.sh); queue paused here" >> "$QLOG"; exit 0
  fi
  if ! wd_running "$CC"; then
    echo "$(date +%FT%T) starting $CC watchdog (crawler resumes from checkpoint)" >> "$QLOG"
    mkdir -p "$STAGE/$CC/_logs" "$STAGE/$CC/_state"
    [ "$CC" = CA ] && [ ! -f "$STAGE/CA/_state/code_map.json" ] && \
      /workspace/world_law/pipeline/venv/bin/python "$DIR/ca_bylaw_crawler.py" --build-code-map >> "$QLOG" 2>&1
    [ "$CC" = IT ] && [ ! -f "$STAGE/IT/_state/code_map.json" ] && \
      /workspace/world_law/pipeline/venv/bin/python "$DIR/it_bylaw_crawler.py" --build-code-map >> "$QLOG" 2>&1
    "$DIR/run_$c.sh" >> "$QLOG" 2>&1
    nohup "$DIR/watchdog_$c.sh" >> "$STAGE/$CC/_logs/watchdog.log" 2>&1 &
    echo $! > "$STAGE/$CC/_state/watchdog.pid"
  fi
  while ! finished "$CC"; do
    sleep 300
    if ! wd_running "$CC" && ! finished "$CC"; then
      echo "$(date +%FT%T) $CC watchdog gone but not finished; restarting it" >> "$QLOG"
      nohup "$DIR/watchdog_$c.sh" >> "$STAGE/$CC/_logs/watchdog.log" 2>&1 &
      echo $! > "$STAGE/$CC/_state/watchdog.pid"
    fi
  done
  echo "$(date +%FT%T) $CC finished" >> "$QLOG"
done
echo "$(date +%FT%T) queue complete" >> "$QLOG"
