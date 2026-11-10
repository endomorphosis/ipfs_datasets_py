#!/bin/bash
# loop: full gkmlpt run (checkpointed), then retry held cities every 6h
W=/workspace/world_law/staging/eap/_eap_work/cn; echo $$ > $W/_cn_waiter.pid
cd /workspace/world_law/pipeline/scrapers/eap
while true; do
  bash /workspace/world_law/pipeline/scrapers/eap/backup_eap.sh
  while [ $(df --output=avail -BG /workspace | tail -1 | tr -dc 0-9) -lt 20 ]; do sleep 600; done
  echo "$(date '+%F %T') start" >> $W/cn_waiter.log
  ARCHIVE_LANE=eap timeout 12h /workspace/world_law/pipeline/scrapers/eap/.venv/bin/python -u eap_cn_gkmlpt.py >> $W/gkmlpt_full.log 2>&1
  echo "$(date '+%F %T') rc=$?" >> $W/cn_waiter.log
  sleep 21600
done
