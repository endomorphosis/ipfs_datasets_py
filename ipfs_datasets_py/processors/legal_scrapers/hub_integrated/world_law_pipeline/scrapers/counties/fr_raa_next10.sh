#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-30 ~09:00 PDT fr_raa_next10 (batch 10): Gers FR-32 (Q12517) conseil départemental, LIVE (robots.txt 404 on cd32-actes.digitechcloud.fr = allow; 3 s).
#   fr_raa_next10_build.py = identical copy of fr_raa_next9_build.py; entries fr_raa_next10_entries.json. Webdelib+ arrêtés summary_orders &date=01..10-2026 (~640)
#   + délibérations of the 5 2026 séances (seance_agenda.jsp, ~330 seen for CP 22-05 + CP 16-10 in the test). openfile.jsp -> downloadFile.jsp?pdf= (query -> ~urlhash doc_ids).
#   Test 2026-10-30 08:16 PDT (_logs/fr_raa_next10_test.log, fr_raa_cd_FR-32_test.log): 3/3 OK text PDFs. us_pdf_list skips already-staged/processed source_urls.
#   Mayotte FR-976 dropped: www.mayotte.fr drops TLS (UNEXPECTED_EOF) on repeat requests (rate-limit/anti-bot), Wayback has only 14 2026 act captures.
#   Disk guard: us_pdf_list.disk_ok floor 20480 MiB (= GUARD_MIN_MIB) + county_chain_guard.sh g().
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh
g; echo "$(date) start live"
$PY -u fr_raa_next10_build.py fr_raa_next10_entries.json
echo "$(date) done"
