#!/bin/bash
# Serial full runs of promoted terms-tagged sources, after the test queues finish (lane RSS < 1 GB).
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
while pgrep -f "terms_queue[2345]?.sh" >/dev/null || pgrep -f "source ca_nl_assembly$" >/dev/null; do sleep 60; done
for k in $(cat /workspace/world_law/pipeline/scrapers/states/terms_full_list.txt); do
  grep -q "^$k$" /workspace/world_law/pipeline/scrapers/states/terms_full_done.txt 2>/dev/null && continue
  echo "$(date) full $k"; $PY -u run_full.py --source $k >> $L/full_$k.out 2>&1; echo "$k" >> /workspace/world_law/pipeline/scrapers/states/terms_full_done.txt
done
echo "$(date) FULLQ_END"
