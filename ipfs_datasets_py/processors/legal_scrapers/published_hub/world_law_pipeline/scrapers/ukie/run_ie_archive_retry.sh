#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Phase 3 archive retry (2026-10-18): only the Irish councils left 'deferred' after run_ie_councils.sh
# (pending archive_deferrals: throttled/timeout lookups, or docs staged from an incomplete fetch). Archive queue only,
# 1 process, shared limiter lane ukie; no live re-crawl for live-mode places (only their requeued doc URLs).
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
. ./archive_passes.sh
$PY -u councils.py run --archive-queue --archive-docs 8 --places-file $S/ie_archive_retry_places.txt
archive_later_passes $S/ie_archive_retry_places.txt 6
echo IE_ARCHIVE_RETRY_DONE
