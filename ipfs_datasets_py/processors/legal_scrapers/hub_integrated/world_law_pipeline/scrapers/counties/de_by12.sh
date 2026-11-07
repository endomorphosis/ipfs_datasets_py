#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-24 de_by12: the last Bavarian Landkreise not covered by de_by1..de_by11 (checked de_by*_entries.json, de_by*.sh, _logs, per-county configs).
#  live crawl (de_kreisrecht_build, robots RFC 9309): Neustadt a.d. Aisch-Bad Windsheim (kreis-nea.de robots 404 = allow),
#     Ansbach (was archive-only in de_by_archive with no archived index; live loadDocument.phtml endpoint now answers, robots allows it)
#  archive-only (de_by12_index_cfg builds configs from robots-allowed live index pages; PDFs fetched ONLY from CC/Wayback by archive_retry):
#     Miesbach (robots Disallow: /output/ = download.php PDFs), Landsberg am Lech (PDF host kxp.landkreis-landsberg.de robots Disallow: /)
# Archive rounds are idempotent (archive_retry skips staged source_urls; query URLs get URL-hash doc_id suffix), 30 min apart. Disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
L=${WORLD_LAW_ROOT}/staging/counties/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
g() { df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }; }
g; echo "$(date) start live crawl"; $PY -u de_kreisrecht_build.py de_by12_entries.json by_kreisrecht; echo "$(date) live crawl done"
g; echo "$(date) refresh archive-only configs"; $PY -u de_by12_index_cfg.py de_by12_archive_index_entries.json by_kreisrecht > $L/de_by12_index_cfg.log 2>&1; tail -n 4 $L/de_by12_index_cfg.log
for round in 1 2 3 4 5 6 7 8; do
  for c in de_by_kreisrecht_landkreis_miesbach_archive.json de_by_kreisrecht_landkreis_landsberg_am_lech_archive.json; do
    g; echo "== archive round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "$(date) done"
