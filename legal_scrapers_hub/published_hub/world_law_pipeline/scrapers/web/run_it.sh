#!/usr/bin/env bash
# Launch / resume the Italian comuni regolamenti crawl (detached). Safe to re-run: finished place_ids in
# _state/done_place_ids.txt are skipped. Memory-bounded defaults: 12 workers, process recycled after
# MAX_PLACES places (the watchdog relaunches it). Stop: kill watchdog first, then kill -TERM crawler.
set -euo pipefail
OUT=/workspace/world_law/staging/web/IT
mkdir -p "$OUT/_logs" "$OUT/_state"
if [ -f "$OUT/_state/crawler.pid" ] && kill -0 "$(cat "$OUT/_state/crawler.pid")" 2>/dev/null; then
  echo "already running pid $(cat "$OUT/_state/crawler.pid")"; exit 0
fi
LOG="$OUT/_logs/crawl_$(date +%Y%m%d_%H%M%S).log"
cd "$(dirname "$0")"
export MALLOC_ARENA_MAX=2        # fewer glibc arenas => far less fragmentation with many threads
export PYTHONUNBUFFERED=1
nohup python3 it_bylaw_crawler.py --out "$OUT" --workers "${WORKERS:-18}" \
  --max-places "${MAX_PLACES:-300}" "$@" > "$LOG" 2>&1 &
echo $! > "$OUT/_state/crawler.pid"
ln -sf "$LOG" "$OUT/_logs/latest.log"
echo "started pid $! log $LOG"
