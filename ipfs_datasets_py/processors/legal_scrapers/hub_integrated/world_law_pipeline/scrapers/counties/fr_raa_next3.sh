#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-24 20:25 PDT fr_raa_next3: Pas-de-Calais FR-62 (Q12689) conseil départemental acts 2026 (pasdecalais.fr 'Publicité des actes administratifs';
#   individual acts since the 2022 reform, no monthly RAA). Lists (fr_raa_next3_entries.json): commission-permanente (CP 2026 = 340), conseil-departemental
#   (CD 2026 = 57), voirie-departementale (arrêtés du Président 2026 = 1306), designations-et-representations, amenagement-foncier-0, realisation-demprunts,
#   lignes-de-tresorerie, elections-professionnelles. Expected ~1750 PDFs.
#   robots.txt (RFC 9309, '*' group) checked 16:11 + 20:10 PDT: listing paths and /download/file/ allowed; Crawl-Delay 10 honoured (10 s between listing
#   requests in fr_raa_next3_build.py and between PDFs via crawl_delay in us_pdf_list.py). Download URLs carry ?key= -> URL-hash doc_id suffix.
#   Not covered by any other lane (no pasdecalais.fr source_url in staging/* or processed/*; préfecture RAA pas-de-calais.gouv.fr is a different issuer).
#   Test 2026-10-24 20:15 PDT (fr_raa_next3_test.log, fr_raa_cd_FR-62_test.log): 6/6 OK text PDFs. Disk guard 45 GB (us_pdf_list disk_ok).
#   Took Pas-de-Calais after fr_raa_next2 was stopped (Oise/Meuse archive-exhausted, see _reports/county_blocked_exhausted_20261024.md).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next3_build.py fr_raa_next3_entries.json
echo "$(date) done"
