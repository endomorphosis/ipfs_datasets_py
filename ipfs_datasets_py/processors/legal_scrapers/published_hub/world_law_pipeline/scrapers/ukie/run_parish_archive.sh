#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Archive-queue pass over phase-2 (town/parish/community) councils blocked live by robots.txt disallow or TLS errors
# (robots.txt unreachable over TLS => disallow-all). Archived copies only (Wayback/CC via the shared limiter, lane ukie,
# source_policy=archived_robots_disallowed), phase-2 bye-law gate applies. 1 process. Resumable; deferred items requeued.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
. ./archive_passes.sh
$PY -u councils.py select-parish-archive --out $S/parish_archive_places.txt
$PY -u councils.py run --archive-queue --archive-docs 8 --places-file $S/parish_archive_places.txt
archive_later_passes $S/parish_archive_places.txt 6
echo PARISH_ARCHIVE_DONE
