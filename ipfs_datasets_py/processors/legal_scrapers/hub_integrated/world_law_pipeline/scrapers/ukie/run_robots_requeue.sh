#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01: re-run places previously skipped by robots.txt (robots ignored per Benjamin; rate limits unchanged).
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/ukie
S=${WORLD_LAW_ROOT}/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie UKIE_IGNORE_ROBOTS=1
LOCK=$S/robots_requeue.lock
exec 9>$LOCK; flock -n 9 || { echo "already running"; exit 1; }
$PY -u councils.py run --places-file $S/robots_requeue_rest_20261101.txt
echo ROBOTS_REQUEUE_DONE
