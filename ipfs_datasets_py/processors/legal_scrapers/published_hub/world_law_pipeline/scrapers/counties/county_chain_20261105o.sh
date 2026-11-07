#!/bin/bash
# 2026-11-05 05:25 PST county chain o: ONE fetcher. Target: Landkreis Oberspreewald-Lausitz DE-BB (wd:Q6156) Amtsblatt,
#  444 issues 1997-2026 (www.osl-online.de/amtsblatt, verwaltungsportal; public download form fetched as GET with form/hash params,
#  query string -> URL-hash doc_id). Never staged by any lane. Lister de_osl_list.py -> entries/de_osl_amtsblatt.json;
#  test 8/8 (6 text + 2 scanned raw -> staging/pdf batch_0913; _logs/de_osl_test.log).
#  Rejected: Gard FR-30 (www.gard.fr Cloudflare 403 to all requests incl. robots.txt -> no bypass); Arcade-API host probe of
#  ~45 other departements found no new portal (deliberations.sarthe.fr = F5 'Request Rejected').
# Guard: 10 GB disk / 2 GB RAM (guard_retry); waits while staging/pdf > 4 GB. Polite 2 s/request, honest WorldLawBot UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261105o.log
echo "$(date) chain o start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [o] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
n=de_osl; f=entries/de_osl_amtsblatt.json
if [ ! -s "$f" ]; then
  guard_retry list_$n $PY -u de_osl_list.py "$f" >> $L/${n}_list.log 2>&1; rc=$?
  echo "$(date) [o] list $n rc=$rc $(tail -1 $L/${n}_list.log)" >> $C
  [ $rc -eq 99 ] && { echo "$(date) [o] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
fi
[ -s "$f" ] && [ -e "entries/_test_$n.ok" ] || { echo "$(date) [o] skip $n (no entries/test-ok marker)" >> $C; exit 1; }
tries=0
while [ $tries -lt 3 ]; do pdfhold
  guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
  echo "$(date) [o] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
  [ $rc -eq 99 ] && { echo "$(date) [o] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
  [ $rc -eq 130 ] && exit 130
  if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
  grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
  break; done
echo "$(date) chain o done" >> $C
