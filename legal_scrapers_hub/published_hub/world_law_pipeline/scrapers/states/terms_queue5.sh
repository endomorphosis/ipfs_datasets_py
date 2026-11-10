#!/bin/bash
# NS regs r2 test after queues 3/4 (title fix).
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
while pgrep -f "terms_queue[34].sh" >/dev/null; do sleep 30; done
echo "$(date) test ca_ns_regs r2"; /workspace/world_law/pipeline/venv/bin/python -u run_full.py --source ca_ns_regs --test 20 > $L/test_ca_ns_regs.out 2>&1
echo "$(date) QUEUE5_END"
