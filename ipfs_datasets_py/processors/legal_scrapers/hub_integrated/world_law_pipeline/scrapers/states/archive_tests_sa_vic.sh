#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# For each archive-only source: once its Wayback URL list exists, run a 20-row test into _review (HELD, never auto-promoted).
# 2026-11-01: copy of archive_tests.sh limited to SA/VIC (nsw/qc/bc/yt test .out files were gzipped, so the original would rerun those tests).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
L=${WORLD_LAW_ROOT}/staging/states/_logs
for pair in sa:au_sa_archive vic:au_vic_archive; do
  f=${pair%%:*}; k=${pair##*:}
  [ -s $L/test_$k.out ] && grep -q "END" $L/test_$k.out && continue
  while [ ! -e data/archive/$f.txt ]; do sleep 300; done
  ${WORLD_LAW_ROOT}/pipeline/venv/bin/python run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
