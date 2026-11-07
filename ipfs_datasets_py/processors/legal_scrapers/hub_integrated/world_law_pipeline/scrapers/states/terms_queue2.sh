#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Second serial queue: waits for terms_queue.sh, then tests AE-AZ gazette and NS regs (one job at a time).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
L=${WORLD_LAW_ROOT}/staging/states/_logs
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
while pgrep -f terms_queue.sh >/dev/null; do sleep 30; done
for k in ae_az_gazette ca_ns_regs; do
  echo "$(date) test $k"; $PY -u run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
echo "$(date) QUEUE2_END"
