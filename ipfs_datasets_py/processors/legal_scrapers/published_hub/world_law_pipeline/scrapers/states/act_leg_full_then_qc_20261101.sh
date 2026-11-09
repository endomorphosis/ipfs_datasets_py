#!/bin/bash
# 2026-11-01 18:25 PST: ACT legislation FULL (r2 test eyeballed + promoted), RAM-gated, log _logs/full_au_act_leg.log
# (resumes from _state/au_act_leg.done.tsv).
# est 125 MB (test r2 peak rss 128 MB; lane_rss_mb also counts ~12 MB of bash ramgate wrappers, so python RSS stays < 1 GB). ca_qc_full_queue.sh was stopped at 18:18 PST to free its RAM slot (QC was
# Wayback-blocked, 983 todo); it is relaunched here once the ACT full has ended, whatever the outcome.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
export ARCHIVE_LANE=states STATES_MAX_DEFERS=10000 STATES_MIN_FREE_GB=10
if pgrep -f "run_full.py --source au_act_leg( |$)" >/dev/null; then echo "$(date) au_act_leg already running"; else
  echo "$(date) full au_act_leg"
  ramgate_run 125 $L/full_au_act_leg.log $PY -u run_full.py --source au_act_leg; echo "$(date) full au_act_leg rc=$?"
fi
pgrep -f "ca_qc_full_queue.sh" >/dev/null || { setsid nohup bash ca_qc_full_queue.sh >> $L/ca_qc_full_queue.out 2>&1 < /dev/null & echo "$(date) relaunched ca_qc_full_queue.sh pid $!"; }
