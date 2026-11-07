#!/bin/bash
cd "$(dirname "$0")"
TS=$(date +%Y%m%d_%H%M)
nohup python3 za_bylaws.py --workers 3 --retry-failed >> /workspace/world_law/staging/asia_latam/_logs/za_bylaws_$TS.log 2>&1 &
echo $! $TS
