#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25: serial RAM-gated full runs of US gap sources after their test was checked by eye and promoted.
# Add a key to us_gap_full_list.txt to queue it; finished keys go to us_gap_full_done.txt. Polls the list every 5 min.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
touch us_gap_full_list.txt us_gap_full_done.txt
while true; do
  k=$(grep -vxFf us_gap_full_done.txt us_gap_full_list.txt | head -1)
  if [ -z "$k" ]; then sleep 300; continue; fi
  if pgrep -f "source $k( |$)" >/dev/null; then sleep 300; continue; fi
  echo "$(date) full $k"; ramgate_run 130 $L/full_$k.out $PY -u run_full.py --source $k; rc=$?; echo "$(date) full $k rc=$rc"
  echo "$k" >> us_gap_full_done.txt
done
