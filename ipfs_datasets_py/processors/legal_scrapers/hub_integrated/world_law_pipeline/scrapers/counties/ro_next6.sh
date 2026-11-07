#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-23 ro_next6: continuation of capped (MAXU 400) RO county runs from their saved found-lists (adopted HCJ only; no annexes/projects),
# then nothing else. us_pdf_list skips URLs already staged/processed. Disk guard 45 GB (also inside us_pdf_list).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
L=${WORLD_LAW_ROOT}/staging/counties/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for s in sălaj vaslui călărași; do
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "$(date) start $s"; $PY -u us_pdf_list.py ro_next6_${s}_rest.json > $L/ro_next6_${s}.log 2>&1; echo "$(date) $s $(tail -1 $L/ro_next6_${s}.log)"
done
echo "$(date) done"
