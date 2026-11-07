#!/bin/bash
# 2026-11-03 13:25 PST: hold FR-29 PDF staging until staging/pdf < 4 GB; check every 10 min, give up after 24 h.
cd /workspace/world_law/pipeline/scrapers/counties; L=/workspace/world_law/staging/counties/_logs/fr29_pdfhold_waiter.log
echo "$(date) waiter start pid=$$" >> $L; end=$(( $(date +%s) + 86400 ))
while [ $(date +%s) -lt $end ]; do
  b=$(du -sb /workspace/world_law/staging/pdf 2>/dev/null | cut -f1)
  echo "$(date) staging/pdf=$b B" >> $L
  if [ -n "$b" ] && [ "$b" -lt 4000000000 ]; then
    pgrep -f "pdf_list_fetch.py entries/fr_raa_cd_fr29_finistere.json" >/dev/null && { echo "$(date) FR-29 already running -> exit" >> $L; exit 0; }
    echo "$(date) under 4 GB -> relaunch county_chain_20261103_fr29.sh" >> $L
    nohup setsid ./county_chain_20261103_fr29.sh >/dev/null 2>&1 < /dev/null & echo "$(date) chain pid $!" >> $L; exit 0
  fi
  sleep 600
done
echo "$(date) gave up after 24 h" >> $L
