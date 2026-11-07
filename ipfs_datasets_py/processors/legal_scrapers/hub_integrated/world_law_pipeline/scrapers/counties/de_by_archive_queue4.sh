#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-24 (fr_raa_next1 worker): archive-only queue for Landkreis Ansbach deferred URLs (de_by12 live crawl: 135 ok / 66 fail;
#   all fails are /output/download.php?fid=... which robots.txt disallows -> archive fallback deferred by CC/Wayback busy).
#   64 URLs (2 dropped: already staged via loadDocument.phtml twins). Mirrors de_by_archive_queue3.sh: idempotent rounds
#   (archive_retry skips already staged source_urls; query URLs get URL-hash doc_id suffix), 30 min apart, disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in de_by_kreisrecht_landkreis_ansbach_archive.json; do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
