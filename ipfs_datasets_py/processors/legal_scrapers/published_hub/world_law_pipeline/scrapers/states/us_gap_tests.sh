#!/bin/bash
# 2026-10-25 US gap states (Benjamin 19:00): test-first runs (20 rows -> _review), RAM-gated; US HF skip active in run_full/oldskip.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
for k in "$@"; do
  echo "$(date) test $k"; ramgate_run 120 $L/test_$k.out $PY -u run_full.py --source $k --test 20; echo "$(date) test $k rc=$?"
done
echo "$(date) GAPTESTS_END $*"
