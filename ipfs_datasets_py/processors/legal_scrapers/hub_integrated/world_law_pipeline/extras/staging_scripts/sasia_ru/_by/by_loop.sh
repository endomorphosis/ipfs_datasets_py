#!/bin/bash -l
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
cd ${WORLD_LAW_ROOT}/staging/sasia_ru
while true; do
  if [ $(df --output=avail -B1 /workspace | tail -1) -lt 10000000000 ]; then echo "$(date) DISK LOW skip" >> _by/by_collect.log; else env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy ARCHIVE_LANE=sasia_ru RESPECT_ROBOTS=0 ${WORLD_LAW_ROOT}/staging/sasia_ru/_venv/bin/python -u ${WORLD_LAW_ROOT}/pipeline/scrapers/sasia_ru/by_pravo_new.py --collect-only >> _by/by_collect.log 2>&1; fi
  sleep 43200
done
