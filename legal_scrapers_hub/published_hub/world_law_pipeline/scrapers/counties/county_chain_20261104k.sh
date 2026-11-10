#!/bin/bash
# 2026-11-04 12:15 PST county chain k: Brandenburg Landkreis Amtsblatt archives (never staged), ONE fetcher, targets sequential:
#  list: de_amtsblatt_list.py entries/cfg/de_los*.json; test 8/8 (_logs/de_los_test.log).
# Lists by de_amtsblatt_list.py (entries/cfg/de_{tf,bar,hvl}.json); tests 8/8 ok (_logs/de_*_test.log). Cap: 3 county fetchers total.
# Sheds itself: GUARD_MIN_RAM_MIB=2048 -> stopfile, clean stop, guard_retry waits/resumes (done ledger = resume-safe).
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261104k.log
echo "$(date) chain k start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [k] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() { local n=$1 f=entries/$1_amtsblatt.json tries=0 rc=0
  [ -s "$f" ] && [ -e "entries/_test_$1.ok" ] || { echo "$(date) [k] skip $n (no entries/test-ok marker)" >> $C; return; }
  while [ $tries -lt 3 ]; do pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [k] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [k] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break; done; }
for n in de_los; do run_target $n; done
echo "$(date) chain k done" >> $C
