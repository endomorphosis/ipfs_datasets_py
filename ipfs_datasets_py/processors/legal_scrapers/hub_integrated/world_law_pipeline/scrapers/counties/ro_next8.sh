#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-23 ro_next8: continuation of capped (MAXU 400) RO county runs from their saved found-lists, adopted HCJ only
# (title "Hotărâre..." / /hotarari/ paths; drop Proiect de hotărâre, PH-files, anexe, anunțuri, dispoziții de convocare, rapoarte, registre, procese verbale, spreadsheets).
# Ilfov 606, Dolj 126. us_pdf_list skips URLs already staged/processed. Disk guard 45 GB (also inside us_pdf_list).
# Not included: Brăila (Domino portal, hotărâri not reachable by generic crawler: test found 2 PDFs in 60 pages -> needs custom lister),
# Tulcea (SharePoint, JS-rendered list), Alba (Cloudflare 403), Argeș (robots.txt 403), Gorj (robots Disallow: /) -> archive-only candidates.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
L=${WORLD_LAW_ROOT}/staging/counties/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for s in ilfov dolj; do
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "$(date) start $s"; $PY -u us_pdf_list.py ro_next8_${s}_rest.json > $L/ro_next8_${s}.log 2>&1; echo "$(date) $s $(tail -1 $L/ro_next8_${s}.log)"
done
echo "$(date) done"
