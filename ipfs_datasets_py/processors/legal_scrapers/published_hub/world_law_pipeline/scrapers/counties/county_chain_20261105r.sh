#!/bin/bash
# 2026-11-06 ~00:15 PST county chain r: ONE fetcher. Outside-Brandenburg Amtsblatt archives never staged:
#  Zwickau SN (wd:Q6330, 319 PDFs, e-amtsblatt-archiv) ->
#  Herford NW (wd:Q6234, 511 PDFs 2010-2026 year pages, download.php) ->
#  Vogtlandkreis SN (wd:Q6337, 57 PDFs; download.php rewritten to /media/custom/*.PDF) ->
#  Saale-Orla-Kreis TH (wd:Q7883, 14 PDFs amtsblattarchiv) ->
#  Hochsauerlandkreis NW (wd:Q5946, 184 PDFs) ->
#  Märkischer Kreis NW (wd:Q5937, 243 PDFs).
#  Lists: de_amtsblatt_list.py (pdf match + max_pages). Tests 8/8 (_logs/de_*_test.log). Cap: one county chain.
#  Rejected this round after verify: Vogtland download.php 404 (rewrote to direct media); Stendal TLS EOF flaky
#  (queued for supervisor follow-up); Unna FID HTML not direct PDF (queued); Recklinghausen session/abo-online
#  cross-host; Wittenberg schedule-only; Jerichower Land TLS EOF; Salzlandkreis Cloudflare; Harz domain for sale;
#  Görlitz/Leipzig/Sächsische Schweiz TLS errors; Warendorf already done (chain i).
# Guard: 10 GB disk / 2 GB RAM; staging/pdf >4 GB hold. Polite 2 s/request, honest WorldLawBot UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261105r.log
echo "$(date) chain r start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [r] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() { local n=$1 f=entries/${n}_amtsblatt.json tries=0 rc=0
  [ -s "$f" ] && [ -e "entries/_test_$n.ok" ] || { echo "$(date) [r] skip $n (no entries/test-ok marker)" >> $C; return; }
  while [ $tries -lt 3 ]; do pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [r] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [r] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break; done; }
for n in de_zw de_hf de_vg de_sok de_hsk de_mk; do run_target $n; done
echo "$(date) chain r done" >> $C
