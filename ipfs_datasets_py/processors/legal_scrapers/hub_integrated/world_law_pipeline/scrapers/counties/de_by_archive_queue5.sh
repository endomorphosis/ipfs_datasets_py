#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-24 20:20 PDT de_by_archive_queue5: requeue of Landkreis Ansbach (Q10454) deferred /output/download.php?fid=... PDFs (robots Disallow: /output/
#   -> archive copies only). de_by_archive_queue4.sh ended 16:56 PDT after 8 rounds without a final 'written' line: round 8 fetched 6 OK but the outer
#   `timeout 3000` killed archive_retry before flush (internal deadline 45 min + up to 300 s deferral sleep + fetch time > 50 min) -> those 6 were not staged.
#   State at requeue: 17 staged, 47 todo. Test batch 20:06-20:07 PDT (de_by_archive_queue5_test.log, de_by_archive_queue5_test_ansbach.json): 3/3 OK wayback
#   (fid 3797.555/.565/.564), doc_ids carry the URL-hash suffix (~xxxxxxxx) -> 44 todo for the full run.
#   Same pattern as queue4 (archive_retry skips already-staged source_urls across ${WORLD_LAW_ROOT}/*/counties/DE), but internal deadline 40 min so the
#   writer flushes before timeout 3000. 8 rounds, 30 min apart, disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in de_by_kreisrecht_landkreis_ansbach_archive.json; do
    df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 40 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
