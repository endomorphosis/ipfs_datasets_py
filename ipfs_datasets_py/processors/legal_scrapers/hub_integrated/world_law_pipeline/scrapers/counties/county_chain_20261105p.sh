#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-05 ~07:00 PST county chain p: ONE fetcher. Brandenburg Amtsblatt archives never staged:
#  Prignitz BB (wd:Q6132, 504 PDFs 2019-2026, landkreis-prignitz.de year pages) ->
#  Ostprignitz-Ruppin BB (wd:Q6125, 187 PDFs thru Jun 2022, paginated media/custom; query-string URL-hash doc_ids) ->
#  Spree-Neiße BB (wd:Q6165, HTML 2026 (40) + HEAD-probed 2024 (54) + 2025 (40) = 134 PDFs on lkspn.de/media/file/amtsblatt/).
#  Lists: de_amtsblatt_list.py (+ SPN year probe). Tests 8/8 (_logs/de_*_test.log). Cap: one county chain.
#  Rejected: Oberhavel (no Amtsblatt archive; Bekanntmachungen/Zustellungen only); Elbe-Elster (year object pages 404 from
#  logo links; needs deeper CMS probe); Uckermark (Veröffentlichungen thin / SessionNet not a gazette PDF list);
#  Gard FR-30 Cloudflare (prior). Guard: 10 GB disk / 2 GB RAM; staging/pdf >4 GB hold.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs; C=$L/county_chain_20261105p.log
echo "$(date) chain p start pid=$$" >> $C
pdfhold() { while [ "$(du -sm ${WORLD_LAW_ROOT}/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [p] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() { local n=$1 f=entries/${n}_amtsblatt.json tries=0 rc=0
  [ -s "$f" ] && [ -e "entries/_test_$n.ok" ] || { echo "$(date) [p] skip $n (no entries/test-ok marker)" >> $C; return; }
  while [ $tries -lt 3 ]; do pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [p] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [p] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break; done; }
for n in de_pr de_opr de_spn; do run_target $n; done
echo "$(date) chain p done" >> $C
