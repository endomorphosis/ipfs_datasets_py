#!/bin/bash
# 2026-11-04 20:20 PST county chain n: ONE fetcher. Target: Charente-Maritime FR-17 (wd:Q3278) conseil départemental
#  'Délibérations et actes' (la.charente-maritime.fr, Drupal view, ~6,400 arrêtés/délibérations 2020-2026, 640 pages).
#  Previously skipped (10-26 probe): PDFs /deliberation?path=... are robots-Disallowed -> now fetched live per Benjamin's 11-01
#  robots decision (rows tagged robots_disallowed_ignored; schema HOLD set is empty). No WAF/captcha on the host.
#  Why this target: Romanian judete re-probed 20:10 PST, still blocked (Alba/Argeș 403, Suceava 503, BN/Iași/Brașov connect fail,
#  Tulcea SharePoint JS, Vrancea .doc only); all 71 Bavarian Landkreise already have staged/processed rows (remaining ones are
#  archive-exhausted). Host never staged by any lane (rg staging/processed/held).
#  Lister fr17_cm_list.py (2 s/page) -> entries/fr_raa_cd_fr17_cm.json; test 8/8 (4 text + 4 scanned raw -> staging/pdf batch_0858;
#  _logs/fr17_cm_test.log). doc_id = fr_raa_conseil_departemental:sha1(url)[:16] (query-string URL -> hash id).
# Guard: 10 GB disk / 2 GB RAM (guard_retry); waits while staging/pdf > 4 GB. Polite 2 s/request, honest WorldLawBot UA.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=2048; source ./county_guard_run.sh
export FETCH_STAMP_RE='D[ée]pos[ée]e? en Pr[ée]fecture|Affich[ée]e? le|Ex[ée]cutoire le|ID T[ée]l[ée]transmission|Publi[ée]e? le|^\s*\d{1,2}(er)?\s+\w+\s+\d{4}\s*$'
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261104n.log
echo "$(date) chain n start pid=$$" >> $C
pdfhold() { while [ "$(du -sm /workspace/world_law/staging/pdf | cut -f1)" -gt 4096 ]; do echo "$(date) [n] staging/pdf > 4 GB -> wait 15 min" >> $C; sleep 900; done; }
n=fr17_cm; f=entries/fr_raa_cd_${n}.json
if [ ! -s "$f" ]; then
  guard_retry list_$n $PY -u fr17_cm_list.py "$f" >> $L/${n}_list.log 2>&1; rc=$?
  echo "$(date) [n] list $n rc=$rc $(tail -1 $L/${n}_list.log)" >> $C
  [ $rc -eq 99 ] && { echo "$(date) [n] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
fi
[ -s "$f" ] && [ -e "entries/_test_$n.ok" ] || { echo "$(date) [n] skip $n (no entries/test-ok marker)" >> $C; exit 1; }
tries=0
while [ $tries -lt 3 ]; do pdfhold
  guard_retry $n $PY -u pdf_list_fetch.py "$f" --delay 2 >> $L/${n}.log 2>&1; rc=$?; tries=$((tries+1))
  echo "$(date) [n] fetch $n pass $tries rc=$rc $(grep SUMMARY $L/${n}.log | tail -1 | cut -c1-160)" >> $C
  [ $rc -eq 99 ] && { echo "$(date) [n] guard stop (floors) - rerun chain to resume" >> $C; exit 99; }
  [ $rc -eq 130 ] && exit 130
  if tail -3 $L/${n}.log | grep -q "consecutive errors"; then sleep 2700; continue; fi
  grep SUMMARY $L/${n}.log | tail -1 | grep -qE '"err": [1-9]' && { sleep 600; continue; }
  break; done
echo "$(date) chain n done" >> $C
