#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-26 15:14 PDT: DC r2 test (r1 rejected: 4/20 '[Repealed]'/'[Recodified]' chapters had in_force=True; USDCCode.fetch now sets None). RAM-gated; held in _review.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs
echo "$(date) test us_dc_code r2"
ramgate_run 120 $L/test_us_dc_code_r2.out ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source us_dc_code --test 20
echo "$(date) test us_dc_code r2 rc=$?"
