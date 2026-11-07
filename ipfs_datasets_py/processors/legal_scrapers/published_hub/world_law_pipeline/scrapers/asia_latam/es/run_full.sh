#!/bin/bash
# Full ES sedelectronica run (robots-first; resumable via staging/asia_latam/_state/es). Re-run to resume.
cd /workspace/world_law/pipeline/scrapers/asia_latam/es
LOG=/workspace/world_law/staging/asia_latam/_logs/es_full_$(date +%Y%m%d_%H%M).log
python3 -u es_sede.py --workers 2 --interval 1.0 "$@" >> "$LOG" 2>&1
python3 status.py >> "$LOG" 2>&1
