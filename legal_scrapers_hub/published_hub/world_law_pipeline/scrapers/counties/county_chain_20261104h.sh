#!/bin/bash
# 2026-11-04 04:10 PST county chain h: Alpes-de-Haute-Provence FR-04 (wd:Q3131) conseil départemental délibérations (+annexes, PV)
# from the Digitech Webdelib+ public portal deliberations.mondepartement04.fr (new fr_webdelib_list.py: seances.jsp +
# seances_archives.jsp -> every seance_agenda.jsp -> showFile.jsp?pdf=T PDFs -> pdf_list_fetch.py). Sessions 2009->2026 (~100).
# Department never staged by any lane (no wd_Q3131 in processed/counties). No Arcade/Digitech portal found for other untried
# departements (04:0x PST probe of portail-actes/actes/e-deliberations/actesadministratifs.<dept> + cdNN*.digitechcloud.fr);
# Romanian leftovers (Bistrița-Năsăud, Iași, Brașov) still unreachable, Suceava 503, Tulcea SharePoint JS.
# Test 04:07 PST (entries/_test_fr04_s.json, _logs/fr04_ahp_test.log): 8/8 ok (1 scanned), 0 err.
# Runs alongside chain g (FR-03, different host). Guard: 10 GB disk / 1.5 GB RAM (guard_retry); waits while staging/pdf > 4 GB.
# Polite 2 s/request, honest UA. Stamp-only scans -> staging/pdf (FETCH_STAMP_RE, as chain g).
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
export FETCH_STAMP_RE='D[ée]pos[ée]e? en Pr[ée]fecture|Affich[ée]e? le|Ex[ée]cutoire le|ID T[ée]l[ée]transmission|Publi[ée]e? le|^\s*\d{1,2}(er)?\s+\w+\s+\d{4}\s*$'
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261104h.log
echo "$(date) chain h start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [h] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
run_target() {  # name base qid place iso
  local n=$1 b=$2 q=$3 p=$4 i=$5 f=entries/fr_raa_cd_$1.json tries=0 rc=0
  if [ -s "$f" ]; then echo "$(date) [h] $n entries exist, resume fetch" >> $C; else
  guard_retry list_$n $PY -u fr_webdelib_list.py "$b" "$q" "$p" "$i" "$f" >> $L/${n}_list.log 2>&1; rc=$?
  echo "$(date) [h] list $n rc=$rc $(tail -1 $L/${n}_list.log)" >> $C; fi
  [ $rc -eq 99 ] && { echo "$(date) [h] guard stop" >> $C; exit 99; }
  [ $rc -ne 0 ] || [ ! -s "$f" ] && return 1
  while [ $tries -lt 4 ]; do
    pdfhold
    guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
    echo "$(date) [h] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
    [ $rc -eq 99 ] && { echo "$(date) [h] guard stop" >> $C; exit 99; }
    [ $rc -eq 130 ] && { echo "$(date) [h] interrupted" >> $C; exit 130; }
    if tail -3 $L/${n}.log | grep -q "consecutive errors"; then echo "$(date) [h] $n failing -> wait 45 min" >> $C; sleep 2700; continue; fi
    if [ $tries -lt 2 ] && grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]'; then sleep 600; continue; fi
    break
  done
}
run_target fr04_ahp https://deliberations.mondepartement04.fr Q3131 "Alpes-de-Haute-Provence" FR-04
echo "$(date) chain h done" >> $C
