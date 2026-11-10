#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Phase 2 test batch (30 town/parish/community councils), live only.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
$PY -u councils.py run --no-archive --places-file $S/phase2_test_places.txt
echo PHASE2_TEST_DONE
