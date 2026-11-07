#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-26 00:15 PDT: RI r2 test (strict UTF-8 decode w/ cp1252 fallback for section pages + chapter titles, &nbsp; unescaped). RAM-gated.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs
echo "$(date) test us_ri_gl r2"
ramgate_run 120 $L/test_us_ri_gl_r2.out ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source us_ri_gl --test 20
echo "$(date) test us_ri_gl r2 rc=$?"
