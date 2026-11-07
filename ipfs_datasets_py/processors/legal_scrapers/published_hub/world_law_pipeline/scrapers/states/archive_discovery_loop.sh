#!/bin/bash
# 2026-11-01 18:15 PST: disk floor 36 -> 11 GB gate (lane floor 10 GB, Benjamin 16:48 PST).
# 2026-10-24: re-run the resumable Wayback discovery passes (ACT a/ sl/, then QC/BC/YT/SA/VIC) until every list exists.
# cdx_list.py caches finished parts, so each pass only retries deferred parts. Sleeps 30 min between passes.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
for pass in $(seq 1 200); do
  [ -s data/act_sl_cdx.txt ] && [ -s data/act_a_cdx.txt ] || bash act_on_cdx.sh >> $L/cdx_list_act.out 2>&1
  missing=""
  for f in qc bc yt sa vic; do [ -s data/archive/$f.txt ] || missing="$missing $f"; done
  [ -n "$missing" ] && bash archive_discovery.sh >> $L/archive_discovery.out 2>&1
  if [ -s data/act_sl_cdx.txt ] && [ -z "$missing" ]; then echo "$(date) all lists done" >> $L/archive_discovery_loop.log; break; fi
  echo "$(date) pass $pass done; still missing:$missing $( [ -s data/act_sl_cdx.txt ] || echo act)" >> $L/archive_discovery_loop.log
  g=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ "$g" -lt 11 ] && { echo "$(date) disk floor: stop" >> $L/archive_discovery_loop.log; exit 0; }
  sleep 1800
done
