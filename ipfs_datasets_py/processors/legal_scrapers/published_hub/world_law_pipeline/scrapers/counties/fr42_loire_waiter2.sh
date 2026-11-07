#!/bin/bash
# 2026-11-01 22:20 PST: Loire FR-42 resume v4 with the watchdog fetcher (pdf_list_fetch.py: per-request deadline, commit-after-flush,
# resume skips staged+processed+provenance+published). Replaces fr42_loire_waiter.sh (PID 2350129, killed with its hung fetch 2350353).
# Run under guard (10 GB disk / 1.5 GB RAM). 25 consecutive errors -> wait 45 min, retry (24 h max). After a clean pass with
# per-doc errors, one extra pass retries only what's still missing. Block page -> fetcher logs + skips; no bypass, no proxy.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; W=$L/fr42_loire_waiter.log
end=$(( $(date +%s) + 86400 )); passes=0
echo "$(date) waiter2 start pid=$$" >> $W
while [ $(date +%s) -lt $end ]; do
  guard_run loire_fr42 $PY -u pdf_list_fetch.py entries/fr_raa_cd_fr-42.json >> $L/loire_fr42.log 2>&1; rc=$?
  s=$(grep SUMMARY $L/loire_fr42.log | tail -1); echo "$(date) pass ended rc=$rc; $s" >> $W
  [ $rc -eq 99 ] && { echo "$(date) guard stop -> exit" >> $W; exit 99; }
  [ $rc -eq 130 ] && { echo "$(date) interrupted -> exit" >> $W; exit 130; }
  if tail -3 $L/loire_fr42.log | grep -q "consecutive errors"; then echo "$(date) documents failing -> wait 45 min" >> $W; sleep 2700; continue; fi
  passes=$((passes+1))
  if [ $passes -lt 2 ] && echo "$s" | grep -qE '"err": [1-9]'; then echo "$(date) retry pass for errored docs in 10 min" >> $W; sleep 600; continue; fi
  echo "$(date) done -> exit" >> $W; exit $rc
done
echo "$(date) 24 h elapsed -> give up" >> $W
