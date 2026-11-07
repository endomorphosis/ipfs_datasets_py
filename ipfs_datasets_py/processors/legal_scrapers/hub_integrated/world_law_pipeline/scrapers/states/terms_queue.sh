#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Serial queue for terms-tagged sources (keeps lane RSS < 1 GB): one job at a time after Sarawak full.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
L=${WORLD_LAW_ROOT}/staging/states/_logs
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
while pgrep -f "source my_13_lawnet$" >/dev/null; do sleep 30; done
for k in ae_du_dlp pk_ba_code us_ky_krs ae_az_gazette; do
  echo "$(date) test $k"; $PY -u run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
echo "$(date) KE sweep"; ./ke_counties_chain.sh
echo "$(date) QUEUE_END"
