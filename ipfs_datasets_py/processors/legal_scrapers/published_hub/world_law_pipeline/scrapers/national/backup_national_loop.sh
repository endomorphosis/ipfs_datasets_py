#!/bin/bash
# Hourly national backup loop (no deletes). Log: staging/national/_logs/backup_national.log
while true; do sleep 3600; /workspace/world_law/pipeline/scrapers/national/backup_national.sh >> /workspace/world_law/staging/national/_logs/backup_national.log 2>&1; done
