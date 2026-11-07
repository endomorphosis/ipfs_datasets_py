#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# NS regs r2 test after queues 3/4 (title fix).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
L=${WORLD_LAW_ROOT}/staging/states/_logs
while pgrep -f "terms_queue[34].sh" >/dev/null; do sleep 30; done
echo "$(date) test ca_ns_regs r2"; ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source ca_ns_regs --test 20 > $L/test_ca_ns_regs.out 2>&1
echo "$(date) QUEUE5_END"
