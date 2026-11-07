#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-02 02:10 PST county chain a: next queued French conseil départemental collections via the Digitech "Arcade" public portal
# (successor of Webdelib+/PubliActes; fr_arcade_list.py lists via the portal's public JSON API, pdf_list_fetch.py fetches).
#  1. Haute-Garonne FR-31 (wd:Q12538) actes.haute-garonne.fr: all ACTE (arrêtés/décisions, + PDF annexes) and DELIB (délibérations) documents
#     (~4,741 actes + 1,618 délibérations listed 02:04 PST). Was archive-only (old PubliActes robots Disallow: /); robots now ignored per
#     Benjamin (Nov 1) and the new host's robots.txt is 404 anyway. Test 02:05 PST: 6/6 rows (5 text, 1 scanned -> staging/pdf/FR/wd_Q12538).
#  2. Ardèche FR-07 (wd:Q3148) arcade.ardeche.fr: same platform; host unreachable from the box at 02:09 PST -> listing is tried,
#     skipped if it fails (no proxy, no bypass).
# Runs alongside chain t (Passau, different host). Guard: 10 GB disk / 1.5 GB RAM (guard_run). Polite 2 s/request, honest UA.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python; L=${WORLD_LAW_ROOT}/staging/counties/_logs; C=$L/county_chain_20261102a.log
echo "$(date) chain a start pid=$$" >> $C
run_target() {  # name base qid place
  local n=$1 b=$2 q=$3 p=$4 f=entries/fr_raa_cd_$1.json tries=0
  guard_run list_$n $PY -u fr_arcade_list.py "$b" "$q" "$p" "$f" >> $L/${n}_list.log 2>&1; local rc=$?
  echo "$(date) [a] list $n rc=$rc $(tail -1 $L/${n}_list.log)" >> $C
  [ $rc -eq 99 ] && { echo "$(date) [a] guard stop" >> $C; exit 99; }
  [ $rc -ne 0 ] || [ ! -s "$f" ] && return 1
  while [ $tries -lt 4 ]; do
    guard_run $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [a] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [a] guard stop" >> $C; exit 99; }
    [ $rc -eq 130 ] && { echo "$(date) [a] interrupted" >> $C; exit 130; }
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then echo "$(date) [a] $n failing -> wait 45 min" >> $C; sleep 2700; continue; fi
    if [ $tries -lt 2 ] && grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]'; then sleep 600; continue; fi
    break
  done
}
run_target fr31_hgaronne https://actes.haute-garonne.fr Q12538 Haute-Garonne
run_target fr07_ardeche https://arcade.ardeche.fr Q3148 Ardèche
echo "$(date) chain a done" >> $C
