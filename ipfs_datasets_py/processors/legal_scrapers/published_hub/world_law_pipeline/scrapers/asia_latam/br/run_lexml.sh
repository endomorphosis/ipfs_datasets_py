#!/bin/bash
cd "$(dirname "$0")"
TS=$(date +%Y%m%d_%H%M)
nohup python3 lexml.py --only all >> /workspace/world_law/staging/asia_latam/_logs/br_lexml_$TS.log 2>&1 &
echo $! $TS
