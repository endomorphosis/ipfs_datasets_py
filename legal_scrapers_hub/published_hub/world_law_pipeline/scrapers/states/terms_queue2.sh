#!/bin/bash
# Second serial queue: waits for terms_queue.sh, then tests AE-AZ gazette and NS regs (one job at a time).
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
while pgrep -f terms_queue.sh >/dev/null; do sleep 30; done
for k in ae_az_gazette ca_ns_regs; do
  echo "$(date) test $k"; $PY -u run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
echo "$(date) QUEUE2_END"
