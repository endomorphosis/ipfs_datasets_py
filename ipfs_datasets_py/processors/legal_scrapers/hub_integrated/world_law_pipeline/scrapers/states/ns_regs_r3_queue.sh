#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25 21:12 PDT: NS regs r3 test (titles from regsbyact entry names, filed-PDF titles/numbers, UTF-8/cp1252 decode). RAM-gated.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs
echo "$(date) test ca_ns_regs r3"
ramgate_run 160 $L/test_ca_ns_regs_r3.out ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source ca_ns_regs --test 20
echo "$(date) test ca_ns_regs r3 rc=$?"
