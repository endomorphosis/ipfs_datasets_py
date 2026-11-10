#!/bin/bash
# Kenya counties: test-mode sweep (old-URL skip removes rows already in the dataset); new rows land in _review.
cd /workspace/world_law/pipeline/scrapers/states
for i in $(seq -w 1 47); do
  [ -s /workspace/world_law/staging/states/_logs/test_ke_c${i}_kenyalaw.out ] && grep -q END /workspace/world_law/staging/states/_logs/test_ke_c${i}_kenyalaw.out && continue
  /workspace/world_law/pipeline/venv/bin/python -u run_full.py --source ke_c${i}_kenyalaw --test 20 > /workspace/world_law/staging/states/_logs/test_ke_c${i}_kenyalaw.out 2>&1
done
echo CHAIN_END
