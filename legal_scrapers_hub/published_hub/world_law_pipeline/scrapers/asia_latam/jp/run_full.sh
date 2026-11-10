#!/bin/bash
# Full JP reiki crawl (resumable: per-seed state in staging/asia_latam/_state/jp). Re-run to resume.
cd /workspace/world_law/pipeline/scrapers/asia_latam/jp
LOG=/workspace/world_law/staging/asia_latam/_logs/jp_full_$(date +%Y%m%d_%H%M).log
exec python3 -u jp_reiki.py --vendors gyosei,d1w,d1ops,joureikun,unknown --workers 40 --per-host 2 --interval 1.0 --retry-errors "$@" >> "$LOG" 2>&1
