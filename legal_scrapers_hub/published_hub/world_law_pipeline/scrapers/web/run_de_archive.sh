#!/usr/bin/env bash
# Launch / resume the German archive pass (CC first, then Wayback, via the shared ArchiveFetcher).
# Resumable: finished places are in staging/web/DE/_archive_work/done.jsonl. Stop: kill the watchdog,
# then kill -TERM the pid in _archive_work/archive.pid (in-flight places are redone on resume).
set -euo pipefail
W=/workspace/world_law/staging/web/DE/_archive_work
L=/workspace/world_law/staging/web/DE/_logs
mkdir -p "$W" "$L"
if [ -f "$W/archive.pid" ] && kill -0 "$(cat "$W/archive.pid")" 2>/dev/null; then
  echo "already running pid $(cat "$W/archive.pid")"; exit 0
fi
cd "$(dirname "$0")"
export ARCHIVE_LANE=web
export MALLOC_ARENA_MAX=2 PYTHONUNBUFFERED=1
export WORLD_LAW_CC_INDEX_RETRIES=${WORLD_LAW_CC_INDEX_RETRIES:-1}   # CC index is flaky (502/504): fail fast, then Wayback
export WORLD_LAW_CC_MAX_WAIT=${WORLD_LAW_CC_MAX_WAIT:-20}
LOG="$L/archive_$(date +%Y%m%d_%H%M%S).log"
nohup /workspace/world_law/pipeline/venv/bin/python de_archive_pass.py --lane web --workers "${WORKERS:-1}" \
  --cc-crawls "${CC_CRAWLS:-3}" --log "$LOG" "$@" >> "$LOG.stdout" 2>&1 &
echo $! > "$W/archive.pid"
ln -sf "$LOG" "$L/archive_latest.log"
echo "started pid $! log $LOG"
