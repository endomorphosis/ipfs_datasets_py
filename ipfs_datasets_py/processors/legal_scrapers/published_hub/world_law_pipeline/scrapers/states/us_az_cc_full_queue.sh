#!/bin/bash
# 2026-10-28 21:15 PDT: US-AZ via Common Crawl FULL (20-row us_az_ars_cc test eyeballed + promoted). RAM-gated; resumes from _state/us_az_ars_cc.done.tsv.
# ArchiveDeferred handling: if the run ends with deferred_left>0 (or rc!=0), requeue from checkpoint after 30 min, max 12 passes.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
for i in $(seq 1 12); do
  if pgrep -f "run_full.py --source us_az_ars_cc( |$)" >/dev/null; then echo "$(date) us_az_ars_cc already running"; exit 0; fi
  echo "$(date) full us_az_ars_cc pass $i"
  ramgate_run 150 $L/full_us_az_ars_cc.log $PY -u run_full.py --source us_az_ars_cc; rc=$?
  dl=$(grep -o 'deferred_left=[0-9]*' $L/full_us_az_ars_cc.log | tail -1 | cut -d= -f2)
  echo "$(date) pass $i rc=$rc deferred_left=${dl:-?}"
  [ "$rc" -eq 0 ] && [ "${dl:-1}" = "0" ] && break
  sleep 1800
done
echo "$(date) AZCC_FULL_END"
