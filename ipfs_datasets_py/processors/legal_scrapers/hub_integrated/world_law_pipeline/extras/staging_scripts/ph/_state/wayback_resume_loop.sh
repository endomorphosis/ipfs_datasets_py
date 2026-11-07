#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Resume loop: reruns run_wayback.sh (pass1 from checkpoint, then pass2 on pass1 exit 0).
# Stops on exit 0 (all done), 75 (disk guard), 143 (manual SIGTERM).
LOG=${WORLD_LAW_ROOT}/staging/ph/_logs/wayback_pass.log
while true; do
  bash ${WORLD_LAW_ROOT}/pipeline/scrapers/ph/run_wayback.sh >>"$LOG" 2>&1; rc=$?
  echo "$(date -u +%FT%TZ) resume_loop: run_wayback exit $rc" >>"$LOG"
  case $rc in 0|75|143) exit $rc;; esac
  sleep 60
done
