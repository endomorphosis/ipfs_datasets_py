#!/bin/bash
# 2026-11-03 20:20 PST county chain f: next French conseil départemental collection on a Digitech "Arcade" public portal
# (fr_arcade_list.py public JSON API -> pdf_list_fetch.py), same pattern as chains a/c/d.
#  Morbihan FR-56 (wd:Q12642) portail-actes.morbihan.fr: DELIB 2,477 délibérations (0 ACTE) listed 20:12 PST.
#  Was "JS app, not usable" in the 10-30 probe; the Arcade JSON API works. Host not present in staging/processed (any lane) before launch.
#  Test 20:13 PST (entries/_test_fr56_s.json, _logs/fr56_morbihan_test.log): 6/6 ok, 0 scanned, 0 err.
# Bavaria round 5 not run: round 4 (chain e) staged only ~6 new docs in ~10 h. Runs alongside chain d2 (FR-29, different host).
# Guard: 10 GB disk / 1.5 GB RAM (guard_retry). Polite 2 s/request, honest UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261103f.log
echo "$(date) chain f start pid=$$" >> $C
run_target() {  # name base qid place
  local n=$1 b=$2 q=$3 p=$4 f=entries/fr_raa_cd_$1.json tries=0
  if [ -s "$f" ]; then echo "$(date) [f] $n entries exist, resume fetch" >> $C; rc=0; else
  guard_retry list_$n $PY -u fr_arcade_list.py "$b" "$q" "$p" "$f" >> $L/${n}_list.log 2>&1; local rc=$?
  echo "$(date) [f] list $n rc=$rc $(tail -1 $L/${n}_list.log)" >> $C; fi
  [ $rc -eq 99 ] && { echo "$(date) [f] guard stop" >> $C; exit 99; }
  [ $rc -ne 0 ] || [ ! -s "$f" ] && return 1
  while [ $tries -lt 4 ]; do
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [f] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [f] guard stop" >> $C; exit 99; }
    [ $rc -eq 130 ] && { echo "$(date) [f] interrupted" >> $C; exit 130; }
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then echo "$(date) [f] $n failing -> wait 45 min" >> $C; sleep 2700; continue; fi
    if [ $tries -lt 2 ] && grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]'; then sleep 600; continue; fi
    break
  done
}
run_target fr56_morbihan https://portail-actes.morbihan.fr Q12642 Morbihan
echo "$(date) chain f done" >> $C
