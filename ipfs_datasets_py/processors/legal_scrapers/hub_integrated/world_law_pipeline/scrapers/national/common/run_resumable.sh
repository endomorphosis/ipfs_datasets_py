#!/bin/bash
# run_resumable.sh <logfile> <script> [args...] : rerun a resumable collector until it logs DONE (max 20 tries)
LOG=$1; shift
for i in $(seq 1 20); do
  echo "=== attempt $i $(date -u +%FT%TZ)" >> "$LOG"
  python3 "$@" >> "$LOG" 2>&1
  tail -5 "$LOG" | grep -q "DONE staged=" && exit 0
  sleep 300
done
