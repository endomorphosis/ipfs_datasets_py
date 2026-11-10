#!/bin/bash
# 2026-11-05 ~20:27 PST county chain q: ONE fetcher. Outside-Brandenburg Amtsblatt archives never staged:
#  Börde ST (wd:Q6064, 1364 PDFs ~2009-2026, landkreis-boerde.de single index) ->
#  Steinfurt NW (wd:Q6187, 228 PDFs 2023-2026 year pages) ->
#  Nordsachsen SN (wd:Q6301, 288 PDFs 2016-2026; href /landratsamt/.../files/ rewritten to /files/) ->
#  Borken NW (wd:Q6191, 61 PDFs 2025-2026) ->
#  Mansfeld-Südharz ST (wd:Q6092, 46 PDFs 2023-2026 year pages) ->
#  Anhalt-Bitterfeld ST (wd:Q6071, 11 PDFs 2026 current year on index; older years accordion not separate URLs).
#  Lists: de_amtsblatt_list.py (+ NS URL rewrite). Tests 8/8 (_logs/de_*_test.log; ABF 6 text+2 scanned). Cap: one county chain.
#  Rejected: Jerichower Land TLS EOF; Salzlandkreis Cloudflare challenge; Paderborn/Höxter/Stendal TLS EOF;
#  Wesel per-issue HTML not direct PDF list; Steinfurt 2022- archive not online; Saale-Orla only ~10 current;
#  Gard FR-30 Cloudflare (prior); Börde old dissolved Q836670 ignored (use current Q6064).
# Guard: 10 GB disk / 2 GB RAM; staging/pdf >4 GB hold. Polite 2 s/request, honest WorldLawBot UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261105q.log
echo "$(date) chain q start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [q] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() { local n=$1 f=entries/${n}_amtsblatt.json tries=0 rc=0
  [ -s "$f" ] && [ -e "entries/_test_$n.ok" ] || { echo "$(date) [q] skip $n (no entries/test-ok marker)" >> $C; return; }
  while [ $tries -lt 3 ]; do pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [q] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [q] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
    [ $rc -eq 130 ] && exit 130
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
    grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
    break; done; }
for n in de_boe de_st de_ns de_bk de_msh de_abf; do run_target $n; done
echo "$(date) chain q done" >> $C
