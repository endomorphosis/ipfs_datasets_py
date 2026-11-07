#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-04 09:55 PST county chain i: German Kreis Amtsblatt archives (non-Bavaria, never staged), ONE fetcher, targets run sequentially:
#  Coesfeld NW (Q6210, 714 PDFs) -> Warendorf NW (Q2839, 475) -> Märkisch-Oderland BB (Q6181, 438) -> Soest NW (Q5965, 147).
# Lists by de_amtsblatt_list.py (entries/de_*_amtsblatt.json); tests 8/8 ok each (_logs/de_*_test.log). Cap: 3 county fetchers total.
# Sheds itself: GUARD_MIN_RAM_MIB=2048 -> stopfile, clean stop, guard_retry waits/resumes (done ledger = resume-safe).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs; C=$L/county_chain_20261104i.log
echo "$(date) chain i start pid=$$" >> $C
pdfhold() { while [ "$(du -sm ${WORLD_LAW_ROOT}/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [i] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() { local n=$1 f=entries/$1_amtsblatt.json tries=0 rc=0
  while [ $tries -lt 3 ]; do pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [i] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [i] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break; done; }
for n in de_coe de_waf de_mol de_so; do run_target $n; done
echo "$(date) chain i done" >> $C
