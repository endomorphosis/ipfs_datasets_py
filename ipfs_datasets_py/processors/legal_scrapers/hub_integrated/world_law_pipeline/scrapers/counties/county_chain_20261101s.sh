#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01 PST: fetch the 11 Bavarian Landkreise (entries built by de_by_topup2_build.sh = de_kreisrecht_topup_build.py <entries> by_kreisrecht 0)
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs
echo "$(date) chain start pid=$$" >> $L/county_chain_20261101s.log
for q in Q10410 Q10432 Q10434 Q10459 Q10474 Q10475 Q10482 Q10485 Q10489 Q10497 Q10533; do
  for f in entries/de_by_wd_$q.json; do [ -f "$f" ] || continue
    guard_run "de_by_wd_$q" $PY -u pdf_list_fetch.py "$f" >> $L/de_by_fetch_s.log 2>&1; rc=$?
    echo "$(date) $f rc=$rc" >> $L/county_chain_20261101s.log; [ $rc -eq 99 ] && { echo "$(date) guard stop" >> $L/county_chain_20261101s.log; exit 99; }
  done
done
echo "$(date) chain done" >> $L/county_chain_20261101s.log
