#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# (d) GB principal councils, live worker N (1|2): zero-doc councils, then --refresh for councils with EU docs,
# then the remaining principal councils (counties, Scottish council areas, Welsh principal areas). Resumable.
W=$1
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
$PY -u councils.py run --no-archive --places-file $S/scale_A_zero_w$W.txt
$PY -u councils.py run --no-archive --refresh --places-file $S/scale_B_w$W.txt
$PY -u councils.py run --no-archive --places-file $S/scale_D_w$W.txt
touch $S/live_done_w$W
echo LIVE_DONE_W$W
