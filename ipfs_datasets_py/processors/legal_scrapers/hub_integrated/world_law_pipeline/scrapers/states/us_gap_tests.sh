#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25 US gap states (Benjamin 19:00): test-first runs (20 rows -> _review), RAM-gated; US HF skip active in run_full/oldskip.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for k in "$@"; do
  echo "$(date) test $k"; ramgate_run 120 $L/test_$k.out $PY -u run_full.py --source $k --test 20; echo "$(date) test $k rc=$?"
done
echo "$(date) GAPTESTS_END $*"
