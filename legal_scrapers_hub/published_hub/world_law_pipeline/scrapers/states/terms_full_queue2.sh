#!/bin/bash
# 2026-10-25 12:xx PDT: replaces terms_full_queue.sh (pid 2807101), which waited for the Wayback-bound test queues
# terms_queue3/5 (PEI/AZ CDX + tests, NS regs) although these fulls are live sources with promoted tests.
# Serial fulls of terms-tagged sources (rows tagged terms_restrict_reuse by the adapters), each started only when the
# states lane has RAM headroom (lane_ramgate.sh, cap 1000 MB). Skips sources in terms_full_done.txt or already running.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
for k in $(cat terms_full_list.txt); do
  grep -q "^$k$" terms_full_done.txt 2>/dev/null && continue
  while pgrep -f "source $k( |$)" >/dev/null; do sleep 60; done
  grep -q "^$k$" terms_full_done.txt 2>/dev/null && continue
  echo "$(date) full $k"
  ramgate_run 130 $L/full_$k.out $PY -u run_full.py --source $k
  rc=$?; echo "$(date) full $k rc=$rc"
  [ $rc -eq 0 ] && echo "$k" >> terms_full_done.txt
done
echo "$(date) FULLQ_END"
