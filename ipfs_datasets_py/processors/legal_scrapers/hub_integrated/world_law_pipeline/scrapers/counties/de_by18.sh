#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-28 10:45 PDT de_by18: Landkreis Würzburg (Q10458) ARCHIVE-ONLY. robots.txt Disallow: /output/ and the Amtsblatt only links /output/download.php?file=... -> archive copies only.
#  Config de_by_kreisrecht_landkreis_würzburg_archive.json rebuilt: de_by13_cdx_cfg.py (de_by18_wuerzburg_cdx_entry.json, log _logs/de_by18_cdx_cfg.log, 511 kept) merged with the
#  2026-10-23 499-URL index config (backup de_by18_wuerzburg_archive_prev499.json), deduped on file=/ObjID (newest capture URL kept) -> 549 URLs (437 with known Wayback captures first).
#  All URLs carry query strings -> doc_ids get the ~URL-hash suffix in archive_retry. Titles from fn= (latin-1 fixed). Test: de_by18_test.log. 10 rounds.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 10); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_würzburg_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 10 ] && sleep 600
done
echo "$(date) done"
