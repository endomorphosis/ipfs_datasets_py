#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-30 ~09:00 PDT de_by19: Landkreis Cham (Q10424) ARCHIVE-ONLY (landkreis-cham.de robots.txt 'Disallow: /' re-checked 08:10 PDT).
#  Only 5 Q10424 docs staged so far (2026-10-22 one-shot archive_index_build run, 320 left deferred, never retried). The old 325-URL config was ~95% MUNICIPAL
#  Satzungen hosted by the Landratsamt (Hohenwarth, Falkenstein, Stadt Cham ... - Stadt Cham is covered by the web lane as Q546459) -> rebuilt COUNTY-ONLY:
#  de_by13_cdx_cfg.py (de_by19_cham_cdx_entry.json, keep_re = file name starts landkreis-cham/kreiswerke/amtsblatt/kreis + law keyword; log _logs/de_by19_cdx_cfg.log):
#  9,264 Wayback PDF rows -> 143 kept, + 7 county-level URLs from the old config (backup de_by19_cham_archive_prev325.json) = 150 URLs, none with a query string.
#  Test 2026-10-30 08:34-08:44 PDT (de_by19_test.log, de_by19_test_cham_archive.json): 3/3 OK Wayback text PDFs. archive_retry skips already-staged source_urls. 10 rounds.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480)
for round in $(seq 1 10); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_cham_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 10 ] && sleep 600
done
echo "$(date) done"
