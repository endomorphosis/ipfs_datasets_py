#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-26 18:04 PDT: NM r2 test (r1 rejected: ch. 59 'Insurance [Repealed.]' had in_force=True; USNewMexicoNMSA.fetch now sets None for [Repealed./Recompiled.] headings). RAM-gated; held in _review.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs
echo "$(date) test us_nm_nmsa r2"
ramgate_run 220 $L/test_us_nm_nmsa_r2.out ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source us_nm_nmsa --test 20
echo "$(date) test us_nm_nmsa r2 rc=$?"
