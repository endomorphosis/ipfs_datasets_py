#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-23: archive-only queue for Bavarian robots-blocked URLs (first: Weißenburg-Gunzenhausen timm/download.php?file=..., 67 URLs, robots Disallow: /timm/).
# Same pattern as archive_queue.sh: idempotent rounds (archive_retry skips already staged/processed source_urls), 30 min apart, disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in de_by_kreisrecht_landkreis_weißenburg_gunzenhausen_archive.json; do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
