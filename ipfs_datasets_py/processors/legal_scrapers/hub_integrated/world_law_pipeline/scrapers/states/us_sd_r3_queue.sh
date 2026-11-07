#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-27 03:09 PDT: SD r3 test (r2 rejected: chapters headed '[Repealed]'/'[Repealed and Transferred]' and all-sections-repealed chapters had in_force=True; API Repealed flag is always False. USSouthDakotaCodified.fetch now sets None from the heading / all-dead sections). RAM-gated; held in _review.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs
echo "$(date) test us_sd_sdcl r3"
ramgate_run 150 $L/test_us_sd_sdcl_r3.out ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source us_sd_sdcl --test 20
echo "$(date) test us_sd_sdcl r3 rc=$?"
