#!/bin/bash
# For each archive-only source: once its Wayback URL list exists, run a 20-row test into _review (HELD, never auto-promoted).
# 2026-11-01 12:13 PST: the 11:45 relaunch re-ran the NSW test next to the full run because test_*.out had been gzipped; fixed below.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
for pair in nsw:au_nsw_archive qc:ca_qc_archive bc:ca_bc_archive yt:ca_yt_archive ab:ca_ab_archive sa:au_sa_archive vic:au_vic_archive; do
  f=${pair%%:*}; k=${pair##*:}
  zcat -f $L/test_$k.out $L/test_$k.out.gz 2>/dev/null | grep -q "END" && continue   # 2026-11-01: also look in gzipped logs
  pgrep -f "run_full.py --source $k( |$)" >/dev/null && continue                   # never run a test beside a live full run
  while [ ! -e data/archive/$f.txt ]; do sleep 300; done
  /workspace/world_law/pipeline/venv/bin/python run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
