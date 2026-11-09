#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Phase 3: Irish county/city councils (29 remaining), live crawl then archive for robots-disallowed/blocked. Resumable.
# 2026-10-18: archive 429/5xx -> ArchiveDeferred: items requeued with not_before (state db archive_deferrals),
# places left 'deferred' get up to 6 later archive-queue passes, each started once the earliest item is due.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
. ./archive_passes.sh
$PY -u councils.py run --no-archive --places-file $S/ie_councils_places.txt
$PY -u councils.py run --archive-queue --archive-docs 8 --places-file $S/ie_councils_places.txt
archive_later_passes $S/ie_councils_places.txt 6
echo IE_COUNCILS_DONE
