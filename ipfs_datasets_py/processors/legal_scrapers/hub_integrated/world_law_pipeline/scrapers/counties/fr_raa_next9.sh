#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-26 ~12:10-13:00 PDT fr_raa_next9 (batch 9): Guadeloupe FR-971 (Q17012), La Réunion FR-974 (Q17070), Nord FR-59 (Q12661).
#   fr_raa_next9_build.py = fr_raa_next8_build.py + detail_re/pdf_hosts (two-level listing -> detail page -> PDF, for lenord.fr); entries fr_raa_next9_entries.json.
#   QIDs via Wikidata SPARQL (P300). Guadeloupe cg971.fr documents-reglementaires (~50 PDFs uploaded 2025-26); Réunion Webdelib+ arrêtés monthly 01..10-2026
#   (~500, downloadFile.jsp?pdf= -> urlhash doc_ids); Nord lenord.fr espace-documentaire paged (~2,500 arrêtés/délibérations 2026, PDFs on documents.lenord.fr).
#   No staged source_url from these hosts (rg staging/ processed/ 2026-10-26 ~12:30 PDT; only a lenord.fr section URL in web lane place_results state).
#   Not taken (probes 2026-10-26 ~12:15-12:40 PDT): see _reports/fr_raa_next9_probes_20261026.md. Disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next9_build.py fr_raa_next9_entries.json
echo "$(date) done"
