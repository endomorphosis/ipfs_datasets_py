#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Phase 3b: Irish Statute Book local SIs, all years (newest first). Resumable per year / per SI.
cd /workspace/world_law/pipeline/scrapers/ukie
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
$PY -u isb_local.py --years 1922-2026
echo ISB_DONE_ALL
