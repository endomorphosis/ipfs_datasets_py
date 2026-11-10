#!/bin/sh
# 2026-11-01 ~00:40 PDT fr_raa_next11 (batch 11): four conseil départemental Webdelib+ portals, LIVE (robots.txt 404 on all four hosts = allow; 3 s):
#   Cher FR-18 (Q3286) delib.cd18.digitechcloud.fr, Meurthe-et-Moselle FR-54 (Q12626) delib.meurthe-et-moselle.fr, Haute-Loire FR-43 (Q12572) cd43-webdelibplus.digitechcloud.fr:
#     arrêtés summary_orders &date=01..10-2026 + délibérations of all 2026 séances (seance_agenda.jsp); openfile.jsp -> downloadFile.jsp?pdf= (query -> ~urlhash doc_ids).
#   Loire FR-42 (Q12569) TOP-UP: 12 2026 séances' délibérations (fr_raa_next8 staged only arrêtés) + arrêtés since 10-26; showFile.jsp kept for dedup with next8.
#     (pass-1 fr_raa_cd_fr-42*.json and _logs/fr_raa_cd_FR-42*.log backed up as *.bak_20261101_next8 before the test overwrote the _test files.)
#   fr_raa_next11_build.py = identical copy of fr_raa_next10_build.py; entries fr_raa_next11_entries.json. Test: _logs/fr_raa_next11_test.log + fr_raa_cd_FR-xx_test.log.
#   Test 2026-11-01 00:12-00:23 PDT (--test 3): Cher 3/3, Meurthe-et-Moselle 3/3, Haute-Loire 3/3, Loire 3/3 OK (text PDFs, ~urlhash doc_ids).
#   us_pdf_list skips already-staged/processed source_urls (test docs not refetched). Disk guard: us_pdf_list.disk_ok floor 20480 MiB + county_chain_guard.sh g().
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh
g; echo "$(date) start live"
$PY -u fr_raa_next11_build.py fr_raa_next11_entries.json
echo "$(date) done"
