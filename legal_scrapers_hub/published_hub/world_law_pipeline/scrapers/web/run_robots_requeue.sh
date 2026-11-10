#!/usr/bin/env bash
# Robots requeue (IGNORE_ROBOTS=1) - detached, resumable. Runs lanes in order IT DE FR CA _missing; a lane is
# done when staging/web/_requeue/<lane>/DONE exists. Process recycled every MAX_PLACES places (watchdog relaunches).
# Refuses to launch below MIN_FREE_GB free disk. Stop: kill watchdog (watchdog.pid) first, then kill -TERM crawler.pid.
set -uo pipefail
RQ=/workspace/world_law/staging/web/_requeue
MIN_FREE_GB=${MIN_FREE_GB:-10}
mkdir -p "$RQ/_logs"
if [ -f "$RQ/crawler.pid" ] && kill -0 "$(cat "$RQ/crawler.pid")" 2>/dev/null; then
  echo "already running pid $(cat "$RQ/crawler.pid")"; exit 0; fi
FREE=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
if [ "$FREE" -lt "$MIN_FREE_GB" ]; then echo "$(date) disk free ${FREE}G < ${MIN_FREE_GB}G; not launching" | tee -a "$RQ/_logs/watchdog.log"; touch "$RQ/DISK_STOP"; exit 2; fi
LANE=""
for l in IT DE FR CA _missing; do [ -f "$RQ/$l/DONE" ] || { LANE=$l; break; }; done
if [ -z "$LANE" ]; then echo "all lanes done"; touch "$RQ/ALL_DONE"; exit 0; fi
LOG="$RQ/_logs/${LANE}_$(date +%Y%m%d_%H%M%S).log"
cd "$(dirname "$0")"
export MALLOC_ARENA_MAX=2 PYTHONUNBUFFERED=1 IGNORE_ROBOTS=1
nohup /workspace/world_law/pipeline/venv/bin/python robots_requeue.py --lane "$LANE" --workers "${WORKERS:-2}" \
  --max-places "${MAX_PLACES:-150}" > "$LOG" 2>&1 < /dev/null &
echo $! > "$RQ/crawler.pid"; echo "$LANE" > "$RQ/current_lane"
ln -sf "$LOG" "$RQ/_logs/latest.log"
echo "started lane $LANE pid $! log $LOG"
