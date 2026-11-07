#!/usr/bin/env bash
# Launch / resume the missing-URL job (detached). Safe to re-run.
#  - discovery: missing_urls_discover.py (resumable: places already in _discovery/missing_urls_20261020.jsonl skipped)
#  - crawl:     missing_urls_crawler.py live crawl of found sites (resumable via _missing/_state/done_place_ids.txt)
#  - archive:   missing_urls_crawler.py --archive (robots-disallowed/unreachable places; resumable via archive_done.txt)
# Stop: kill watchdog_missing.sh first, then kill -TERM the pids in _missing/_state/*.pid
set -uo pipefail
OUT=/workspace/world_law/staging/web/_missing
mkdir -p "$OUT/_logs" "$OUT/_state" "$OUT/_tmp"
cd "$(dirname "$0")"
export MALLOC_ARENA_MAX=2 PYTHONUNBUFFERED=1 ARCHIVE_LANE=web
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
TS=$(date +%Y%m%d_%H%M%S)
if ! alive "$OUT/_state/discover.pid" && ! grep -qs DISCOVERY_DONE "$OUT"/_logs/discover_*.log; then
  nohup python3 missing_urls_discover.py > "$OUT/_logs/discover_$TS.log" 2>&1 &
  echo $! > "$OUT/_state/discover.pid"; echo "discover pid $!"
fi
if [ "${1:-}" != "--discover-only" ] && ! alive "$OUT/_state/crawler.pid"; then
  LOG="$OUT/_logs/crawl_$TS.log"
  nohup python3 missing_urls_crawler.py --out "$OUT" --workers "${WORKERS:-4}" --max-places "${MAX_PLACES:-60}" > "$LOG" 2>&1 &
  echo $! > "$OUT/_state/crawler.pid"; ln -sf "$LOG" "$OUT/_logs/latest.log"; echo "crawler pid $! log $LOG"
fi
LASTA=$(stat -c %Y "$(ls -t "$OUT"/_logs/archive_*.log 2>/dev/null | head -1)" 2>/dev/null || echo 0)
LASTQ=$(stat -c %Y "$OUT/_state/archive_queue.jsonl" 2>/dev/null || echo 0)
# archive pass: only when the queue grew since the last pass, or every 30 min to retry deferred hosts
if [ "${1:-}" != "--discover-only" ] && ! alive "$OUT/_state/archive.pid" && [ -s "$OUT/_state/archive_queue.jsonl" ] \
   && { [ "$LASTQ" -gt "$LASTA" ] || [ $(( $(date +%s) - LASTA )) -gt 1800 ]; }; then
  nohup python3 missing_urls_crawler.py --archive > "$OUT/_logs/archive_$TS.log" 2>&1 &
  echo $! > "$OUT/_state/archive.pid"; echo "archive pid $!"
fi
