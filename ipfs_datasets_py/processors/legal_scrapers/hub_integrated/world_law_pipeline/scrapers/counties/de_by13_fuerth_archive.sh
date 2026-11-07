#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25 ~09:00 PDT: Fürth (Q10455) archive phase of de_by13.sh. Retry test 3 (archive_retry.py de_by13_test_fuerth_archive.json 20,
#  _logs/de_by13_test_fuerth_retry3.log, 08:47-08:55 PDT): staged 3 / miss 0 / deferred 0 (Wayback) -> passed. landkreis-fuerth.de robots.txt = Cloudflare 403
#  -> archive copies only (CC/Wayback), never live. 658 URLs (de_by_kreisrecht_landkreis_fürth_archive.json). 8 rounds 30 min apart, max 40 min each. Disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
g() { df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }; }
for round in 1 2 3 4 5 6 7 8; do
  g; echo "== archive round $round $(date)"; timeout 3000 $PY -u archive_retry.py de_by_kreisrecht_landkreis_fürth_archive.json 40 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP)'
  [ $round -lt 8 ] && sleep 1800
done
echo "$(date) done"
