#!/bin/bash
cd "$(dirname "$0")"
TS=$(date +%Y%m%d_%H%M)
nohup python3 qld_local_laws.py --workers 3 --retry-failed >> /workspace/world_law/staging/asia_latam/_logs/au_qld_ll_$TS.log 2>&1 &
echo $! $TS
