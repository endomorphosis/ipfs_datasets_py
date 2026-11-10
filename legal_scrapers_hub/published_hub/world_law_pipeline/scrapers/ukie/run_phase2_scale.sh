#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Phase 2 scale (town/parish/community councils with a discovered site), live only, worker N (1|2).
# Council sites first, community (village) sites after; PHASE2_PAGES page budget; phase-2 bye-law gate. Resumable.
W=$1
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
$PY -u councils.py run --no-archive --places-file $S/phase2_scale_w$W.txt
echo PHASE2_SCALE_DONE_W$W
