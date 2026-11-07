#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Kenya counties: test-mode sweep (old-URL skip removes rows already in the dataset); new rows land in _review.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
for i in $(seq -w 1 47); do
  [ -s ${WORLD_LAW_ROOT}/staging/states/_logs/test_ke_c${i}_kenyalaw.out ] && grep -q END ${WORLD_LAW_ROOT}/staging/states/_logs/test_ke_c${i}_kenyalaw.out && continue
  ${WORLD_LAW_ROOT}/pipeline/venv/bin/python -u run_full.py --source ke_c${i}_kenyalaw --test 20 > ${WORLD_LAW_ROOT}/staging/states/_logs/test_ke_c${i}_kenyalaw.out 2>&1
done
echo CHAIN_END
