#!/bin/bash
# ES gazettes: new-issues pass (state _state/es_bop/<g>_fwd.json, head -> today), repeated every 6 h. Re-run to resume.
cd /workspace/world_law/pipeline/scrapers/asia_latam/es
LOG=/workspace/world_law/staging/asia_latam/_logs/es_bop_forward_$(date +%Y%m%d_%H%M).log
exec python3 -u es_bop.py --forward --every-hours 6 --gazettes bocm,borm,caceres,gipuzkoa,cordoba,granada,leon,huesca,soria,avila,guadalajara,lugo,ourense,cadiz,castellon "$@" >> "$LOG" 2>&1
