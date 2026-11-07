#!/bin/bash
# Fourth serial queue: SK Freelaw test after queues 1-3.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
while pgrep -f "terms_queue[23]?.sh" >/dev/null; do sleep 30; done
for k in ca_sk_freelaw; do echo "$(date) test $k"; $PY -u run_full.py --source $k --test 20 > $L/test_$k.out 2>&1; done
echo "$(date) QUEUE4_END"
