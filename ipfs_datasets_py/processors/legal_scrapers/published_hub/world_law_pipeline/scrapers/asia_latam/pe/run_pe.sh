#!/bin/bash
# Peru gob.pe normas-legales (municipal ordinances + decretos de alcaldía). Resumable via staging/asia_latam/_state/pe/<slug>.json.
cd /workspace/world_law/pipeline/scrapers/asia_latam/pe
LOG=/workspace/world_law/staging/asia_latam/_logs/pe_gobpe_$(date +%Y%m%d_%H%M).log
exec python3 -u pe_gobpe.py "$@" >> "$LOG" 2>&1
