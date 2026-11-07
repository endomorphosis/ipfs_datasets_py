#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Hourly national backup loop (no deletes). Log: staging/national/_logs/backup_national.log
while true; do sleep 3600; ${WORLD_LAW_ROOT}/pipeline/scrapers/national/backup_national.sh >> ${WORLD_LAW_ROOT}/staging/national/_logs/backup_national.log 2>&1; done
