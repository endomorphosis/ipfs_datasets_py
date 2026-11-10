#!/bin/bash
# waits until /workspace has >45 GB free, then resumes run_queue.sh (which itself stops below 35 GB)
L=/workspace/world_law/staging/national/_hf_import/_logs
while :; do
  f=$(df --output=avail -B1G /workspace | tail -1 | tr -d ' ')
  [ -f /workspace/world_law/staging/national/_hf_import/STOP ] && exit 0
  if [ "$f" -gt 45 ]; then echo "$(date) free ${f}G, resuming"; exec /workspace/world_law/pipeline/scrapers/national/hf_import/run_queue.sh > $L/queue_$(date +%Y%m%dT%H%M).log 2>&1; fi
  sleep 300
done
