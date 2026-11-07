#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-23 de_by11: next Bavarian Landkreise not yet staged/processed (checked staging/counties, processed, out, staging/web/DE).
#  live crawl (de_kreisrecht_build, robots RFC 9309): München, Rosenheim, Main-Spessart, Neustadt a.d. Waldnaab, Dingolfing-Landau
#  custom list (us_pdf_list): Bad Tölz-Wolfratshausen - Kreisrecht page links PDFs via onclick=window.open(...), generic crawler found 0 (robots.txt 404 = allow)
#  archive-only (archive_index_build, CC/Wayback only): Ebersberg (lra-ebe.de unreachable), Rottal-Inn + Fürth (robots.txt 403), Forchheim (lra-fo.de unreachable)
# Disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
L=${WORLD_LAW_ROOT}/staging/counties/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
g() { df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }; }
g; echo "$(date) start live crawl"; $PY -u de_kreisrecht_build.py de_by11_entries.json by_kreisrecht; echo "$(date) live crawl done"
g; echo "$(date) start bad_toelz list"; $PY -u us_pdf_list.py de_by11_bad_toelz_list.json > $L/de_by_kreisrecht_landkreis_bad_tölz_wolfratshausen.log 2>&1; echo "$(date) bad_toelz $(tail -1 $L/de_by_kreisrecht_landkreis_bad_tölz_wolfratshausen.log)"
g; echo "$(date) start archive-only"; $PY -u archive_index_build.py de_by11_archive_entries.json by_kreisrecht 600 > $L/de_by11_archive.log 2>&1; echo "$(date) archive-only $(tail -1 $L/de_by11_archive.log)"
echo "$(date) done"
