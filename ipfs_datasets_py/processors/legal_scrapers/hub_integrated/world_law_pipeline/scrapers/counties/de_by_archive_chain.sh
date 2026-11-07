#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-21: archive lane for Bavarian Landkreise not crawlable live. Waits for the Kulmbach test (3 URLs) to stage >=1 doc,
# retrying the test up to 4x (archives are often deferred/breaker-open box-wide), then runs the full archive list. Disk guard 45 GB.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
L=${WORLD_LAW_ROOT}/staging/counties/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
while pgrep -f "archive_index_build.py de_by_archive_test_entries.json" >/dev/null; do sleep 60; done
n=0
until grep -q "written: /" $L/de_by_archive_test.log; do
  n=$((n+1)); [ $n -gt 4 ] && { echo "$(date) test never staged a doc; giving up"; exit 0; }
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "$(date) test attempt $n"; $PY -u archive_index_build.py de_by_archive_test_entries.json by_kreisrecht 90 3 > $L/de_by_archive_test.log 2>&1
done
df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
echo "$(date) test passed; full archive run"; $PY -u archive_index_build.py de_by_archive_entries.json by_kreisrecht 900 > $L/de_by_archive.log 2>&1
echo "$(date) done"
