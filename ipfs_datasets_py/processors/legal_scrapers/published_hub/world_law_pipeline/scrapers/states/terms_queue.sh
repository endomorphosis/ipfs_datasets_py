#!/bin/bash
# Serial queue for terms-tagged sources (keeps lane RSS < 1 GB): one job at a time after Sarawak full.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
while pgrep -f "source my_13_lawnet$" >/dev/null; do sleep 30; done
for k in ae_du_dlp pk_ba_code us_ky_krs ae_az_gazette; do
  echo "$(date) test $k"; $PY -u run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
echo "$(date) KE sweep"; ./ke_counties_chain.sh
echo "$(date) QUEUE_END"
