#!/bin/bash
# 2026-11-01 22:20 PST: re-run Landkreis Passau (Q10489) with the watchdog fetcher once chain county_chain_20261101s.sh
# (PID given as $1) has finished Q10497/Q10533. Passau's first attempt hung in an SSL read (PID 2829244, killed 22:2x PST).
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261101s.log
W=${1:-0}; echo "$(date) chain t start pid=$$ (waiting for chain pid $W)" >> $C
while [ "$W" -gt 0 ] && kill -0 "$W" 2>/dev/null; do sleep 60; done
for q in Q10489; do f=entries/de_by_wd_$q.json
  guard_run "de_by_wd_$q" $PY -u pdf_list_fetch.py "$f" >> $L/de_by_fetch_s.log 2>&1; rc=$?
  echo "$(date) [t] $f rc=$rc" >> $C; [ $rc -eq 99 ] && { echo "$(date) [t] guard stop" >> $C; exit 99; }
done
echo "$(date) chain t done" >> $C
