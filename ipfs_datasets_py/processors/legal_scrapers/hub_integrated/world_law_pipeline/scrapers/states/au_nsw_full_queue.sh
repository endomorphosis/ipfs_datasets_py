#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-02 03:10 PST: AU-NSW archive deferred-retry queue (the 2026-11-01 16:58 PST pass ended 21:17 PST with
# deferred_left=1882 and nothing requeued it). RAM-gated; resumes from _state/au_nsw_archive.done.tsv + deferred.tsv.
# Lock-protected (flock) + pgrep guard: never two NSW run_full at once. Requeue after 30 min while deferred_left>0, max 12 passes.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
exec 7>${WORLD_LAW_ROOT}/staging/states/_state/au_nsw_full_queue.lock
flock -n 7 || { echo "$(date) au_nsw_full_queue already running (lock)"; exit 0; }
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for i in $(seq 1 12); do
  if pgrep -f "run_full.py --source au_nsw_archive( |$)" >/dev/null; then echo "$(date) au_nsw_archive already running"; exit 0; fi
  echo "$(date) full au_nsw_archive pass $i"
  ramgate_run 130 $L/full_au_nsw_archive_20261020_0345.out $PY -u run_full.py --source au_nsw_archive 7>&-; rc=$?
  dl=$(grep -o 'deferred_left=[0-9]*' $L/full_au_nsw_archive.log | tail -1 | cut -d= -f2)
  echo "$(date) pass $i rc=$rc deferred_left=${dl:-?}"
  [ "$rc" -eq 0 ] && [ "${dl:-1}" = "0" ] && break
  sleep 1800
done
echo "$(date) AUNSW_FULL_END"
