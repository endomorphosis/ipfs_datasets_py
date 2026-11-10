#!/bin/bash
cd "$(dirname "$0")"
TS=$(date +%Y%m%d_%H%M)
MALLOC_ARENA_MAX=2 nohup python3 sapl.py --workers 12 --slice 25 >> /workspace/world_law/staging/asia_latam/_logs/br_sapl_$TS.log 2>&1 &
echo $! $TS
