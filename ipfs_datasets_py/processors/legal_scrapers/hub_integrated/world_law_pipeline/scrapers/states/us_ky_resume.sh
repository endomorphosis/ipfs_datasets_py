#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25 19:10: KY resume for chapters missing upstream (US HF cite skip: chapters with >=3 good HF sections are skipped).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
echo "$(date) full us_ky_krs (resume, gap chapters)"; ramgate_run 130 $L/full_us_ky_krs.out $PY -u run_full.py --source us_ky_krs; echo "$(date) rc=$?"
echo "$(date) KYRESUME_END"
