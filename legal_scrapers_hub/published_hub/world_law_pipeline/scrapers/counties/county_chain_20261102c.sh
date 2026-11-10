#!/bin/bash
# 2026-11-02 10:15 PST county chain c: next French conseil départemental collections on Digitech "Arcade" public portals
# (fr_arcade_list.py public JSON API -> pdf_list_fetch.py). Neither host present in staging/processed (counties, web lane cache) before launch.
#  1. Eure FR-27 (wd:Q3372) actesadministratifs.eure.fr: ACTE (906 arrêtés/RAA + PDF annexes) + DELIB (14,553 délibérations since 2007).
#     Test 10:12 PST: 6/6 ok (0 scanned, 0 err).
#  2. Finistère FR-29 (wd:Q3389) e-deliberations.finistere.fr: ACTE (9,107) + DELIB (37,978) -> ~28+ h.
#  Ardèche FR-07 arcade.ardeche.fr retried 10:11 PST: still TLS EOF -> skipped.
# Runs alongside chain b (Bavaria archive rounds, different hosts). Guard: 10 GB disk / 1.5 GB RAM. Polite 2 s/request, honest UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261102c.log
echo "$(date) chain c start pid=$$" >> $C
run_target() {  # name base qid place
  local n=$1 b=$2 q=$3 p=$4 f=entries/fr_raa_cd_$1.json tries=0
  guard_run list_$n $PY -u fr_arcade_list.py "$b" "$q" "$p" "$f" >> $L/${n}_list.log 2>&1; local rc=$?
  echo "$(date) [c] list $n rc=$rc $(tail -1 $L/${n}_list.log)" >> $C
  [ $rc -eq 99 ] && { echo "$(date) [c] guard stop" >> $C; exit 99; }
  [ $rc -ne 0 ] || [ ! -s "$f" ] && return 1
  while [ $tries -lt 4 ]; do
    guard_run $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [c] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [c] guard stop" >> $C; exit 99; }
    [ $rc -eq 130 ] && { echo "$(date) [c] interrupted" >> $C; exit 130; }
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then echo "$(date) [c] $n failing -> wait 45 min" >> $C; sleep 2700; continue; fi
    if [ $tries -lt 2 ] && grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]'; then sleep 600; continue; fi
    break
  done
}
run_target fr27_eure https://actesadministratifs.eure.fr Q3372 Eure
run_target fr29_finistere https://e-deliberations.finistere.fr Q3389 Finistère
echo "$(date) chain c done" >> $C
