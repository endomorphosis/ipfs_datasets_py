#!/bin/bash
# ES gazettes (BOP family) full run; resumable via staging/asia_latam/_state/es_bop/<gazette>.json. Re-run to resume.
cd /workspace/world_law/pipeline/scrapers/asia_latam/es
LOG=/workspace/world_law/staging/asia_latam/_logs/es_bop_$(date +%Y%m%d_%H%M).log
exec python3 -u es_bop.py "$@" >> "$LOG" 2>&1
