#!/bin/bash
# JP legal-square (Gyosei Super Reiki-Base, 86 bodies): anonymous visitor session, 1 req/s/host, 2 hosts in parallel.
# Resumable via staging/asia_latam/_state/jp_legal_square/<seed>.json. Re-run to resume.
cd /workspace/world_law/pipeline/scrapers/asia_latam/jp
LOG=/workspace/world_law/staging/asia_latam/_logs/jp_legal_square_$(date +%Y%m%d_%H%M).log
export MALLOC_ARENA_MAX=2
exec python3 -u legal_square.py --workers 2 --retry-errors "$@" >> "$LOG" 2>&1
