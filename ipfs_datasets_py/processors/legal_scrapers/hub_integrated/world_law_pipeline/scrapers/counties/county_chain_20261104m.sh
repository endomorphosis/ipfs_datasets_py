#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-04 18:10 PST county chain m: ONE fetcher, targets sequential (never staged):
#  de_pm = Potsdam-Mittelmark wd:Q6142 (Amtsblatt 2024+, Bekanntmachungen, Satzungen/Kreisrecht; einladungen dropped),
#          list de_amtsblatt_list.py entries/cfg/de_pm.json; test 8/8 (_logs/de_pm_test.log).
#  de_gt = Kreis Gütersloh wd:Q6218 Amtsblatt 2003-2026 (dedicated lister de_gt_list.py, one HTML page per old issue);
#          test 8/8 (_logs/de_gt_test.log); chain waits for the lister (_logs/de_gt_list.log) to finish.
# Lists by de_amtsblatt_list.py (entries/cfg/de_{tf,bar,hvl}.json); tests 8/8 ok (_logs/de_*_test.log). Cap: 3 county fetchers total.
# Sheds itself: GUARD_MIN_RAM_MIB=2048 -> stopfile, clean stop, guard_retry waits/resumes (done ledger = resume-safe).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs; C=$L/county_chain_20261104m.log
echo "$(date) chain m start pid=$$" >> $C
pdfhold() { while [ "$(du -sm ${WORLD_LAW_ROOT}/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [m] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() { local n=$1 f=entries/$1_amtsblatt.json tries=0 rc=0
  [ -s "$f" ] && [ -e "entries/_test_$1.ok" ] || { echo "$(date) [m] skip $n (no entries/test-ok marker)" >> $C; return; }
  while [ $tries -lt 3 ]; do pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [m] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [m] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break; done; }
run_target de_pm
while ! grep -q '^LISTED' $L/de_gt_list.log 2>/dev/null; do pgrep -f de_gt_list.py >/dev/null || break; sleep 60; done
if grep -q '^LISTED' $L/de_gt_list.log && [ -s entries/de_gt_amtsblatt.json.tmp ]; then mv entries/de_gt_amtsblatt.json.tmp entries/de_gt_amtsblatt.json; echo "$(date) [m] gt $(grep '^LISTED' $L/de_gt_list.log)" >> $C
else echo "$(date) [m] gt lister failed - see de_gt_list.log" >> $C; fi
run_target de_gt
echo "$(date) chain m done" >> $C
