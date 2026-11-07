#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25: AZ remainder via archive copies (shared Wayback module). HF covers ~9k ARS sections; their azleg URLs are skipped
# by the US HF skip (oldskip us_hf_index). CDX list first, then the 20-row test.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
while pgrep -f "cdx_list.py data/archive/pe_pdf" >/dev/null; do sleep 60; done
echo "$(date) cdx AZ"; ramgate_run 60 $L/cdx_az_ars.out $PY -u cdx_list.py data/archive/az_ars.txt "www.azleg.gov/ars/" $(seq 1 49 | sed 's|$|/|'); echo "rc=$?"
[ -s data/archive/az_ars.txt ] && { echo "$(date) test us_az_ars_archive"; ramgate_run 120 $L/test_us_az_ars_archive.out $PY -u run_full.py --source us_az_ars_archive --test 20; echo "rc=$?"; }
echo "$(date) AZARCH_END"
