#!/bin/bash
# 2026-11-04 00:20 PST county chain g: Allier FR-03 (wd:Q3113) conseil départemental acts from delib.allier.fr (public Laravel portal;
# fr_allier_list.py lists via the page's own public list + details calls -> pdf_list_fetch.py). Host never staged by any lane
# (was "maintenance / lists 404" in the 10-26 probe, "JS shell" in the 10-30 probe; both now work). Year by year, newest first:
# arrêtés (+annexes), décisions, CP délibérations (+dossier annexes), CD session délibérations (+dossier annexes); rapports skipped.
# 2026 rows listed 00:05 PST: 301 arrêtés + 267 décisions + 545 CP + 103 sessions; 2025: ~700 CP, ~200 sessions, ~312 décisions.
# Arrêtés/décisions are scans with a prefecture e-transmission stamp text layer -> FETCH_STAMP_RE makes stamp-only PDFs count as
# scanned (raw to staging/pdf + manifest, no OCR). Test 00:14 PST (entries/_test_fr03_s.json, _logs/fr03_allier_test.log): 10/10
# (4 text délibérations, 6 scanned, 0 err). Replaces the empty Ardèche FR-07 slot (arcade.ardeche.fr still unreachable 00:04 PST).
# Runs alongside chain d2 (FR-29, different host). Guard: 10 GB disk / 1.5 GB RAM (guard_retry); waits while staging/pdf > 4 GB.
# Polite 2 s/request, honest UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
export FETCH_STAMP_RE='D[ée]pos[ée]e? en Pr[ée]fecture|Affich[ée]e? le|Ex[ée]cutoire le|ID T[ée]l[ée]transmission|Publi[ée]e? le|^\s*\d{1,2}(er)?\s+\w+\s+\d{4}\s*$'
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261104g.log
echo "$(date) chain g start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [g] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_year() {  # year
  local y=$1 n=fr03_allier f=entries/fr_raa_cd_fr03_allier_$1.json tries=0 rc=0
  if [ -s "$f" ]; then echo "$(date) [g] $n $y entries exist, resume fetch" >> $C; else
  guard_retry list_${n}_$y $PY -u fr_allier_list.py "$f" --years $y >> $L/${n}_list.log 2>&1; rc=$?
  echo "$(date) [g] list $n $y rc=$rc $(tail -1 $L/${n}_list.log)" >> $C; fi
  [ $rc -eq 99 ] && { echo "$(date) [g] guard stop" >> $C; exit 99; }
  [ $rc -ne 0 ] || [ ! -s "$f" ] && return 1
  while [ $tries -lt 4 ]; do
    pdfhold
    guard_retry ${n}_$y $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [g] fetch $n $y pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [g] guard stop" >> $C; exit 99; }
    [ $rc -eq 130 ] && { echo "$(date) [g] interrupted" >> $C; exit 130; }
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then echo "$(date) [g] $n failing -> wait 45 min" >> $C; sleep 2700; continue; fi
    if [ $tries -lt 2 ] && grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]'; then sleep 600; continue; fi
    break
  done
}
for y in 2026 2025 2024 2023 2022; do run_year $y; done
echo "$(date) chain g done" >> $C
