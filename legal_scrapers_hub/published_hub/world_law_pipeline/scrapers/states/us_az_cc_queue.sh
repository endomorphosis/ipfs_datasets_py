#!/bin/bash
# 2026-10-28 (Benjamin): AZ remainder via Common Crawl (Wayback listing parked, data/cdx_parts kept). Resumable:
# CC listing (cc_az_list.py, per-crawl parts in data/cc_az_parts) until all 12 newest crawls are listed (max 8 passes),
# then the 20-row test into staging/states/_review (held for eyeball; NOT promoted, full run NOT started by this script).
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
while pgrep -f "cc_az_list.py" >/dev/null; do sleep 60; done
for i in $(seq 1 8); do
  echo "$(date) cc list pass $i"; CC_AZ_MAX_SECS=7200 ramgate_run 80 $L/cc_az_list.out $PY -u cc_az_list.py 12; rc=$?; echo "rc=$rc"
  [ $rc -eq 0 ] && break; sleep 1800
done
n=$(wc -l < data/archive/az_ars_cc.jsonl 2>/dev/null || echo 0); echo "$(date) cc unique section urls: $n"
[ "$rc" -eq 0 ] && [ "$n" -gt 0 ] && { echo "$(date) test us_az_ars_cc"; ramgate_run 150 $L/test_us_az_ars_cc.out $PY -u run_full.py --source us_az_ars_cc --test 20; echo "rc=$?"; }
echo "$(date) AZCC_END"
